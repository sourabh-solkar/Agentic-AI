from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage

from db.db_operations import (
    append_assistant_message,
    combine_messages,
    create_session_for_user,
    delete_session_for_user,
    get_messages_for_session,
    list_sessions_for_user,
    persist_chat_request,
    session_belongs_to_user,
)
from db.user_operations import create_user, get_user_by_username, verify_password
from db.db_operations import get_database_url
from langchain.agents import create_agent
from typing import Annotated, Any
from contextlib import asynccontextmanager
import os
import time
import uuid
import asyncio
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Body, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pyrate_limiter import Duration, Limiter, Rate
from fastapi_limiter.depends import RateLimiter
from utils.auth import create_access_token, verify_token
from fastapi.security import OAuth2PasswordBearer
from langchain.agents.middleware import PIIMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import interrupt, Command
from langchain.agents.middleware import SummarizationMiddleware
from graph.router_graph import build_router_graph
# langchain.verbose = True
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
origins = [

    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000/"
]

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=api_key,
    streaming=False,
)


def _email_request_id(to: str, subject: str, body: str) -> str:
    return f"{to}|{subject}|{body}"


def _sanitize_approval_payload(payload: dict[str, str] | None) -> dict[str, str] | None:
    if not payload:
        return None
    action = payload.get("action", "send_email")
    sanitized: dict[str, str] = {"action": action, "id": payload.get("id", "pending")}
    if action == "send_email":
        sanitized["to"] = payload.get("to", "unknown")
        sanitized["subject"] = payload.get("subject", "unknown")
    elif action == "human_review":
        sanitized["query"] = payload.get("query", "")
    return sanitized


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email after explicit HITL approval. Call this tool as soon as the user asks to send mail and you know who it is for and what to say—do not ask follow-ups in chat instead of calling. If the user omitted subject, infer a short subject from their message (e.g. topic or '(No subject)')."""
    approval = interrupt(
        {
            "action": "send_email",
            "id": _email_request_id(to, subject, body),
            "to": to,
            "subject": subject,
            "body": body,
            "prompt": "Approve sending this email?",
        }
    )
    approved = False
    if isinstance(approval, bool):
        approved = approval
    elif isinstance(approval, dict):
        approved = bool(approval.get("approved"))

    if not approved:
        return "Email send was rejected."

    return (
        f"[MOCK] send_email approved and executed for to='{to}', "
        f"subject='{subject}'. No real email was sent."
    )


pii_middleware = [
        # Do not redact emails on input: the model must see real addresses to call
        # send_email correctly; HITL approval is the safety gate instead.
        PIIMiddleware("credit_card", strategy="mask", apply_to_input=True),
        PIIMiddleware("ip", strategy="mask", apply_to_input=True),
        PIIMiddleware("mac_address", strategy="redact", apply_to_input=True),
        PIIMiddleware("url", strategy="redact", apply_to_input=True),
        SummarizationMiddleware(
            model=llm,
            trigger=("tokens", 600),
            keep=("messages", 10),
            summary_prompt=(
                "You are a helpful assistant. Summarize the conversation history in a concise manner."
            ),
        ),
         # Layer 4: Model-based safety check (after agent)
        # SafetyGuardrailMiddleware(),
         # Persist the state across interrupts
    ]


_AGENT_SYSTEM_PROMPT = """You are a helpful assistant.

Answer normal questions using your general knowledge.

When the user asks to send email / mail / message someone:
- Call send_email immediately once you have recipient address and body text (what they want said).
- If they did not give a subject, infer a short subject from context (e.g. first words of the topic, or "(No subject)").
- Do not stall by asking for subject or extra details in plain text if you can reasonably infer them—the approval step lets a human review the draft."""

general_agent = create_agent(
    model=llm,
    tools=[send_email],
    system_prompt=_AGENT_SYSTEM_PROMPT,
    middleware=pii_middleware,
    checkpointer=InMemorySaver(),
)

router_builder = build_router_graph(llm, general_agent)
router_graph = router_builder.compile(checkpointer=InMemorySaver())

@app.get("/")
def read_root():
    return {"message": "Hello from the local FastAPI server!"}



class ChatRequest(BaseModel):
    message: str
    session_id: str

def _assistant_text(message: AIMessage) -> str:
    """Flatten assistant message content (Gemini may use str or block lists)."""
    c = message.content
    if not c:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                elif "text" in block:
                    parts.append(str(block["text"]))
        return "".join(parts)
    return ""


def _sse_data_lines(text: str) -> str:
    """One SSE event; prefix each newline per https://html.spec.whatwg.org/multipage/server-sent-events.html"""
    if not text:
        return ""
   
    return "".join(f"data: {line}\n" for line in text.split("\n")) + "\n"


def _verify_auth_payload(token: str) -> dict:
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    exp = payload.get("exp")
    if exp and exp < time.time():
        raise HTTPException(status_code=401, detail="Token expired")
    if not payload.get("user_id"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return payload


async def event_generator(
    user_input: str,
    combined_context: str,
    session_id: str,
    user_id: str,
):
    try:
        result = await router_graph.ainvoke(
            {
                "messages": [{"role": "user", "content": user_input}],
                "intent": "",
                "combined_context": combined_context,
            },
            config={"configurable": {"thread_id": session_id}},
        )
        if isinstance(result, dict) and result.get("__interrupt__"):
            global _pending_approval
            payload: dict[str, str] = {
                "action": "human_review",
                "id": "pending-approval",
                "query": user_input,
            }
            first_interrupt = result["__interrupt__"][0]
            value = getattr(first_interrupt, "value", None)
            if isinstance(value, dict):
                action = str(value.get("action", "human_review"))
                payload = {
                    "action": action,
                    "id": str(value.get("id", "pending-approval")),
                }
                if action == "send_email":
                    payload["to"] = str(value.get("to", "unknown"))
                    payload["subject"] = str(value.get("subject", "unknown"))
                elif action == "human_review":
                    payload["query"] = str(value.get("query", user_input))
            with _approval_lock:
                _pending_approval = payload
            if payload.get("action") == "send_email":
                approval_msg = (
                    "[APPROVAL REQUIRED] Pending send_email request. "
                    "Click 'Approve' to continue."
                )
            else:
                approval_msg = (
                    "[APPROVAL REQUIRED] This request needs human review. "
                    "Click 'Approve' to escalate to a human agent."
                )
            yield _sse_data_lines(approval_msg)
            return

        messages = result.get("messages", []) if isinstance(result, dict) else []
        assistant_text = ""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                assistant_text = _assistant_text(message)
                break

        if not assistant_text:
            assistant_text = "I could not generate a response."
        try:
            append_assistant_message(session_id, assistant_text, user_id=user_id)
        except Exception as persist_err:
            print("append_assistant_message failed:", persist_err)
        yield _sse_data_lines(assistant_text)
    except Exception as e:
        yield _sse_data_lines(f"[error] {e}")
    finally:
        yield "event: done\ndata: [DONE]\n\n"


@app.api_route(
    "/chat",
    methods=["GET", "POST"],
    dependencies=[Depends(RateLimiter(limiter=Limiter(Rate(2, Duration.SECOND * 5))))],
)
async def chat(
    token: Annotated[str, Depends(oauth2_scheme)],
    message: str | None = None,
    session_id: str | None = None,
    request: ChatRequest | None = Body(default=None),
):
    try:
        payload = _verify_auth_payload(token)
        user_id = payload["user_id"]

        user_message = message or (request.message if request else None)
        if not user_message:
            raise HTTPException(status_code=400, detail="`message` is required")

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        resolved_session_id = session_id or (request.session_id if request else None)
        if not resolved_session_id:
            raise HTTPException(status_code=400, detail="`session_id` is required")

        if not session_belongs_to_user(resolved_session_id, user_id):
            raise HTTPException(status_code=403, detail="Session not found")

        combined_context = combine_messages(resolved_session_id)
        try:
            persist_chat_request(
                resolved_session_id,
                user_message,
                combined_context,
                user_id=user_id,
            )
        except Exception as persist_err:
            print("persist_chat_request failed:", persist_err)

        return StreamingResponse(
            event_generator(user_message, combined_context, resolved_session_id, user_id),
            media_type="text/event-stream",
            headers=headers,
           
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
def login(req: LoginRequest):
    try:
        user = get_user_by_username(req.username)
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        access_token = create_access_token(
            username=user["username"],
            user_id=str(user["id"]),
        )
        if not access_token:
            raise HTTPException(status_code=500, detail="Failed to generate access token")

        session_id = str(uuid.uuid4())
        create_session_for_user(str(user["id"]), session_id)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/register")
def register(req: LoginRequest):
    try:
        if get_user_by_username(req.username):
            raise HTTPException(status_code=409, detail="Username already exists")
        user = create_user(req.username, req.password)
        access_token = create_access_token(
            username=user["username"],
            user_id=str(user["id"]),
        )
        if not access_token:
            raise HTTPException(status_code=500, detail="Failed to generate access token")
        session_id = str(uuid.uuid4())
        create_session_for_user(str(user["id"]), session_id)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "session_id": session_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions")
def list_sessions(token: Annotated[str, Depends(oauth2_scheme)]):
    payload = _verify_auth_payload(token)
    sessions = list_sessions_for_user(payload["user_id"])
    return {"sessions": sessions}


@app.post("/sessions")
def create_session(token: Annotated[str, Depends(oauth2_scheme)]):
    payload = _verify_auth_payload(token)
    session_id = str(uuid.uuid4())
    create_session_for_user(payload["user_id"], session_id)
    return {"session_id": session_id}


@app.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
):
    payload = _verify_auth_payload(token)
    if not session_belongs_to_user(session_id, payload["user_id"]):
        raise HTTPException(status_code=404, detail="Session not found")
    messages = get_messages_for_session(session_id)
    return {"messages": messages}


@app.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    token: Annotated[str, Depends(oauth2_scheme)],
):
    payload = _verify_auth_payload(token)
    if not delete_session_for_user(session_id, payload["user_id"]):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


def _get_pending_approval(token: Annotated[str, Depends(oauth2_scheme)]):
    _verify_auth_payload(token)
    with _approval_lock:
        pending = _sanitize_approval_payload(_pending_approval)
    return {"pending": pending}


def _approve_pending(
    token: Annotated[str, Depends(oauth2_scheme)],
    session_id: str | None = None,
):
    payload_auth = _verify_auth_payload(token)

    with _approval_lock:
        global _pending_approval
        if not _pending_approval:
            raise HTTPException(status_code=404, detail="No pending approval")
        approved = _sanitize_approval_payload(_pending_approval)
        _pending_approval = None

    thread_id = session_id or payload_auth.get("user_id", "default")
    try:
        result = router_graph.invoke(
            Command(resume={"approved": True}),
            config={"configurable": {"thread_id": thread_id}},
        )
        messages = result.get("messages", []) if isinstance(result, dict) else []
        assistant_text = ""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                assistant_text = _assistant_text(message)
                break
        return {
            "status": "approved",
            "approved": approved,
            "assistant_message": assistant_text or "Approval recorded.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval resume failed: {e}")


@app.get("/approval/pending")
def get_pending_approval(token: Annotated[str, Depends(oauth2_scheme)]):
    return _get_pending_approval(token)


@app.post("/approval/approve")
def approve_pending(
    token: Annotated[str, Depends(oauth2_scheme)],
    session_id: str | None = None,
):
    return _approve_pending(token, session_id)


@app.get("/email-approval/pending")
def get_pending_email_approval(token: Annotated[str, Depends(oauth2_scheme)]):
    return _get_pending_approval(token)


@app.post("/email-approval/approve")
def approve_pending_email(
    token: Annotated[str, Depends(oauth2_scheme)],
    session_id: str | None = None,
):
    return _approve_pending(token, session_id)


if __name__ == "__main__":
    if os.name == "nt":
        # Avoid noisy Proactor socket-accept disconnect traces on Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="0.0.0.0", port=9005)
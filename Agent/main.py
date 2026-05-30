from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage

from db.db_operations import append_chat_messages, combine_messages
from langchain.agents import create_agent
from typing import Annotated
import os
import time
import uuid
import asyncio
import threading
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pyrate_limiter import Duration, Limiter, Rate
from fastapi_limiter.depends import RateLimiter
from utils.auth import create_access_token, verify_token
from fastapi.security import OAuth2PasswordBearer
from langchain.agents.middleware import PIIMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.tools import tool
from langgraph.types import interrupt, Command
from langchain.agents.middleware import SummarizationMiddleware
import langchain
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

app = FastAPI();

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_approval_lock = threading.Lock()
_pending_email_approval: dict[str, str] | None = None
_THREAD_ID = "chat-session"


def _email_request_id(to: str, subject: str, body: str) -> str:
    return f"{to}|{subject}|{body}"


def _sanitize_approval_payload(payload: dict[str, str] | None) -> dict[str, str] | None:
    if not payload:
        return None
    return {
        "id": payload["id"],
        "to": payload["to"],
        "subject": payload["subject"],
    }


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

agent = create_agent(
    model=llm,
    tools=[send_email],
    system_prompt=_AGENT_SYSTEM_PROMPT,
    middleware=pii_middleware,
    checkpointer=InMemorySaver(),
)

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


async def event_generator(user_input: str, combined_context: str, session_id: str):
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_input}], "system": SystemMessage(content=combined_context)},
            config={"configurable": {"thread_id": _THREAD_ID}},
        )
        print("result ----->", result.get("__interrupt__"))
        if isinstance(result, dict) and result.get("__interrupt__"):
            global _pending_email_approval
            payload: dict[str, str] = {
                "id": "pending-email",
                "to": "unknown",
                "subject": "unknown",
            }
            first_interrupt = result["__interrupt__"][0]
            value = getattr(first_interrupt, "value", None)
            if isinstance(value, dict):
                payload = {
                    "id": str(value.get("id", "pending-email")),
                    "to": str(value.get("to", "unknown")),
                    "subject": str(value.get("subject", "unknown")),
                }
            with _approval_lock:
                _pending_email_approval = payload
            yield _sse_data_lines(
                "[APPROVAL REQUIRED] Pending send_email request. Click 'Approve Send Email'."
            )
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
            append_chat_messages(session_id, user_input, assistant_text)
        except Exception as persist_err:
            # Do not fail the stream if persistence fails; log for ops.
            print("append_chat_messages failed:", persist_err)
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
    request: ChatRequest | None = Body(default=None),
):
    try:
        payload = verify_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        exp = payload.get("exp")
        if exp and exp < time.time():
            raise HTTPException(status_code=401, detail="Token expired")

        user_message = message or (request.message if request else None)
        if not user_message:
            raise HTTPException(status_code=400, detail="`message` is required")

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        session_id = request.session_id 
        if not session_id:
            raise HTTPException(status_code=400, detail="`session_id` is required")
       
        combined_context = combine_messages(session_id)

        return StreamingResponse(
            event_generator(user_message, combined_context, session_id),
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
        if req.username == "admin" and req.password == "admin":
            access_token = create_access_token(username=req.username, password=req.password)
            if not access_token:
                raise HTTPException(status_code=500, detail="Failed to generate access token")
            session_id = str(uuid.uuid4())
            return {"access_token": access_token, "token_type": "bearer" , "session_id": session_id}
        raise HTTPException(status_code=401, detail="Invalid credentials")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/email-approval/pending")
def get_pending_email_approval(token: Annotated[str, Depends(oauth2_scheme)]):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    exp = payload.get("exp")
    if exp and exp < time.time():
        raise HTTPException(status_code=401, detail="Token expired")

    with _approval_lock:
        pending = _sanitize_approval_payload(_pending_email_approval)
    return {"pending": pending}


@app.post("/email-approval/approve")
def approve_pending_email(token: Annotated[str, Depends(oauth2_scheme)]):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    exp = payload.get("exp")
    if exp and exp < time.time():
        raise HTTPException(status_code=401, detail="Token expired")

    with _approval_lock:
        global _pending_email_approval
        if not _pending_email_approval:
            raise HTTPException(status_code=404, detail="No pending email approval")
        approved = _sanitize_approval_payload(_pending_email_approval)
        _pending_email_approval = None

    try:
        result = agent.invoke(
            Command(resume={"approved": True}),
            config={"configurable": {"thread_id": _THREAD_ID}},
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


if __name__ == "__main__":
    if os.name == "nt":
        # Avoid noisy Proactor socket-accept disconnect traces on Windows.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(app, host="0.0.0.0", port=9005)
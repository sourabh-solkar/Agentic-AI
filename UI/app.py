import json
import os
import urllib.error
import urllib.parse
import urllib.request

import requests
import streamlit as st
import streamlit.components.v1 as components

_FASTAPI_HOST = os.getenv("FASTAPI_HOST", "127.0.0.1")
_FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "9005"))
_FASTAPI_BASE_URL = f"http://{_FASTAPI_HOST}:{_FASTAPI_PORT}"
FASTAPI_CHAT_URL = f"{_FASTAPI_BASE_URL}/chat"
FASTAPI_LOGIN_URL = f"{_FASTAPI_BASE_URL}/login"
FASTAPI_EMAIL_PENDING_URL = f"{_FASTAPI_BASE_URL}/email-approval/pending"
FASTAPI_EMAIL_APPROVE_URL = f"{_FASTAPI_BASE_URL}/email-approval/approve"

SESSION_ID_LOCAL_STORAGE_KEY = "session_id"


def _browser_persist_session_id(session_id: str | None) -> None:
    """Write or clear session_id in the browser's localStorage (runs in component iframe)."""
    key_js = json.dumps(SESSION_ID_LOCAL_STORAGE_KEY)
    if session_id:
        val_js = json.dumps(session_id)
        script = f"localStorage.setItem({key_js}, {val_js});"
    else:
        script = f"localStorage.removeItem({key_js});"
    components.html(f"<script>{script}</script>", height=0)


if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "approval_requested" not in st.session_state:
    st.session_state.approval_requested = False


def post_email_approval(headers: dict[str, str]) -> tuple[bool, str, str]:
    """POST /email-approval/approve. Returns (ok, error_detail, assistant_message)."""
    try:
        approve_resp = requests.post(
            FASTAPI_EMAIL_APPROVE_URL,
            headers=headers,
            timeout=15,
        )
        if approve_resp.status_code == 200:
            data = approve_resp.json()
            return True, "", (data.get("assistant_message") or "").strip()
        return False, approve_resp.text or f"HTTP {approve_resp.status_code}", ""
    except requests.RequestException as e:
        return False, str(e), ""


def login():
    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Log In"):
        response = requests.post(
            FASTAPI_LOGIN_URL,
            json={"username": username, "password": password},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            st.session_state.access_token = data.get("access_token")
            st.session_state.session_id = data.get("session_id")
            st.session_state._ls_session_id_synced = False
            st.session_state.messages = []
            st.session_state.approval_requested = False
            st.success("Logged in successfully!")
            st.rerun()
        else:
            st.error("Invalid credentials")


def chat_interface():
    if st.session_state.session_id and not st.session_state.get("_ls_session_id_synced"):
        _browser_persist_session_id(st.session_state.session_id)
        st.session_state._ls_session_id_synced = True

    st.title("Chat with AI")
    st.caption(f"Backend: `{FASTAPI_CHAT_URL}`")

    if st.button("Logout"):
        _browser_persist_session_id(None)
        st.session_state.access_token = None
        st.session_state.session_id = None
        st.session_state._ls_session_id_synced = False
        st.session_state.messages = []
        st.session_state.approval_requested = False
        st.rerun()

    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    pending_email = None
    pending_fetch_error = None
    try:
        pending_resp = requests.get(FASTAPI_EMAIL_PENDING_URL, headers=headers, timeout=15)
        if pending_resp.status_code == 200:
            pending_email = pending_resp.json().get("pending")
        else:
            pending_fetch_error = f"HTTP {pending_resp.status_code}: {pending_resp.text}"
    except requests.RequestException:
        pending_fetch_error = "Could not reach approval endpoint."

    # Server is source of truth: if API says something is pending, show approve UI.
    if pending_email:
        st.session_state.approval_requested = True

    if pending_fetch_error:
        st.info(f"Approval status unavailable: {pending_fetch_error}")

    need_approval_ui = st.session_state.approval_requested

    if need_approval_ui:
        with st.container(border=True):
            st.markdown("### Pending email send")
            st.caption(
                "The assistant paused for approval. Review the draft below, then approve."
            )
            if pending_email:
                st.write(f"**To:** `{pending_email.get('to', 'unknown')}`")
                st.write(f"**Subject:** `{pending_email.get('subject', 'unknown')}`")
            else:
                st.caption(
                    "Pending details did not load from the API; you can still try approving "
                    "if this chat turn showed **[APPROVAL REQUIRED]**."
                )
            if st.button("Approve Send Email", type="primary", key="approve_email_main"):
                ok, err, resumed_message = post_email_approval(headers)
                if ok:
                    if resumed_message:
                        st.session_state.messages.append(
                            {"role": "assistant", "content": resumed_message}
                        )
                    st.session_state.approval_requested = False
                    st.success("Email approved and resumed.")
                    st.rerun()
                else:
                    st.error(f"Approval failed: {err}")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if not (prompt := st.chat_input("Type your message here...")):
        return

    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        query = urllib.parse.urlencode({
            "message": prompt,
            "session_id": st.session_state.session_id or "",
        })
        req_url = f"{FASTAPI_CHAT_URL}?{query}"
        request = urllib.request.Request(
            req_url,
            headers=headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as resp:
                current_event = "message"
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()

                    # Empty line marks end of an SSE event frame.
                    if not line:
                        current_event = "message"
                        continue

                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                        continue

                    if not line.startswith("data:"):
                        continue

                    data = line.split(":", 1)[1].lstrip()

                    if current_event == "done" or data == "[DONE]":
                        break

                    full_response += data + "\n"
                    message_placeholder.markdown(full_response.rstrip("\n") + "▌")
        except urllib.error.HTTPError as e:
            full_response = f"HTTP error from API: {e.code} — {e.read().decode(errors='replace')}"
        except urllib.error.URLError as e:
            full_response = (
                f"Could not reach `{FASTAPI_CHAT_URL}`. "
                f"Start the API (`Agent/main.py`) and ensure FASTAPI_PORT matches uvicorn "
                f"(default **{_FASTAPI_PORT}**). Reason: {e.reason}"
            )

        message_placeholder.markdown(full_response.rstrip("\n"))

    st.session_state.messages.append({"role": "assistant", "content": full_response})
    if "[APPROVAL REQUIRED]" in full_response:
        st.session_state.approval_requested = True
        st.rerun()


if st.session_state.access_token is None:
    login()
else:
    chat_interface()

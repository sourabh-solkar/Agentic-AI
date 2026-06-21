import json
import os
import urllib.error
import urllib.parse
import urllib.request

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_javascript import st_javascript

_FASTAPI_HOST = os.getenv("FASTAPI_HOST", "127.0.0.1")
_FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "9005"))
_FASTAPI_BASE_URL = f"http://{_FASTAPI_HOST}:{_FASTAPI_PORT}"
FASTAPI_CHAT_URL = f"{_FASTAPI_BASE_URL}/chat"
FASTAPI_LOGIN_URL = f"{_FASTAPI_BASE_URL}/login"
FASTAPI_REGISTER_URL = f"{_FASTAPI_BASE_URL}/register"
FASTAPI_SESSIONS_URL = f"{_FASTAPI_BASE_URL}/sessions"
FASTAPI_EMAIL_PENDING_URL = f"{_FASTAPI_BASE_URL}/email-approval/pending"
FASTAPI_EMAIL_APPROVE_URL = f"{_FASTAPI_BASE_URL}/email-approval/approve"

ACCESS_TOKEN_LOCAL_STORAGE_KEY = "access_token"
SESSION_ID_LOCAL_STORAGE_KEY = "session_id"


def _local_storage_js() -> str:
    """Target the main Streamlit page localStorage, not the component iframe."""
    return "(() => { try { return window.top.localStorage; } catch (e) { return localStorage; } })()"


def _browser_persist_auth(
    access_token: str | None = None,
    session_id: str | None = None,
) -> None:
    """Write or clear auth credentials in the browser's localStorage."""
    store = _local_storage_js()
    token_key = json.dumps(ACCESS_TOKEN_LOCAL_STORAGE_KEY)
    session_key = json.dumps(SESSION_ID_LOCAL_STORAGE_KEY)

    if access_token:
        token_js = f"{store}.setItem({token_key}, {json.dumps(access_token)});"
    else:
        token_js = f"{store}.removeItem({token_key});"

    if session_id:
        session_js = f"{store}.setItem({session_key}, {json.dumps(session_id)});"
    else:
        session_js = f"{store}.removeItem({session_key});"

    components.html(f"<script>{token_js}{session_js}</script>", height=0)


def _clear_auth_state() -> None:
    st.session_state.access_token = None
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.sessions_list = []
    st.session_state.approval_requested = False
    st.session_state._auth_persisted = False


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def fetch_sessions() -> list[dict]:
    try:
        response = requests.get(FASTAPI_SESSIONS_URL, headers=_auth_headers(), timeout=15)
        if response.status_code == 200:
            return response.json().get("sessions", [])
    except requests.RequestException:
        pass
    return []


def load_session_messages(session_id: str) -> list[dict]:
    try:
        response = requests.get(
            f"{FASTAPI_SESSIONS_URL}/{session_id}/messages",
            headers=_auth_headers(),
            timeout=15,
        )
        if response.status_code == 200:
            return [
                {"role": msg["role"], "content": msg["content"]}
                for msg in response.json().get("messages", [])
            ]
    except requests.RequestException:
        pass
    return []


def create_new_session() -> str | None:
    try:
        response = requests.post(FASTAPI_SESSIONS_URL, headers=_auth_headers(), timeout=15)
        if response.status_code == 200:
            return response.json().get("session_id")
    except requests.RequestException:
        pass
    return None


def delete_session(session_id: str) -> bool:
    try:
        response = requests.delete(
            f"{FASTAPI_SESSIONS_URL}/{session_id}",
            headers=_auth_headers(),
            timeout=15,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _apply_auth(access_token: str, session_id: str | None = None) -> bool:
    """Validate token with the API and populate session state."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(FASTAPI_SESSIONS_URL, headers=headers, timeout=15)
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    st.session_state.access_token = access_token
    st.session_state.sessions_list = response.json().get("sessions", [])

    resolved_session_id = session_id
    if resolved_session_id:
        session_ids = {s["session_id"] for s in st.session_state.sessions_list}
        if resolved_session_id not in session_ids:
            resolved_session_id = None

    if not resolved_session_id and st.session_state.sessions_list:
        resolved_session_id = st.session_state.sessions_list[0]["session_id"]

    st.session_state.session_id = resolved_session_id
    st.session_state.messages = (
        load_session_messages(resolved_session_id) if resolved_session_id else []
    )
    st.session_state.approval_requested = False
    st.session_state._auth_persisted = False
    return True


def _parse_auth_storage(stored) -> dict | None:
    if stored is None:
        return None
    if isinstance(stored, dict):
        return stored
    if isinstance(stored, str):
        try:
            parsed = json.loads(stored)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _restore_auth_from_browser() -> None:
    """On page load, restore login from localStorage if a valid token exists."""
    if st.session_state.access_token is not None:
        return
    if st.session_state.get("_auth_restore_done"):
        return

    stored = st_javascript(
        f"""
        ({{
            access_token: localStorage.getItem({json.dumps(ACCESS_TOKEN_LOCAL_STORAGE_KEY)}),
            session_id: localStorage.getItem({json.dumps(SESSION_ID_LOCAL_STORAGE_KEY)})
        }})
        """,
        key="auth_restore",
    )

    if stored is None:
        return

    st.session_state._auth_restore_done = True

    payload = _parse_auth_storage(stored)
    if not payload:
        return

    access_token = payload.get("access_token")
    if not access_token:
        return

    if _apply_auth(access_token, payload.get("session_id")):
        st.rerun()

    _browser_persist_auth(None, None)


if "access_token" not in st.session_state:
    st.session_state.access_token = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "approval_requested" not in st.session_state:
    st.session_state.approval_requested = False
if "sessions_list" not in st.session_state:
    st.session_state.sessions_list = []


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

    col_login, col_register = st.columns(2)
    with col_login:
        login_clicked = st.button("Log In", use_container_width=True)
    with col_register:
        register_clicked = st.button("Register", use_container_width=True)

    if login_clicked or register_clicked:
        url = FASTAPI_LOGIN_URL if login_clicked else FASTAPI_REGISTER_URL
        response = requests.post(
            url,
            json={"username": username, "password": password},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            session_id = data.get("session_id")
            if not access_token or not _apply_auth(access_token, session_id):
                st.error("Login succeeded but session could not be restored.")
                return
            _browser_persist_auth(access_token, st.session_state.session_id)
            st.session_state._auth_persisted = True
            st.success("Logged in successfully!" if login_clicked else "Account created!")
            st.rerun()
        else:
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else response.text
            st.error(detail or "Request failed")


def _session_label(session: dict) -> str:
    title = (session.get("title") or "").strip()
    if title and title != "New chat":
        return title

    updated = session.get("updated_at") or session.get("created_at")
    if updated:
        try:
            from datetime import datetime

            if isinstance(updated, str):
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            else:
                dt = updated
            return dt.strftime("Chat · %b %d, %I:%M %p")
        except (ValueError, TypeError, AttributeError):
            pass

    return f"Chat · {session['session_id'][:8]}"


def render_session_sidebar() -> None:
    with st.sidebar:
        st.header("Chats")

        if st.button("+ New chat", key="new_chat_btn", use_container_width=True):
            new_session_id = create_new_session()
            if new_session_id:
                st.session_state.session_id = new_session_id
                st.session_state.messages = []
                st.session_state._auth_persisted = False
                st.session_state.sessions_list = fetch_sessions()
                st.rerun()
            else:
                st.error("Could not create a new chat.")

        st.session_state.sessions_list = fetch_sessions()

        if not st.session_state.sessions_list:
            st.caption("No chats yet. Start a new one.")
            return

        for session in st.session_state.sessions_list:
            session_id = session["session_id"]
            label = _session_label(session)
            is_active = session_id == st.session_state.session_id
            if is_active:
                label = f"▶ {label}"

            chat_col, delete_col = st.columns([6, 1])
            with chat_col:
                if st.button(label, key=f"session_{session_id}", use_container_width=True):
                    st.session_state.session_id = session_id
                    st.session_state.messages = load_session_messages(session_id)
                    st.session_state._auth_persisted = False
                    st.session_state.approval_requested = False
                    st.rerun()
            with delete_col:
                if st.button("✕", key=f"delete_{session_id}", help="Delete chat"):
                    if delete_session(session_id):
                        st.session_state.sessions_list = fetch_sessions()
                        if st.session_state.session_id == session_id:
                            st.session_state.session_id = None
                            st.session_state.messages = []
                            if st.session_state.sessions_list:
                                next_id = st.session_state.sessions_list[0]["session_id"]
                                st.session_state.session_id = next_id
                                st.session_state.messages = load_session_messages(next_id)
                        st.session_state._auth_persisted = False
                        st.rerun()
                    else:
                        st.error("Could not delete chat.")


def chat_interface():
    if st.session_state.access_token and not st.session_state.get("_auth_persisted"):
        _browser_persist_auth(
            st.session_state.access_token,
            st.session_state.session_id,
        )
        st.session_state._auth_persisted = True

    render_session_sidebar()

    st.title("Chat with AI")
    st.caption(f"Backend: `{FASTAPI_CHAT_URL}`")

    if st.button("Logout"):
        _browser_persist_auth(None, None)
        _clear_auth_state()

        st.session_state._auth_restore_done = False
        st.rerun()

    if not st.session_state.session_id:
        st.info("Select a chat from the sidebar or create a new one.")
        return

    headers = _auth_headers()
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
            if e.code in (401, 403):
                _browser_persist_auth(None, None)
                _clear_auth_state()
                st.session_state._auth_restore_done = False
                full_response = "Session expired. Please log in again."
                st.warning(full_response)
                st.rerun()
            else:
                full_response = f"HTTP error from API: {e.code} — {e.read().decode(errors='replace')}"
        except urllib.error.URLError as e:
            full_response = (
                f"Could not reach `{FASTAPI_CHAT_URL}`. "
                f"Start the API (`Agent/main.py`) and ensure FASTAPI_PORT matches uvicorn "
                f"(default **{_FASTAPI_PORT}**). Reason: {e.reason}"
            )

        message_placeholder.markdown(full_response.rstrip("\n"))

    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.sessions_list = fetch_sessions()
    if "[APPROVAL REQUIRED]" in full_response:
        st.session_state.approval_requested = True
        st.rerun()


_restore_auth_from_browser()

if st.session_state.access_token is None:
    if not st.session_state.get("_auth_restore_done"):
        st.empty()
        st.stop()
    login()
else:
    chat_interface()

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_cookies_controller import CookieController

_FASTAPI_HOST = os.getenv("FASTAPI_HOST", "127.0.0.1")
_FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "9005"))
_FASTAPI_BASE_URL = f"http://{_FASTAPI_HOST}:{_FASTAPI_PORT}"
FASTAPI_CHAT_URL = f"{_FASTAPI_BASE_URL}/chat"
FASTAPI_LOGIN_URL = f"{_FASTAPI_BASE_URL}/login"
FASTAPI_REGISTER_URL = f"{_FASTAPI_BASE_URL}/register"
FASTAPI_SESSIONS_URL = f"{_FASTAPI_BASE_URL}/sessions"
FASTAPI_APPROVAL_PENDING_URL = f"{_FASTAPI_BASE_URL}/approval/pending"
FASTAPI_APPROVAL_APPROVE_URL = f"{_FASTAPI_BASE_URL}/approval/approve"
FASTAPI_EMAIL_PENDING_URL = FASTAPI_APPROVAL_PENDING_URL
FASTAPI_EMAIL_APPROVE_URL = FASTAPI_APPROVAL_APPROVE_URL

ACCESS_TOKEN_COOKIE = "access_token"
SESSION_ID_COOKIE = "session_id"
AUTH_COOKIES_STATE_KEY = "auth_cookies"
AUTH_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 days


def _ensure_cookie_dict(cookies: CookieController) -> dict:
    """CookieController may hold None before hydration; never mutate the widget key."""
    raw = getattr(cookies, "_CookieController__cookies", None)
    if isinstance(raw, dict):
        return raw
    empty: dict = {}
    cookies._CookieController__cookies = empty
    return empty


def _cookie_controller() -> CookieController:
    """Create the cookie controller. Must run every script pass so it stays mounted."""
    controller = CookieController(key=AUTH_COOKIES_STATE_KEY)
    _ensure_cookie_dict(controller)
    return controller


def _cookie_get(cookies: CookieController, name: str):
    """Read a cookie without raising when the controller cache is not ready."""
    return _ensure_cookie_dict(cookies).get(name)


def _persist_auth(
    cookies: CookieController,
    access_token: str | None = None,
    session_id: str | None = None,
) -> None:
    """Write or clear auth credentials in browser cookies."""
    _ensure_cookie_dict(cookies)

    expires = datetime.now() + timedelta(seconds=AUTH_COOKIE_MAX_AGE_SECONDS)
    common = {
        "max_age": AUTH_COOKIE_MAX_AGE_SECONDS,
        "expires": expires,
        "same_site": "lax",
        "path": "/",
    }
    if access_token:
        cookies.set(ACCESS_TOKEN_COOKIE, access_token, **common)
    else:
        cookies.remove(ACCESS_TOKEN_COOKIE)

    if session_id:
        cookies.set(SESSION_ID_COOKIE, session_id, **common)
    else:
        cookies.remove(SESSION_ID_COOKIE)


def _clear_auth_state() -> None:
    st.session_state.access_token = None
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.sessions_list = []
    st.session_state.approval_requested = False


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
                {
                    "id": msg.get("id"),
                    "role": msg["role"],
                    "content": msg["content"],
                    "trace_id": msg.get("trace_id"),
                    "trace_url": msg.get("trace_url"),
                    "created_at": msg.get("created_at"),
                }
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


def _apply_auth(access_token: str, session_id: str | None = None) -> str:
    """Validate token with the API and populate session state.

    Returns "ok", "invalid" (clear stored token), or "unavailable" (keep token).
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(FASTAPI_SESSIONS_URL, headers=headers, timeout=15)
    except requests.RequestException:
        return "unavailable"

    if response.status_code in (401, 403):
        return "invalid"
    if response.status_code != 200:
        return "unavailable"

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
    return "ok"


def _restore_auth_from_cookies(cookies: CookieController) -> None:
    """On page load, restore login from cookies if a valid token exists."""
    if st.session_state.access_token is not None:
        return
    if st.session_state.get("_auth_restore_done"):
        return

    # CookieController loads browser cookies asynchronously. Give the component
    # time to report values, then re-read on a fresh run.
    passes = st.session_state.get("_cookie_hydrate_passes", 0)
    access_token = _cookie_get(cookies, ACCESS_TOKEN_COOKIE)
    session_id = _cookie_get(cookies, SESSION_ID_COOKIE)

    if not access_token and passes < 2:
        st.session_state._cookie_hydrate_passes = passes + 1
        # Wall-clock wait so the browser can send cookies before the next run.
        time.sleep(0.8)
        st.rerun()

    st.session_state._auth_restore_done = True

    if not access_token:
        return

    result = _apply_auth(access_token, session_id)
    if result == "ok":
        st.rerun()
    elif result == "invalid":
        _persist_auth(cookies, None, None)


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

# Keep the cookie component mounted on every run.
_cookies = _cookie_controller()


def _read_sse(resp, on_status, on_message, on_trace=None) -> tuple[str, dict | None]:
    """Read a graph SSE stream. Status lines are live steps; message lines are the answer."""
    full_response = ""
    trace_meta = None
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

        if current_event == "status":
            on_status(data)
            continue

        if current_event == "trace":
            try:
                trace_meta = json.loads(data)
            except json.JSONDecodeError:
                trace_meta = {"trace_url": data}
            if on_trace:
                on_trace(trace_meta)
            continue

        full_response += data + "\n"
        on_message(full_response)
    return full_response, trace_meta


def _focus_message_id() -> int | None:
    raw = st.query_params.get("msg")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _message_permalink(message_id: int | None) -> str | None:
    if not message_id:
        return None
    session_id = st.session_state.session_id or ""
    return f"?session={session_id}&msg={message_id}"


def _render_chat_message(message: dict, *, focused: bool = False) -> None:
    role = message.get("role", "assistant")
    content = message.get("content") or ""
    message_id = message.get("id")
    trace_url = message.get("trace_url")
    anchor = f"msg-{message_id}" if message_id else None

    with st.chat_message(role):
        if anchor:
            st.markdown(
                f'<div id="{anchor}"></div>',
                unsafe_allow_html=True,
            )
        if focused:
            st.info("Focused message")
        st.markdown(content)

        meta_bits: list[str] = []
        if role == "assistant" and trace_url:
            meta_bits.append(f"[View trace]({trace_url})")
        permalink = _message_permalink(message_id)
        if permalink:
            meta_bits.append(f"[Link to message]({permalink})")
        if meta_bits:
            st.caption(" · ".join(meta_bits))


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
            if not access_token or _apply_auth(access_token, session_id) != "ok":
                st.error("Login succeeded but session could not be restored.")
                return
            _persist_auth(_cookies, access_token, st.session_state.session_id)
            st.session_state._auth_restore_done = True
            st.success("Logged in successfully!" if login_clicked else "Account created!")
            # Give the cookie component time to write before rerun.
            time.sleep(0.4)
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
        st.markdown("### Chats")
        st.caption("Your conversations in this account.")

        if st.button("New chat", key="new_chat_btn", use_container_width=True, type="primary"):
            new_session_id = create_new_session()
            if new_session_id:
                st.session_state.session_id = new_session_id
                st.session_state.messages = []
                _persist_auth(
                    _cookies,
                    st.session_state.access_token,
                    new_session_id,
                )
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
                    _persist_auth(
                        _cookies,
                        st.session_state.access_token,
                        session_id,
                    )
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
                        _persist_auth(
                            _cookies,
                            st.session_state.access_token,
                            st.session_state.session_id,
                        )
                        st.rerun()
                    else:
                        st.error("Could not delete chat.")


def chat_interface():
    render_session_sidebar()

    # Honor deep links like ?session=<id>&msg=<message_id>
    qp_session = st.query_params.get("session")
    if qp_session and qp_session != st.session_state.session_id:
        session_ids = {s["session_id"] for s in fetch_sessions()}
        if qp_session in session_ids:
            st.session_state.session_id = qp_session
            st.session_state.messages = load_session_messages(qp_session)
            st.session_state.approval_requested = False

    title_col, logout_col = st.columns([6, 1])
    with title_col:
        st.title("Villa assistant")
        st.caption("Ask about availability, bookings, or general questions.")
    with logout_col:
        st.write("")
        if st.button("Logout", use_container_width=True):
            _persist_auth(_cookies, None, None)
            _clear_auth_state()
            st.session_state._auth_restore_done = True
            time.sleep(0.3)
            st.rerun()

    if not st.session_state.session_id:
        st.info("Select a chat from the sidebar or create a new one.")
        return

    headers = _auth_headers()
    pending_approval = None
    pending_fetch_error = None
    try:
        pending_resp = requests.get(
            FASTAPI_APPROVAL_PENDING_URL,
            headers=headers,
            params={"session_id": st.session_state.session_id},
            timeout=15,
        )
        if pending_resp.status_code == 200:
            pending_approval = pending_resp.json().get("pending")
        else:
            pending_fetch_error = f"HTTP {pending_resp.status_code}: {pending_resp.text}"
    except requests.RequestException:
        pending_fetch_error = "Could not reach approval endpoint."

    if pending_approval:
        st.session_state.approval_requested = True

    if pending_fetch_error:
        st.caption(f"Approval status unavailable: {pending_fetch_error}")

    need_approval_ui = st.session_state.approval_requested

    if need_approval_ui:
        with st.container(border=True):
            action = (pending_approval or {}).get("action", "human_review")
            if action == "confirm_booking":
                st.markdown("### Confirm booking")
                st.caption(
                    "The assistant paused before writing the reservation. "
                    "Review the details, then approve to complete the booking."
                )
                if pending_approval:
                    st.write(f"**Villa:** {pending_approval.get('villa_name', 'unknown')}")
                    st.write(f"**Location:** {pending_approval.get('location', '')}")
                    st.write(
                        f"**Check-in:** `{pending_approval.get('check_in_date', '')}`"
                    )
                    st.write(
                        f"**Check-out:** `{pending_approval.get('check_out_date', '')}`"
                    )
                    price = pending_approval.get("price_per_night")
                    if price:
                        st.write(f"**Price / night:** ₹{price}")
            elif action == "human_review":
                st.markdown("### Human review required")
                st.caption(
                    "This request is outside automated handling. "
                    "Approve to escalate to a human agent."
                )
                if pending_approval:
                    st.write(f"**Query:** {pending_approval.get('query', 'unknown')}")
            else:
                st.markdown("### Pending email send")
                st.caption(
                    "The assistant paused for approval. Review the draft below, then approve."
                )
                if pending_approval:
                    st.write(f"**To:** `{pending_approval.get('to', 'unknown')}`")
                    st.write(f"**Subject:** `{pending_approval.get('subject', 'unknown')}`")
            if not pending_approval:
                st.caption(
                    "Pending details did not load from the API; you can still try approving "
                    "if this chat turn showed **[APPROVAL REQUIRED]**."
                )
            if action == "confirm_booking":
                approve_label = "Approve booking"
            elif action == "human_review":
                approve_label = "Approve escalation"
            else:
                approve_label = "Approve Send Email"
            if st.button(approve_label, type="primary", key="approve_main"):
                run_status = st.status("Resuming…", expanded=True)
                message_placeholder = st.empty()
                resumed_message = ""
                trace_meta = None
                approve_url = (
                    f"{FASTAPI_APPROVAL_APPROVE_URL}?"
                    + urllib.parse.urlencode(
                        {"session_id": st.session_state.session_id or ""}
                    )
                )
                approve_request = urllib.request.Request(
                    approve_url,
                    data=b"",
                    headers=headers,
                    method="POST",
                )
                approve_ok = False
                try:
                    with urllib.request.urlopen(approve_request, timeout=120) as resp:
                        resumed_message, trace_meta = _read_sse(
                            resp,
                            on_status=lambda step: (
                                run_status.write(step),
                                run_status.update(label=step),
                            ),
                            on_message=lambda text: message_placeholder.markdown(
                                text.rstrip("\n") + "▌"
                            ),
                        )
                    run_status.update(label="Finished", state="complete", expanded=True)
                    message_placeholder.markdown(resumed_message.rstrip("\n"))
                    approve_ok = True
                except urllib.error.HTTPError as e:
                    run_status.update(label="Approval failed", state="error")
                    detail = e.read().decode(errors="replace")
                    st.error(f"Approval failed: HTTP {e.code} — {detail}")
                except urllib.error.URLError as e:
                    run_status.update(label="Approval failed", state="error")
                    st.error(f"Approval failed: {e.reason}")

                if approve_ok and resumed_message.startswith("[error]"):
                    run_status.update(label="Approval failed", state="error")
                    st.error(resumed_message.strip())
                    approve_ok = False

                if approve_ok:
                    if resumed_message.strip():
                        st.session_state.messages.append(
                            {
                                "id": (trace_meta or {}).get("message_id"),
                                "role": "assistant",
                                "content": resumed_message,
                                "trace_id": (trace_meta or {}).get("trace_id"),
                                "trace_url": (trace_meta or {}).get("trace_url"),
                            }
                        )
                    st.session_state.approval_requested = (
                        "[APPROVAL REQUIRED]" in resumed_message
                    )
                    st.rerun()

    focus_id = _focus_message_id()
    for message in st.session_state.messages:
        _render_chat_message(
            message,
            focused=bool(focus_id and message.get("id") == focus_id),
        )

    if focus_id:
        components.html(
            f"""
            <script>
            const doc = window.parent.document;
            const el = doc.getElementById("msg-{focus_id}");
            if (el) {{
              el.scrollIntoView({{ behavior: "smooth", block: "center" }});
            }}
            </script>
            """,
            height=0,
        )

    if not (prompt := st.chat_input("Ask about villas, dates, or bookings…")):
        return

    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        run_status = st.status("Working…", expanded=True)
        message_placeholder = st.empty()
        trace_placeholder = st.empty()
        full_response = ""
        trace_meta = None
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
                full_response, trace_meta = _read_sse(
                    resp,
                    on_status=lambda step: (
                        run_status.write(step),
                        run_status.update(label=step),
                    ),
                    on_message=lambda text: message_placeholder.markdown(
                        text.rstrip("\n") + "▌"
                    ),
                    on_trace=lambda meta: (
                        trace_placeholder.caption(
                            f"[View trace]({meta['trace_url']})"
                        )
                        if meta.get("trace_url")
                        else None
                    ),
                )
            if full_response.startswith("[error]"):
                run_status.update(label="Something went wrong", state="error", expanded=True)
            else:
                run_status.update(label="Finished", state="complete", expanded=True)
        except urllib.error.HTTPError as e:
            run_status.update(label="Request failed", state="error")
            if e.code in (401, 403):
                _persist_auth(_cookies, None, None)
                _clear_auth_state()
                st.session_state._auth_restore_done = True
                full_response = "Session expired. Please log in again."
                st.warning(full_response)
                time.sleep(0.3)
                st.rerun()
            else:
                full_response = f"HTTP error from API: {e.code} — {e.read().decode(errors='replace')}"
        except urllib.error.URLError as e:
            run_status.update(label="Request failed", state="error")
            full_response = (
                f"Could not reach `{FASTAPI_CHAT_URL}`. "
                f"Start the API (`Agent/main.py`) and ensure FASTAPI_PORT matches uvicorn "
                f"(default **{_FASTAPI_PORT}**). Reason: {e.reason}"
            )

        message_placeholder.markdown(full_response.rstrip("\n"))
        if trace_meta and trace_meta.get("trace_url"):
            trace_placeholder.caption(f"[View trace]({trace_meta['trace_url']})")

    st.session_state.messages.append(
        {
            "id": (trace_meta or {}).get("message_id"),
            "role": "assistant",
            "content": full_response,
            "trace_id": (trace_meta or {}).get("trace_id"),
            "trace_url": (trace_meta or {}).get("trace_url"),
        }
    )
    st.session_state.sessions_list = fetch_sessions()
    if "[APPROVAL REQUIRED]" in full_response:
        st.session_state.approval_requested = True
        st.rerun()


_restore_auth_from_cookies(_cookies)

if st.session_state.access_token is None:
    if not st.session_state.get("_auth_restore_done"):
        st.empty()
        st.stop()
    login()
else:
    chat_interface()

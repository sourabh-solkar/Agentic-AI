import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import requests
import streamlit as st
import streamlit.components.v1 as components
from streamlit_cookies_controller import CookieController

st.set_page_config(
    page_title="Villa assistant",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded",
)

_FASTAPI_HOST = os.getenv("FASTAPI_HOST", "127.0.0.1")
_FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "9005"))
_FASTAPI_BASE_URL = f"http://{_FASTAPI_HOST}:{_FASTAPI_PORT}"
FASTAPI_CHAT_URL = f"{_FASTAPI_BASE_URL}/chat"
FASTAPI_LOGIN_URL = f"{_FASTAPI_BASE_URL}/login"
FASTAPI_REGISTER_URL = f"{_FASTAPI_BASE_URL}/register"
FASTAPI_ME_URL = f"{_FASTAPI_BASE_URL}/me"
FASTAPI_SESSIONS_URL = f"{_FASTAPI_BASE_URL}/sessions"
FASTAPI_APPROVAL_PENDING_URL = f"{_FASTAPI_BASE_URL}/approval/pending"
FASTAPI_APPROVAL_APPROVE_URL = f"{_FASTAPI_BASE_URL}/approval/approve"
FASTAPI_EMAIL_PENDING_URL = FASTAPI_APPROVAL_PENDING_URL
FASTAPI_EMAIL_APPROVE_URL = FASTAPI_APPROVAL_APPROVE_URL

APP_NAME = "Villa assistant"
APP_TAGLINE = "Ask about availability, bookings, or general questions."

_GMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@gmail\.com$", re.IGNORECASE)

# Empty-chat starters shown as clickable chips above the input.
DEMO_PROMPTS = [
    "Find villas in Goa for 4 people from 2026-12-20 to 2026-12-25, then book the best option.",
    "Show me available villas in Mumbai with prices.",
    "Book Sea Breeze Villa in Mumbai for 2 people from 2026-11-10 to 2026-11-12.",
]

# ChatGPT-style shell (light sidebar + floating input) adapted from the Figma reference.
_CHAT_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;500;600;700&display=swap');

html, body, [class*="css"] {
  font-family: "DM Sans", "Segoe UI", sans-serif;
}

:root {
  --va-blue: #5B6CFF;
  --va-blue-hover: #4A5AE6;
  --va-blue-soft: #EEF1FF;
  --va-bg: #F5F6FA;
  --va-surface: #FFFFFF;
  --va-text: #1F2937;
  --va-muted: #9CA3AF;
  --va-border: #E8EAF0;
  --va-danger: #EF4444;
  --va-radius-pill: 999px;
  --va-shadow: 0 8px 28px rgba(31, 41, 55, 0.08);
}

[data-testid="stAppViewContainer"] {
  background: var(--va-bg);
}

[data-testid="stHeader"] {
  background: transparent;
}

section[data-testid="stSidebar"] {
  background: var(--va-surface) !important;
  border-right: 1px solid var(--va-border);
}

section[data-testid="stSidebar"] > div {
  padding-top: 1.1rem;
  padding-bottom: 1rem;
}

section[data-testid="stSidebar"] .block-container {
  padding-top: 0.5rem;
}

.va-brand {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  margin: 0 0 1.1rem 0.15rem;
  font-weight: 700;
  font-size: 1.2rem;
  letter-spacing: -0.02em;
  color: var(--va-text);
}
.va-brand-mark {
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 0.55rem;
  background: linear-gradient(135deg, #5B6CFF 0%, #7C8CFF 100%);
  color: white;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  font-weight: 700;
}
.va-section-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--va-muted);
  font-size: 0.78rem;
  font-weight: 600;
  margin: 1rem 0.2rem 0.55rem;
  text-transform: none;
  letter-spacing: 0.01em;
}

section[data-testid="stSidebar"] .chat-list-row {
  margin-bottom: 0.2rem;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
  align-items: center;
  gap: 0.25rem;
  flex-wrap: nowrap !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"] {
  min-width: 0 !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:last-child {
  flex: 0 0 2.25rem !important;
  width: 2.25rem !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:first-child {
  flex: 1 1 auto !important;
}
section[data-testid="stSidebar"] .stButton > button {
  min-height: 2.35rem;
  padding: 0.35rem 0.85rem;
  font-size: 0.86rem;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 0.85rem !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  color: var(--va-text) !important;
  justify-content: flex-start;
  box-shadow: none !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--va-blue-soft) !important;
  border-color: transparent !important;
  color: var(--va-text) !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:last-child .stButton > button {
  padding-left: 0 !important;
  padding-right: 0 !important;
  min-width: 2.1rem;
  justify-content: center;
  color: var(--va-muted) !important;
  background: transparent !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:last-child .stButton > button:hover {
  color: var(--va-danger) !important;
  background: #FEE2E2 !important;
}
/* Active conversation: soft blue chip (not solid CTA). */
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:first-child .stButton > button[kind="primary"],
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:first-child .stButton > button[data-testid="baseButton-primary"] {
  background: var(--va-blue-soft) !important;
  color: var(--va-blue) !important;
  font-weight: 600 !important;
  border: none !important;
  box-shadow: none !important;
  border-radius: 0.85rem !important;
}
/* Solid blue pill reserved for New chat / Upgrade. */
section[data-testid="stSidebar"] > div .stButton > button[kind="primary"],
section[data-testid="stSidebar"] > div .stButton > button[data-testid="baseButton-primary"] {
  background: var(--va-blue) !important;
  border: none !important;
  color: white !important;
  border-radius: var(--va-radius-pill) !important;
  font-weight: 600 !important;
  justify-content: center !important;
  box-shadow: 0 6px 16px rgba(91, 108, 255, 0.28) !important;
}
section[data-testid="stSidebar"] > div .stButton > button[kind="primary"]:hover,
section[data-testid="stSidebar"] > div .stButton > button[data-testid="baseButton-primary"]:hover {
  background: var(--va-blue-hover) !important;
  border: none !important;
  color: white !important;
}
/* Re-assert soft active style with higher specificity than New chat. */
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:first-child .stButton > button[kind="primary"],
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"]
> div[data-testid="stColumn"]:first-child .stButton > button[data-testid="baseButton-primary"] {
  background: var(--va-blue-soft) !important;
  color: var(--va-blue) !important;
  box-shadow: none !important;
  border-radius: 0.85rem !important;
  justify-content: flex-start !important;
}

.va-user-card {
  margin-top: 0.75rem;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--va-border);
  border-radius: var(--va-radius-pill);
  background: var(--va-surface);
  display: flex;
  align-items: center;
  gap: 0.65rem;
}
.va-avatar {
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: linear-gradient(135deg, #5B6CFF, #A5B4FC);
  color: white;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.8rem;
  font-weight: 700;
  flex-shrink: 0;
}
.va-user-meta {
  min-width: 0;
  flex: 1;
}
.va-user-name {
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--va-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.va-user-credits {
  font-size: 0.75rem;
  color: var(--va-muted);
}

.va-hero {
  max-width: 42rem;
  margin: 8vh auto 1.5rem;
  text-align: center;
}
.va-hero h1 {
  margin: 0;
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--va-text);
}
.va-hero p {
  margin: 0.65rem 0 0;
  color: var(--va-muted);
  font-size: 1rem;
}

.va-suggest-wrap {
  max-width: 42rem;
  margin: 0 auto 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.va-suggest-wrap a {
  display: block;
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  padding: 0.7rem 1.05rem;
  border: 1px solid var(--va-border);
  border-radius: var(--va-radius-pill);
  background: var(--va-surface);
  color: var(--va-text);
  font-size: 0.9rem;
  line-height: 1.4;
  text-decoration: none;
  box-shadow: 0 2px 10px rgba(31, 41, 55, 0.04);
  transition: border-color 0.15s ease, box-shadow 0.15s ease, color 0.15s ease;
}
.va-suggest-wrap a:hover {
  border-color: #C7CEFF;
  color: var(--va-blue);
  box-shadow: 0 4px 16px rgba(91, 108, 255, 0.12);
}

.va-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}
.va-topbar-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--va-text);
}
.va-credit-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.8rem;
  border-radius: var(--va-radius-pill);
  background: var(--va-blue-soft);
  color: var(--va-blue);
  font-size: 0.8rem;
  font-weight: 600;
}
.va-credit-pill.warn {
  background: #FEF3C7;
  color: #B45309;
}

div[data-testid="stChatMessage"] {
  background: transparent;
  padding: 0.35rem 0;
}
div[data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
  background: var(--va-surface);
  border: 1px solid var(--va-border);
  border-radius: 1.1rem;
  padding: 0.85rem 1.05rem;
  box-shadow: 0 2px 10px rgba(31, 41, 55, 0.03);
}

[data-testid="stBottomBlockContainer"] {
  background: transparent !important;
  padding-bottom: 0.75rem;
}
[data-testid="stChatInput"] {
  background: var(--va-surface) !important;
  border: 1px solid var(--va-border) !important;
  border-radius: var(--va-radius-pill) !important;
  box-shadow: var(--va-shadow) !important;
  padding: 0.35rem 0.5rem 0.35rem 1rem !important;
}
[data-testid="stChatInput"] textarea {
  font-size: 0.95rem !important;
}
[data-testid="stChatInput"] button {
  background: var(--va-blue) !important;
  border: none !important;
  border-radius: 50% !important;
  color: white !important;
}
[data-testid="stChatInput"] button:hover {
  background: var(--va-blue-hover) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 1.1rem !important;
  border-color: var(--va-border) !important;
  background: var(--va-surface);
  box-shadow: 0 2px 12px rgba(31, 41, 55, 0.04);
}

.main .block-container {
  padding-top: 1.5rem;
  padding-bottom: 6rem;
  max-width: 860px;
}

.va-login-card {
  margin: 6vh 0 1.25rem;
  padding: 0.25rem 0.15rem 0;
}
.va-login-card h1 {
  margin: 0;
  font-size: 1.7rem;
  font-weight: 700;
  letter-spacing: -0.03em;
}
.va-login-card p {
  margin: 0.45rem 0 0;
  color: var(--va-muted);
  font-size: 0.95rem;
}
</style>
"""


def _inject_chat_theme() -> None:
    st.markdown(_CHAT_THEME_CSS, unsafe_allow_html=True)


def _user_initials(username: str | None) -> str:
    if not username:
        return "U"
    local = username.split("@")[0]
    parts = re.split(r"[._\-\s]+", local)
    letters = [p[0] for p in parts if p]
    if not letters:
        return local[:1].upper() or "U"
    return "".join(letters[:2]).upper()

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
    st.session_state.credits = None
    st.session_state.username = None


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def _is_valid_gmail(email: str) -> bool:
    value = (email or "").strip()
    return bool(value and _GMAIL_RE.match(value))


def fetch_me() -> dict | None:
    """Load current user profile (credits + username) from the API."""
    try:
        response = requests.get(FASTAPI_ME_URL, headers=_auth_headers(), timeout=15)
        if response.status_code == 200:
            data = response.json()
            st.session_state.credits = int(data.get("credits", 0))
            st.session_state.username = data.get("username")
            return data
    except requests.RequestException:
        pass
    return None


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
    fetch_me()
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
if "credits" not in st.session_state:
    st.session_state.credits = None
if "username" not in st.session_state:
    st.session_state.username = None

# Keep the cookie component mounted on every run.
_cookies = _cookie_controller()


def _read_sse(
    resp,
    on_status,
    on_message,
    on_trace=None,
    on_credits=None,
) -> tuple[str, dict | None]:
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

        if current_event == "credits":
            try:
                credits_payload = json.loads(data)
            except json.JSONDecodeError:
                credits_payload = {}
            if isinstance(credits_payload.get("credits"), int):
                st.session_state.credits = credits_payload["credits"]
            if on_credits:
                on_credits(credits_payload)
            continue

        if current_event != "message":
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
    message_kwargs = {"avatar": "🏡"} if role == "assistant" else {}

    with st.chat_message(role, **message_kwargs):
        if anchor:
            st.markdown(
                f'<div id="{anchor}"></div>',
                unsafe_allow_html=True,
            )
        if role == "assistant":
            st.caption(f"**{APP_NAME}**")
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
    _inject_chat_theme()
    _, mid, _ = st.columns([1, 1.35, 1])
    with mid:
        st.markdown(
            (
                f'<div class="va-login-card">'
                f'<div class="va-brand" style="margin-bottom:0.85rem">'
                f'<span class="va-brand-mark">V</span>{APP_NAME}</div>'
                f"<h1>Welcome back</h1>"
                f"<p>Register with your Gmail to get free credits and start chatting.</p>"
                f"</div>"
            ),
            unsafe_allow_html=True,
        )

        email = st.text_input("Gmail address", placeholder="you@gmail.com")
        password = st.text_input("Password", type="password")

        col_login, col_register = st.columns(2)
        with col_login:
            login_clicked = st.button("Log In", use_container_width=True, type="primary")
        with col_register:
            register_clicked = st.button("Register", use_container_width=True)

        if not (login_clicked or register_clicked):
            return

        if not email.strip() or not password:
            st.error("Gmail and password are required.")
            return
        if not _is_valid_gmail(email):
            st.error("Please use a valid Gmail address ending with @gmail.com.")
            return

        url = FASTAPI_LOGIN_URL if login_clicked else FASTAPI_REGISTER_URL
        response = requests.post(
            url,
            json={"username": email.strip().lower(), "password": password},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            access_token = data.get("access_token")
            session_id = data.get("session_id")
            if data.get("credits") is not None:
                st.session_state.credits = int(data["credits"])
            if data.get("username"):
                st.session_state.username = data["username"]
            if not access_token or _apply_auth(access_token, session_id) != "ok":
                st.error("Login succeeded but session could not be restored.")
                return
            _persist_auth(_cookies, access_token, st.session_state.session_id)
            st.session_state._auth_restore_done = True
            if register_clicked:
                credits = st.session_state.credits
                st.success(
                    f"Account created! You have {credits} free credits to start chatting."
                )
            else:
                st.success("Logged in successfully!")
            # Give the cookie component time to write before rerun.
            time.sleep(0.4)
            st.rerun()

        detail = (
            response.json().get("detail")
            if response.headers.get("content-type", "").startswith("application/json")
            else response.text
        )
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        if response.status_code == 409:
            st.warning(
                "An account with this Gmail already exists. Please log in instead."
            )
        elif response.status_code == 401:
            st.error("Incorrect Gmail or password. If you are new, click Register.")
        else:
            st.error(detail or "Request failed")


def _session_label(session: dict, *, max_len: int = 28) -> str:
    title = (session.get("title") or "").strip()
    if title and title != "New chat":
        label = title
    else:
        label = None
        updated = session.get("updated_at") or session.get("created_at")
        if updated:
            try:
                if isinstance(updated, str):
                    dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                else:
                    dt = updated
                label = dt.strftime("%b %d · %I:%M %p")
            except (ValueError, TypeError, AttributeError):
                pass
        if not label:
            label = f"Chat · {session['session_id'][:8]}"

    if len(label) > max_len:
        return label[: max_len - 1].rstrip() + "…"
    return label


def _credits_label() -> str:
    credits = st.session_state.get("credits")
    if credits is None:
        fetch_me()
        credits = st.session_state.get("credits")
    if credits is None:
        return "Credits: —"
    if credits <= 0:
        return f"{credits} credits · upgrade needed"
    return f"{credits} credits left"


def _render_credits_badge() -> None:
    """Compact credits pill for the main chat top bar."""
    credits = st.session_state.get("credits")
    if credits is None:
        fetch_me()
        credits = st.session_state.get("credits")
    if credits is None:
        st.markdown(
            '<span class="va-credit-pill">Credits: —</span>',
            unsafe_allow_html=True,
        )
        return
    warn = " warn" if credits <= 0 else ""
    label = f"{credits} credits" if credits > 0 else f"{credits} credits · upgrade"
    st.markdown(
        f'<span class="va-credit-pill{warn}">{label}</span>',
        unsafe_allow_html=True,
    )


def _delete_session_and_refresh(session_id: str) -> None:
    if not delete_session(session_id):
        st.error("Could not delete chat.")
        return
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


def render_session_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            f'<div class="va-brand"><span class="va-brand-mark">V</span>{APP_NAME}</div>',
            unsafe_allow_html=True,
        )

        if st.button("+  New chat", key="new_chat_btn", use_container_width=True, type="primary"):
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

        st.markdown(
            '<div class="va-section-label"><span>Your conversations</span></div>',
            unsafe_allow_html=True,
        )

        st.session_state.sessions_list = fetch_sessions()

        if not st.session_state.sessions_list:
            st.caption("No chats yet. Start a new one.")
        else:
            for session in st.session_state.sessions_list:
                session_id = session["session_id"]
                label = _session_label(session)
                is_active = session_id == st.session_state.session_id
                if is_active:
                    label = f"●  {label}"

                chat_col, delete_col = st.columns([5, 1], gap="small")
                with chat_col:
                    if st.button(
                        label,
                        key=f"session_{session_id}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary",
                    ):
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
                    if st.button(
                        "×",
                        key=f"delete_{session_id}",
                        help="Delete chat",
                        use_container_width=True,
                    ):
                        _delete_session_and_refresh(session_id)

        if st.session_state.get("credits") is not None and st.session_state.credits <= 0:
            st.warning("Out of credits. Upgrade to keep chatting.")
            if st.button("Upgrade plan", key="sidebar_upgrade_btn", use_container_width=True):
                st.info("Paid plans coming soon. Contact support to upgrade.")

        st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)
        username = html.escape(st.session_state.get("username") or "Account")
        initials = html.escape(_user_initials(st.session_state.get("username")))
        credits_text = html.escape(_credits_label())
        st.markdown(
            (
                f'<div class="va-user-card">'
                f'<div class="va-avatar">{initials}</div>'
                f'<div class="va-user-meta">'
                f'<div class="va-user-name">{username}</div>'
                f'<div class="va-user-credits">{credits_text}</div>'
                f"</div></div>"
            ),
            unsafe_allow_html=True,
        )
        if st.button("Logout", key="sidebar_logout_btn", use_container_width=True):
            _persist_auth(_cookies, None, None)
            _clear_auth_state()
            st.session_state._auth_restore_done = True
            time.sleep(0.3)
            st.rerun()


def chat_interface():
    _inject_chat_theme()
    # Refresh credits on every chat view so the badge stays accurate.
    fetch_me()
    render_session_sidebar()

    # Honor deep links like ?session=<id>&msg=<message_id>
    qp_session = st.query_params.get("session")
    if qp_session and qp_session != st.session_state.session_id:
        session_ids = {s["session_id"] for s in fetch_sessions()}
        if qp_session in session_ids:
            st.session_state.session_id = qp_session
            st.session_state.messages = load_session_messages(qp_session)
            st.session_state.approval_requested = False

    title_col, credits_col = st.columns([5, 2])
    with title_col:
        st.markdown(
            f'<div class="va-topbar"><div class="va-topbar-title">{APP_NAME}</div></div>',
            unsafe_allow_html=True,
        )
    with credits_col:
        _render_credits_badge()

    credits = st.session_state.get("credits")
    if credits is not None and credits <= 0:
        st.error(
            "You don't have enough credits left. "
            "Please upgrade your plan to continue asking questions."
        )
        if st.button("Upgrade plan", key="main_upgrade_btn", type="primary"):
            st.info("Paid plans coming soon. Contact support to upgrade.")

    if not st.session_state.session_id:
        st.markdown(
            (
                f'<div class="va-hero"><h1>How can I help you?</h1>'
                f"<p>Select a chat from the sidebar or create a new one.</p></div>"
            ),
            unsafe_allow_html=True,
        )
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

    out_of_credits = (
        st.session_state.get("credits") is not None and st.session_state.credits <= 0
    )
    chat_disabled = out_of_credits

    # Clickable suggestion text uses ?suggest=<i>; turn it into a pending prompt.
    suggest_raw = st.query_params.get("suggest")
    if suggest_raw is not None:
        try:
            suggest_idx = int(suggest_raw)
            if 0 <= suggest_idx < len(DEMO_PROMPTS):
                st.session_state._pending_demo_prompt = DEMO_PROMPTS[suggest_idx]
        except ValueError:
            pass
        del st.query_params["suggest"]

    # Suggested demos: pill chips above the chat input (empty state).
    if not st.session_state.messages and not need_approval_ui and not chat_disabled:
        st.markdown(
            (
                f'<div class="va-hero">'
                f"<h1>How can I help you?</h1>"
                f"<p>{APP_TAGLINE}</p>"
                f"</div>"
            ),
            unsafe_allow_html=True,
        )
        links = "".join(
            f'<a href="?suggest={i}">{html.escape(text)}</a>'
            for i, text in enumerate(DEMO_PROMPTS)
        )
        st.markdown(
            f'<div class="va-suggest-wrap">{links}</div>',
            unsafe_allow_html=True,
        )

    typed_prompt = st.chat_input(
        "What's on your mind? Ask about villas, dates, or bookings…"
        if not chat_disabled
        else "Upgrade required — no credits left",
        disabled=chat_disabled,
    )
    prompt = st.session_state.pop("_pending_demo_prompt", None) or typed_prompt
    if not prompt:
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
                remaining_header = resp.headers.get("X-Credits-Remaining")
                if remaining_header is not None:
                    try:
                        st.session_state.credits = int(remaining_header)
                    except ValueError:
                        pass
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
                fetch_me()
        except urllib.error.HTTPError as e:
            run_status.update(label="Request failed", state="error")
            body = e.read().decode(errors="replace")
            if e.code == 402:
                st.session_state.credits = 0
                try:
                    detail = json.loads(body).get("detail", {})
                    if isinstance(detail, dict):
                        full_response = detail.get(
                            "message",
                            "You don't have enough credits left. Please upgrade to continue.",
                        )
                    else:
                        full_response = str(detail)
                except json.JSONDecodeError:
                    full_response = (
                        "You don't have enough credits left. Please upgrade to continue."
                    )
                st.error(full_response)
            elif e.code in (401, 403):
                _persist_auth(_cookies, None, None)
                _clear_auth_state()
                st.session_state._auth_restore_done = True
                full_response = "Session expired. Please log in again."
                st.warning(full_response)
                time.sleep(0.3)
                st.rerun()
            else:
                full_response = f"HTTP error from API: {e.code} — {body}"
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
    # Refresh credits badge after each turn.
    st.rerun()


_restore_auth_from_cookies(_cookies)

if st.session_state.access_token is None:
    if not st.session_state.get("_auth_restore_done"):
        st.empty()
        st.stop()
    login()
else:
    chat_interface()

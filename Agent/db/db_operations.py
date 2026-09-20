import os
from urllib.parse import quote_plus

import psycopg
from psycopg.rows import dict_row
from langchain_core.messages import HumanMessage, AIMessage

# Configuration
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

WINDOW_SIZE = 5  # Keep exactly 5 messages raw
api_key = os.getenv("GEMINI_API_KEY")
chat_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    user = quote_plus(os.getenv("DB_USER", "postgres"))
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "sessions")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_db_connection():
    return psycopg.connect(get_database_url(), row_factory=dict_row)

# 1. Fetch summary from sessions (primary) with conversation_summaries fallback
def get_current_summary(conn, session_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_summary FROM sessions WHERE session_id = %s;",
            (session_id,),
        )
        row = cur.fetchone()
        if row and row["current_summary"]:
            return row["current_summary"]
        cur.execute(
            "SELECT summary FROM conversation_summaries WHERE session_id = %s;",
            (session_id,),
        )
        row = cur.fetchone()
        return row["summary"] if row and row["summary"] else ""


def save_session_summary(conn, session_id: str, new_summary: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET current_summary = %s WHERE session_id = %s;",
            (new_summary, session_id),
        )
        cur.execute(
            """
            INSERT INTO conversation_summaries (session_id, summary, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (session_id)
            DO UPDATE SET summary = EXCLUDED.summary, updated_at = CURRENT_TIMESTAMP;
            """,
            (session_id, new_summary),
        )
    conn.commit()


# 2. Update Database Summary with New Delta (kept for callers using conn)
def update_summary_in_db(conn, session_id: str, new_summary: str):
    save_session_summary(conn, session_id, new_summary)




# 3. Micro-Summarization (existing summary + one new turn)
def update_rolling_summary(existing_summary: str, role: str, content: str) -> str:
    msg_role = "User" if role == "user" else "AI"
    new_info = f"{msg_role}: {content}"

    prompt = (
        "You are updating a continuous conversation log summary.\n"
        f"Existing Summary: {existing_summary if existing_summary else 'No prior conversation.'}\n"
        f"Newest expired turn to incorporate: {new_info}\n\n"
        "Task: Write an updated, concise single-paragraph summary combining the existing summary and the new turn."
    )

    response = chat_llm.invoke([HumanMessage(content=prompt)])
    return response.content


def _summarize_latest_turn(existing_summary: str, user_content: str, assistant_content: str) -> str:
    prompt = (
        "You are updating a continuous conversation log summary.\n"
        f"Existing Summary: {existing_summary if existing_summary else 'No prior conversation.'}\n"
        f"Latest user message: {user_content}\n"
        f"Latest assistant reply: {assistant_content}\n\n"
        "Task: Write an updated, concise single-paragraph summary incorporating this exchange."
    )
    response = chat_llm.invoke([HumanMessage(content=prompt)])
    return response.content


def refresh_session_summary(session_id: str) -> None:
    """Update sessions.current_summary after a completed user/assistant turn."""
    with get_db_connection() as conn:
        existing_summary = get_current_summary(conn, session_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = %s AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT 2
                """,
                (session_id,),
            )
            recent = list(cur.fetchall())

        user_msg = next((m for m in recent if m["role"] == "user"), None)
        assistant_msg = next((m for m in recent if m["role"] == "assistant"), None)
        if not user_msg or not assistant_msg:
            return

        new_summary = _summarize_latest_turn(
            existing_summary,
            user_msg["content"],
            assistant_msg["content"],
        )
        save_session_summary(conn, session_id, new_summary)


def trim_messages_to_window(session_id: str) -> None:
    """Drop oldest user/assistant rows once they are folded into the summary."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM messages
                WHERE session_id = %s AND role IN ('user', 'assistant')
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
            message_ids = [row["id"] for row in cur.fetchall()]
            if len(message_ids) <= WINDOW_SIZE:
                return
            expired_ids = message_ids[: len(message_ids) - WINDOW_SIZE]
            cur.execute("DELETE FROM messages WHERE id = ANY(%s);", (expired_ids,))
        conn.commit()

def get_old_messages(session_id: str, limit: int = 5) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = %s AND role IN ('user', 'assistant')
                ORDER BY created_at ASC LIMIT %s;
                """,
                (session_id, limit),
            )
            return list(cur.fetchall())


def ensure_session(session_id: str, user_id: str | None = None) -> None:
    """Create a sessions row if missing (required by messages FK)."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (session_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (session_id, user_id),
            )
        conn.commit()


def create_session_for_user(user_id: str, session_id: str) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (session_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO NOTHING;
                """,
                (session_id, user_id),
            )
        conn.commit()


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM sessions WHERE session_id = %s AND user_id = %s;",
                (session_id, user_id),
            )
            return cur.fetchone() is not None


def list_sessions_for_user(user_id: str) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, title, created_at, updated_at
                FROM sessions
                WHERE user_id = %s
                ORDER BY updated_at DESC;
                """,
                (user_id,),
            )
            return list(cur.fetchall())


def get_messages_for_session(session_id: str) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = %s AND role IN ('user', 'assistant')
                ORDER BY created_at ASC;
                """,
                (session_id,),
            )
            return list(cur.fetchall())


def delete_session_for_user(session_id: str, user_id: str) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sessions WHERE session_id = %s AND user_id = %s;",
                (session_id, user_id),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def touch_session(session_id: str, title: str | None = None) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if title:
                cur.execute(
                    """
                    UPDATE sessions
                    SET updated_at = CURRENT_TIMESTAMP, title = %s
                    WHERE session_id = %s AND title = 'New chat';
                    """,
                    (title, session_id),
                )
            else:
                cur.execute(
                    "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = %s;",
                    (session_id,),
                )
        conn.commit()


def persist_chat_request(
    session_id: str,
    user_content: str,
    summarized_context: str,
    user_id: str | None = None,
) -> None:
    """Save the user message and summarized context before the agent responds."""
    ensure_session(session_id, user_id)
    title = user_content[:50] + ("..." if len(user_content) > 50 else "")
    touch_session(session_id, title=title)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, "user", user_content),
            )
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, "context", summarized_context),
            )
        conn.commit()


def append_assistant_message(session_id: str, assistant_content: str, user_id: str | None = None) -> None:
    """Persist the assistant reply after the agent finishes."""
    ensure_session(session_id, user_id)
    touch_session(session_id)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, "assistant", assistant_content),
            )
        conn.commit()
    try:
        refresh_session_summary(session_id)
        trim_messages_to_window(session_id)
    except Exception as err:
        print("refresh_session_summary failed:", err)

def combine_messages(session_id: str) -> str:
    with get_db_connection() as conn:
        current_summary = get_current_summary(conn, session_id)
    if not current_summary:
        current_summary = "No summary found for this session."
    else:
        current_summary = f"Current summary: {current_summary}"

    old_messages = get_old_messages(session_id, 6)
    langchain_messages: list = []

    for msg in old_messages:
        if msg["role"] == "user":
            langchain_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            langchain_messages.append(AIMessage(content=msg["content"]))
    # return langchain_messages

    combined_context = f"{current_summary}\n\n{langchain_messages}"
    return combined_context
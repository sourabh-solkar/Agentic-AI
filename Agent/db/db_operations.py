import os

import psycopg
from psycopg.rows import dict_row
from langchain_postgres import PostgresChatMessageHistory
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# Configuration
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

WINDOW_SIZE = 5  # Keep exactly 5 messages raw
api_key = os.getenv("GEMINI_API_KEY")
DB_CONN_STRING = "postgresql://user:password@localhost:5432/chat_db"
chat_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=api_key)


def get_db_connection():
    return psycopg.connect(
        dbname="sessions",
        user="postgres",
        password="",
        host="localhost",
        port="5432",
        row_factory=dict_row,
    )

# 1. Fetch or Initialize Summary from Database
def get_current_summary(conn, session_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT summary FROM conversation_summaries WHERE session_id = %s;", (session_id,))
        row = cur.fetchone()
        return row[0] if row else ""

# 2. Update Database Summary with New Delta
def update_summary_in_db(conn, session_id: str, new_summary: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conversation_summaries (session_id, summary, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (session_id) 
            DO UPDATE SET summary = EXCLUDED.summary, updated_at = CURRENT_TIMESTAMP;
            """,
            (session_id, new_summary)
        )
    conn.commit()




# 3. Micro-Summarization (Takes existing summary + 1 newly expired message)
def update_rolling_summary(existing_summary: str, expired_message) -> str:
    msg_role = "User" if expired_message.type == "human" else "AI"
    new_info = f"{msg_role}: {expired_message.content}"
    
    prompt = (
        "You are updating a continuous conversation log summary.\n"
        f"Existing Summary: {existing_summary if existing_summary else 'No prior conversation.'}\n"
        f"Newest expired turn to incorporate: {new_info}\n\n"
        "Task: Write an updated, concise single-paragraph summary combining the existing summary and the new turn."
    )
    
    response = chat_llm.invoke([HumanMessage(content=prompt)])
    return response.content

def get_old_messages(session_id: str, limit: int = 5) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM messages WHERE session_id = %s ORDER BY created_at ASC LIMIT %s;",
                (session_id, limit),
            )
            return list(cur.fetchall())


def append_chat_messages(session_id: str, user_content: str, assistant_content: str) -> None:
    """Persist one user turn and the assistant reply for this session."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, "user", user_content),
            )
            cur.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s);",
                (session_id, "assistant", assistant_content),
            )

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
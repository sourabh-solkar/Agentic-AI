"""Initialize database schema and seed a default admin user."""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from db.user_operations import create_user, get_user_by_username

load_dotenv()

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin")


def _connection_kwargs() -> dict:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return {"conninfo": db_url}
    return {
        "dbname": os.getenv("DB_NAME", "sessions"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
    }


def init_db() -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(**_connection_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()

    if not get_user_by_username(DEFAULT_ADMIN_USERNAME):
        create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
        print(f"Created default user '{DEFAULT_ADMIN_USERNAME}'.")
    else:
        print(f"User '{DEFAULT_ADMIN_USERNAME}' already exists.")


if __name__ == "__main__":
    init_db()
    print("Database initialized.")

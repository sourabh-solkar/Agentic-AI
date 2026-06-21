import uuid

import bcrypt

from db.db_operations import get_db_connection


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def get_user_by_username(username: str) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username = %s;",
                (username,),
            )
            return cur.fetchone()


def create_user(username: str, password: str) -> dict:
    user_id = uuid.uuid4()
    password_hash = hash_password(password)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, username, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id, username, created_at;
                """,
                (user_id, username, password_hash),
            )
            row = cur.fetchone()
        conn.commit()
    return row

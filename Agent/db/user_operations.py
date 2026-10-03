import os
import re
import uuid
from datetime import datetime, timezone

import bcrypt

from db.db_operations import get_db_connection
from utils.usage import credit_hold_amount, tokens_to_credits

# Gmail-only signup: basic format check, no inbox verification.
_GMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@gmail\.com$", re.IGNORECASE)

FREE_QUESTION_CREDITS = int(os.getenv("FREE_QUESTION_CREDITS", "30"))


def is_valid_gmail(email: str) -> bool:
    """Sanity-check that the address looks like a Gmail account."""
    if not email or not isinstance(email, str):
        return False
    return bool(_GMAIL_RE.match(email.strip()))


def normalize_gmail(email: str) -> str:
    return email.strip().lower()


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
                """
                SELECT id, username, password_hash, credits, created_at
                FROM users
                WHERE username = %s;
                """,
                (username,),
            )
            return cur.fetchone()


def get_user_by_id(user_id: str) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, username, password_hash, credits, created_at
                FROM users
                WHERE id = %s;
                """,
                (user_id,),
            )
            return cur.fetchone()


def get_user_credits(user_id: str) -> int | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT credits FROM users WHERE id = %s;", (user_id,))
            row = cur.fetchone()
            if not row:
                return None
            return int(row["credits"])


def try_consume_credit(user_id: str) -> int | None:
    """Backward-compatible alias: reserve the default hold amount without a run id."""
    return reserve_credits(user_id, credit_hold_amount(), run_id=str(uuid.uuid4()))


def reserve_credits(
    user_id: str,
    amount: int | None = None,
    *,
    run_id: str | uuid.UUID,
    session_id: str | None = None,
) -> int | None:
    """Hold credits at turn start. Returns remaining balance, or None if insufficient."""
    hold = max(1, int(amount if amount is not None else credit_hold_amount()))
    run_uuid = uuid.UUID(str(run_id))
    session_key = str(session_id) if session_id is not None else None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET credits = credits - %s
                WHERE id = %s AND credits >= %s
                RETURNING credits;
                """,
                (hold, user_id, hold),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None
            cur.execute(
                """
                INSERT INTO credit_holds (run_id, user_id, session_id, amount, status)
                VALUES (%s, %s, %s, %s, 'held')
                ON CONFLICT (run_id) DO NOTHING;
                """,
                (run_uuid, user_id, session_key, hold),
            )
        conn.commit()
    return int(row["credits"])


def _add_credits(cur, user_id: str, amount: int) -> int:
    cur.execute(
        """
        UPDATE users
        SET credits = credits + %s
        WHERE id = %s
        RETURNING credits;
        """,
        (amount, user_id),
    )
    row = cur.fetchone()
    return int(row["credits"]) if row else 0


def settle_usage(
    user_id: str,
    *,
    run_id: str | uuid.UUID,
    session_id: str | None,
    input_tokens: int,
    output_tokens: int,
    purpose: str = "chat",
    provider: str | None = None,
    model: str | None = None,
    turn_failed: bool = False,
) -> dict:
    """Settle a hold against measured tokens. Returns billing summary + remaining credits."""
    run_uuid = uuid.UUID(str(run_id))
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    total = inp + out
    due = 0 if (turn_failed and total <= 0) else tokens_to_credits(inp, out)
    now = datetime.now(timezone.utc)
    session_key = str(session_id) if session_id is not None else None

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT amount, status FROM credit_holds
                WHERE run_id = %s AND user_id = %s
                FOR UPDATE;
                """,
                (run_uuid, user_id),
            )
            hold = cur.fetchone()
            if hold and hold["status"] != "held":
                cur.execute("SELECT credits FROM users WHERE id = %s;", (user_id,))
                rem_row = cur.fetchone()
                remaining = int(rem_row["credits"]) if rem_row else 0
                conn.commit()
                return {
                    "credits": remaining,
                    "credits_charged": due,
                    "credits_held": int(hold["amount"]),
                    "input_tokens": inp,
                    "output_tokens": out,
                    "total_tokens": total,
                }

            held = int(hold["amount"]) if hold else 0

            if held and due < held:
                remaining = _add_credits(cur, user_id, held - due)
            elif held and due > held:
                extra = due - held
                cur.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE;", (user_id,))
                bal_row = cur.fetchone()
                balance = int(bal_row["credits"]) if bal_row else 0
                take = min(extra, balance)
                if take:
                    cur.execute(
                        """
                        UPDATE users
                        SET credits = credits - %s
                        WHERE id = %s
                        RETURNING credits;
                        """,
                        (take, user_id),
                    )
                    rem_row = cur.fetchone()
                    remaining = int(rem_row["credits"]) if rem_row else 0
                else:
                    remaining = balance
                # If balance couldn't cover full due, record what we intended.
            elif held and due == held:
                cur.execute("SELECT credits FROM users WHERE id = %s;", (user_id,))
                rem_row = cur.fetchone()
                remaining = int(rem_row["credits"]) if rem_row else 0
            else:
                # No active hold (e.g. orphan settle): charge due from balance.
                cur.execute("SELECT credits FROM users WHERE id = %s FOR UPDATE;", (user_id,))
                bal_row = cur.fetchone()
                balance = int(bal_row["credits"]) if bal_row else 0
                take = min(due, balance)
                if take:
                    cur.execute(
                        """
                        UPDATE users
                        SET credits = credits - %s
                        WHERE id = %s
                        RETURNING credits;
                        """,
                        (take, user_id),
                    )
                    rem_row = cur.fetchone()
                    remaining = int(rem_row["credits"]) if rem_row else 0
                else:
                    remaining = balance

            if hold and hold["status"] == "held":
                cur.execute(
                    """
                    UPDATE credit_holds
                    SET status = %s, settled_at = %s
                    WHERE run_id = %s;
                    """,
                    ("released" if due == 0 else "settled", now, run_uuid),
                )

            cur.execute(
                """
                INSERT INTO usage_events (
                    user_id, session_id, run_id, provider, model, purpose,
                    input_tokens, output_tokens, total_tokens, credits_charged
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    user_id,
                    session_key,
                    run_uuid,
                    provider,
                    model,
                    purpose,
                    inp,
                    out,
                    total,
                    due,
                ),
            )
        conn.commit()

    return {
        "credits": remaining,
        "credits_charged": due,
        "credits_held": held,
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": total,
    }


def create_user(
    username: str,
    password: str,
    *,
    initial_credits: int | None = None,
) -> dict:
    user_id = uuid.uuid4()
    password_hash = hash_password(password)
    credits = FREE_QUESTION_CREDITS if initial_credits is None else initial_credits
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, username, password_hash, credits)
                VALUES (%s, %s, %s, %s)
                RETURNING id, username, credits, created_at;
                """,
                (user_id, username, password_hash, credits),
            )
            row = cur.fetchone()
        conn.commit()
    return row

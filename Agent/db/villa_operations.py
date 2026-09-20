from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from db.db_operations import get_db_connection


def _parse_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _villa_row(row: dict) -> dict:
    price = row["price_per_night"]
    if isinstance(price, Decimal):
        price = float(price)
    return {
        "id": row["id"],
        "name": row["name"],
        "location": row["location"],
        "type": row["type"],
        "rooms_available": int(row["rooms_available"]),
        "price_per_night": price,
    }


def get_villa_by_id(villa_id: int) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, location, type, rooms_available, price_per_night
                FROM villas
                WHERE id = %s;
                """,
                (villa_id,),
            )
            row = cur.fetchone()
    return _villa_row(row) if row else None


def get_villa_by_name(name: str) -> dict | None:
    needle = name.strip()
    if not needle:
        return None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, location, type, rooms_available, price_per_night
                FROM villas
                WHERE LOWER(name) LIKE LOWER(%s)
                ORDER BY id
                LIMIT 1;
                """,
                (f"%{needle}%",),
            )
            row = cur.fetchone()
    return _villa_row(row) if row else None


def list_villas_by_location(location: str) -> list[dict]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, location, type, rooms_available, price_per_night
                FROM villas
                WHERE LOWER(location) = LOWER(%s)
                ORDER BY id;
                """,
                (location.strip(),),
            )
            rows = cur.fetchall()
    return [_villa_row(row) for row in rows]


def get_alternative_villas(villa_id: int) -> list[dict]:
    villa = get_villa_by_id(villa_id)
    if not villa:
        return []
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, location, type, rooms_available, price_per_night
                FROM villas
                WHERE LOWER(location) = LOWER(%s)
                  AND id <> %s
                  AND rooms_available > 0
                ORDER BY id;
                """,
                (villa["location"], villa_id),
            )
            rows = cur.fetchall()
    return [_villa_row(row) for row in rows]


def book_villa(
    villa_id: int,
    check_in_date: str,
    check_out_date: str,
    user_id: str | None = None,
) -> dict:
    check_in = _parse_date(check_in_date)
    check_out = _parse_date(check_out_date)
    if not check_in or not check_out:
        return {
            "ok": False,
            "error": "Invalid dates. Use YYYY-MM-DD for check-in and check-out.",
        }
    if check_out <= check_in:
        return {"ok": False, "error": "Check-out date must be after check-in date."}

    user_uuid: UUID | None = None
    if user_id:
        try:
            user_uuid = UUID(str(user_id))
        except ValueError:
            user_uuid = None

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE villas
                SET rooms_available = rooms_available - 1
                WHERE id = %s AND rooms_available > 0
                RETURNING id, name, location, type, rooms_available, price_per_night;
                """,
                (villa_id,),
            )
            villa = cur.fetchone()
            if not villa:
                cur.execute("SELECT id FROM villas WHERE id = %s;", (villa_id,))
                exists = cur.fetchone()
                conn.rollback()
                if not exists:
                    return {"ok": False, "error": "Villa not found"}
                return {"ok": False, "error": "No rooms available"}

            cur.execute(
                """
                INSERT INTO bookings (villa_id, user_id, check_in_date, check_out_date, status)
                VALUES (%s, %s, %s, %s, 'confirmed')
                RETURNING id;
                """,
                (villa_id, user_uuid, check_in, check_out),
            )
            booking = cur.fetchone()
        conn.commit()

    return {
        "ok": True,
        "booking_id": str(booking["id"]),
        "villa": _villa_row(villa),
        "check_in_date": check_in.isoformat(),
        "check_out_date": check_out.isoformat(),
    }

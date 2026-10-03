from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from langgraph.types import interrupt

from db import villa_operations


def get_alternative_villas(villa_id: int) -> list[dict]:
    """Return other available villas in the same location."""
    return villa_operations.get_alternative_villas(villa_id)


@tool
def get_villas(location: str) -> list[dict] | str:
    """Search villas by city or location name."""
    villas = villa_operations.list_villas_by_location(location)
    if not villas:
        return "No villas found in this location"
    return villas


@tool
def find_villa_by_name(name: str) -> dict | str:
    """Find a villa by partial name match."""
    villa = villa_operations.get_villa_by_name(name)
    if not villa:
        return f"No villa found matching '{name}'"
    return villa


@tool
def check_availability(villa_id: int) -> bool | str:
    """Check whether a villa has rooms available."""
    villa = villa_operations.get_villa_by_id(villa_id)
    if not villa:
        return "Villa not found"
    return villa["rooms_available"] > 0


@tool
def booking_villa(
    villa_id: int,
    check_in_date: str,
    check_out_date: str,
    runtime: ToolRuntime,
) -> str:
    """Book a villa for the given dates. Pauses for human approval before writing the booking."""
    villa = villa_operations.get_villa_by_id(villa_id)
    if not villa:
        return "Villa not found"
    if villa["rooms_available"] <= 0:
        return "No rooms available"

    approval = interrupt(
        {
            "action": "confirm_booking",
            "id": f"{villa_id}|{check_in_date}|{check_out_date}",
            "villa_id": str(villa_id),
            "villa_name": villa["name"],
            "location": villa["location"],
            "check_in_date": check_in_date,
            "check_out_date": check_out_date,
            "price_per_night": str(villa["price_per_night"]),
            "prompt": "Approve this villa booking?",
        }
    )
    approved = False
    if isinstance(approval, bool):
        approved = approval
    elif isinstance(approval, dict):
        approved = bool(approval.get("approved"))

    if not approved:
        return "Booking was not approved. No reservation was created."

    configurable = (runtime.config or {}).get("configurable") or {}
    user_id = configurable.get("user_id")
    result = villa_operations.book_villa(
        villa_id,
        check_in_date,
        check_out_date,
        user_id=str(user_id) if user_id else None,
    )
    if not result.get("ok"):
        return result.get("error") or "Booking failed"
    booked = result["villa"]
    return (
        f"Booking confirmed ({result['booking_id']}) at {booked['name']} "
        f"from {result['check_in_date']} to {result['check_out_date']}"
    )


@tool
def get_villa_policy(villa_id: int, topic: str = "cancellation") -> str:
    """Return villa policy details such as cancellation, refund, or check-in rules."""
    villa = villa_operations.get_villa_by_id(villa_id)
    if not villa:
        return "Villa not found"
    return (
        f"{villa['name']} {topic} policy: Free cancellation up to 24 hours before check-in. "
        "Late cancellations may incur one night's charge."
    )


# Backward-compatible hotel aliases
get_hotels = get_villas
booking_hotel = booking_villa
get_hotel_policy = get_villa_policy

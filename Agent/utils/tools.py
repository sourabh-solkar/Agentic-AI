from utils import local_db
from langchain_core.tools import tool


def _find_hotel(hotel_id: int) -> dict | None:
    return next((hotel for hotel in local_db.HOTELS_DB if hotel["id"] == hotel_id), None)


@tool
def get_hotels(location: str) -> list[dict] | str:
    """Search hotels by city or location name."""
    hotels = [hotel for hotel in local_db.HOTELS_DB if hotel["location"].lower() == location.lower()]
    if not hotels:
        return "No hotels found in this location"
    return hotels


@tool
def check_availability(hotel_id: int) -> bool | str:
    """Check whether a hotel has rooms available."""
    hotel = _find_hotel(hotel_id)
    if not hotel:
        return "Hotel not found"
    return hotel["rooms_available"] > 0


@tool
def booking_hotel(hotel_id: int, check_in_date: str, check_out_date: str) -> str:
    """Book a hotel room for the given dates."""
    hotel = _find_hotel(hotel_id)
    if not hotel:
        return "Hotel not found"
    if hotel["rooms_available"] <= 0:
        return "No rooms available"
    return f"Booking confirmed at {hotel['name']} from {check_in_date} to {check_out_date}"


@tool
def get_hotel_policy(hotel_id: int, topic: str = "cancellation") -> str:
    """Return hotel policy details such as cancellation, refund, or check-in rules."""
    hotel = _find_hotel(hotel_id)
    if not hotel:
        return "Hotel not found"
    return (
        f"{hotel['name']} {topic} policy: Free cancellation up to 24 hours before check-in. "
        "Late cancellations may incur one night's charge."
    )

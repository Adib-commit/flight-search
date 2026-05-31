"""Convert Kiwi.com Tequila /v2/search responses into internal Itineraries.

Kiwi returns one object per bookable trip. `route` is a flat list of segments
across both directions; each segment's `return` flag is 0 (outbound) or 1
(inbound). `price` is the total trip price (all passengers) in the requested
currency. `duration` holds wall-clock seconds: {departure, return, total}.
Kiwi includes LCCs (Wizz, Ryanair) and builds self-transfer combos.
"""
from __future__ import annotations

from datetime import datetime

from .models import Itinerary, Segment


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _seg_flight_min(r: dict) -> int:
    dep = _parse_dt(r.get("utc_departure", ""))
    arr = _parse_dt(r.get("utc_arrival", ""))
    if dep and arr:
        return max(int((arr - dep).total_seconds()) // 60, 0)
    return 0


def _seg_from_route(r: dict) -> Segment:
    return Segment(
        carrier_code=r.get("airline", ""),
        flight_number=str(r.get("flight_no", "")),
        origin=r.get("flyFrom", ""),
        destination=r.get("flyTo", ""),
        departure_at=r.get("local_departure", ""),
        arrival_at=r.get("local_arrival", ""),
        duration_min=_seg_flight_min(r),
    )


def transform_trip(trip: dict, currency: str = "") -> Itinerary:
    route = trip.get("route", [])
    outbound = [r for r in route if int(r.get("return", 0)) == 0]
    inbound = [r for r in route if int(r.get("return", 0)) == 1]

    segments = [_seg_from_route(r) for r in route]

    carriers: list[str] = []
    for s in segments:
        if s.carrier_code and s.carrier_code not in carriers:
            carriers.append(s.carrier_code)

    # stops = transfers per direction (segments - 1), summed
    stops = max(len(outbound) - 1, 0) + max(len(inbound) - 1, 0)

    dur = trip.get("duration", {}) or {}
    wall_out = int(dur.get("departure", 0))
    wall_in = int(dur.get("return", 0))
    total_wall = int(dur.get("total", wall_out + wall_in))
    total_duration_min = total_wall // 60

    flight_out = sum(_seg_flight_min(r) for r in outbound)
    flight_in = sum(_seg_flight_min(r) for r in inbound)
    layover_min = max(wall_out // 60 - flight_out, 0) + max(wall_in // 60 - flight_in, 0)

    return Itinerary(
        id=str(trip.get("id", "")),
        price_total=float(trip.get("price", 0.0)),
        currency=currency or trip.get("currency", ""),
        carriers=carriers,
        stops_count=stops,
        total_duration_min=total_duration_min,
        layover_min=layover_min,
        segments=segments,
    )


def transform_trips(trips: list[dict], currency: str = "") -> list[Itinerary]:
    return [transform_trip(t, currency) for t in trips]

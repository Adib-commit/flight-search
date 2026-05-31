"""Transform Skyscanner API response → internal Itinerary objects.

Skyscanner response structure:
  {
    itineraries: [
      {
        id: str,
        price: {amount: float, currency: str, formatted: str},
        legs: [
          {
            origin: str,           # IATA
            destination: str,      # IATA
            departure: str,        # ISO datetime
            arrival: str,          # ISO datetime
            durationMinutes: int,
            stopCount: int,
            carriers: [{name: str, logoUrl: str}]
          }
        ],
        bookingUrl: str,
        score: float,
        tags: []
      }
    ],
    sessionToken: str,
    status: str
  }

Note: the API returns leg-level data only (no per-segment breakdown). Each
leg is mapped to a single Segment. carrier_code is taken from the first
carrier name (trimmed to a reasonable length for display).
"""
from __future__ import annotations

from .models import Itinerary, Segment


def _carrier_code(name: str) -> str:
    """Best-effort short code from a carrier display name."""
    if not name:
        return "??"
    # Use first two uppercase words joined, trimmed to 10 chars
    parts = name.split()
    return parts[0][:10] if parts else name[:10]


def transform_result(item: dict, currency: str) -> Itinerary | None:
    """Map a single Skyscanner itinerary dict to an internal Itinerary."""
    try:
        price_info = item.get("price") or {}
        price = float(price_info.get("amount", 0))
        cur = price_info.get("currency") or currency

        legs: list[dict] = item.get("legs") or []
        if not legs:
            return None

        segments: list[Segment] = []
        carriers_set: list[str] = []
        total_stops = 0
        total_duration = 0

        for leg_idx, leg in enumerate(legs):
            origin = leg.get("origin", "")
            destination = leg.get("destination", "")
            departure = leg.get("departure", "")
            arrival = leg.get("arrival", "")
            duration_min = int(leg.get("durationMinutes") or 0)
            stop_count = int(leg.get("stopCount") or 0)
            carriers = leg.get("carriers") or []

            total_stops += stop_count
            total_duration += duration_min

            # Use first carrier for the segment's code/name
            if carriers:
                c_name = carriers[0].get("name", "")
                c_code = _carrier_code(c_name)
            else:
                c_name = ""
                c_code = "??"

            for c in carriers:
                cname = c.get("name", "")
                if cname and cname not in carriers_set:
                    carriers_set.append(cname)

            direction = "outbound" if leg_idx == 0 else "inbound"

            seg = Segment(
                carrier_code=c_code,
                flight_number="",
                origin=origin,
                destination=destination,
                departure_at=departure,
                arrival_at=arrival,
                duration_min=duration_min,
                direction=direction,
                layover_after_min=0,
            )
            segments.append(seg)

        booking_url = item.get("bookingUrl") or ""
        itin_id = item.get("id") or ""

        return Itinerary(
            id=f"sky_{itin_id}",
            price_total=price,
            currency=cur,
            carriers=carriers_set or ["Unknown"],
            stops_count=total_stops,
            total_duration_min=total_duration,
            max_stops_per_dir=max(
                (int((leg.get("stopCount") or 0)) for leg in legs), default=-1
            ),
            booking_url=booking_url,
            segments=segments,
        )
    except Exception:
        return None


def transform_response(data: dict, currency: str = "USD") -> list[Itinerary]:
    """Transform full Skyscanner searchFlights response to Itinerary list."""
    itineraries_raw = data.get("itineraries") or []
    result: list[Itinerary] = []
    for item in itineraries_raw:
        it = transform_result(item, currency)
        if it is not None and it.price_total > 0:
            result.append(it)
    return result

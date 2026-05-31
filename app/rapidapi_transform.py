"""Convert Sky-Scrapper (RapidAPI) itineraries into internal Itineraries.

Shape (per itinerary):
  price.raw : float total trip price
  legs[]    : one per direction; each has durationInMinutes, stopCount,
              carriers.marketing[].{name, alternateId(IATA)}, and segments[].
Layover per leg = leg duration - sum(segment flight durations).
"""
from __future__ import annotations

from .models import Itinerary, Segment


def _seg_from_raw(s: dict) -> Segment:
    mc = s.get("marketingCarrier", {}) or {}
    origin = s.get("origin", {}) or {}
    dest = s.get("destination", {}) or {}
    return Segment(
        carrier_code=mc.get("alternateId", "") or "",
        flight_number=str(s.get("flightNumber", "")),
        origin=origin.get("displayCode", "") or origin.get("id", ""),
        destination=dest.get("displayCode", "") or dest.get("id", ""),
        departure_at=s.get("departure", ""),
        arrival_at=s.get("arrival", ""),
        duration_min=int(s.get("durationInMinutes", 0) or 0),
    )


def transform_itinerary(it: dict) -> Itinerary:
    legs = it.get("legs", []) or []
    segments: list[Segment] = []
    total_duration = 0
    stops = 0
    layover = 0
    carriers: list[str] = []

    for leg in legs:
        leg_dur = int(leg.get("durationInMinutes", 0) or 0)
        total_duration += leg_dur
        stops += int(leg.get("stopCount", 0) or 0)

        seg_list = [_seg_from_raw(s) for s in (leg.get("segments", []) or [])]
        segments.extend(seg_list)
        flight_time = sum(s.duration_min for s in seg_list)
        layover += max(leg_dur - flight_time, 0)

        # carriers from segments (IATA) + leg-level marketing as fallback
        for s in seg_list:
            if s.carrier_code and s.carrier_code not in carriers:
                carriers.append(s.carrier_code)
        for c in (leg.get("carriers", {}) or {}).get("marketing", []) or []:
            code = c.get("alternateId", "")
            if code and code not in carriers:
                carriers.append(code)

    price = it.get("price", {}) or {}
    return Itinerary(
        id=str(it.get("id", "")),
        price_total=float(price.get("raw", 0.0) or 0.0),
        currency=price.get("currency", "") or "",
        carriers=carriers,
        stops_count=stops,
        total_duration_min=total_duration,
        layover_min=layover,
        segments=segments,
    )


def transform_itineraries(items: list[dict]) -> list[Itinerary]:
    return [transform_itinerary(i) for i in items]

from __future__ import annotations

import re

from .models import Itinerary, Segment

# ISO8601 duration like "PT11H30M" / "PT55M" / "PT2H"
_DUR_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")


def parse_iso_duration(value: str) -> int:
    """Convert ISO8601 duration to minutes. Returns 0 on no match."""
    if not value:
        return 0
    m = _DUR_RE.fullmatch(value)
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    return hours * 60 + minutes


def _segment_from_raw(raw: dict) -> Segment:
    dep = raw.get("departure", {})
    arr = raw.get("arrival", {})
    return Segment(
        carrier_code=raw.get("carrierCode", ""),
        flight_number=str(raw.get("number", "")),
        origin=dep.get("iataCode", ""),
        destination=arr.get("iataCode", ""),
        departure_at=dep.get("at", ""),
        arrival_at=arr.get("at", ""),
        duration_min=parse_iso_duration(raw.get("duration", "")),
    )


def transform_offer(offer: dict) -> Itinerary:
    """Convert one Amadeus flight-offer into an internal Itinerary."""
    segments: list[Segment] = []
    total_duration = 0
    layover_min = 0
    for itin in offer.get("itineraries", []):
        seg_list = [_segment_from_raw(s) for s in itin.get("segments", [])]
        flight_time = sum(s.duration_min for s in seg_list)
        # prefer the itinerary-level duration (incl. layovers) when present
        itin_dur = parse_iso_duration(itin.get("duration", "")) or flight_time
        segments.extend(seg_list)
        total_duration += itin_dur
        # layover = wall-clock itinerary time minus actual flying time
        layover_min += max(itin_dur - flight_time, 0)

    # stops = (segments per itinerary - 1) summed over itineraries
    stops = 0
    for itin in offer.get("itineraries", []):
        n = len(itin.get("segments", []))
        stops += max(n - 1, 0)

    carriers: list[str] = []
    for s in segments:
        if s.carrier_code and s.carrier_code not in carriers:
            carriers.append(s.carrier_code)

    price = offer.get("price", {})
    return Itinerary(
        id=str(offer.get("id", "")),
        price_total=float(price.get("grandTotal", price.get("total", 0.0))),
        currency=price.get("currency", ""),
        carriers=carriers,
        stops_count=stops,
        total_duration_min=total_duration,
        layover_min=layover_min,
        segments=segments,
    )


def transform_offers(offers: list[dict]) -> list[Itinerary]:
    return [transform_offer(o) for o in offers]

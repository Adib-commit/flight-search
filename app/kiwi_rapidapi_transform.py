"""Convert 'Kiwi.com Cheap Flights' (RapidAPI) itineraries -> internal Itinerary.

Each itinerary has `price.amount` (string) and `outbound` (+ `inbound` for round
trips). A sector has `duration` (seconds, wall-clock incl. layovers) and
`sectorSegments[]`, each with a `segment` (source/destination station code,
localTime, flight `duration` seconds, `carrier.code`) and a `layover`.
"""
from __future__ import annotations

from .models import Itinerary, Segment


def _station_label(station: dict) -> str:
    """Return 'Airport Name, City' e.g. 'Ben Gurion, Tel Aviv'."""
    name = station.get("name", "") or ""
    city = (station.get("city") or {}).get("name", "") or ""
    if name and city and name.lower() not in city.lower():
        return f"{name}, {city}"
    return name or city


def _segment_from(seg: dict) -> Segment:
    src = seg.get("source", {}) or {}
    dst = seg.get("destination", {}) or {}
    carrier = seg.get("carrier", {}) or {}
    src_station = src.get("station", {}) or {}
    dst_station = dst.get("station", {}) or {}
    return Segment(
        carrier_code=carrier.get("code", "") or "",
        flight_number=str(seg.get("code", "")),
        origin=src_station.get("code", ""),
        destination=dst_station.get("code", ""),
        departure_at=src.get("localTime", ""),
        arrival_at=dst.get("localTime", ""),
        duration_min=int(seg.get("duration", 0) or 0) // 60,
        origin_name=_station_label(src_station),
        destination_name=_station_label(dst_station),
    )


def _accumulate_sector(sector: dict, segments: list[Segment], direction: str) -> tuple[int, int, int]:
    """Return (wall_min, stops, layover_min) for one sector; append its segments."""
    if not sector:
        return 0, 0, 0
    sector_segs = sector.get("sectorSegments", []) or []
    wall_min = int(sector.get("duration", 0) or 0) // 60

    flight_min = 0
    for ss in sector_segs:
        seg = ss.get("segment", {}) or {}
        s = _segment_from(seg)
        s.direction = direction
        # layover field is on the sectorSegment entry (null on last leg)
        raw_layover = ss.get("layover") or {}
        s.layover_after_min = int(raw_layover.get("duration", 0) or 0) // 60
        segments.append(s)
        flight_min += s.duration_min

    stops = max(len(sector_segs) - 1, 0)
    if not wall_min:
        wall_min = flight_min
    layover_min = max(wall_min - flight_min, 0)
    return wall_min, stops, layover_min


def transform_itinerary(it: dict, currency: str) -> Itinerary:
    segments: list[Segment] = []

    # Round-trip responses use outbound/inbound; one-way uses a single `sector`.
    if it.get("outbound") or it.get("inbound"):
        out_wall, out_stops, out_lay = _accumulate_sector(it.get("outbound", {}) or {}, segments, "outbound")
        in_wall, in_stops, in_lay = _accumulate_sector(it.get("inbound", {}) or {}, segments, "inbound")
    else:
        out_wall, out_stops, out_lay = _accumulate_sector(it.get("sector", {}) or {}, segments, "outbound")
        in_wall, in_stops, in_lay = 0, 0, 0

    carriers: list[str] = []
    for s in segments:
        if s.carrier_code and s.carrier_code not in carriers:
            carriers.append(s.carrier_code)

    # Extract the cheapest booking URL (first edge = best price)
    edges = (it.get("bookingOptions") or {}).get("edges") or []
    raw_url = (edges[0]["node"]["bookingUrl"] if edges else "") or ""
    booking_url = ("https://www.kiwi.com" + raw_url) if raw_url.startswith("/") else raw_url

    price = it.get("price", {}) or {}
    return Itinerary(
        id=str(it.get("id", "")),
        price_total=float(price.get("amount", 0.0) or 0.0),
        currency=currency,
        carriers=carriers,
        stops_count=out_stops + in_stops,
        max_stops_per_dir=max(out_stops, in_stops),
        total_duration_min=out_wall + in_wall,
        layover_min=out_lay + in_lay,
        booking_url=booking_url,
        segments=segments,
    )


def transform_itineraries(items: list[dict], currency: str) -> list[Itinerary]:
    return [transform_itinerary(i, currency) for i in items]

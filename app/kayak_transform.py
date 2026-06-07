"""Convert Kayak (kayak-api.p.rapidapi.com) response to internal Itinerary.

Response shape:
  results[]        – trip objects (type="core" = real flights, skip "inlineAd")
    .resultId      – unique trip ID
    .legs[]        – [{id, segments:[{id, layover?:{duration}}]}]  leg refs
    .bookingOptions[] – sorted cheapest-first; [0] has .displayPrice.price
                        and .bookingUrl.url (relative; prepend kayak.com)
  legs{}           – keyed by legId: {departure, arrival, duration (min), segments[]}
  segments{}       – keyed by segId: {airline, flightNumber, origin, destination,
                                      departure, arrival, duration (min)}
  airports{}       – keyed by IATA: {cityName, displayName, fullDisplayName}
"""
from __future__ import annotations

import uuid

from .models import Itinerary, Segment

KAYAK_BASE = "https://www.kayak.com"


def _airport_label(airports: dict, iata: str) -> str:
    ap = airports.get(iata) or {}
    display = ap.get("displayName") or ap.get("fullDisplayName") or ""
    city = ap.get("cityName") or ""
    if display and city and display.lower() not in city.lower():
        return f"{display}, {city}"
    return display or city or iata


def _booking_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    if raw_url.startswith("http"):
        return raw_url
    return KAYAK_BASE + raw_url


def transform_result(result: dict, legs_dict: dict, segs_dict: dict, airports: dict, currency: str) -> Itinerary | None:
    """Transform a single Kayak core result into an Itinerary, or None on failure."""
    result_id = result.get("resultId") or result.get("tripId") or str(uuid.uuid4())[:8]
    leg_refs = result.get("legs") or []

    # Price: cheapest booking option
    bk_opts = result.get("bookingOptions") or []
    if bk_opts:
        price_block = bk_opts[0].get("displayPrice") or {}
        price = float(price_block.get("price") or 0)
        result_currency = price_block.get("currency") or currency
        raw_url = (bk_opts[0].get("bookingUrl") or {}).get("url") or ""
        booking_url = _booking_url(raw_url)
    else:
        # Fall back to bucket pricing
        buckets = result.get("bookingOptionsBuckets") or []
        if not buckets:
            return None
        price_block = buckets[0].get("topPrice") or {}
        price = float(price_block.get("price") or 0)
        result_currency = price_block.get("currency") or currency
        booking_url = KAYAK_BASE + (result.get("shareableUrl") or "")

    if price <= 0:
        return None

    segments: list[Segment] = []
    carriers: list[str] = []
    total_duration = 0
    total_layover = 0
    stops_per_dir: list[int] = []
    has_ground = False   # bus/train segment present -> not a flight, drop it

    for dir_idx, leg_ref in enumerate(leg_refs):
        direction = "outbound" if dir_idx == 0 else "inbound"

        # leg_ref may be a dict with {id, segments[]} or just an id string
        if isinstance(leg_ref, dict):
            leg_id = leg_ref.get("id", "")
            ref_segs = leg_ref.get("segments") or []
        else:
            leg_id = str(leg_ref)
            ref_segs = []

        leg = legs_dict.get(leg_id) or {}
        leg_duration = int(leg.get("duration") or 0)
        total_duration += leg_duration

        # prefer leg's own segment list (has layover info) if present
        leg_seg_refs = leg.get("segments") or ref_segs
        dir_stops = max(len(leg_seg_refs) - 1, 0)
        stops_per_dir.append(dir_stops)

        flight_min = 0
        for ss in leg_seg_refs:
            if isinstance(ss, dict):
                seg_id = ss.get("id", "")
                layover_min = int((ss.get("layover") or {}).get("duration") or 0)
            else:
                seg_id = str(ss)
                layover_min = 0

            seg_data = segs_dict.get(seg_id) or {}
            # Kayak mixes ground transport (bus/train) into "flight" results,
            # flagged by isBus / equipmentTypeName "Bus". A bus leg is not a
            # flight — mark the whole itinerary for removal.
            if seg_data.get("isBus") or str(seg_data.get("equipmentTypeName") or "").strip().lower() in ("bus", "train"):
                has_ground = True
            carrier = seg_data.get("airline") or ""
            if carrier and carrier not in carriers:
                carriers.append(carrier)

            dur = int(seg_data.get("duration") or 0)
            flight_min += dur

            s = Segment(
                carrier_code=carrier,
                flight_number=seg_data.get("flightNumber") or "",
                origin=seg_data.get("origin") or "",
                destination=seg_data.get("destination") or "",
                departure_at=seg_data.get("departure") or "",
                arrival_at=seg_data.get("arrival") or "",
                duration_min=dur,
                origin_name=_airport_label(airports, seg_data.get("origin") or ""),
                destination_name=_airport_label(airports, seg_data.get("destination") or ""),
                direction=direction,
                layover_after_min=layover_min,
            )
            segments.append(s)
            total_layover += layover_min

        # if leg duration not provided, sum flight durations
        if leg_duration == 0:
            total_duration += flight_min

    # Reject the whole itinerary if any leg is ground transport (bus/train).
    if has_ground:
        return None

    total_stops = sum(stops_per_dir)
    max_stops = max(stops_per_dir) if stops_per_dir else total_stops

    # The per-fare `book/flight?code=` deeplink is session-scoped and expires
    # fast — reopening it later makes Kayak fall back to "anything for this city
    # pair", which can surface a BUS/train instead of the flight. For one-way
    # legs (split tickets) replace it with a STABLE search URL pinned to the
    # exact route + date + carrier + stop-count, so the link always lands on the
    # real flight and never decays into ground transport.
    if len(leg_refs) == 1 and segments:
        o = segments[0].origin
        d = segments[-1].destination
        dep_date = (segments[0].departure_at or "")[:10]
        if o and d and dep_date:
            url = f"{KAYAK_BASE}/flights/{o}-{d}/{dep_date}?sort=price_a"
            filters = [f"stops={total_stops}"]
            if carriers and "?" not in carriers:
                filters.append("airlines=" + ",".join(carriers))
            booking_url = url + "&fs=" + ";".join(filters)

    return Itinerary(
        id=result_id,
        price_total=price,
        currency=result_currency,
        carriers=carriers or ["?"],
        stops_count=total_stops,
        max_stops_per_dir=max_stops,
        total_duration_min=total_duration,
        layover_min=total_layover,
        booking_url=booking_url,
        segments=segments,
    )


def transform_response(data: dict) -> list[Itinerary]:
    """Transform the full Kayak API response dict into a list of Itinerary."""
    results = data.get("results") or []
    legs_dict = data.get("legs") or {}
    segs_dict = data.get("segments") or {}
    airports = data.get("airports") or {}
    currency = data.get("currency") or "USD"

    itineraries: list[Itinerary] = []
    for r in results:
        if r.get("type") != "core":
            continue
        it = transform_result(r, legs_dict, segs_dict, airports, currency)
        if it is not None:
            itineraries.append(it)

    return itineraries

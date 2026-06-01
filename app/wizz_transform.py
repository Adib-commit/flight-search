"""Convert Wizz Air timetable JSON into internal Itinerary objects.

Timetable shape (single-day window per direction):
  {"outboundFlights":[{departureStation, arrivalStation, departureDate,
                       price:{amount,currencyCode}, departureDates:[ISO,...]}],
   "returnFlights":[ ... same ... ]}

Wizz is point-to-point, so every itinerary is direct (0 stops, 0 layover).
The timetable has no arrival time, so segment duration is *estimated* from a
small per-sector table with a sane default — price is the value here, and the
0-stops/0-layover facts are exact.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from .models import Itinerary, Segment

WIZZ_CODE = "W6"
WIZZ_NAME = "Wizz Air"
_BOOK_BASE = "https://wizzair.com/en-gb/booking/select-flight"

# Approx block times (minutes) for common Wizz sectors; symmetric. Default 150.
_DUR = {
    frozenset({"TLV", "OTP"}): 190,
    frozenset({"TLV", "BUD"}): 215,
    frozenset({"TLV", "VIE"}): 235,
    frozenset({"TLV", "KTW"}): 235,
    frozenset({"TLV", "WAW"}): 240,
    frozenset({"OTP", "CLJ"}): 70,
}


def _estimate_duration(origin: str, dest: str) -> int:
    return _DUR.get(frozenset({origin.upper(), dest.upper()}), 150)


def _to_target(amount: float, cur: str, target: str, eur_usd: float) -> tuple[float, str]:
    cur = (cur or "").upper()
    target = (target or "USD").upper()
    if not amount:
        return 0.0, target
    if cur == target:
        return round(amount, 2), target
    if cur == "EUR" and target == "USD":
        return round(amount * eur_usd, 2), target
    # Unknown pair: keep the amount but label it with its real currency.
    return round(amount, 2), cur or target


def _cheapest(flights: list[dict]) -> dict | None:
    valid = [f for f in flights if (f.get("price") or {}).get("amount")]
    if not valid:
        return None
    return min(valid, key=lambda f: f["price"]["amount"])


def _times(flight: dict) -> list[str]:
    ts = flight.get("departureDates") or []
    if ts:
        return ts
    d = flight.get("departureDate")
    return [d] if d else []


def _segment(flight: dict, dep_iso: str, direction: str) -> Segment:
    origin = flight.get("departureStation", "")
    dest = flight.get("arrivalStation", "")
    dur = _estimate_duration(origin, dest)
    arrival_iso = ""
    try:
        arrival_iso = (datetime.fromisoformat(dep_iso) + timedelta(minutes=dur)).isoformat()
    except (ValueError, TypeError):
        pass
    return Segment(
        carrier_code=WIZZ_CODE,
        flight_number="",
        origin=origin,
        destination=dest,
        departure_at=dep_iso,
        arrival_at=arrival_iso,
        duration_min=dur,
        direction=direction,
        layover_after_min=0,
    )


def _booking_url(o: str, d: str, dep: str, ret: str | None) -> str:
    url = f"{_BOOK_BASE}/{o}/{d}/{dep}"
    if ret:
        url += f"/{d}/{o}/{ret}"
    return url


def transform_timetable(
    data: dict,
    origin: str,
    destination: str,
    dep_date: str,
    ret_date: str | None,
    target_currency: str = "USD",
    eur_usd: float = 1.08,
) -> list[Itinerary]:
    out_flights = data.get("outboundFlights") or []
    ret_flights = data.get("returnFlights") or []
    out = _cheapest(out_flights)
    if not out:
        return []

    out_price, cur = _to_target((out.get("price") or {}).get("amount", 0),
                                (out.get("price") or {}).get("currencyCode", ""),
                                target_currency, eur_usd)

    book = _booking_url(origin, destination, dep_date, ret_date)

    # Round-trip: single combined itinerary (cheapest out + cheapest return).
    if ret_date:
        ret = _cheapest(ret_flights)
        if not ret:
            return []
        ret_price, _ = _to_target((ret.get("price") or {}).get("amount", 0),
                                  (ret.get("price") or {}).get("currencyCode", ""),
                                  target_currency, eur_usd)
        out_dep = (_times(out) or [dep_date])[0]
        ret_dep = (_times(ret) or [ret_date])[0]
        out_seg = _segment(out, out_dep, "outbound")
        ret_seg = _segment(ret, ret_dep, "inbound")
        total = round(out_price + ret_price, 2)
        return [Itinerary(
            id=str(uuid.uuid4())[:12],
            price_total=total,
            currency=cur,
            carriers=[WIZZ_CODE],
            stops_count=0,
            max_stops_per_dir=0,
            total_duration_min=out_seg.duration_min + ret_seg.duration_min,
            layover_min=0,
            booking_url=book,
            segments=[out_seg, ret_seg],
        )]

    # One-way: one itinerary per departure time (all at the date's price).
    itins: list[Itinerary] = []
    for dep_iso in _times(out) or [dep_date]:
        seg = _segment(out, dep_iso, "outbound")
        itins.append(Itinerary(
            id=str(uuid.uuid4())[:12],
            price_total=out_price,
            currency=cur,
            carriers=[WIZZ_CODE],
            stops_count=0,
            max_stops_per_dir=0,
            total_duration_min=seg.duration_min,
            layover_min=0,
            booking_url=book,
            segments=[seg],
        ))
    return itins

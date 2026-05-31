"""Offline mock provider — realistic sample flights, no API key needed.

Lets the full app (validation -> filter -> score -> chart) run with zero signup.
Returns hand-built itineraries; for TLV<->CLJ it mirrors the real market
(direct Wizz + cheaper via-OTP self-transfer) so the 'best value' demo is honest.
Generic routes get a small synthetic spread. NOT real-time fares.
"""
from __future__ import annotations

from .models import Itinerary, Segment


def _seg(carrier, num, o, d, dep, arr, dur) -> Segment:
    return Segment(
        carrier_code=carrier, flight_number=num,
        origin=o, destination=d, departure_at=dep, arrival_at=arr, duration_min=dur,
    )


def _tlv_clj(dep_date: str, ret_date: str | None, adults: int) -> list[Itinerary]:
    rt = ret_date is not None
    f = float(adults)
    items: list[Itinerary] = []

    # Direct Wizz both ways
    out = [_seg("W6", "5101", "TLV", "CLJ", f"{dep_date}T06:00", f"{dep_date}T09:10", 190)]
    if rt:
        out.append(_seg("W6", "5102", "CLJ", "TLV", f"{ret_date}T10:00", f"{ret_date}T13:15", 195))
    items.append(Itinerary(
        id="direct-wizz", price_total=320 * f, currency="USD", carriers=["W6"],
        stops_count=0, total_duration_min=190 + (195 if rt else 0), layover_min=0,
        segments=out))

    # Self-transfer via OTP (cheaper, 2 stops, long layover)
    st = [
        _seg("W6", "5201", "TLV", "OTP", f"{dep_date}T05:00", f"{dep_date}T07:30", 150),
        _seg("W6", "5202", "OTP", "CLJ", f"{dep_date}T11:00", f"{dep_date}T12:00", 60),
    ]
    if rt:
        st += [
            _seg("W6", "5203", "CLJ", "OTP", f"{ret_date}T08:00", f"{ret_date}T09:00", 60),
            _seg("W6", "5204", "OTP", "TLV", f"{ret_date}T13:00", f"{ret_date}T15:30", 150),
        ]
    items.append(Itinerary(
        id="selftransfer-otp", price_total=250 * f, currency="USD", carriers=["W6"],
        stops_count=2 if rt else 1,
        total_duration_min=(450 + (450 if rt else 0)), layover_min=240 + (240 if rt else 0),
        segments=st))

    # TAROM via Bucharest (1 stop each way, mainstream, pricier)
    tr = [
        _seg("RO", "152", "TLV", "OTP", f"{dep_date}T07:00", f"{dep_date}T09:40", 160),
        _seg("RO", "601", "OTP", "CLJ", f"{dep_date}T12:30", f"{dep_date}T13:35", 65),
    ]
    if rt:
        tr += [
            _seg("RO", "602", "CLJ", "OTP", f"{ret_date}T14:00", f"{ret_date}T15:05", 65),
            _seg("RO", "153", "OTP", "TLV", f"{ret_date}T18:00", f"{ret_date}T20:40", 160),
        ]
    items.append(Itinerary(
        id="tarom-otp", price_total=395 * f, currency="USD", carriers=["RO"],
        stops_count=2 if rt else 1,
        total_duration_min=(290 + (290 if rt else 0)), layover_min=130 + (130 if rt else 0),
        segments=tr))

    return items


def _generic(origin: str, dest: str, dep_date: str, ret_date: str | None, adults: int) -> list[Itinerary]:
    rt = ret_date is not None
    f = float(adults)
    base = [
        ("LH", 0, 240, 0, 480),     # direct
        ("AF", 1, 300, 90, 560),    # 1 stop
        ("LX", 1, 270, 75, 530),    # 1 stop cheaper-ish
        ("UA", 2, 360, 210, 690),   # 2 stops cheapest
    ]
    prices = [560, 520, 540, 470]
    items: list[Itinerary] = []
    for i, ((cc, stops, fdur, lay, _), price) in enumerate(zip(base, prices)):
        out = [_seg(cc, f"{100 + i}", origin, dest, f"{dep_date}T08:00", f"{dep_date}T14:00", fdur)]
        if rt:
            out.append(_seg(cc, f"{200 + i}", dest, origin, f"{ret_date}T18:00", f"{ret_date}T23:00", fdur))
        items.append(Itinerary(
            id=f"opt-{i}", price_total=price * f, currency="USD", carriers=[cc],
            stops_count=stops * (2 if rt else 1),
            total_duration_min=(fdur + lay) * (2 if rt else 1),
            layover_min=lay * (2 if rt else 1), segments=out))
    return items


class MockProvider:
    async def search(
        self, *, origin, destination, departure_date, return_date,
        adults, non_stop, included_airlines, excluded_airlines, currency,
    ) -> list[Itinerary]:
        o, d = origin.upper(), destination.upper()
        if {o, d} == {"TLV", "CLJ"}:
            return _tlv_clj(departure_date, return_date, adults)
        return _generic(o, d, departure_date, return_date, adults)

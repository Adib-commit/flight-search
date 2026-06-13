"""E2E sanity test — Agent-built multi-day split-ticket via NAP.

Reproduces the exact search that exposed the missing NAP hub bug:
  TLV -> CLJ (via Naples) 04/08/2026 – 11/08/2026

Expected split pattern (Wizz Air):
  Leg 1  TLV → NAP   04/08/2026
  Leg 2  NAP → CLJ   05–07/08/2026 (any of dep+1…dep+3)
  Leg 3  CLJ → NAP   11–13/08/2026 (any of ret+0…ret+2)
  Leg 4  NAP → TLV   12–15/08/2026 (any of ret+1…ret+4)

Run:        pytest -m e2e
Auto-skips when RAPIDAPI_KEY is not set.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.config import Settings
from app.models import AirlineFilters, FlightDates, SearchRequest
from app.search import run_split_suggestion

pytestmark = pytest.mark.e2e

settings = Settings(provider="rapidapi-kiwi")

needs_key = pytest.mark.skipif(
    not settings.rapidapi_key,
    reason="RAPIDAPI_KEY not set in .env — skipping live split-suggestion e2e.",
)

DEP = date(2026, 8, 4)
RET = date(2026, 8, 11)


def _split_request(**kw) -> SearchRequest:
    base = dict(
        origin="TLV",
        destination="CLJ",
        flight_dates=FlightDates(departure=DEP, ret=RET),
        traveler_count=1,
        max_connections=2,          # split requires ≥1 connection allowed
        airline_filters=AirlineFilters(),
    )
    base.update(kw)
    return SearchRequest(**base)


# ---------------------------------------------------------------------------
# Core sanity: a split result is returned at all
# ---------------------------------------------------------------------------

@needs_key
def test_split_suggestion_returns_result():
    """run_split_suggestion must find at least one valid 4-leg combination."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, (
        "Split suggestion returned None — no valid 4-leg hub route found. "
        "Check that NAP (or another LCC hub) is in the Wizz route-map intersection "
        "for TLV and CLJ."
    )


@needs_key
def test_split_suggestion_has_four_legs():
    """Must return exactly 4 legs: origin→via, via→dest, dest→via, via→origin."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result — cannot check leg count."
    assert len(resp.legs) == 4, (
        f"Expected 4 legs, got {len(resp.legs)}: {[l.label for l in resp.legs]}"
    )


@needs_key
def test_split_suggestion_all_legs_have_options():
    """Every leg must have at least one bookable direct flight option."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    failed = [l for l in resp.legs if not l.options or l.cheapest_price == 0.0]
    assert not failed, (
        f"Legs with no options or zero price: {[(l.label, l.date, l.error) for l in failed]}"
    )


@needs_key
def test_split_suggestion_positive_total_price():
    """Total price must be positive and match the sum of the cheapest per-leg fares."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    assert resp.total_price > 0, f"total_price={resp.total_price}"
    expected = round(sum(l.cheapest_price for l in resp.legs), 2)
    assert abs(resp.total_price - expected) < 0.05, (
        f"total_price {resp.total_price} does not match leg sum {expected}"
    )


# ---------------------------------------------------------------------------
# Route correctness: legs must follow the TLV <-> CLJ via-hub pattern
# ---------------------------------------------------------------------------

@needs_key
def test_split_suggestion_route_origin_and_destination():
    """Leg 1 must start at TLV and Leg 4 must end at TLV (round trip)."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    legs = resp.legs
    # Leg 1: TLV → <hub>
    assert "TLV" in legs[0].label.upper(), f"Leg 1 should start at TLV: {legs[0].label}"
    # Leg 4: <hub> → TLV
    assert "TLV" in legs[3].label.upper(), f"Leg 4 should end at TLV: {legs[3].label}"
    # Leg 2: <hub> → CLJ
    assert "CLJ" in legs[1].label.upper(), f"Leg 2 should end at CLJ: {legs[1].label}"
    # Leg 3: CLJ → <hub>
    assert "CLJ" in legs[2].label.upper(), f"Leg 3 should start at CLJ: {legs[2].label}"


@needs_key
def test_split_suggestion_leg_dates_are_valid():
    """Leg dates must fall within the allowed date windows."""
    from datetime import date as date_t, timedelta

    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    legs = resp.legs

    leg1_date = date_t.fromisoformat(legs[0].date)
    leg2_date = date_t.fromisoformat(legs[1].date)
    leg3_date = date_t.fromisoformat(legs[2].date)
    leg4_date = date_t.fromisoformat(legs[3].date)

    # Leg 1 must be on departure date
    assert leg1_date == DEP, f"Leg 1 date {leg1_date} != {DEP}"

    # Leg 2: dep+1 .. dep+3
    assert DEP + timedelta(1) <= leg2_date <= DEP + timedelta(3), (
        f"Leg 2 date {leg2_date} out of window [{DEP + timedelta(1)}, {DEP + timedelta(3)}]"
    )

    # Leg 3: ret+0 .. ret+2
    assert RET <= leg3_date <= RET + timedelta(2), (
        f"Leg 3 date {leg3_date} out of window [{RET}, {RET + timedelta(2)}]"
    )

    # Leg 4: ret+1 .. ret+4
    assert RET + timedelta(1) <= leg4_date <= RET + timedelta(4), (
        f"Leg 4 date {leg4_date} out of window [{RET + timedelta(1)}, {RET + timedelta(4)}]"
    )


@needs_key
def test_split_suggestion_chronological_leg_order():
    """Legs must be in strict chronological order (no time-travel)."""
    from datetime import date as date_t

    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    dates = [date_t.fromisoformat(l.date) for l in resp.legs]
    for i in range(len(dates) - 1):
        assert dates[i] < dates[i + 1], (
            f"Leg {i+1} date {dates[i]} is not before leg {i+2} date {dates[i+1]}"
        )


# ---------------------------------------------------------------------------
# Via-hub: NAP (Naples) must be tried — the original bug was it was cut off
# ---------------------------------------------------------------------------

@needs_key
def test_split_via_nap_included_in_candidates(monkeypatch):
    """NAP must appear in the candidate hubs tried by run_split_suggestion.

    This directly guards against the regression where NAP was position 10
    in the intersection and got cut off by _MAX_VIA_CANDIDATES=3.
    """
    import app.search as search_mod

    seen_hubs: list[str] = []
    original = search_mod._split_for_one_via

    async def _spy(req, via, settings):
        seen_hubs.append(via)
        return await original(req, via, settings)

    monkeypatch.setattr(search_mod, "_split_for_one_via", _spy)

    asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))

    assert "NAP" in seen_hubs, (
        f"NAP was never tried as a split hub — hub candidates were: {seen_hubs}. "
        "Check _find_via_airports() ordering and _MAX_VIA_CANDIDATES cap."
    )


# ---------------------------------------------------------------------------
# Direct-only legs: each leg's cheapest option must be a direct flight
# ---------------------------------------------------------------------------

@needs_key
def test_split_suggestion_legs_are_direct():
    """All selected leg options must be direct flights (stops_count == 0)."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    for leg in resp.legs:
        for opt in leg.options:
            assert opt.stops_count == 0, (
                f"Leg '{leg.label}' option has {opt.stops_count} stop(s) — "
                "split legs must be direct flights only."
            )


# ---------------------------------------------------------------------------
# Price sanity: total cost should be reasonable for TLV<->CLJ via NAP
# (guard against wildly wrong prices due to pax-count or currency bugs)
# ---------------------------------------------------------------------------

@needs_key
def test_split_suggestion_price_in_plausible_range():
    """Total price for 1 pax TLV-CLJ-TLV via NAP should be between $50 and $2000."""
    resp = asyncio.run(run_split_suggestion(_split_request(), via="", settings=settings))
    assert resp is not None, "No split result."
    assert 50 < resp.total_price < 2000, (
        f"Total price {resp.total_price} {resp.currency} is outside the plausible "
        "range $50–$2000. Check currency conversion or pax-count multiplication."
    )

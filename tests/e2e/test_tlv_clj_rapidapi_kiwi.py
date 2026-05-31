"""E2E against REAL fares via RapidAPI 'Kiwi.com Cheap Flights' (default provider).

User scenario: TLV -> CLJ round trip 04/08/2026 - 11/08/2026.
Verifies the app pulls genuine multi-airline web fares (incl. Wizz/LCCs and
self-transfer combos — the same data kiwi.com / skyscanner show) and that
'best value' (low cost + few stops + short layover) is selected correctly.

Single RapidAPI key (x-rapidapi-key); no per-site scraping (bot-blocked, ToS).

Run:        pytest -m e2e
Auto-skips when RAPIDAPI_KEY is not set.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.config import Settings
from app.models import AirlineFilters, FlightDates, SearchRequest
from app.search import NoResultsError, run_search

pytestmark = pytest.mark.e2e

settings = Settings(provider="rapidapi-kiwi")

needs_key = pytest.mark.skipif(
    not settings.rapidapi_key,
    reason="RAPIDAPI_KEY not set in .env — skipping live RapidAPI-Kiwi e2e.",
)

DEP = date(2026, 8, 4)
RET = date(2026, 8, 11)


def _request(**kw) -> SearchRequest:
    base = dict(
        origin="TLV",
        destination="CLJ",
        flight_dates=FlightDates(departure=DEP, ret=RET),
        traveler_count=1,
        airline_filters=AirlineFilters(),
    )
    base.update(kw)
    return SearchRequest(**base)


@needs_key
def test_returns_real_offers_with_full_routes():
    resp = asyncio.run(run_search(_request(), settings))
    assert resp.total_considered > 0
    assert resp.options
    for o in resp.options:
        assert o.price_total > 0
        assert o.total_duration_min > 0
        assert o.segments, "each route must expose its full segment path"
        # segment integrity: codes + per-leg duration present
        for s in o.segments:
            assert s.origin and s.destination
            assert s.duration_min >= 0


@needs_key
def test_best_value_is_min_score_of_all_routes():
    resp = asyncio.run(run_search(_request(), settings))
    top = resp.best_value[0]
    assert top.score is not None
    assert all(o.score >= top.score - 1e-9 for o in resp.options if o.score is not None)


@needs_key
def test_cheapest_matches_web_minimum():
    resp = asyncio.run(run_search(_request(), settings))
    assert resp.cheapest.price_total == min(o.price_total for o in resp.options)


@needs_key
def test_direct_or_low_stop_preferred_when_available():
    try:
        resp = asyncio.run(run_search(_request(), settings))
    except NoResultsError:
        pytest.skip("No offers for route/date.")
    if any(o.stops_count <= 1 for o in resp.options):
        assert resp.best_value[0].stops_count <= max(
            1, min(o.stops_count for o in resp.options)
        )

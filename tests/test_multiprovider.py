"""MultiProvider per-provider timeout — offline, deterministic.

Reproduces the production split-ticket bug WITHOUT live APIs or the Kayak lock:
a slow provider must NOT cancel a fast provider's already-returned results. Before
the fix, `_one_leg` wrapped the whole MultiProvider in one wait_for, so a slow
Kayak (queued behind its global lock) cancelled the fast Kiwi/Skyscanner results
and nulled the leg → the entire split returned None.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.models import Itinerary
from app.providers import MultiProvider


def _itin(price: float, carrier: str = "W6") -> Itinerary:
    return Itinerary(
        id=f"{carrier}-{price}",
        price_total=price,
        currency="USD",
        carriers=[carrier],
        stops_count=0,
        total_duration_min=120,
    )


class _FastProvider:
    async def search(self, **kw):
        return [_itin(100.0)]


class _SlowProvider:
    """Sleeps far past any sane per-provider cap (stands in for lock-queued Kayak)."""
    def __init__(self, delay: float = 30.0):
        self._delay = delay

    async def search(self, **kw):
        await asyncio.sleep(self._delay)
        return [_itin(50.0, "XX")]


def test_slow_provider_does_not_cancel_fast_one():
    """With provider_timeout set, the fast provider's result is returned and the
    call completes near the cap — not after the slow provider's full delay."""
    mp = MultiProvider([_FastProvider(), _SlowProvider(delay=30.0)], provider_timeout=2)
    t0 = time.monotonic()
    out = asyncio.run(mp.search(origin="TLV", destination="OTP", departure_date="2026-08-04"))
    elapsed = time.monotonic() - t0
    assert [it.price_total for it in out] == [100.0], (
        f"Expected only the fast provider's itin, got {[it.price_total for it in out]}"
    )
    assert elapsed < 5, f"Should finish near the 2s cap, took {elapsed:.1f}s — slow provider was awaited"


def test_all_fast_providers_merge():
    """Sanity: when nothing is slow, results from all providers merge."""
    class _OtherFast:
        async def search(self, **kw):
            return [_itin(80.0, "FR")]

    mp = MultiProvider([_FastProvider(), _OtherFast()], provider_timeout=5)
    out = asyncio.run(mp.search(origin="TLV", destination="OTP", departure_date="2026-08-04"))
    assert sorted(it.price_total for it in out) == [80.0, 100.0]


def test_all_providers_slow_raises():
    """If every provider exceeds the cap, MultiProvider raises (nothing to merge)."""
    mp = MultiProvider([_SlowProvider(delay=30.0), _SlowProvider(delay=30.0)], provider_timeout=1)
    with pytest.raises(RuntimeError):
        asyncio.run(mp.search(origin="TLV", destination="OTP", departure_date="2026-08-04"))

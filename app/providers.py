"""Data-provider abstraction: turn a search into normalized Itineraries.

Each provider returns `list[Itinerary]` so the filtering/scoring/output layers
stay source-agnostic. Choose via Settings.provider ("kiwi" or "amadeus").
"""
from __future__ import annotations

import asyncio
from typing import Protocol

from .amadeus_client import AmadeusClient
from .config import Settings
from .kayak_client import KayakClient, KayakError
from .kayak_transform import transform_response as transform_kayak
from .skyscanner_client import SkyscannerClient, SkyscannerError
from .skyscanner_transform import transform_response as transform_skyscanner
from .kiwi_client import KiwiClient
from .kiwi_transform import transform_trips
from .kiwi_rapidapi_client import KiwiRapidClient
from .kiwi_rapidapi_transform import transform_itineraries as transform_kiwi_rapid
from .mock_provider import MockProvider
from .models import Itinerary
from .rapidapi_client import RapidApiClient
from .rapidapi_transform import transform_itineraries
from .transform import transform_offers
from .wizz_client import WizzClient
from .wizz_transform import transform_timetable as transform_wizz


class Provider(Protocol):
    async def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None,
        adults: int,
        non_stop: bool,
        included_airlines: list[str] | None,
        excluded_airlines: list[str] | None,
        currency: str,
    ) -> list[Itinerary]: ...


class AmadeusProvider:
    def __init__(self, settings: Settings):
        self._client = AmadeusClient(settings)

    async def search(self, **kw) -> list[Itinerary]:
        offers = await self._client.search_offers(**kw)
        return transform_offers(offers)


class KiwiProvider:
    def __init__(self, settings: Settings):
        self._client = KiwiClient(settings)

    async def search(self, **kw) -> list[Itinerary]:
        trips, currency = await self._client.search(**kw)
        return transform_trips(trips, currency)


class RapidApiProvider:
    def __init__(self, settings: Settings):
        self._client = RapidApiClient(settings)
        self._currency = settings.currency

    async def search(self, **kw) -> list[Itinerary]:
        items = await self._client.search(**kw)
        itins = transform_itineraries(items)
        for it in itins:            # API often omits currency in response
            if not it.currency:
                it.currency = self._currency
        return itins


# Caps concurrent Kiwi/RapidAPI calls across the whole process. The parallel split
# search fans out ~60 leg calls (hubs × legs); without a cap RapidAPI returns 429.
# A Semaphore (NOT a serializing Lock like Kayak's) allows real concurrency while
# bounding the burst: ~60 / 8 × 1.5s ≈ 12s.
_KIWI_SEMAPHORE = asyncio.Semaphore(8)


class KiwiRapidProvider:
    """Kiwi.com Cheap Flights via RapidAPI — real LCC + self-transfer fares."""

    def __init__(self, settings: Settings):
        self._client = KiwiRapidClient(settings)
        self._currency = settings.currency

    async def search(self, **kw) -> list[Itinerary]:
        async with _KIWI_SEMAPHORE:
            items = await self._client.search(**kw)
        return transform_kiwi_rapid(items, self._currency.upper())


class KayakProvider:
    """Kayak flight search via RapidAPI."""

    def __init__(self, settings: Settings):
        self._client = KayakClient(settings)

    async def search(self, **kw) -> list[Itinerary]:
        data = await self._client.search(**kw)
        return transform_kayak(data)


class SkyscannerProvider:
    """Skyscanner Flights Travel API via RapidAPI."""

    def __init__(self, settings: Settings):
        self._client = SkyscannerClient(settings)
        self._currency = settings.currency

    async def search(self, **kw) -> list[Itinerary]:
        data = await self._client.search(**kw)
        return transform_skyscanner(data, self._currency)


class WizzProvider:
    """Wizz Air direct fares via the public be.wizzair.com timetable API.

    Returns itineraries only for routes Wizz actually flies direct; everything
    else comes back empty (no Wizz on that sector).
    """

    def __init__(self, settings: Settings):
        self._client = WizzClient(settings)
        self._settings = settings

    async def get_direct_destinations(self, iata: str) -> list[str]:
        """Return all airports Wizz flies to directly from `iata`."""
        return await self._client.get_direct_destinations(iata)

    async def search(self, **kw) -> list[Itinerary]:
        data = await self._client.search(
            origin=kw["origin"], destination=kw["destination"],
            departure_date=kw["departure_date"], return_date=kw.get("return_date"),
        )
        return transform_wizz(
            data,
            origin=kw["origin"].upper(),
            destination=kw["destination"].upper(),
            dep_date=kw["departure_date"],
            ret_date=kw.get("return_date"),
            target_currency=self._settings.currency,
            eur_usd=self._settings.wizz_eur_usd,
        )


class MultiProvider:
    """Run multiple providers in parallel and merge results."""

    def __init__(self, providers: list, provider_timeout: float | None = None):
        self._providers = providers
        # Per-provider wall-clock cap. When set, each provider.search is wrapped in
        # its own wait_for so one slow provider (e.g. Kayak queued behind its global
        # lock) can NEVER cancel the siblings or hang the leg — it just times out,
        # is caught by the return_exceptions gather, and the fast providers' results
        # are still merged. Without this, an outer wait_for around the whole
        # MultiProvider would cancel already-returned Kiwi/Skyscanner results too.
        self._provider_timeout = provider_timeout

    async def search(self, **kw) -> list[Itinerary]:
        import asyncio
        import logging
        import time
        log = logging.getLogger(__name__)

        timeout = self._provider_timeout

        async def _call(provider, **kw) -> list[Itinerary]:
            if timeout is None:
                return await provider.search(**kw)
            return await asyncio.wait_for(provider.search(**kw), timeout=timeout)

        async def _fetch_with_retry(provider, **kw) -> list[Itinerary]:
            """One retry after 2 s for transient failures.

            A TimeoutError is NOT retried: the provider is already slow, so a second
            bounded attempt only burns more wall-clock for marginal gain. Let it
            drop out and keep the fast providers' results."""
            name = type(provider).__name__
            t0 = time.monotonic()
            try:
                out = await _call(provider, **kw)
                log.info("PERF provider=%s returned=%d in %.2fs", name, len(out), time.monotonic() - t0)
                return out
            except asyncio.TimeoutError:
                log.warning("%s timed out after %.2fs (cap=%ss) — skipping", name, time.monotonic() - t0, timeout)
                raise
            except Exception as e:
                log.warning("%s failed (attempt 1) after %.2fs: %s — retrying in 2 s", name, time.monotonic() - t0, e)
                await asyncio.sleep(2)
                t1 = time.monotonic()
                try:
                    out = await _call(provider, **kw)
                    log.info("PERF provider=%s returned=%d in %.2fs (retry)", name, len(out), time.monotonic() - t1)
                    return out
                except Exception as e2:
                    log.error("%s failed (attempt 2) after %.2fs: %s — skipping", name, time.monotonic() - t1, e2)
                    raise

        tasks = [asyncio.create_task(_fetch_with_retry(p, **kw)) for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[Itinerary] = []
        seen: set[str] = set()
        errors: list[str] = []
        for provider, batch in zip(self._providers, results):
            name = type(provider).__name__
            if isinstance(batch, Exception):
                errors.append(f"{name}: {batch}")
                continue
            for it in batch:
                key = (
                    ",".join(sorted(it.carriers)),
                    it.price_total,
                    it.segments[0].departure_at if it.segments else "",
                )
                if key not in seen:
                    seen.add(key)
                    merged.append(it)

        if not merged and errors:
            raise RuntimeError(
                f"All {len(errors)} provider(s) failed — "
                + "; ".join(errors)
            )

        if errors:
            log.warning("Partial provider failures (%d/%d): %s", len(errors), len(self._providers), "; ".join(errors))

        return merged


def get_provider(settings: Settings, fast: bool = False) -> Provider:
    if settings.provider == "amadeus":
        return AmadeusProvider(settings)
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider == "kiwi":
        return KiwiProvider(settings)
    if settings.provider == "rapidapi":
        return RapidApiProvider(settings)
    if settings.provider == "kayak":
        return KayakProvider(settings)
    if settings.provider == "skyscanner":
        return SkyscannerProvider(settings)
    if settings.provider == "multi":
        # fast tier drops the slow Skyscanner provider (~40s) so the first
        # results render in ~3s; the full tier folds Skyscanner back in.
        # Wizz (direct LCC fares, ~0.5s) is in both tiers — it's fast and
        # surfaces cheap fares the aggregators miss.
        fast_set = [KiwiRapidProvider(settings), KayakProvider(settings)]
        if settings.wizz_enabled:
            fast_set.append(WizzProvider(settings))
        if fast:
            return MultiProvider(fast_set)
        return MultiProvider(fast_set + [SkyscannerProvider(settings)])
    return KiwiRapidProvider(settings)

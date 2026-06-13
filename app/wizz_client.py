"""Wizz Air direct fetcher via the public be.wizzair.com timetable API.

Ultra-low-cost Wizz fares that the RapidAPI aggregators (Kiwi/Kayak/Skyscanner)
under-represent. Wizz is point-to-point (every flight is direct), so the
timetable endpoint — which returns the cheapest price per date — is enough.

Notes / limits:
  - The detailed `/Api/search/search` endpoint is Akamai bot-protected (429);
    `/Api/search/timetable` is open and is what we use.
  - The API version in the path rotates; we auto-discover it from the public
    site and fall back to a configured constant.
  - Timetable gives price + departure datetime(s) per date but no arrival time,
    so segment duration is estimated (see wizz_transform).
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

# Wizz rate-limits bursts of timetable calls.  The semaphore is now per-instance
# so that parallel split-hub searches don't all queue through a single slot.
# Each WizzProvider (= one hub candidate) gets its own 2-slot semaphore.
_MAX_429_RETRIES = 3
_WIZZ_SEM_SLOTS = 6   # concurrent calls per provider instance; 6 fits ~12 legs in 2 batches ≤45s

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
_VERSION_RE = re.compile(r"be\.wizzair\.com\\?/(\d+\.\d+\.\d+)\\?/Api")


class WizzError(RuntimeError):
    """Raised when the Wizz timetable API fails."""


class WizzClient:
    BASE = "https://be.wizzair.com"
    SITE = "https://wizzair.com/en-gb"

    def __init__(self, settings):
        self._s = settings
        self._version: str | None = None
        self._sem = asyncio.Semaphore(_WIZZ_SEM_SLOTS)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://wizzair.com",
            "Referer": "https://wizzair.com/",
            "User-Agent": _UA,
        }

    async def _get_version(self, client: httpx.AsyncClient) -> str:
        """Discover the current API version from the site; cache per instance."""
        if self._version:
            return self._version
        try:
            r = await client.get(self.SITE, headers={"User-Agent": _UA}, follow_redirects=True)
            m = _VERSION_RE.search(r.text)
            if m:
                self._version = m.group(1)
                logger.info("WIZZ discovered API version %s", self._version)
        except Exception as e:  # pragma: no cover - network best-effort
            logger.warning("WIZZ version discovery failed (%s); using fallback %s", e, self._s.wizz_version)
        self._version = self._version or self._s.wizz_version
        return self._version

    async def _timetable(self, client, version, flight_list) -> dict:
        url = f"{self.BASE}/{version}/Api/search/timetable"
        body = {
            "flightList": flight_list,
            "priceType": "regular",
            "adultCount": 1,
            "childCount": 0,
            "infantCount": 0,
        }
        return await client.post(url, json=body, headers=self._headers())

    async def get_direct_destinations(self, origin: str) -> list[str]:
        """Return IATA codes of all airports Wizz flies to directly from `origin`.

        Uses the public route-map endpoint (no auth needed). Falls back to []
        on any error so callers can degrade gracefully.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                version = await self._get_version(client)
                url = f"{self.BASE}/{version}/Api/asset/map"
                resp = await client.get(
                    url,
                    params={"languageCode": "en-gb"},
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                for city in data.get("cities", []):
                    if city.get("iata", "").upper() == origin.upper():
                        return [
                            c["iata"].upper()
                            for c in city.get("connections", [])
                            if c.get("iata")
                        ]
        except Exception as exc:
            logger.debug("WIZZ route-map failed for %s: %s", origin, exc)
        return []

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None,
        **_kw,
    ) -> dict:
        """Return raw timetable JSON for the exact date(s).

        Queries a single-day window per direction (from==to==date). Wizz routes
        it does not serve come back with empty flight lists, which the transform
        turns into zero itineraries — exactly the desired behaviour.
        """
        flight_list = [{
            "departureStation": origin,
            "arrivalStation": destination,
            "from": departure_date,
            "to": departure_date,
        }]
        if return_date:
            flight_list.append({
                "departureStation": destination,
                "arrivalStation": origin,
                "from": return_date,
                "to": return_date,
            })

        empty = {"outboundFlights": [], "returnFlights": []}
        async with self._sem:
            async with httpx.AsyncClient(timeout=20) as client:
                version = await self._get_version(client)
                resp = await self._timetable(client, version, flight_list)
                # Stale version → path 404; rediscover once and retry.
                if resp.status_code == 404:
                    self._version = None
                    version = await self._get_version(client)
                    resp = await self._timetable(client, version, flight_list)
                # 429/503 = rate limited (burst of leg calls); back off and retry.
                for attempt in range(_MAX_429_RETRIES):
                    if resp.status_code not in (429, 503):
                        break
                    await asyncio.sleep(0.8 * (attempt + 1))
                    resp = await self._timetable(client, version, flight_list)
                # 400 = route Wizz does not serve; 429/503 = throttled → no flights,
                # not a hard error (don't fail the whole multi-provider search).
                if resp.status_code in (400, 429, 503):
                    return empty
                if resp.status_code != 200:
                    raise WizzError(f"Wizz timetable HTTP {resp.status_code}")
                return resp.json()

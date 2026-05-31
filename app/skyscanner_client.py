"""Client for Skyscanner Flights Travel API on RapidAPI.

Two-step flow:
  1. Airport lookup  GET /flights/searchAirport?query={iata}  → skyId + entityId
  2. Flight search   GET /flights/searchFlights               → itineraries[]

Results are returned as-is so skyscanner_transform.py can normalize them.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings

SKYSCANNER_BASE = "https://skyscanner-flights-travel-api.p.rapidapi.com"


class SkyscannerError(RuntimeError):
    pass


class SkyscannerRateLimitError(SkyscannerError):
    pass


# Simple in-memory cache: IATA → (skyId, entityId)
_airport_cache: dict[str, tuple[str, str]] = {}


class SkyscannerClient:
    def __init__(self, settings: Settings):
        self._s = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-rapidapi-key": self._s.rapidapi_key,
            "x-rapidapi-host": self._s.skyscanner_rapidapi_host,
        }

    async def _lookup_airport(self, iata: str) -> tuple[str, str]:
        """Return (skyId, entityId) for an IATA code, with caching."""
        iata_upper = iata.upper()
        if iata_upper in _airport_cache:
            return _airport_cache[iata_upper]

        url = f"{SKYSCANNER_BASE}/flights/searchAirport"
        params = {"market": "US", "locale": "en-US", "query": iata_upper}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
        if resp.status_code == 429:
            raise SkyscannerRateLimitError("Skyscanner rate-limited on airport lookup")
        if resp.status_code != 200:
            raise SkyscannerError(f"Airport lookup failed: {resp.status_code} {resp.text[:200]}")

        data = resp.json()
        places = data.get("places") or []

        # Prefer exact AIRPORT match for the queried IATA
        for place in places:
            if place.get("skyId", "").upper() == iata_upper and place.get("placeType") == "AIRPORT":
                result = (place["skyId"], place["entityId"])
                _airport_cache[iata_upper] = result
                return result

        # Fall back to first airport result
        for place in places:
            if place.get("placeType") == "AIRPORT":
                result = (place["skyId"], place["entityId"])
                _airport_cache[iata_upper] = result
                return result

        # Fall back to first result of any type
        if places:
            result = (places[0]["skyId"], places[0]["entityId"])
            _airport_cache[iata_upper] = result
            return result

        raise SkyscannerError(f"No airport found for IATA code: {iata_upper}")

    @retry(
        retry=retry_if_exception_type(SkyscannerRateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
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
    ) -> dict:
        if not self._s.rapidapi_key:
            raise SkyscannerError("RapidAPI key missing. Set RAPIDAPI_KEY in .env.")

        # Resolve both airports in parallel
        (origin_sky, origin_entity), (dest_sky, dest_entity) = await asyncio.gather(
            self._lookup_airport(origin),
            self._lookup_airport(destination),
        )

        params: dict = {
            "originSkyId": origin_sky,
            "destinationSkyId": dest_sky,
            "originEntityId": origin_entity,
            "destinationEntityId": dest_entity,
            "date": departure_date,
            "cabinClass": "economy",
            "adults": str(max(adults, 1)),
            "sortBy": "best",
            "currency": currency.upper(),
            "market": "US",
            "locale": "en-US",
            "countryCode": "US",
        }

        if non_stop:
            params["stops"] = "0"

        if return_date:
            params["returnDate"] = return_date

        url = f"{SKYSCANNER_BASE}/flights/searchFlights"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers=self._headers(), params=params)

        if resp.status_code == 429:
            raise SkyscannerRateLimitError("Skyscanner rate-limited on flight search")
        if resp.status_code != 200:
            raise SkyscannerError(f"Skyscanner search failed: {resp.status_code} {resp.text[:300]}")

        return resp.json()

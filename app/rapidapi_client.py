"""Client for the Sky-Scrapper API on RapidAPI (Skyscanner flight data).

Two steps: resolve each airport (skyId + entityId), then search flights.
Only needs a single RapidAPI key (x-rapidapi-key). Free tier available.

Subscribe: https://rapidapi.com/apiheya/api/sky-scrapper
"""
from __future__ import annotations

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings


class RapidApiError(RuntimeError):
    pass


class RapidApiRateLimitError(RapidApiError):
    pass


class RapidApiClient:
    def __init__(self, settings: Settings):
        self._s = settings
        self._airport_cache: dict[str, dict] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self._s.rapidapi_key,
            "x-rapidapi-host": self._s.rapidapi_host,
        }

    @property
    def _base(self) -> str:
        return f"https://{self._s.rapidapi_host}"

    @retry(
        retry=retry_if_exception_type(RapidApiRateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        resp = await client.get(
            f"{self._base}{path}", params=params, headers=self._headers()
        )
        if resp.status_code == 429:
            raise RapidApiRateLimitError("RapidAPI rate limit (429).")
        if resp.status_code >= 400:
            raise RapidApiError(f"RapidAPI {path} failed ({resp.status_code}): {resp.text}")
        return resp.json()

    async def _resolve_airport(self, client: httpx.AsyncClient, iata: str) -> dict:
        if iata in self._airport_cache:
            return self._airport_cache[iata]
        data = await self._get(
            client,
            "/api/v1/flights/searchAirport",
            {"query": iata, "locale": self._s.rapidapi_locale},
        )
        items = data.get("data", []) or []
        # prefer an exact IATA (skyId) match
        chosen = None
        for it in items:
            if str(it.get("skyId", "")).upper() == iata.upper():
                chosen = it
                break
        chosen = chosen or (items[0] if items else None)
        if not chosen:
            raise RapidApiError(f"Airport '{iata}' not found via RapidAPI.")
        nav = chosen.get("navigation", {}) or {}
        rp = nav.get("relevantFlightParams", {}) or {}
        info = {
            "skyId": chosen.get("skyId") or rp.get("skyId"),
            "entityId": rp.get("entityId") or nav.get("entityId") or chosen.get("entityId"),
        }
        if not info["skyId"] or not info["entityId"]:
            raise RapidApiError(f"Incomplete airport data for '{iata}'.")
        self._airport_cache[iata] = info
        return info

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
        max_results: int = 50,
    ) -> list[dict]:
        if not self._s.rapidapi_key:
            raise RapidApiError("RapidAPI key missing. Set RAPIDAPI_KEY in .env.")

        async with httpx.AsyncClient(timeout=45) as client:
            o = await self._resolve_airport(client, origin)
            d = await self._resolve_airport(client, destination)

            params: dict[str, str | int] = {
                "originSkyId": o["skyId"],
                "destinationSkyId": d["skyId"],
                "originEntityId": o["entityId"],
                "destinationEntityId": d["entityId"],
                "date": departure_date,
                "cabinClass": "economy",
                "adults": adults,
                "sortBy": "best",
                "currency": currency,
                "market": self._s.rapidapi_market,
                "countryCode": self._s.rapidapi_market,
            }
            if return_date:
                params["returnDate"] = return_date

            payload = await self._get(client, "/api/v2/flights/searchFlights", params)

        data = payload.get("data", {}) or {}
        itineraries = data.get("itineraries", []) or []
        return itineraries[:max_results]

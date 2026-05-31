"""Client for 'Kiwi.com Cheap Flights' on RapidAPI.

Single RapidAPI key (x-rapidapi-key). Real multi-airline fares incl. LCCs
(Wizz, Ryanair) and self-transfer combos. GraphQL-style JSON response with
`itineraries[]`, each split into `outbound` / `inbound` sectors.

Endpoints: /round-trip and /one-way.
Locations are passed as `Airport:XXX` (IATA).
Subscribe: https://rapidapi.com/.../kiwi-com-cheap-flights
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


class KiwiRapidError(RuntimeError):
    pass


class KiwiRapidRateLimitError(KiwiRapidError):
    pass


class KiwiRapidClient:
    def __init__(self, settings: Settings):
        self._s = settings

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self._s.rapidapi_key,
            "x-rapidapi-host": self._s.kiwi_rapidapi_host,
        }

    @property
    def _base(self) -> str:
        return f"https://{self._s.kiwi_rapidapi_host}"

    @retry(
        retry=retry_if_exception_type(KiwiRapidRateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        resp = await client.get(
            f"{self._base}{path}", params=params, headers=self._headers()
        )
        if resp.status_code == 429:
            raise KiwiRapidRateLimitError("RapidAPI rate limit (429).")
        if resp.status_code >= 400:
            raise KiwiRapidError(
                f"Kiwi RapidAPI {path} failed ({resp.status_code}): {resp.text[:300]}"
            )
        return resp.json()

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
            raise KiwiRapidError("RapidAPI key missing. Set RAPIDAPI_KEY in .env.")

        params: dict[str, str | int] = {
            "source": f"Airport:{origin}",
            "destination": f"Airport:{destination}",
            "currency": currency.lower(),
            "locale": "en",
            "adults": adults,
            "children": 0,
            "infants": 0,
            "handbags": 1,
            "holdbags": 0,
            "cabinClass": "ECONOMY",
            "sortBy": "QUALITY",
            "sortOrder": "ASCENDING",
            "transportTypes": "FLIGHT",
            "limit": max_results,
            "outboundDepartureDateStart": f"{departure_date}T00:00:00",
            "outboundDepartureDateEnd": f"{departure_date}T23:59:59",
        }
        if non_stop:
            params["maxStopsCount"] = 0
            params["enableSelfTransfer"] = "false"
        else:
            params["enableSelfTransfer"] = "true"

        path = "/one-way"
        if return_date:
            path = "/round-trip"
            params["inboundDepartureDateStart"] = f"{return_date}T00:00:00"
            params["inboundDepartureDateEnd"] = f"{return_date}T23:59:59"

        async with httpx.AsyncClient(timeout=60) as client:
            payload = await self._get(client, path, params)

        return payload.get("itineraries", []) or []

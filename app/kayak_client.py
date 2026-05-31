"""Client for 'Kayak' flight search via RapidAPI (kayak-api.p.rapidapi.com).

POST /search-flights — returns results[], legs{}, segments{}, airports{}.
Legs are indexed by ID in top-level dicts; result.legs[] contains ordered
references. Duration fields are in minutes.
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

KAYAK_BASE = "https://kayak-api.p.rapidapi.com"


class KayakError(RuntimeError):
    pass


class KayakRateLimitError(KayakError):
    pass


class KayakClient:
    def __init__(self, settings: Settings):
        self._s = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-rapidapi-key": self._s.rapidapi_key,
            "x-rapidapi-host": self._s.kayak_rapidapi_host,
        }

    @retry(
        retry=retry_if_exception_type(KayakRateLimitError),
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
        max_results: int = 50,
    ) -> dict:
        if not self._s.rapidapi_key:
            raise KayakError("RapidAPI key missing. Set RAPIDAPI_KEY in .env.")

        passengers = ["ADT"] * max(adults, 1)

        payload: dict = {
            "origin": origin,
            "destination": destination,
            "departure_date": departure_date,
            "searchMetaData": {
                "pageNumber": 1,
                "priceMode": "per-person",
            },
            "userSearchParams": {
                "sortMode": "price_a",
                "passengers": passengers,
            },
        }

        if return_date:
            payload["return_date"] = return_date

        # Stops filter: non_stop = direct only
        filter_parts = []
        if non_stop:
            filter_parts.append("stops=-1")  # -1 = direct only in Kayak

        # Airline filters
        if included_airlines:
            filter_parts.append("airlines=" + ",".join(included_airlines))
        elif excluded_airlines:
            filter_parts.append("airlines=" + ",".join(f"-{a}" for a in excluded_airlines))

        if filter_parts:
            payload["filterParams"] = {"fs": ";".join(filter_parts)}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{KAYAK_BASE}/search-flights",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code == 429:
            raise KayakRateLimitError("Kayak RapidAPI rate limit (429).")
        if resp.status_code >= 400:
            raise KayakError(
                f"Kayak API failed ({resp.status_code}): {resp.text[:300]}"
            )

        body = resp.json()
        data = body.get("data") or {}
        return {
            "results": data.get("results") or [],
            "legs": data.get("legs") or {},
            "segments": data.get("segments") or {},
            "airports": data.get("airports") or {},
            "currency": currency.upper(),
        }

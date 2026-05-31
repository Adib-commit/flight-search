from __future__ import annotations

from datetime import date

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings


class KiwiError(RuntimeError):
    pass


class KiwiRateLimitError(KiwiError):
    pass


def _kiwi_date(iso: str) -> str:
    """Kiwi Tequila wants dd/mm/yyyy."""
    d = date.fromisoformat(iso)
    return d.strftime("%d/%m/%Y")


class KiwiClient:
    """Client for Kiwi.com Tequila /v2/search."""

    def __init__(self, settings: Settings):
        self._s = settings

    @retry(
        retry=retry_if_exception_type(KiwiRateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, params: dict) -> dict:
        resp = await client.get(
            f"{self._s.kiwi_base_url}/v2/search",
            params=params,
            headers={"apikey": self._s.kiwi_api_key, "accept": "application/json"},
        )
        if resp.status_code == 429:
            raise KiwiRateLimitError("Kiwi rate limit (429).")
        if resp.status_code >= 400:
            raise KiwiError(f"Kiwi search failed ({resp.status_code}): {resp.text}")
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
    ) -> tuple[list[dict], str]:
        if not self._s.kiwi_api_key:
            raise KiwiError("Kiwi credentials missing. Set KIWI_API_KEY in .env.")

        params: dict[str, str | int] = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": _kiwi_date(departure_date),
            "date_to": _kiwi_date(departure_date),
            "adults": adults,
            "curr": currency,
            "vehicle_type": "aircraft",
            "limit": max_results,
            "sort": "price",
        }
        if return_date:
            params["return_from"] = _kiwi_date(return_date)
            params["return_to"] = _kiwi_date(return_date)
        if non_stop:
            params["max_stopovers"] = 0
        if included_airlines:
            params["select_airlines"] = ",".join(included_airlines)
            params["select_airlines_exclude"] = "false"
        elif excluded_airlines:
            params["select_airlines"] = ",".join(excluded_airlines)
            params["select_airlines_exclude"] = "true"

        async with httpx.AsyncClient(timeout=40) as client:
            payload = await self._get(client, params)
        return payload.get("data", []), payload.get("currency", currency)

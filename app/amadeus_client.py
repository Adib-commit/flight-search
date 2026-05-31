from __future__ import annotations

import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings


class AmadeusError(RuntimeError):
    pass


class RateLimitError(AmadeusError):
    pass


class AmadeusClient:
    """Async client for Amadeus Flight Offers Search with token caching."""

    def __init__(self, settings: Settings):
        self._s = settings
        self._token: str | None = None
        self._token_exp: float = 0.0

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token

        if not self._s.amadeus_api_key or not self._s.amadeus_api_secret:
            raise AmadeusError(
                "Amadeus credentials missing. Set AMADEUS_API_KEY and "
                "AMADEUS_API_SECRET in .env."
            )

        resp = await client.post(
            f"{self._s.amadeus_base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._s.amadeus_api_key,
                "client_secret": self._s.amadeus_api_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise AmadeusError(f"Auth failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = now + float(data.get("expires_in", 1799))
        return self._token

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, params: dict) -> dict:
        token = await self._get_token(client)
        resp = await client.get(
            f"{self._s.amadeus_base_url}/v2/shopping/flight-offers",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 429:
            raise RateLimitError("Amadeus rate limit (429).")
        if resp.status_code >= 400:
            raise AmadeusError(f"Flight search failed ({resp.status_code}): {resp.text}")
        return resp.json()

    async def search_offers(
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
        params: dict[str, str | int | bool] = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": departure_date,
            "adults": adults,
            "currencyCode": currency,
            "max": max_results,
        }
        if return_date:
            params["returnDate"] = return_date
        if non_stop:
            params["nonStop"] = "true"
        # Amadeus: included/excluded are mutually exclusive
        if included_airlines:
            params["includedAirlineCodes"] = ",".join(included_airlines)
        elif excluded_airlines:
            params["excludedAirlineCodes"] = ",".join(excluded_airlines)

        async with httpx.AsyncClient(timeout=30) as client:
            payload = await self._get(client, params)
        return payload.get("data", [])

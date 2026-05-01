"""HTTP client for exchangerate-api.com with retry and timeout."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class ExchangeRateError(RuntimeError):
    """Raised when the API returns an unexpected payload or a missing rate."""


class ExchangeRateClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
        reraise=True,
    )
    def fetch_rates_to_usd(self, currencies: list[str]) -> dict[str, float]:
        if not self._api_key:
            raise ExchangeRateError("EXCHANGE_RATE_API_KEY is not set")
        wanted = {c for c in currencies if c != "USD"}
        url = f"{self._base_url}/{self._api_key}/latest/USD"
        resp = httpx.get(url, timeout=self._timeout)
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()

        if payload.get("result") != "success":
            err = payload.get("error-type") or payload.get("error") or "unknown"
            raise ExchangeRateError(f"API returned non-success: {err}")

        rates = payload.get("conversion_rates")
        if not isinstance(rates, dict):
            raise ExchangeRateError("unexpected payload: missing 'conversion_rates'")

        result: dict[str, float] = {"USD": 1.0}
        for cur in wanted:
            value = rates.get(cur)
            if not isinstance(value, (int, float)) or value <= 0:
                raise ExchangeRateError(f"invalid rate for {cur}: {value!r}")
            result[cur] = 1.0 / float(value)
        return result

"""Shared HTTP helper: retrying, rate-limited GET returning JSON."""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .. import config


class PolyAPIError(RuntimeError):
    pass


_RETRYABLE = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.WriteError,
)


class PolyClient:
    """A small wrapper around httpx with retry, rate-limit, and JSON helpers."""

    def __init__(self, base_url: str, *, timeout: float | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout or config.HTTP_TIMEOUT_SEC,
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._last_req_at: float = 0.0

    def __enter__(self) -> "PolyClient":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _throttle(self) -> None:
        delta = time.monotonic() - self._last_req_at
        if delta < config.RATE_LIMIT_DELAY_SEC:
            time.sleep(config.RATE_LIMIT_DELAY_SEC - delta)
        self._last_req_at = time.monotonic()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=config.HTTP_BACKOFF_BASE_SEC, min=1, max=20),
        stop=stop_after_attempt(config.HTTP_MAX_RETRIES),
        reraise=True,
    )
    def get_json(self, path: str, params: dict | None = None) -> Any:
        self._throttle()
        url = f"{self.base_url}{path}"
        r = self._client.get(url, params=params)
        if r.status_code == 429:
            # explicit backoff for rate-limit
            time.sleep(2.0)
            raise httpx.ReadTimeout("rate-limited 429", request=r.request)
        if r.status_code >= 500:
            raise httpx.RemoteProtocolError(f"{r.status_code} from {url}", request=r.request)
        if r.status_code >= 400:
            # Polymarket signals "you've paginated past our cap" with 400 + a
            # specific message. Treat as end-of-data so callers can stop iterating.
            if r.status_code == 400 and "max historical activity offset" in (r.text or ""):
                return []
            raise PolyAPIError(f"GET {url} -> {r.status_code} {r.text[:300]}")
        return r.json()

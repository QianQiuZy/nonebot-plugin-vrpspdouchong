"""Shared request pacing and 429 handling for all VR / PSP API calls."""

from __future__ import annotations

from asyncio import Lock, sleep
from time import monotonic

import httpx

_REQUEST_INTERVAL = 1.0 / 15
_RETRY_DELAY = 1.0
_MAX_429_RETRIES = 3


class _RequestLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_request_at = 0.0

    async def wait(self) -> None:
        # Serialize only request starts; slow responses can still overlap.
        async with self._lock:
            while True:
                now = monotonic()
                delay = self._next_request_at - now
                if delay <= 0:
                    self._next_request_at = now + _REQUEST_INTERVAL
                    return
                # A concurrent 429 may extend the cooldown while we sleep.
                await sleep(delay)

    def cooldown(self) -> None:
        self._next_request_at = max(self._next_request_at, monotonic() + _RETRY_DELAY)


_limiter = _RequestLimiter()


async def get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: httpx.QueryParamTypes | None = None,
) -> httpx.Response:
    """Pace every attempt globally and retry a 429 up to three times."""
    for attempt in range(_MAX_429_RETRIES + 1):
        await _limiter.wait()
        response = await client.get(url, params=params)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        _limiter.cooldown()
        if attempt == _MAX_429_RETRIES:
            response.raise_for_status()
        await response.aclose()

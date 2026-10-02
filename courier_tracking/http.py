"""Shared polite HTTP client: honest User-Agent, timeouts, retries, per-host rate limit.

Every adapter goes through `PoliteClient`, so politeness rules live in one place.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from . import __version__
from .errors import CourierUnavailableError

log = logging.getLogger(__name__)

# Where a courier's ops team can find out who is calling. Works with no setup;
# COURIER_TRACKING_CONTACT overrides it (e.g. a fork's repo URL). Blank values are ignored.
DEFAULT_CONTACT = "https://github.com/MohammedZaid-AI/courier-tracking-api"


def contact() -> str:
    return os.environ.get("COURIER_TRACKING_CONTACT", "").strip() or DEFAULT_CONTACT


def build_user_agent() -> str:
    return f"courier-tracking-api/{__version__} (+{contact()}; public tracking pages only)"


USER_AGENT = build_user_agent()

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HostRateLimiter:
    """At most one request per `min_interval` seconds per host."""

    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_slot: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            slot = self._next_slot.get(host, now)
            if slot > now:
                await self._sleep(slot - now)
                now = slot
            self._next_slot[host] = now + self.min_interval


class PoliteClient:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        max_retry_after: float = 10.0,
        rate_limiter: HostRateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_retry_after = max_retry_after
        self.rate_limiter = rate_limiter or HostRateLimiter()
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-IN,en;q=0.8"},
        )

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies

    async def request(self, method: str, url: str, *, courier: str, **kwargs) -> httpx.Response:
        """Send with retries. Returns any non-retryable response (incl. 4xx) to the caller.

        Raises CourierUnavailableError once retries are exhausted.
        """
        host = urlsplit(url).hostname or ""
        last_problem = "unknown error"
        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                await self._sleep(self._backoff(attempt, last_response))
                last_response = None
            await self.rate_limiter.wait(host)
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                last_problem = "timed out"
            except httpx.TransportError as exc:
                last_problem = f"network error ({type(exc).__name__})"
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return resp
                last_response = resp
                last_problem = f"HTTP {resp.status_code}"
            log.warning("%s %s attempt %d/%d failed: %s", courier, host, attempt + 1, self.max_retries + 1, last_problem)
        raise CourierUnavailableError(
            f"{courier} is unavailable: {last_problem} after {self.max_retries + 1} attempts",
            courier=courier,
        )

    def _backoff(self, attempt: int, resp: httpx.Response | None) -> float:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                return min(float(retry_after), self.max_retry_after)
        delay = self.backoff_base * (2 ** (attempt - 1))
        return delay + random.uniform(0, delay / 2)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

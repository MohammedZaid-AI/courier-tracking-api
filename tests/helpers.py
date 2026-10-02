"""Offline test helpers: load fixtures and build clients on httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from courier_tracking.http import HostRateLimiter, PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(courier: str, name: str) -> str:
    return (FIXTURES / courier / name).read_text(encoding="utf-8")


async def _no_sleep(_seconds: float) -> None:
    return None


def mock_client(handler: Callable[[httpx.Request], httpx.Response], *, max_retries: int = 3) -> PoliteClient:
    """A PoliteClient that never touches the network and never really sleeps."""
    return PoliteClient(
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        rate_limiter=HostRateLimiter(0.0, sleep=_no_sleep),
        sleep=_no_sleep,
    )

"""Offline mode: a TrackingService that answers from the saved fixtures, never the network.

Used by `python -m courier_tracking.mcp_server --offline` so an MCP client can be tried
without calling trackon.in. Needs a repo checkout (the fixtures live in tests/fixtures).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .http import HostRateLimiter, PoliteClient
from .service import TrackingService

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

DATA_SOURCE = "offline fixtures: synthetic shipments, not real data"

# Synthetic AWBs -> fixture. Any other well-formed AWB gets the real (captured) unknown-AWB page.
SYNTHETIC_AWBS = {
    "999000000001": "delivered.synthetic.html",
    "999000000002": "in_transit.synthetic.html",
    "999000000003": "rto.synthetic.html",
    "999000000004": "failed.synthetic.html",
    "999000000005": "rto_prepaid.synthetic.html",
}


def _fixture_trackon(request: httpx.Request) -> httpx.Response:
    if request.url.host != "trackon.in":
        return httpx.Response(404)
    name = SYNTHETIC_AWBS.get(request.url.params.get("awb", ""), "invalid.live.html")
    return httpx.Response(200, text=(FIXTURES / "trackon" / name).read_text(encoding="utf-8"))


async def _no_sleep(_: float) -> None:
    return None


def offline_service() -> TrackingService:
    if not (FIXTURES / "trackon").is_dir():
        raise RuntimeError(f"Offline mode needs the fixtures in {FIXTURES} (run from a repo checkout).")
    client = PoliteClient(
        transport=httpx.MockTransport(_fixture_trackon),  # in-process: no socket is ever opened
        rate_limiter=HostRateLimiter(0.0, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    return TrackingService(client)

"""Run every agreed case for every courier, offline, and print a pass/fail table.

    python scripts/run_all_cases.py

Cases: delivered, in transit, returned to origin, invalid ID, site down
(plus failed attempt and malformed ID). Courier sites are simulated with
httpx.MockTransport serving the saved fixtures; nothing goes over the network.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from courier_tracking.errors import TrackingError  # noqa: E402
from courier_tracking.http import HostRateLimiter, PoliteClient  # noqa: E402
from courier_tracking.service import TrackingService  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _read(courier: str, name: str) -> str:
    return (FIXTURES / courier / name).read_text(encoding="utf-8")


@dataclass
class Case:
    courier: str
    name: str
    tracking_id: str
    fixture: str | None  # None = site down
    expect: str  # a status value or an error code


CASES = [
    Case("trackon", "delivered", "999000000001", "delivered.synthetic.html", "delivered"),
    Case("trackon", "in transit", "999000000002", "in_transit.synthetic.html", "in_transit"),
    Case("trackon", "returned to origin (COD)", "999000000003", "rto.synthetic.html", "returned"),
    Case("trackon", "returned to origin (prepaid)", "999000000005", "rto_prepaid.synthetic.html", "returned"),
    Case("trackon", "failed attempt", "999000000004", "failed.synthetic.html", "failed"),
    Case("trackon", "invalid ID (unknown)", "100000000000", "invalid.live.html", "NOT_FOUND"),
    Case("trackon", "invalid ID (malformed)", "12AB", "invalid.live.html", "INVALID_TRACKING_ID"),
    Case("trackon", "site down", "999000000001", None, "COURIER_UNAVAILABLE"),
]


def _site(case: Case):
    def handler(request: httpx.Request) -> httpx.Response:
        if case.fixture is None:
            raise httpx.ConnectError("simulated outage", request=request)
        return httpx.Response(200, text=_read(case.courier, case.fixture))

    return handler


async def _no_sleep(_: float) -> None:
    return None


async def run_case(case: Case) -> tuple[bool, str]:
    client = PoliteClient(
        transport=httpx.MockTransport(_site(case)),
        rate_limiter=HostRateLimiter(0.0, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    service = TrackingService(client)
    try:
        result = await service.track(case.courier, case.tracking_id)
        got = result.status.value
        detail = f"{got}, {len(result.events)} events, payment={result.payment_mode}"
    except TrackingError as exc:
        got = exc.code.value
        detail = f"{got}: {exc.message}"
    finally:
        await service.aclose()
    return got == case.expect, detail


async def run_all() -> list[tuple[Case, bool, str]]:
    return [(case, *await run_case(case)) for case in CASES]


def main() -> int:
    # The "site down" cases log one warning per retry; the table already reports the outcome.
    logging.getLogger("courier_tracking.http").setLevel(logging.ERROR)
    rows = asyncio.run(run_all())
    width = max(len(c.name) for c, _, _ in rows)
    print(f"{'courier':<8}  {'case':<{width}}  {'expect':<20}  result")
    print("-" * (width + 60))
    for case, ok, detail in rows:
        print(f"{case.courier:<8}  {case.name:<{width}}  {case.expect:<20}  {'PASS' if ok else 'FAIL'}  {detail[:90]}")
    failed = sum(not ok for _, ok, _ in rows)
    print(f"\n{len(rows) - failed}/{len(rows)} cases passed (offline, fixtures only)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

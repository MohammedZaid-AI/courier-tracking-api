"""Two-minute offline demo of the API and the MCP tool.

    python scripts/demo.py            # runs straight through
    python scripts/demo.py --pause    # waits for Enter between sections (for screen recording)

Answers come from the saved fixtures (mostly synthetic, see tests/fixtures/README.md).
Nothing goes over the network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import textwrap
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from courier_tracking import mcp_server  # noqa: E402
from courier_tracking.api import create_app  # noqa: E402
from courier_tracking.http import HostRateLimiter, PoliteClient  # noqa: E402
from courier_tracking.refund_hint import refund_hint  # noqa: E402
from courier_tracking.schema import TrackingResult  # noqa: E402
from courier_tracking.service import TrackingService  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
WIDTH = 78

# tracking ID -> fixture the fake courier site serves
PAGES = {
    "999000000001": ("trackon", "delivered.synthetic.html"),
    "999000000005": ("trackon", "rto_prepaid.synthetic.html"),
    "999000000003": ("trackon", "rto.synthetic.html"),
    "999000000004": ("trackon", "failed.synthetic.html"),
    "100000000000": ("trackon", "invalid.live.html"),
}


def _fake_courier_sites(request: httpx.Request) -> httpx.Response:
    tid = request.url.params.get("awb", "")
    courier, name = PAGES[tid]
    return httpx.Response(200, text=(FIXTURES / courier / name).read_text(encoding="utf-8"))


async def _no_sleep(_: float) -> None:
    return None


def make_service() -> TrackingService:
    return TrackingService(
        PoliteClient(
            transport=httpx.MockTransport(_fake_courier_sites),
            rate_limiter=HostRateLimiter(0.0, sleep=_no_sleep),
            sleep=_no_sleep,
        )
    )


class Demo:
    def __init__(self, pause: bool):
        self.pause = pause
        self.step = 0

    def section(self, title: str, subtitle: str) -> None:
        if self.pause and self.step:
            input("\n[Enter] next ")
        self.step += 1
        print("\n" + "=" * WIDTH)
        print(f" {self.step}. {title}")
        print(f"    {subtitle}")
        print("=" * WIDTH)

    @staticmethod
    def request(line: str, status: int) -> None:
        print(f"\n  {line}   ->  HTTP {status}\n")

    @staticmethod
    def json(payload) -> None:
        for line in json.dumps(payload, indent=2, ensure_ascii=False).splitlines():
            print("  " + line)

    @staticmethod
    def hint(h: dict) -> None:
        print(f"\n  refund hint: {h['action']}")
        print(textwrap.fill(h["message"], WIDTH, initial_indent="    ", subsequent_indent="    "))


def compact(body: dict) -> dict:
    """Trim for the screen: newest 2 events, drop fields that are noise in a demo."""
    events = body["events"]
    short = [
        f"{e['timestamp'][:16].replace('T', ' ')}  {e['location'] or '-':<11} {e['description']}" for e in events[:2]
    ]
    if len(events) > 2:
        more = len(events) - 2
        short.append(f"... {more} older event{'s' if more > 1 else ''}")
    keep = ["courier", "tracking_id", "status", "raw_status", "payment_mode", "last_updated"]
    return {**{k: body[k] for k in keep}, "events (newest first)": short}


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline demo of the courier tracking API and MCP tool.")
    ap.add_argument("--pause", action="store_true", help="wait for Enter between sections")
    args = ap.parse_args()
    logging.disable(logging.WARNING)  # mocked requests would otherwise log real courier URLs

    demo = Demo(args.pause)
    print("Courier Tracking API (Trackon): one JSON shape, plus a COD/refund hint. Demonstration project.")
    print("Offline demo: answers come from saved fixtures, nothing goes over the network.")

    with TestClient(create_app(make_service())) as api:

        def track(courier: str, tid: str) -> dict:
            r = api.get(f"/track/{courier}/{tid}")
            demo.request(f"GET /track/{courier}/{tid}", r.status_code)
            return r.json()

        demo.section("Delivered parcel", "Trackon: server-rendered public tracking page; prepaid order")
        demo.json(compact(track("trackon", "999000000001")))

        demo.section("Returned parcel (RTO)", "COD order")
        body = track("trackon", "999000000003")
        demo.json(compact(body))
        demo.hint(refund_hint(TrackingResult(**body)).model_dump())

        demo.section("Failed delivery attempt", "COD order")
        body = track("trackon", "999000000004")
        demo.json(compact(body))
        demo.hint(refund_hint(TrackingResult(**body)).model_dump())

        demo.section("Typed error", "Unknown AWB: the real Trackon answer, captured live")
        demo.json(track("trackon", "100000000000"))

    demo.section("MCP tool", "An agent asks: \"Parcel 999000000005 came back. Should I refund?\"")

    async def ask() -> dict:
        mcp_server._service = make_service()
        try:
            res = await mcp_server.server.call_tool(
                "get_delivery_status", {"courier": "trackon", "tracking_id": "999000000005"}
            )
        finally:
            await mcp_server._service.aclose()
            mcp_server._service = None
        return getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)

    print('\n  get_delivery_status(courier="trackon", tracking_id="999000000005")\n')
    out = asyncio.run(ask())
    demo.json({k: out[k] for k in ("status", "raw_status", "payment_mode", "last_updated")})
    demo.hint(out["refund_hint"])
    print(f"\n  is_suggestion: {str(out['refund_hint']['is_suggestion']).lower()}")
    print(textwrap.fill(out["refund_hint"]["disclaimer"], WIDTH, initial_indent="    ", subsequent_indent="    "))
    print("\n" + "=" * WIDTH)
    print(" Done. Read-only: the tool suggests, it never refunds or cancels anything.")
    print("=" * WIDTH)


if __name__ == "__main__":
    main()

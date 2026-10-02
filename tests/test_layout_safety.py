"""When a real page does not match what the parser expects, the API must answer
502 LAYOUT_CHANGED (or an honest 'unknown'), never a confident wrong status."""

import re

import httpx
import pytest
from fastapi.testclient import TestClient

from courier_tracking.api import create_app
from courier_tracking.service import TrackingService
from tests.helpers import fixture, mock_client


def api_for(*, trackon: str) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=trackon)

    return TestClient(create_app(TrackingService(mock_client(handler, max_retries=0))))


def get(client: TestClient, path: str) -> httpx.Response:
    with client:
        return client.get(path)


DELIVERED = fixture("trackon", "delivered.synthetic.html")


def history(rows, *, page=DELIVERED, current: str | None = None) -> str:
    """Replace the history rows (and the 'Current Status' row) of the delivered fixture."""
    page = re.sub(
        r"<tr><th>Current Status</th><td>[^<]*</td></tr>",
        f"<tr><th>Current Status</th><td>{current}</td></tr>" if current else "",
        page,
    )
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return re.sub(
        r'(<table class="table table-bordered track-history">.*?<tbody>).*?(</tbody>)',
        lambda m: m.group(1) + body + m.group(2),
        page,
        flags=re.S,
    )


TRACKON_MISMATCHES = {
    "result block renamed (page still shows the AWB)": DELIVERED.replace('id="divtrackStatus"', 'id="resultV2"'),
    "newest row has merged cells": history(
        [("26/09/2026 14:05", "PUNE", "DELIVERED"), ("26/09/2026", "09:30", "PUNE", "OUT FOR DELIVERY")]
    ),
    "dates in a format we cannot read": history(
        [("Sep 26th", "2:05pm", "PUNE", "DELIVERED"), ("Sep 26th", "9:30am", "PUNE", "OUT FOR DELIVERY")]
    ),
    "dates misread (out of order)": history(
        [
            ("01/10/2026", "09:00", "PUNE", "DELIVERED"),
            ("03/10/2026", "09:00", "PUNE", "OUT FOR DELIVERY"),
            ("02/10/2026", "09:00", "PUNE", "IN TRANSIT"),
        ]
    ),
    "dates misread (in the future)": history(
        [("31/12/2026", "14:05", "PUNE", "DELIVERED"), ("12/09/2026", "09:30", "PUNE", "OUT FOR DELIVERY")]
    ),
    "summary contradicts newest event": history(
        [("27/09/2026", "16:40", "DELHI", "RTO DELIVERED"), ("19/09/2026", "09:20", "JAIPUR", "OUT FOR DELIVERY")],
        current="DELIVERED",
    ),
    "status column now holds something else": history(
        [("26/09/2026", "14:05", "PUNE", "MH-12-AB-1234"), ("26/09/2026", "09:30", "PUNE", "MH-12-CD-5678")]
    ),
    "one column labelled both date and status": DELIVERED.replace(
        "<th>Date</th><th>Time</th><th>Location</th><th>Status</th>",
        "<th>Status Date</th><th>Time</th><th>Location</th><th>Remarks</th>",
    ),
}


@pytest.mark.parametrize("page", TRACKON_MISMATCHES.values(), ids=TRACKON_MISMATCHES.keys())
def test_trackon_mismatch_is_layout_changed(page):
    resp = get(api_for(trackon=page), "/track/trackon/999000000001")
    assert resp.status_code == 502, resp.json()
    assert resp.json()["error"] == "LAYOUT_CHANGED"


def test_trackon_unrecognised_newest_status_is_unknown_not_an_older_guess():
    page = history([("26/09/2026", "14:05", "PUNE", "HANDED OVER TO CONSIGNEE"), ("26/09/2026", "09:30", "PUNE", "OUT FOR DELIVERY")])
    body = get(api_for(trackon=page), "/track/trackon/999000000001").json()
    assert body["status"] == "unknown"  # not in_transit from the older event
    assert body["raw_status"] == "HANDED OVER TO CONSIGNEE"


def test_trackon_other_status_labels_do_not_override_events():
    page = DELIVERED.replace(
        "<tr><th>Current Status</th><td>DELIVERED</td></tr>",
        "<tr><th>Booking Status</th><td>BOOKED</td></tr><tr><th>Payment Status</th><td>RETURNED</td></tr>",
    )
    body = get(api_for(trackon=page), "/track/trackon/999000000001").json()
    assert body["status"] == "delivered"


def test_trackon_unknown_awb_is_still_not_found():
    resp = get(api_for(trackon=fixture("trackon", "invalid.live.html")), "/track/trackon/100000000000")
    assert resp.status_code == 404


def test_mcp_tool_gives_no_refund_hint_on_layout_change():
    import asyncio

    from courier_tracking import mcp_server

    async def run():
        def handler(request):
            return httpx.Response(200, text=TRACKON_MISMATCHES["summary contradicts newest event"])

        service = TrackingService(mock_client(handler, max_retries=0))
        try:
            return await mcp_server.delivery_status(service, "trackon", "999000000001")
        finally:
            await service.aclose()

    out = asyncio.run(run())
    assert out["ok"] is False and out["error"] == "LAYOUT_CHANGED"
    assert out["refund_hint"]["action"] == "check_manually"

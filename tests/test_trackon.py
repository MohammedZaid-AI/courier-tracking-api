import re

import httpx
import pytest

from courier_tracking.adapters.base import RawResponse
from courier_tracking.adapters.trackon import TRACK_URL, TrackonAdapter
from courier_tracking.dates import IST
from courier_tracking.errors import (
    CourierUnavailableError,
    InvalidTrackingIdError,
    LayoutDriftError,
    NotFoundError,
)
from courier_tracking.schema import Status
from tests.helpers import fixture, mock_client


def trackon_site(page: str, *, status: int = 200, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.method == "GET" and request.url.path == "/courier-tracking":
            return httpx.Response(status, text=page, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404)

    return handler


async def track(name: str, awb: str):
    adapter = TrackonAdapter(mock_client(trackon_site(fixture("trackon", name))))
    async with adapter.client:
        return await adapter.track(awb)


async def test_delivered_prepaid():
    r = await track("delivered.synthetic.html", "999000000001")
    assert r.status is Status.DELIVERED
    assert r.raw_status == "DELIVERED"
    assert r.payment_mode == "prepaid"
    assert len(r.events) == 5
    assert r.events[0].description == "DELIVERED"
    assert r.events[0].location == "PUNE"
    assert r.last_updated == r.events[0].timestamp
    assert r.last_updated.isoformat() == "2026-09-26T14:05:00+05:30"


async def test_in_transit_cod():
    r = await track("in_transit.synthetic.html", "999000000002")
    assert r.status is Status.IN_TRANSIT
    assert r.payment_mode == "cod"


async def test_returned_to_origin_cod():
    r = await track("rto.synthetic.html", "999000000003")
    assert r.status is Status.RETURNED
    assert r.raw_status == "RTO DELIVERED"  # must not be read as a normal delivery
    assert r.payment_mode == "cod"


async def test_failed_attempt():
    r = await track("failed.synthetic.html", "999000000004")
    assert r.status is Status.FAILED


async def test_invalid_id_live_page_is_not_found():
    with pytest.raises(NotFoundError, match="75 days"):
        await track("invalid.live.html", "100000000000")


async def test_uses_advertised_get_url_with_awb_param():
    calls = []
    adapter = TrackonAdapter(mock_client(trackon_site(fixture("trackon", "delivered.synthetic.html"), calls=calls)))
    async with adapter.client:
        await adapter.track("999000000001")
    assert len(calls) == 1
    assert str(calls[0].url) == f"{TRACK_URL}?awb=999000000001"


@pytest.mark.parametrize("bad", ["12345", "1234567890123", "AB1234567", "99900000000'"])
async def test_malformed_ids_never_hit_network(bad):
    calls = []
    adapter = TrackonAdapter(mock_client(trackon_site("", calls=calls)))
    async with adapter.client:
        with pytest.raises(InvalidTrackingIdError):
            await adapter.track(bad)
    assert calls == []


async def test_site_down_raises_courier_unavailable():
    adapter = TrackonAdapter(mock_client(trackon_site("", status=503), max_retries=1))
    async with adapter.client:
        with pytest.raises(CourierUnavailableError):
            await adapter.track("999000000001")


async def test_timeout_raises_courier_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("no answer", request=request)

    adapter = TrackonAdapter(mock_client(handler, max_retries=1))
    async with adapter.client:
        with pytest.raises(CourierUnavailableError, match="timed out"):
            await adapter.track("999000000001")


def test_redesigned_page_is_layout_drift_not_not_found():
    adapter = TrackonAdapter(client=None)
    raw = RawResponse(url=TRACK_URL, status_code=200, text="<html><body><h1>New Trackon site</h1></body></html>")
    with pytest.raises(LayoutDriftError, match="awbSingleTrackingId"):
        adapter.parse(raw, "999000000001")


def test_result_block_without_history_table_is_layout_drift():
    page = fixture("trackon", "delivered.synthetic.html")
    page = re.sub(r"<thead>.*?</thead>", "<thead><tr><th>When</th><th>What</th></tr></thead>", page, flags=re.S)
    adapter = TrackonAdapter(client=None)
    with pytest.raises(LayoutDriftError, match="Date and Status"):
        adapter.parse(RawResponse(url=TRACK_URL, status_code=200, text=page), "999000000001")


def test_columns_found_by_header_text_not_position():
    page = fixture("trackon", "delivered.synthetic.html")
    page = page.replace(
        "<th>Date</th><th>Time</th><th>Location</th><th>Status</th>",
        "<th>Activity</th><th>Branch</th><th>Date</th><th>Time</th>",
    )
    page = re.sub(
        r"<tr><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td></tr>",
        r"<tr><td>\4</td><td>\3</td><td>\1</td><td>\2</td></tr>",
        page,
    )
    r = TrackonAdapter(client=None).parse(RawResponse(url=TRACK_URL, status_code=200, text=page), "999000000001")
    assert r.events[0].description == "DELIVERED"
    assert r.events[0].location == "PUNE"
    assert r.events[0].timestamp.tzinfo == IST


def test_all_fixtures_pass_drift_check_and_are_redacted():
    adapter = TrackonAdapter(client=None)
    for name in ["invalid.live", "delivered.synthetic", "in_transit.synthetic", "rto.synthetic", "failed.synthetic"]:
        page = fixture("trackon", f"{name}.html")
        assert adapter.drift_problems(RawResponse(url=TRACK_URL, status_code=200, text=page)) == [], name
        tokens = re.findall(r'name="__RequestVerificationToken" type="hidden" value="([^"]*)"', page)
        assert tokens == ["REDACTED-FORM-TOKEN"], name

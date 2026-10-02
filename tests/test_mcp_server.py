import httpx
import pytest

from courier_tracking import mcp_server
from courier_tracking.service import TrackingService
from tests.helpers import fixture, mock_client


def service_for(trackon_page: str | None = None, *, down: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if down:
            return httpx.Response(503)
        return httpx.Response(200, text=fixture("trackon", trackon_page))

    return TrackingService(mock_client(handler, max_retries=0))


async def status(service, courier, tid):
    try:
        return await mcp_server.delivery_status(service, courier, tid)
    finally:
        await service.aclose()


async def test_returned_cod_gets_no_refund_due_hint():
    out = await status(service_for("rto.synthetic.html"), "trackon", "999000000003")
    assert out["ok"] is True
    assert out["status"] == "returned"
    assert out["payment_mode"] == "cod"
    assert out["refund_hint"]["action"] == "no_refund_due"
    assert out["refund_hint"]["is_suggestion"] is True


async def test_failed_says_wait():
    out = await status(service_for("failed.synthetic.html"), "trackon", "999000000004")
    assert out["status"] == "failed"
    assert out["refund_hint"]["message"] == "Delivery attempt failed. Wait for the next delivery attempt, do not cancel yet."


async def test_returned_prepaid_suggests_refund():
    out = await status(service_for("rto_prepaid.synthetic.html"), "trackon", "999000000005")
    assert out["payment_mode"] == "prepaid"
    assert out["refund_hint"]["action"] == "consider_refund"


async def test_delivered_has_no_refund_action_and_latest_event():
    out = await status(service_for("delivered.synthetic.html"), "trackon", "999000000001")
    assert out["refund_hint"]["action"] == "none"
    assert out["latest_event"]["description"] == "DELIVERED"


@pytest.mark.parametrize(
    "kwargs, courier, tid, code",
    [
        ({"trackon_page": "invalid.live.html"}, "trackon", "100000000000", "NOT_FOUND"),
        ({"trackon_page": "invalid.live.html"}, "trackon", "abc", "INVALID_TRACKING_ID"),
        ({"down": True}, "trackon", "999000000001", "COURIER_UNAVAILABLE"),
        ({}, "bluedart", "12345678901", "UNSUPPORTED_COURIER"),
    ],
)
async def test_errors_are_returned_not_raised_and_say_take_no_action(kwargs, courier, tid, code):
    out = await status(service_for(**kwargs), courier, tid)
    assert out["ok"] is False
    assert out["error"] == code
    assert out["refund_hint"]["action"] == "check_manually"


async def test_tool_is_registered_read_only_with_only_trackon():
    tools = await mcp_server.server.list_tools()
    tool = next(t for t in tools if t.name == "get_delivery_status")
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    schema = tool.input_schema if hasattr(tool, "input_schema") else tool.inputSchema
    courier = schema["properties"]["courier"]
    assert courier.get("enum", [courier.get("const")]) == ["trackon"]
    assert set(schema["required"]) == {"courier", "tracking_id"}
    assert "never refunds or cancels" in tool.description


async def test_tool_call_end_to_end_through_mcp_server(monkeypatch):
    service = service_for("rto.synthetic.html")
    monkeypatch.setattr(mcp_server, "_service", service)
    try:
        res = await mcp_server.server.call_tool("get_delivery_status", {"courier": "trackon", "tracking_id": "999000000003"})
    finally:
        await service.aclose()
    payload = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    assert payload["status"] == "returned"
    assert payload["refund_hint"]["action"] == "no_refund_due"

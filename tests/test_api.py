import httpx
import pytest
from fastapi.testclient import TestClient

from courier_tracking.api import create_app
from courier_tracking.service import TrackingService
from tests.helpers import fixture, mock_client


def fake_couriers(trackon_page: str = "delivered.synthetic.html", *, down: bool = False, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if down:
            return httpx.Response(503)
        if request.url.host == "trackon.in":
            return httpx.Response(200, text=fixture("trackon", trackon_page))
        return httpx.Response(404)

    return handler


@pytest.fixture
def make_client():
    clients = []

    def _make(handler, **kw):
        service = TrackingService(mock_client(handler, max_retries=1), **kw)
        c = TestClient(create_app(service))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_health_does_not_call_couriers(make_client):
    calls = []
    client = make_client(fake_couriers(calls=calls))
    assert client.get("/health").json()["status"] == "ok"
    assert calls == []


def test_couriers_lists_only_trackon(make_client):
    client = make_client(fake_couriers())
    assert [c["courier"] for c in client.get("/couriers").json()] == ["trackon"]


def test_track_trackon_delivered(make_client):
    client = make_client(fake_couriers())
    resp = client.get("/track/trackon/999000000001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "delivered"
    assert body["courier"] == "trackon"
    assert body["events"][0]["description"] == "DELIVERED"
    assert body["last_updated"] == "2026-09-26T14:05:00+05:30"


def test_courier_name_is_case_insensitive(make_client):
    client = make_client(fake_couriers())
    resp = client.get("/track/Trackon/999000000001")
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"


def test_not_found_is_404(make_client):
    client = make_client(fake_couriers("invalid.live.html"))
    resp = client.get("/track/trackon/100000000000")
    assert resp.status_code == 404
    assert resp.json()["error"] == "NOT_FOUND"


def test_invalid_id_is_422_without_network(make_client):
    calls = []
    client = make_client(fake_couriers(calls=calls))
    resp = client.get("/track/trackon/abc")
    assert resp.status_code == 422
    assert resp.json()["error"] == "INVALID_TRACKING_ID"
    assert calls == []


@pytest.mark.parametrize("courier", ["bluedart", "dtdc", "indiapost"])
def test_unsupported_courier_is_a_clear_typed_404_without_network(make_client, courier):
    calls = []
    client = make_client(fake_couriers(calls=calls))
    resp = client.get(f"/track/{courier}/12345678901")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"] == "UNSUPPORTED_COURIER"
    assert body["message"] == f"Unsupported courier '{courier}'. Supported: trackon"
    assert calls == []


def test_site_down_is_503(make_client):
    client = make_client(fake_couriers(down=True))
    resp = client.get("/track/trackon/999000000001")
    assert resp.status_code == 503
    assert resp.json()["error"] == "COURIER_UNAVAILABLE"


def test_layout_change_is_502(make_client):
    client = make_client(lambda req: httpx.Response(200, text="<html>redesigned</html>"))
    resp = client.get("/track/trackon/999000000001")
    assert resp.status_code == 502
    assert resp.json()["error"] == "LAYOUT_CHANGED"


def test_results_are_cached(make_client):
    calls = []
    client = make_client(fake_couriers(calls=calls))
    client.get("/track/trackon/999000000001")
    client.get("/track/trackon/999000000001")
    assert len(calls) == 1


def test_cache_expires(make_client):
    calls = []
    now = [0.0]
    client = make_client(fake_couriers(calls=calls), cache_ttl=300, clock=lambda: now[0])
    client.get("/track/trackon/999000000001")
    now[0] = 301
    client.get("/track/trackon/999000000001")
    assert len(calls) == 2


def test_batch_mixed_items_each_get_their_own_answer(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        name = "delivered.synthetic.html" if request.url.params.get("awb") == "999000000001" else "invalid.live.html"
        return httpx.Response(200, text=fixture("trackon", name))

    client = make_client(handler)
    items = [
        {"courier": "trackon", "tracking_id": "999000000001"},
        {"courier": "trackon", "tracking_id": "100000000000"},
        {"courier": "trackon", "tracking_id": "12AB"},
        {"courier": "bluedart", "tracking_id": "12345678901"},
        {"courier": "trackon", "tracking_id": "999000000001"},  # repeated: looked up once
    ]
    resp = client.post("/track/batch", json={"items": items})
    assert resp.status_code == 200
    body = resp.json()
    got = [r["result"]["status"] if r["ok"] else r["error"]["error"] for r in body["results"]]
    assert got == ["delivered", "NOT_FOUND", "INVALID_TRACKING_ID", "UNSUPPORTED_COURIER", "delivered"]
    assert [r["tracking_id"] for r in body["results"]] == [i["tracking_id"] for i in items]
    assert (body["ok"], body["failed"]) == (2, 3)
    assert len(calls) == 2


@pytest.mark.parametrize("count", [0, 21])
def test_batch_size_is_limited(make_client, count):
    client = make_client(fake_couriers())
    items = [{"courier": "trackon", "tracking_id": "999000000001"}] * count
    assert client.post("/track/batch", json={"items": items}).status_code == 422

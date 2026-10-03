import httpx
import pytest

from courier_tracking.errors import CourierUnavailableError
from courier_tracking.http import DEFAULT_CONTACT, USER_AGENT, HostRateLimiter, PoliteClient, build_user_agent


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(handler, *, max_retries=3):
    clock = FakeClock()
    client = PoliteClient(
        transport=httpx.MockTransport(handler),
        max_retries=max_retries,
        rate_limiter=HostRateLimiter(1.0, clock=clock, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    return client, clock


async def test_sends_honest_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, text="ok")

    client, _ = make_client(handler)
    async with client:
        await client.request("GET", "https://courier.example/x", courier="test")
    assert seen["ua"] == USER_AGENT
    assert "courier-tracking-api" in USER_AGENT and "Mozilla" not in USER_AGENT


def test_user_agent_has_contact_without_any_env_var(monkeypatch):
    monkeypatch.delenv("COURIER_TRACKING_CONTACT", raising=False)
    assert f"(+{DEFAULT_CONTACT};" in build_user_agent()


def test_contact_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("COURIER_TRACKING_CONTACT", "https://github.com/someone/fork")
    assert "(+https://github.com/someone/fork;" in build_user_agent()


def test_blank_contact_env_var_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("COURIER_TRACKING_CONTACT", "   ")
    assert f"(+{DEFAULT_CONTACT};" in build_user_agent()


async def test_retries_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    client, _ = make_client(handler)
    async with client:
        resp = await client.request("GET", "https://courier.example/x", courier="test")
    assert resp.status_code == 200
    assert len(calls) == 3


async def test_gives_up_after_max_retries_with_courier_unavailable():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502)

    client, _ = make_client(handler, max_retries=3)
    async with client:
        with pytest.raises(CourierUnavailableError, match="HTTP 502 after 4 attempts"):
            await client.request("GET", "https://courier.example/x", courier="test")
    assert len(calls) == 4


async def test_timeout_is_retried_then_reported():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = make_client(handler, max_retries=2)
    async with client:
        with pytest.raises(CourierUnavailableError, match="timed out"):
            await client.request("GET", "https://courier.example/x", courier="test")


async def test_connection_refused_is_reported_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(handler, max_retries=1)
    async with client:
        with pytest.raises(CourierUnavailableError, match="network error"):
            await client.request("GET", "https://courier.example/x", courier="test")


async def test_4xx_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404)

    client, _ = make_client(handler)
    async with client:
        resp = await client.request("GET", "https://courier.example/x", courier="test")
    assert resp.status_code == 404
    assert len(calls) == 1


async def test_retry_after_header_is_honoured_and_capped():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        if len(calls) == 2:
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(200)

    client, clock = make_client(handler)
    async with client:
        await client.request("GET", "https://courier.example/x", courier="test")
    assert 3.0 in clock.sleeps
    assert 10.0 in clock.sleeps  # 999 capped to max_retry_after
    assert 999.0 not in clock.sleeps


async def test_rate_limiter_spaces_requests_per_host():
    clock = FakeClock()
    limiter = HostRateLimiter(1.0, clock=clock, sleep=clock.sleep)
    await limiter.wait("a.example")
    await limiter.wait("a.example")
    await limiter.wait("a.example")
    assert clock.sleeps == [1.0, 1.0]
    await limiter.wait("b.example")  # different host, no wait
    assert clock.sleeps == [1.0, 1.0]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post"])
async def test_client_is_read_only(method):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200)

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(ValueError, match="read-only"):
            await client.request(method, "https://courier.example/x", courier="test")
    assert calls == []

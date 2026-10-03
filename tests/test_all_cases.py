"""scripts/run_all_cases.py: offline cases must pass in CI; --live is exercised here against a
mocked Trackon (the offline guard in conftest blocks any real network call)."""

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from tests.helpers import fixture, mock_client

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_all_cases.py"
_spec = importlib.util.spec_from_file_location("run_all_cases", _SCRIPT)
run_all_cases = importlib.util.module_from_spec(_spec)
sys.modules["run_all_cases"] = run_all_cases  # @dataclass looks its module up here
_spec.loader.exec_module(run_all_cases)

REQUIRED_OFFLINE = {
    "delivered",
    "in transit",
    "returned to origin (COD)",
    "failed delivery attempt",
    "unknown ID",
    "bad ID format",
    "unsupported courier",
    "batch: mixed good and bad items",
    "site down",
}
REAL_AWB = "123456789012"


@pytest.fixture(autouse=True)
def _no_ci_unless_a_test_sets_it(monkeypatch):
    """GitHub Actions sets CI=true, and --live refuses to run under CI. Start every test here
    from a known environment; tests that check the CI guard set CI themselves."""
    monkeypatch.delenv("CI", raising=False)


def test_offline_cases_all_pass_and_cover_the_required_cases():
    rows = run_all_cases.run_offline()
    assert REQUIRED_OFFLINE <= {r.case for r in rows}
    for r in rows:
        assert r.ok, f"{r.case}: got {r.got}, expected {r.expect} ({r.detail})"
        assert r.source.startswith("offline"), r.case


def test_offline_rows_are_labelled_honestly():
    sources = {r.case: r.source for r in run_all_cases.run_offline()}
    assert sources["delivered"] == "offline (synthetic)"
    assert sources["unknown ID"] == "offline (real capture)"  # the saved real page, not synthetic
    assert sources["site down"] == "offline (simulated outage)"


def fake_trackon(real_page: str | None = None, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if real_page and request.url.params.get("awb") == REAL_AWB:
            return httpx.Response(200, text=real_page)
        return httpx.Response(200, text=fixture("trackon", "invalid.live.html"))

    return handler


def page_with_personal_data() -> str:
    page = fixture("trackon", "delivered.synthetic.html").replace("999000000001", REAL_AWB)
    return page.replace(
        "<td>PUNE</td><td>DELIVERED</td>",
        "<td>PUNE</td><td>DELIVERED TO RAMESH KUMAR 9876543210</td>",
        1,
    )


def test_live_cases_pass_against_a_trackon_that_behaves_like_the_real_one():
    calls = []
    rows, real = run_all_cases.run_live([], client=mock_client(fake_trackon(calls=calls)))
    assert {r.case for r in rows} == {"unknown ID", "bad ID format", "unsupported courier", "batch: mixed good and bad items"}
    for r in rows:
        assert r.ok, f"{r.case}: {r.got} ({r.detail})"
        assert r.source in {"live", "live (no request needed)"}
    assert len(calls) == 2  # unknown ID + the batch's one valid item; bad items never reach the site
    assert all("courier-tracking-api" in c.headers["User-Agent"] for c in calls)
    assert real == []


def test_live_real_id_is_printed_with_personal_data_redacted(capsys):
    client = mock_client(fake_trackon(page_with_personal_data()))
    code = run_all_cases.main(["--live", "--id", f"trackon={REAL_AWB}"], live_client=client)
    out = capsys.readouterr().out
    assert code == 0
    assert f"PASS    live                        real ID {REAL_AWB}" in out
    assert "RAMESH" not in out and "9876543210" not in out
    assert "DELIVERED TO [name redacted] [phone redacted]" in out
    assert "nothing saved" in out


def test_live_real_id_that_does_not_match_the_parser_fails_clearly(capsys):
    page = page_with_personal_data().replace('id="divtrackStatus"', 'id="newResult"')
    code = run_all_cases.main(["--live", "--id", f"trackon={REAL_AWB}"], live_client=mock_client(fake_trackon(page)))
    out = " ".join(capsys.readouterr().out.split())  # failures are wrapped, so compare without line breaks
    assert code == 1
    assert "FAIL" in out and "LAYOUT_CHANGED" in out and "refused to guess" in out
    assert "RAMESH" not in out


def test_live_unknown_id_that_turns_out_to_exist_shows_no_details(capsys):
    def handler(request):
        return httpx.Response(200, text=page_with_personal_data().replace(REAL_AWB, "100000000000"))

    rows, real = run_all_cases.run_live([], client=mock_client(handler))
    unknown = next(r for r in rows if r.case == "unknown ID")
    assert not unknown.ok
    assert "details not shown" in unknown.detail
    assert real == []


@pytest.mark.parametrize("ci_value", ["1", "true"])
@pytest.mark.parametrize("argv", [["--live"], ["--live", "--id", f"trackon={REAL_AWB}"]])
def test_live_is_refused_in_ci_and_makes_no_network_call(monkeypatch, capsys, ci_value, argv):
    monkeypatch.setenv("CI", ci_value)
    calls = []
    code = run_all_cases.main(argv, live_client=mock_client(fake_trackon(page_with_personal_data(), calls=calls)))
    captured = capsys.readouterr()
    assert code == 2
    assert "Refusing --live" in captured.err
    assert calls == []  # the guard runs before any request, live or offline
    assert "PASS" not in captured.out  # and before any case runs


@pytest.mark.parametrize("argv", [["--id", "trackon=123456789012"], ["--live", "--id", "bluedart=1"]])
def test_bad_arguments_are_rejected(argv):
    with pytest.raises(SystemExit):
        run_all_cases.main(argv)

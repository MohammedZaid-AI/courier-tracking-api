"""Drift checker tests. 'Live' mode is exercised against httpx.MockTransport, never the real sites."""

import re

import httpx

from courier_tracking import drift
from tests.helpers import fixture, mock_client


def fake_sites(*, trackon_page=None, down=False):
    trackon_page = trackon_page or fixture("trackon", "invalid.live.html")

    def handler(request: httpx.Request) -> httpx.Response:
        if down:
            return httpx.Response(503)
        return httpx.Response(200, text=trackon_page)

    return handler


async def run(argv, handler):
    return await drift.main_async(argv, client=mock_client(handler, max_retries=0))


async def test_offline_mode_checks_fixtures_and_passes(capsys):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    assert await run([], handler) == 0
    assert calls == []  # offline mode never sends a request
    assert "offline" in capsys.readouterr().out


async def test_unchanged_sites_report_no_drift(capsys):
    assert await run(["--live"], fake_sites()) == 0
    out = capsys.readouterr().out
    assert "DRIFT" not in out and "WARN" not in out


async def test_removed_form_field_is_drift(capsys):
    page = fixture("trackon", "invalid.live.html").replace('name="awbSingleTrackingId"', 'name="awb"')
    assert await run(["--live"], fake_sites(trackon_page=page)) == 1
    out = capsys.readouterr().out
    assert "[DRIFT      ] trackon" in out
    assert "awbSingleTrackingId" in out


async def test_cosmetic_change_is_warn_not_drift(capsys):
    page = fixture("trackon", "invalid.live.html").replace("<body", '<div id="newPromoBanner"></div><body', 1)
    assert await run(["--live"], fake_sites(trackon_page=page)) == 0
    out = capsys.readouterr().out
    assert "[WARN       ] trackon" in out
    assert "+ #newPromoBanner" in out


async def test_strict_turns_warn_into_failure():
    page = fixture("trackon", "invalid.live.html").replace("<body", '<div id="newPromoBanner"></div><body', 1)
    assert await run(["--live", "--strict"], fake_sites(trackon_page=page)) == 1


async def test_site_down_is_unreachable(capsys):
    assert await run(["--live"], fake_sites(down=True)) == 2
    assert "UNREACHABLE" in capsys.readouterr().out


async def test_real_id_is_parsed_and_reported(capsys):
    page = fixture("trackon", "rto.synthetic.html")
    assert await run(["--live", "--id", "trackon=999000000003"], fake_sites(trackon_page=page)) == 0
    assert "parsed: status=returned" in capsys.readouterr().out


async def test_real_trackon_id_with_unexpected_result_layout_is_drift(capsys):
    # A real AWB whose result lives in a block the parser does not know: must not pass as "not found".
    page = fixture("trackon", "rto.synthetic.html").replace('id="divtrackStatus"', 'id="trackResultNew"')
    assert await run(["--live", "--id", "trackon=999000000003"], fake_sites(trackon_page=page)) == 1
    out = capsys.readouterr().out
    assert "[DRIFT      ] trackon  real ID 999000000003" in out
    assert "API returns LAYOUT_CHANGED" in out


async def test_real_id_unknown_to_trackon_warns_not_found(capsys):
    page = fixture("trackon", "invalid.live.html")
    assert await run(["--live", "--id", "trackon=999000000009"], fake_sites(trackon_page=page)) == 0
    out = capsys.readouterr().out
    assert "[WARN       ] trackon  real ID 999000000009" in out
    assert "came back NOT_FOUND" in out


def _history(page: str, rows: list[tuple[str, str, str, str]]) -> str:
    page = re.sub(r"<tr><th>Current Status</th><td>[^<]*</td></tr>", "", page)
    body = "".join(f"<tr><td>{d}</td><td>{t}</td><td>{loc}</td><td>{st}</td></tr>" for d, t, loc, st in rows)
    return re.sub(
        r"(<table class=\"table table-bordered track-history\">.*?<tbody>).*?(</tbody>)",
        lambda m: m.group(1) + body + m.group(2),
        page,
        flags=re.S,
    )


async def test_real_id_with_no_recognisable_status_is_drift(capsys):
    page = _history(fixture("trackon", "delivered.synthetic.html"), [("26/09/2026", "14:05", "PUNE", "PARCEL HANDED OVER")])
    assert await run(["--live", "--id", "trackon=999000000001"], fake_sites(trackon_page=page)) == 1
    assert "recognisable status" in capsys.readouterr().out


async def test_real_id_with_unrecognised_newest_status_warns(capsys):
    page = _history(
        fixture("trackon", "delivered.synthetic.html"),
        [("26/09/2026", "14:05", "PUNE", "PARCEL HANDED OVER"), ("26/09/2026", "09:30", "PUNE", "OUT FOR DELIVERY")],
    )
    assert await run(["--live", "--id", "trackon=999000000001"], fake_sites(trackon_page=page)) == 0
    out = capsys.readouterr().out
    assert "parsed: status=unknown" in out
    assert "newest status not recognised" in out


async def test_save_writes_redacted_files(tmp_path, monkeypatch):
    monkeypatch.setattr(drift, "SAVE_DIR", tmp_path)
    page = fixture("trackon", "invalid.live.html").replace("REDACTED-FORM-TOKEN", "real-secret-form-token")
    await run(["--live", "--save"], fake_sites(trackon_page=page))
    saved = list(tmp_path.rglob("*.html"))
    assert saved
    text = "\n".join(p.read_text(encoding="utf-8") for p in saved)
    assert "real-secret-form-token" not in text
    assert "REDACTED-FORM-TOKEN" in text


def test_redaction_covers_tokens_ips_and_telemetry_keys():
    page = (
        '<meta name="csrf-token" content="abc123"> <span data-public-ip="203.0.113.7"></span> '
        'NREUM={accountID:"1234567",licenseKey:"NRJS-abc123def4567"} '
        'dsn:"https://0123456789abcdef0123456789abcdef@sentry.example.com/31"'
    )
    out = drift.redact(page)
    for secret in ["abc123", "203.0.113.7", "1234567", "NRJS-", "0123456789abcdef0123456789abcdef"]:
        assert secret not in out, secret


def test_json_fingerprint_ignores_tracking_id_keys():
    a = drift.json_fingerprint('{"123456789012": {"events": [{"date": 1, "status": "x"}]}}')
    b = drift.json_fingerprint('{"999999999999": {"events": [{"date": 2, "status": "y"}]}}')
    assert a == b
    assert "<id>.events[].status" in a

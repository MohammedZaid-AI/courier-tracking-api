"""Run the test cases through the real API and print a pass/fail table.

    python scripts/run_all_cases.py                          # offline: saved fixtures (default; CI uses this)
    python scripts/run_all_cases.py --live                   # also check the real Trackon site (by hand only)
    python scripts/run_all_cases.py --live --id trackon=<AWB>    # ...and one real tracking ID

Every row says where its answer came from:
  offline (synthetic)          hand-built fixture
  offline (real capture)       saved, redacted copy of the real Trackon page
  offline (simulated outage)   network failure simulated in-process
  offline (no request)         rejected before any request
  live                         trackon.in was called just now
  live (no request needed)     run in live mode, but rejected before any request

--live is polite: at most one request per second, an honest User-Agent, about two requests
in total (plus one per --id), and nothing is written to disk. Real results are printed with
names, phone numbers and emails redacted. --live refuses to run when CI is set.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from courier_tracking.api import create_app  # noqa: E402
from courier_tracking.http import USER_AGENT, HostRateLimiter, PoliteClient  # noqa: E402
from courier_tracking.redact import redact_personal  # noqa: E402
from courier_tracking.service import TrackingService  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

SYNTHETIC = "offline (synthetic)"
CAPTURE = "offline (real capture)"
OUTAGE = "offline (simulated outage)"
NO_REQUEST = "offline (no request)"
LIVE = "live"
LIVE_NO_REQUEST = "live (no request needed)"

# AWB -> fixture the offline fake Trackon serves; anything else gets the real unknown-AWB page.
OFFLINE_PAGES = {
    "999000000001": "delivered.synthetic.html",
    "999000000002": "in_transit.synthetic.html",
    "999000000003": "rto.synthetic.html",
    "999000000004": "failed.synthetic.html",
    "999000000005": "rto_prepaid.synthetic.html",
}
UNKNOWN_AWB = "100000000000"
BAD_FORMAT = "12AB"
UNSUPPORTED = ("bluedart", "12345678901")


@dataclass
class Row:
    case: str
    source: str
    expect: str
    got: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.got == self.expect or (self.expect == "any status" and self.got in STATUSES)


STATUSES = {"delivered", "in_transit", "returned", "failed", "unknown"}


async def _no_sleep(_: float) -> None:
    return None


def _offline_client(handler) -> PoliteClient:
    return PoliteClient(
        transport=httpx.MockTransport(handler),
        max_retries=1,
        rate_limiter=HostRateLimiter(0.0, sleep=_no_sleep),
        sleep=_no_sleep,
    )


def _fixture_site(request: httpx.Request) -> httpx.Response:
    name = OFFLINE_PAGES.get(request.url.params.get("awb", ""), "invalid.live.html")
    return httpx.Response(200, text=(FIXTURES / "trackon" / name).read_text(encoding="utf-8"))


def _outage(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("simulated outage", request=request)


def _single(api: TestClient, case: str, source: str, courier: str, tid: str, expect: str) -> tuple[Row, dict]:
    resp = api.get(f"/track/{courier}/{tid}")
    body = resp.json()
    if resp.status_code == 200:
        got, detail = body["status"], f"{len(body['events'])} events, payment={body['payment_mode']}"
    else:
        got, detail = body["error"], f"HTTP {resp.status_code}: {body['message']}"
    return Row(case, source, expect, got, detail), body


def _batch(api: TestClient, source: str, items: list[tuple[str, str]], expects: list[str]) -> Row:
    resp = api.post("/track/batch", json={"items": [{"courier": c, "tracking_id": t} for c, t in items]})
    if resp.status_code != 200:
        return Row("batch: mixed good and bad items", source, " + ".join(expects), f"HTTP {resp.status_code}")
    got = [r["result"]["status"] if r["ok"] else r["error"]["error"] for r in resp.json()["results"]]
    body = resp.json()
    return Row(
        "batch: mixed good and bad items",
        source,
        " + ".join(expects),
        " + ".join(got),
        f"HTTP 200, {body['ok']} ok / {body['failed']} failed, one bad item did not fail the batch",
    )


def run_offline() -> list[Row]:
    rows = []
    with TestClient(create_app(TrackingService(_offline_client(_fixture_site)))) as api:
        for case, awb, expect in [
            ("delivered", "999000000001", "delivered"),
            ("in transit", "999000000002", "in_transit"),
            ("returned to origin (COD)", "999000000003", "returned"),
            ("returned to origin (prepaid)", "999000000005", "returned"),
            ("failed delivery attempt", "999000000004", "failed"),
        ]:
            rows.append(_single(api, case, SYNTHETIC, "trackon", awb, expect)[0])
        rows.append(_single(api, "unknown ID", CAPTURE, "trackon", UNKNOWN_AWB, "NOT_FOUND")[0])
        rows.append(_single(api, "bad ID format", NO_REQUEST, "trackon", BAD_FORMAT, "INVALID_TRACKING_ID")[0])
        rows.append(_single(api, "unsupported courier", NO_REQUEST, *UNSUPPORTED, "UNSUPPORTED_COURIER")[0])
        rows.append(_batch(
            api, SYNTHETIC,
            [("trackon", "999000000001"), ("trackon", UNKNOWN_AWB), ("trackon", BAD_FORMAT), UNSUPPORTED],
            ["delivered", "NOT_FOUND", "INVALID_TRACKING_ID", "UNSUPPORTED_COURIER"],
        ))
    with TestClient(create_app(TrackingService(_offline_client(_outage)))) as api:
        rows.append(_single(api, "site down", OUTAGE, "trackon", "999000000001", "COURIER_UNAVAILABLE")[0])
    return rows


def run_live(real_ids: list[str], client: PoliteClient | None = None) -> tuple[list[Row], list[dict]]:
    """About two requests to trackon.in (plus one per real ID), at most one per second."""
    rows, real = [], []
    with TestClient(create_app(TrackingService(client or PoliteClient()))) as api:
        row, body = _single(api, "unknown ID", LIVE, "trackon", UNKNOWN_AWB, "NOT_FOUND")
        if row.got != "NOT_FOUND":  # never print details of a shipment that might belong to someone
            row.detail = f"HTTP answer was {row.got}; expected NOT_FOUND. This AWB may exist: details not shown."
        rows.append(row)
        rows.append(_single(api, "bad ID format", LIVE_NO_REQUEST, "trackon", BAD_FORMAT, "INVALID_TRACKING_ID")[0])
        rows.append(_single(api, "unsupported courier", LIVE_NO_REQUEST, *UNSUPPORTED, "UNSUPPORTED_COURIER")[0])
        rows.append(_batch(
            api, LIVE,
            [("trackon", "100000000001"), ("trackon", BAD_FORMAT), UNSUPPORTED],
            ["NOT_FOUND", "INVALID_TRACKING_ID", "UNSUPPORTED_COURIER"],
        ))
        for tid in real_ids:
            row, body = _single(api, f"real ID {tid}", LIVE, "trackon", tid, "any status")
            if not row.ok and row.got == "LAYOUT_CHANGED":
                row.detail = "the real page does not match the parser, so the API refused to guess | " + row.detail
            rows.append(row)
            if "status" in body:
                real.append(body)
    return rows, real


def render(rows: list[Row]) -> str:
    w_src = max(len(r.source) for r in rows)
    lines = [f"result  {'source':<{w_src}}  case", "-" * 78]
    for r in rows:
        lines.append(f"{'PASS' if r.ok else 'FAIL':<6}  {r.source:<{w_src}}  {r.case}")
        outcome = f"got {r.got}" + ("" if r.ok else f", expected {r.expect}") + (f" | {r.detail}" if r.detail else "")
        if r.ok:
            lines.append(f"        {outcome if len(outcome) <= 110 else outcome[:107] + '...'}")
        else:  # failures are shown in full
            lines.append(textwrap.fill(outcome, 110, initial_indent=" " * 8, subsequent_indent=" " * 10))
    return "\n".join(lines)


def render_real(body: dict) -> str:
    lines = [
        f"\nReal ID {body['tracking_id']} (live; names, phone numbers and emails redacted; nothing saved)",
        f"  status: {body['status']}   courier says: {redact_personal(body['raw_status'])}",
        f"  payment: {body['payment_mode']}   last update: {body['last_updated']}",
        "  events (newest first):",
    ]
    for e in body["events"]:
        when = (e["timestamp"] or "no date")[:16].replace("T", " ")
        lines.append(f"    {when}  {redact_personal(e['location']) or '-':<14} {redact_personal(e['description'])}")
    return "\n".join(lines)


def _parse_ids(values: list[str]) -> list[str]:
    ids = []
    for v in values:
        courier, _, tid = v.partition("=")
        if courier != "trackon" or not tid:
            raise SystemExit(f"--id must look like trackon=<AWB>, got {v!r}")
        ids.append(tid)
    return ids


def main(argv: list[str] | None = None, *, live_client: PoliteClient | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the test cases and print a pass/fail table.")
    ap.add_argument("--live", action="store_true", help="also call the real Trackon site (run by hand only)")
    ap.add_argument("--id", action="append", default=[], metavar="trackon=<AWB>", help="a real tracking ID to check (needs --live)")
    args = ap.parse_args(argv)
    real_ids = _parse_ids(args.id)
    if real_ids and not args.live:
        ap.error("--id needs --live")
    if args.live and os.environ.get("CI"):
        print("Refusing --live: CI is set. Live checks are run by hand only.", file=sys.stderr)
        return 2
    # Retries are logged per attempt; the table already reports the outcome.
    logging.getLogger("courier_tracking.http").setLevel(logging.ERROR)

    rows = run_offline()
    real: list[dict] = []
    if args.live:
        print(f"LIVE mode: calling trackon.in at most once per second as\n  {USER_AGENT}\n")
        live_rows, real = run_live(real_ids, client=live_client)
        rows += live_rows

    print(render(rows))
    for body in real:
        print(render_real(body))
    failed = sum(not r.ok for r in rows)
    live_count = sum(r.source.startswith("live") for r in rows)
    print(f"\n{len(rows) - failed}/{len(rows)} cases passed "
          f"({len(rows) - live_count} offline, {live_count} live)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

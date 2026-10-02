"""Drift check: warns when a courier page or response no longer looks like our baseline.

    python -m courier_tracking.drift                 # offline: checks the saved fixtures
    python -m courier_tracking.drift --live          # calls the live sites (run by hand only)
    python -m courier_tracking.drift --live --id trackon=123456789012 --save

Two levels per sample:
  DRIFT  required markers are missing; the adapter will fail. Exit code 1.
  WARN   structure differs from the saved baseline (ids, form fields, JSON keys),
         but required markers are still there. Look before it breaks.

This is the only code path that may call live sites, and only with --live.
Tests and CI never pass --live.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from .adapters.base import CourierAdapter, RawResponse
from .errors import LayoutDriftError, NotFoundError, TrackingError
from .http import PoliteClient
from .service import COURIERS

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SAVE_DIR = Path(".drift")


# ---------- fingerprints ----------

def html_fingerprint(html: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    fp = {f"#{el['id']}" for el in soup.find_all(id=True)}
    fp |= {f"input[name={el['name']}]" for el in soup.find_all("input", attrs={"name": True})}
    fp |= {f"meta[name={el['name']}]" for el in soup.find_all("meta", attrs={"name": True})}
    fp |= {f"header:{' '.join(el.get_text(' ', strip=True).split())}" for el in soup.find_all(class_="header")}
    return fp


def json_fingerprint(text: str) -> set[str]:
    def walk(node, path: str, out: set[str]):
        if isinstance(node, dict):
            for k, v in node.items():
                key = "<id>" if re.search(r"\d{6,}", str(k)) else str(k)  # keys that are tracking IDs
                p = f"{path}.{key}" if path else key
                out.add(p)
                walk(v, p, out)
        elif isinstance(node, list):
            for item in node:
                walk(item, f"{path}[]", out)

    out: set[str] = set()
    try:
        walk(json.loads(text), "", out)
    except ValueError:
        out.add("<not json>")
    return out


def fingerprint(kind: str, text: str) -> set[str]:
    return html_fingerprint(text) if kind == "html" else json_fingerprint(text)


# ---------- redaction for --save ----------

_REDACTIONS = [
    # Session tokens and the visitor's own IP, which some pages echo back.
    (re.compile(r'(<meta name="csrf-token" content=")[^"]*"'), r'\1REDACTED-CSRF-TOKEN"'),
    (re.compile(r'(data-public-ip=")[^"]*"'), r'\g<1>0.0.0.0"'),
    (re.compile(r'(name="__RequestVerificationToken" type="hidden" value=")[^"]*"'), r'\1REDACTED-FORM-TOKEN"'),
    # Third-party telemetry keys embedded in courier pages (New Relic, Sentry). Public, but still keys.
    (re.compile(r'(licenseKey:")[^"]*"'), r'\1REDACTED"'),
    (re.compile(r'\b(accountID|trustKey|agentID|applicationID):"\d+"'), r'\1:"0"'),
    (re.compile(r"https://[a-f0-9]{20,}@[A-Za-z0-9.-]+/\d+"), "https://REDACTED@sentry.invalid/0"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


# ---------- samples ----------

@dataclass
class Sample:
    courier: str
    label: str
    kind: str  # "html" | "json"
    fetch: Callable[[], Awaitable[RawResponse]]
    check: Callable[[RawResponse], list[str]]
    baseline: str | None = None  # fixture file to compare structure against


@dataclass
class Outcome:
    sample: Sample
    problems: list[str] = field(default_factory=list)
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    error: str | None = None
    note: str | None = None
    warnings: list[str] = field(default_factory=list)
    raw: RawResponse | None = None

    @property
    def level(self) -> str:
        if self.error:
            return "UNREACHABLE"
        if self.problems:
            return "DRIFT"
        if self.added or self.removed or self.warnings:
            return "WARN"
        return "OK"


def _fixture(courier: str, name: str) -> str:
    return (FIXTURES / courier / name).read_text(encoding="utf-8")


def build_samples(adapters: dict[str, CourierAdapter], *, live: bool, extra_ids: dict[str, list[str]]) -> list[Sample]:
    samples: list[Sample] = []

    def offline(courier: str, name: str, url: str) -> Callable[[], Awaitable[RawResponse]]:
        async def read() -> RawResponse:
            return RawResponse(url=url, status_code=200, text=_fixture(courier, name))
        return read

    for name, adapter in adapters.items():
        probe, baseline, kind = adapter.probe_id, adapter.drift_baseline, adapter.raw_kind
        samples.append(Sample(
            name, f"unknown-ID answer ({probe})", kind,
            (lambda a=adapter, p=probe: a.fetch_raw(p)) if live else offline(name, baseline, "fixture"),
            adapter.drift_problems,
            baseline=baseline,
        ))

        for tid in extra_ids.get(name, []) if live else []:
            samples.append(Sample(
                name, f"real ID {tid}", kind,
                lambda a=adapter, t=tid: a.fetch_raw(a.normalize_id(t)),
                adapter.drift_problems,
            ))
    return samples


async def run_samples(samples: list[Sample], adapters: dict[str, CourierAdapter]) -> list[Outcome]:
    outcomes = []
    for s in samples:
        out = Outcome(s)
        try:
            out.raw = await s.fetch()
        except TrackingError as exc:
            out.error = exc.message
            outcomes.append(out)
            continue
        out.problems = s.check(out.raw)
        if s.baseline:
            now = fingerprint(s.kind, out.raw.text)
            then = fingerprint(s.kind, _fixture(s.courier, s.baseline))
            out.added, out.removed = now - then, then - now
        elif not out.problems and s.label.startswith("real ID"):
            tid = s.label.removeprefix("real ID ")
            try:
                result = adapters[s.courier].parse(out.raw, adapters[s.courier].normalize_id(tid))
                out.note = f"parsed: status={result.status.value}, {len(result.events)} events"
                if not result.events:
                    out.warnings.append("a real ID parsed with no events: the history table layout may differ")
                if result.status.value == "unknown":
                    out.warnings.append(
                        f"newest status not recognised (courier says {result.raw_status!r}), so the API answers "
                        "'unknown': add the wording to status_map.py"
                    )
            except LayoutDriftError as exc:
                out.problems.append(f"real result does not match the parser (API returns LAYOUT_CHANGED): {exc.message}")
            except NotFoundError as exc:
                out.note = f"parse: {exc.code.value}: {exc.message}"
                out.warnings.append(
                    "a real ID came back NOT_FOUND: either the ID is wrong/too old, or the result block is not where "
                    "the parser looks. Inspect the saved response (--save)."
                )
            except TrackingError as exc:
                out.note = f"parse: {exc.code.value}: {exc.message}"
        outcomes.append(out)
    return outcomes


def save(outcomes: list[Outcome]) -> list[Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    paths = []
    for o in outcomes:
        if o.raw is None:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", o.sample.label.lower()).strip("-")
        path = SAVE_DIR / o.sample.courier / f"{stamp}-{slug}.{o.sample.kind}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redact(o.raw.text), encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def render(outcomes: list[Outcome]) -> str:
    lines = []
    for o in outcomes:
        lines.append(f"[{o.level:<11}] {o.sample.courier:<8} {o.sample.label}")
        if o.error:
            lines.append(f"              {o.error}")
        for p in o.problems:
            lines.append(f"              missing: {p}")
        for w in o.warnings:
            lines.append(f"              check: {w}")
        for a in sorted(o.added)[:15]:
            lines.append(f"              + {a}")
        for r in sorted(o.removed)[:15]:
            lines.append(f"              - {r}")
        if len(o.added) + len(o.removed) > 30:
            lines.append(f"              ... {len(o.added)} added / {len(o.removed)} removed in total")
        if o.note:
            lines.append(f"              {o.note}")
    return "\n".join(lines)


def exit_code(outcomes: list[Outcome], *, strict: bool = False) -> int:
    levels = {o.level for o in outcomes}
    if "DRIFT" in levels:
        return 1
    if "UNREACHABLE" in levels:
        return 2
    if strict and "WARN" in levels:
        return 1
    return 0


def _parse_ids(values: list[str]) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {}
    for v in values:
        courier, _, tid = v.partition("=")
        if courier not in COURIERS or not tid:
            raise SystemExit(f"--id must look like trackon=123456789012 (supported: {', '.join(COURIERS)}), got {v!r}")
        ids.setdefault(courier, []).append(tid)
    return ids


async def main_async(argv: list[str] | None = None, *, client: PoliteClient | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m courier_tracking.drift", description=__doc__.split("\n\n")[0])
    ap.add_argument("--live", action="store_true", help="call the live courier sites (polite: 1 req/s per host)")
    ap.add_argument("--id", action="append", default=[], metavar="COURIER=ID", help="also check a real tracking ID (live only)")
    ap.add_argument("--save", action="store_true", help="write redacted live responses to .drift/ (gitignored)")
    ap.add_argument("--strict", action="store_true", help="treat WARN as failure")
    args = ap.parse_args(argv)
    extra = _parse_ids(args.id)
    if extra and not args.live:
        ap.error("--id needs --live")

    print(f"Drift check ({'LIVE: calling courier sites' if args.live else 'offline: saved fixtures'})")
    client = client or PoliteClient()
    try:
        adapters = {name: cls(client) for name, cls in COURIERS.items()}
        outcomes = await run_samples(build_samples(adapters, live=args.live, extra_ids=extra), adapters)
    finally:
        await client.aclose()
    print(render(outcomes))
    if args.save and args.live:
        for p in save(outcomes):
            print(f"saved {p}")
        print("Redact names, phone numbers and addresses before copying any saved file into tests/fixtures/.")
    code = exit_code(outcomes, strict=args.strict)
    print({0: "Result: no drift", 1: "Result: DRIFT, adapters need attention", 2: "Result: some sites unreachable"}[code])
    return code


def main() -> None:
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()

"""Adapter interface. `fetch_raw` does I/O; `parse` is pure so fixtures can test it offline."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..errors import InvalidTrackingIdError, LayoutDriftError, TrackingError
from ..http import PoliteClient
from ..schema import Status, TrackingEvent, TrackingResult
from ..status_map import classify


@dataclass(frozen=True)
class RawResponse:
    url: str
    status_code: int
    text: str


class CourierAdapter(ABC):
    """To add a courier: subclass this, fill in the attributes, save the baseline fixture,
    and register the class in service.COURIERS."""

    name: str
    display_name: str
    id_pattern: re.Pattern[str]
    id_hint: str
    # Drift check: a well-formed but unknown ID (never a real shipment), the saved fixture
    # holding the live answer for it, and that answer's format ("html" or "json").
    probe_id: str
    drift_baseline: str
    raw_kind: str = "html"

    def __init__(self, client: PoliteClient):
        self.client = client

    def normalize_id(self, tracking_id: str) -> str:
        tid = tracking_id.strip().upper()
        if not self.id_pattern.fullmatch(tid):
            raise InvalidTrackingIdError(
                f"'{tracking_id}' is not a valid {self.display_name} tracking ID ({self.id_hint})",
                courier=self.name,
                tracking_id=tracking_id,
            )
        return tid

    async def track(self, tracking_id: str) -> TrackingResult:
        tid = self.normalize_id(tracking_id)
        raw = await self.fetch_raw(tid)
        return self.parse(raw, tid)

    def parse(self, raw: RawResponse, tracking_id: str) -> TrackingResult:
        problems = self.drift_problems(raw)
        if problems:
            raise LayoutDriftError(
                f"{self.display_name} response layout changed: " + "; ".join(problems),
                courier=self.name,
                tracking_id=tracking_id,
            )
        try:
            return self._parse(raw, tracking_id)
        except TrackingError:
            raise
        except Exception as exc:  # any surprise in a courier page is a layout problem, never a 500 or a guess
            raise LayoutDriftError(
                f"{self.display_name} response could not be parsed ({type(exc).__name__}: {exc})",
                courier=self.name,
                tracking_id=tracking_id,
            ) from exc

    @abstractmethod
    async def fetch_raw(self, tracking_id: str) -> RawResponse: ...

    @abstractmethod
    def drift_problems(self, raw: RawResponse) -> list[str]:
        """Return what is missing from the expected layout. Empty list means OK."""

    @abstractmethod
    def _parse(self, raw: RawResponse, tracking_id: str) -> TrackingResult: ...

    def _checked_result(
        self,
        tracking_id: str,
        raw: RawResponse,
        events: list[TrackingEvent],
        *,
        summary_status: str | None = None,
        unreadable_rows: int = 0,
        **fields,
    ) -> TrackingResult:
        """Build the result, or raise LayoutDriftError rather than risk a wrong status.

        `events` must be in the order the page lists them. Status comes from the page's own
        "current status" (if any) and the newest event; it never falls back to an older event.
        """
        problems: list[str] = []
        if unreadable_rows:
            problems.append(f"{unreadable_rows} history row(s) could not be read")
        stamps = [e.timestamp for e in events if e.timestamp]
        if events and not stamps:
            problems.append("no event date could be read")
        if any(t > datetime.now(timezone.utc) + timedelta(days=2) for t in stamps):
            problems.append("event dates are in the future (date format misread?)")
        pairs = list(zip(stamps, stamps[1:]))
        if len(stamps) >= 3 and not (all(a <= b for a, b in pairs) or all(a >= b for a, b in pairs)):
            problems.append("event dates are out of order on the page (date format misread?)")
        if events and all(classify(e.description) is Status.UNKNOWN for e in events):
            problems.append(f"none of the {len(events)} event descriptions is a recognisable status (wrong column?)")

        result = self._result(tracking_id, raw, events, status=Status.UNKNOWN, **fields)
        newest = result.events[0] if result.events else None
        from_event = classify(newest.description) if newest else Status.UNKNOWN
        from_summary = classify(summary_status)
        if Status.UNKNOWN not in (from_event, from_summary) and from_event is not from_summary:
            problems.append(
                f"page says current status {summary_status!r} but the newest event is {newest.description!r}"
            )
        if problems:
            raise LayoutDriftError(
                f"{self.display_name} result did not match the expected layout: " + "; ".join(problems),
                courier=self.name,
                tracking_id=tracking_id,
            )

        if from_summary is not Status.UNKNOWN:
            result.status, result.raw_status = from_summary, summary_status
        elif from_event is not Status.UNKNOWN:
            result.status, result.raw_status = from_event, newest.description
        else:  # unrecognised wording: say unknown, never guess from an older event
            result.raw_status = summary_status or (newest.description if newest else None)
        return result

    def _result(self, tracking_id: str, raw: RawResponse, events: list[TrackingEvent], **fields) -> TrackingResult:
        events = sorted(
            events,
            key=lambda e: e.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return TrackingResult(
            courier=self.name,
            tracking_id=tracking_id,
            events=events,
            last_updated=next((e.timestamp for e in events if e.timestamp), None),
            source_url=raw.url,
            fetched_at=datetime.now(timezone.utc),
            **fields,
        )

import re
from datetime import datetime, timezone

import pytest

from courier_tracking.adapters.base import CourierAdapter, RawResponse
from courier_tracking.errors import InvalidTrackingIdError, LayoutDriftError
from courier_tracking.schema import Status, TrackingEvent


class DummyAdapter(CourierAdapter):
    name = "dummy"
    display_name = "Dummy"
    id_pattern = re.compile(r"[A-Z]{2}\d{4}")
    id_hint = "2 letters + 4 digits"

    async def fetch_raw(self, tracking_id):
        raise AssertionError("not used")

    def drift_problems(self, raw):
        return [] if "MARKER" in raw.text else ["MARKER missing"]

    def _parse(self, raw, tracking_id):
        t = lambda h: datetime(2026, 9, 30, h, tzinfo=timezone.utc)  # noqa: E731
        events = [
            TrackingEvent(timestamp=t(9), description="Picked up"),
            TrackingEvent(timestamp=None, description="Undated note"),
            TrackingEvent(timestamp=t(15), description="Delivered"),
        ]
        return self._result(tracking_id, raw, events, status=Status.DELIVERED)


@pytest.fixture
def adapter():
    return DummyAdapter(client=None)


def test_normalize_id_strips_and_uppercases(adapter):
    assert adapter.normalize_id("  ab1234 ") == "AB1234"


@pytest.mark.parametrize("bad", ["", "AB12", "AB12345", "A'; DROP", "../etc"])
def test_normalize_id_rejects_bad_ids(adapter, bad):
    with pytest.raises(InvalidTrackingIdError):
        adapter.normalize_id(bad)


def test_parse_raises_layout_drift_when_markers_missing(adapter):
    raw = RawResponse(url="https://x.example", status_code=200, text="something new")
    with pytest.raises(LayoutDriftError, match="MARKER missing"):
        adapter.parse(raw, "AB1234")


def test_events_sorted_newest_first_and_last_updated_set(adapter):
    raw = RawResponse(url="https://x.example", status_code=200, text="MARKER")
    result = adapter.parse(raw, "AB1234")
    assert [e.description for e in result.events] == ["Delivered", "Picked up", "Undated note"]
    assert result.last_updated == datetime(2026, 9, 30, 15, tzinfo=timezone.utc)
    assert result.source_url == "https://x.example"

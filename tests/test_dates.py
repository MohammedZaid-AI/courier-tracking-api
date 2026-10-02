from datetime import datetime, timezone

import pytest

from courier_tracking.dates import IST, parse_datetime


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-30T14:05:00",
        "2026-09-30 14:05:00",
        "30-09-2026 14:05",
        "30/09/2026 14:05:00",
        "30/09/2026 02:05 PM",
        "30 Sep 2026 14:05",
        "30 Sep 2026, 14:05",
        "30-Sep-2026 14:05",
        "  30 Sep 2026   14:05 ",
    ],
)
def test_naive_formats_are_read_as_ist(value):
    assert parse_datetime(value) == datetime(2026, 9, 30, 14, 5, tzinfo=IST)


def test_explicit_timezone_is_kept():
    assert parse_datetime("2026-09-30T08:35:00Z") == datetime(2026, 9, 30, 8, 35, tzinfo=timezone.utc)


def test_epoch_milliseconds_and_seconds():
    expected = datetime(2026, 9, 30, 8, 35, tzinfo=timezone.utc)
    assert parse_datetime(int(expected.timestamp() * 1000)) == expected
    assert parse_datetime(int(expected.timestamp())) == expected


@pytest.mark.parametrize("value", [None, "", "not a date"])
def test_unparseable_returns_none(value):
    assert parse_datetime(value) is None


@pytest.mark.parametrize("value", [10**18, -(10**18)])
def test_out_of_range_epoch_returns_none_instead_of_crashing(value):
    assert parse_datetime(value) is None

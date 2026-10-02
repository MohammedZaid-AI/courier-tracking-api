"""Parse the date formats Indian courier pages use. Naive times and epochs come out in IST."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d %b %Y %H:%M",
    "%d %b %Y, %H:%M",
    "%d %b %Y %I:%M %p",
    "%d-%b-%Y %H:%M",
    "%d %B %Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%d",
]


def parse_datetime(value: str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value  # epoch ms or s
        try:
            return datetime.fromtimestamp(seconds, tz=IST)  # same instant, shown in Indian time like the HTML couriers
        except (OverflowError, OSError, ValueError):
            return None  # out of range: the unit changed; callers treat a missing date as a layout change
    text = " ".join(str(value).split())
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        for fmt in _FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)

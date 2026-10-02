"""Trackon Courier public tracking (server-rendered HTML).

Uses the GET target Trackon itself advertises in its schema.org markup:
    https://trackon.in/courier-tracking?awb=<AWB>

What is verified live: the page shell (tracking form, "Tracking Status" header), and
that an unknown AWB renders the shell with no result block.
What is NOT verified: the markup of a real result. The parser therefore finds the
result block by id and its tables by header text, not by position. The first real
AWB run through `drift --live --save` will confirm or correct this.

Never fetched: proof-of-delivery, signature and NDR images the page can link to.
They can contain personal data.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ..dates import parse_datetime
from ..errors import CourierUnavailableError, LayoutDriftError, NotFoundError
from ..schema import TrackingEvent, TrackingResult
from ..status_map import classify_payment
from .base import CourierAdapter, RawResponse

TRACK_URL = "https://trackon.in/courier-tracking"
RESULT_ID = "divtrackStatus"

_DATE_COL = ("date",)
_TIME_COL = ("time",)
_LOCATION_COL = ("location", "place", "branch", "city", "office")
_STATUS_COL = ("status", "activity", "remark", "description", "event", "details")
# Only these summary labels count as the shipment's current status ("Payment Status" must not).
_CURRENT_STATUS_LABELS = {"current status", "status", "shipment status", "consignment status", "tracking status"}


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _find_col(headers: list[str], keys: tuple[str, ...]) -> int | None:
    return next((i for i, h in enumerate(headers) if any(k in h for k in keys)), None)


def _history_table(result: Tag) -> tuple[Tag, list[str]] | None:
    for table in result.find_all("table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        headers = [_text(c).lower() for c in header_row.find_all(["th", "td"])]
        if len(headers) >= 2 and _find_col(headers, _DATE_COL) is not None and _find_col(headers, _STATUS_COL) is not None:
            return table, headers
    return None


def _summary(result: Tag) -> dict[str, str]:
    """Two-cell label/value rows anywhere in the result block, e.g. <th>Origin</th><td>DELHI</td>."""
    pairs: dict[str, str] = {}
    for row in result.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) == 2:
            label = _text(cells[0]).rstrip(":").lower()
            if label:
                pairs[label] = _text(cells[1])
    return pairs


class TrackonAdapter(CourierAdapter):
    name = "trackon"
    display_name = "Trackon"
    id_pattern = re.compile(r"\d{6,12}")
    id_hint = "6 to 12 digits; Trackon's own form allows at most 12"
    probe_id = "100000000000"
    drift_baseline = "invalid.live.html"

    async def fetch_raw(self, tracking_id: str) -> RawResponse:
        resp = await self.client.request("GET", TRACK_URL, params={"awb": tracking_id}, courier=self.name)
        if resp.status_code != 200:
            raise CourierUnavailableError(f"Trackon returned HTTP {resp.status_code}", courier=self.name)
        return RawResponse(url=str(resp.url), status_code=resp.status_code, text=resp.text)

    def drift_problems(self, raw: RawResponse) -> list[str]:
        soup = BeautifulSoup(raw.text, "html.parser")
        problems = []
        if soup.find("input", attrs={"name": "awbSingleTrackingId"}) is None:
            problems.append("tracking form input 'awbSingleTrackingId' not found")
        if not any(_text(h) == "Tracking Status" for h in soup.find_all(class_="header")):
            problems.append("'Tracking Status' header not found")
        result = soup.find(id=RESULT_ID)
        if result is not None and _history_table(result) is None:
            problems.append(f"#{RESULT_ID} has no table with Date and Status columns")
        return problems

    def _parse(self, raw: RawResponse, tracking_id: str) -> TrackingResult:
        soup = BeautifulSoup(raw.text, "html.parser")
        result = soup.find(id=RESULT_ID)
        if result is None:
            # The live unknown-AWB page never prints the AWB. If this page does, a result is there
            # in a layout we do not recognise: report that instead of "not found".
            if tracking_id in soup.get_text(" "):
                raise LayoutDriftError(
                    f"Trackon page mentions {tracking_id} but has no #{RESULT_ID} result block",
                    courier=self.name,
                    tracking_id=tracking_id,
                )
            raise NotFoundError(
                f"Trackon has no shipment {tracking_id} (unknown AWB, or older than the 75 days Trackon keeps)",
                courier=self.name,
                tracking_id=tracking_id,
            )
        table, headers = _history_table(result)
        cols = {
            "date": _find_col(headers, _DATE_COL),
            "time": _find_col(headers, _TIME_COL),
            "location": _find_col(headers, _LOCATION_COL),
            "status": _find_col(headers, _STATUS_COL),
        }
        if cols["date"] == cols["status"]:
            raise LayoutDriftError(
                f"Trackon history columns are ambiguous: {headers!r}", courier=self.name, tracking_id=tracking_id
            )
        events, unreadable = [], 0
        for row in table.find_all("tr")[1:]:
            cells = [_text(c) for c in row.find_all("td")]
            if len(cells) <= 1:
                continue  # empty row or a full-width note
            get = lambda key: cells[cols[key]] if cols[key] is not None and cols[key] < len(cells) else ""  # noqa: E731
            status_text = get("status")
            if len(cells) < len(headers) or not status_text:
                unreadable += 1
                continue
            events.append(
                TrackingEvent(
                    timestamp=parse_datetime(f"{get('date')} {get('time')}".strip()),
                    location=get("location") or None,
                    description=status_text,
                    raw_status=status_text,
                )
            )

        summary = _summary(result)
        current = next((v for k, v in summary.items() if k in _CURRENT_STATUS_LABELS and v), None)
        payment = next((v for k, v in summary.items() if "payment" in k or k in {"mode", "pay mode"}), None)
        return self._checked_result(
            tracking_id,
            raw,
            events,
            summary_status=current,
            unreadable_rows=unreadable,
            payment_mode=classify_payment(payment),
        )

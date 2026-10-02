from datetime import datetime, timezone

import pytest

from courier_tracking.refund_hint import refund_hint
from courier_tracking.schema import Status, TrackingResult


def result(status: Status, payment: str = "unknown", raw: str | None = None, courier: str = "trackon") -> TrackingResult:
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return TrackingResult(
        courier=courier, tracking_id="999000000001", status=status, raw_status=raw,
        payment_mode=payment, source_url="https://x.example", fetched_at=now,
    )


def test_returned_cod_means_no_refund_due():
    h = refund_hint(result(Status.RETURNED, "cod", "RTO DELIVERED"))
    assert h.action == "no_refund_due"
    assert "COD" in h.message and "back with the seller" in h.message


def test_returned_prepaid_suggests_refund_under_policy():
    h = refund_hint(result(Status.RETURNED, "prepaid", "RTO DELIVERED"))
    assert h.action == "consider_refund"
    assert "your policy" in h.message


def test_returned_still_travelling_says_not_arrived():
    h = refund_hint(result(Status.RETURNED, "prepaid", "RTO IN TRANSIT"))
    assert "has not arrived yet" in h.message


def test_returned_unknown_payment_asks_merchant_to_check():
    h = refund_hint(result(Status.RETURNED, "unknown", "RTO DELIVERED"))
    assert h.action == "check_payment_mode"
    assert "Trackon does not show" in h.message


@pytest.mark.parametrize("payment", ["cod", "prepaid", "unknown"])
def test_failed_always_says_wait_do_not_cancel(payment):
    h = refund_hint(result(Status.FAILED, payment))
    assert h.action == "wait"
    assert "Wait for the next delivery attempt, do not cancel yet." in h.message


@pytest.mark.parametrize("status", [Status.DELIVERED, Status.IN_TRANSIT])
@pytest.mark.parametrize("payment", ["cod", "prepaid", "unknown"])
def test_only_returned_gets_a_refund_hint(status, payment):
    h = refund_hint(result(status, payment))
    assert h.action == "none"
    assert "refund" not in h.message.lower().replace("no refund action", "")


def test_unknown_status_says_check_manually():
    assert refund_hint(result(Status.UNKNOWN, raw="Lost")).action == "check_manually"


@pytest.mark.parametrize("status", list(Status))
def test_every_hint_is_marked_as_a_suggestion(status):
    h = refund_hint(result(status, "cod"))
    assert h.is_suggestion is True
    assert "never refunds, cancels" in h.disclaimer

from datetime import datetime, timezone

from courier_tracking.schema import Status, TrackingEvent, TrackingResult


def test_result_serializes_to_expected_json():
    ts = datetime(2026, 9, 30, 14, 5, tzinfo=timezone.utc)
    result = TrackingResult(
        courier="trackon",
        tracking_id="999000000001",
        status=Status.DELIVERED,
        events=[TrackingEvent(timestamp=ts, location="Mumbai", description="Delivered")],
        last_updated=ts,
        source_url="https://example.invalid",
        fetched_at=ts,
    )
    data = result.model_dump(mode="json")
    assert data["status"] == "delivered"
    assert data["payment_mode"] == "unknown"
    assert data["events"][0]["location"] == "Mumbai"
    assert data["last_updated"] == "2026-09-30T14:05:00Z"


def test_status_values_are_the_agreed_five():
    assert {s.value for s in Status} == {
        "delivered", "in_transit", "returned", "failed", "unknown"
    }

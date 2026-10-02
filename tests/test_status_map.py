import pytest

from courier_tracking.schema import Status
from courier_tracking.status_map import classify, classify_payment


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Delivered", Status.DELIVERED),
        ("Shipment delivered to consignee", Status.DELIVERED),
        ("Undelivered - consignee not available", Status.FAILED),  # contains "delivered"
        ("Not Delivered", Status.FAILED),
        ("Delivery attempt failed", Status.FAILED),
        ("Customer refused delivery", Status.FAILED),
        ("RTO Delivered", Status.RETURNED),  # a delivered return is still a return
        ("Returned to origin", Status.RETURNED),
        ("In Transit For Return", Status.RETURNED),
        ("RTO In Transit", Status.RETURNED),
        ("In Transit", Status.IN_TRANSIT),
        ("Out for delivery", Status.IN_TRANSIT),
        ("Shipment picked up", Status.IN_TRANSIT),
        ("Dispatched", Status.IN_TRANSIT),
        ("Lost", Status.UNKNOWN),
        ("", Status.UNKNOWN),
        (None, Status.UNKNOWN),
    ],
)
def test_classify(text, expected):
    assert classify(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("COD", "cod"),
        ("Cash on Delivery", "cod"),
        ("Pre-paid", "prepaid"),
        ("PREPAID", "prepaid"),
        ("", "unknown"),
        (None, "unknown"),
        ("something else", "unknown"),
    ],
)
def test_classify_payment(text, expected):
    assert classify_payment(text) == expected

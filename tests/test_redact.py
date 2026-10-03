import pytest

from courier_tracking.redact import EMAIL, NAME, PHONE, redact_personal


@pytest.mark.parametrize(
    "text, expected",
    [
        ("DELIVERED TO RAMESH KUMAR", f"DELIVERED TO {NAME}"),
        ("Received by: Priya S.", f"Received by: {NAME}"),
        ("Consignee: ANIL SHARMA", f"Consignee: {NAME}"),
        ("SIGNED BY R K SINGH", f"SIGNED BY {NAME}"),
        ("Call 9876543210 for delivery", f"Call {PHONE} for delivery"),
        ("Contact +91 98765 43210", f"Contact {PHONE}"),
        ("Branch 011-4559 3500", f"Branch {PHONE}"),
        ("mail someone@example.com", f"mail {EMAIL}"),
    ],
)
def test_personal_data_is_redacted(text, expected):
    assert redact_personal(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "UNDELIVERED - CONSIGNEE NOT AVAILABLE",
        "UNDELIVERED - CONSIGNEE REFUSED",
        "DELIVERED TO SELF",
        "DELIVERED TO SECURITY GUARD",
        "RTO DELIVERED",
        "OUT FOR DELIVERY",
        "26/09/2026 14:05",
        "AWB 999000000001",  # 12-digit tracking numbers are not phone numbers
    ],
)
def test_status_wording_dates_and_awbs_are_kept(text):
    assert redact_personal(text) == text


@pytest.mark.parametrize("value", [None, ""])
def test_empty_values_pass_through(value):
    assert redact_personal(value) == value

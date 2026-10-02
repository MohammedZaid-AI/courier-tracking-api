"""Saved fixtures must not carry secrets or personal data. Runs on every push."""

import re
from pathlib import Path

import pytest

from courier_tracking import drift

FIXTURES = Path(__file__).parent / "fixtures"
FILES = sorted(p for p in FIXTURES.rglob("*") if p.is_file() and p.name != "README.md")

# Public business contacts printed on the courier's own page; not personal data.
ALLOWED_EMAILS = {"customercare@trackon.in"}
ALLOWED_IPS = {"0.0.0.0"}

SECRET_PATTERNS = {
    "New Relic key": r"NRJS-[a-f0-9]{8,}",
    "Sentry DSN": r"https://[a-f0-9]{20,}@",
    "Razorpay key": r"rzp_(?:live|test)_[A-Za-z0-9]+",
    "AWS key": r"AKIA[0-9A-Z]{16}",
    "Google API key": r"AIza[0-9A-Za-z_\-]{30,}",
    "JWT": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    "CSRF token": r'name="csrf-token" content="(?!REDACTED-CSRF-TOKEN")',
    "form token": r'__RequestVerificationToken" type="hidden" value="(?!REDACTED-FORM-TOKEN")',
    "Indian mobile number": r"(?<![\d.])(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)",
}


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(FIXTURES)))
def test_fixture_has_no_secrets_or_personal_data(path):
    text = path.read_text(encoding="utf-8")
    for name, pattern in SECRET_PATTERNS.items():
        assert not re.search(pattern, text), f"{name} in {path.name}"
    emails = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
    assert emails <= ALLOWED_EMAILS, emails - ALLOWED_EMAILS
    ips = set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text))
    assert ips <= ALLOWED_IPS, ips - ALLOWED_IPS

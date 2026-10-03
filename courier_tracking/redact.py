"""Best-effort removal of personal data from text we print (never stored).

Courier events sometimes name the person who took the parcel ("DELIVERED TO RAMESH KUMAR")
or show phone numbers. This blanks phone numbers, emails, and names that follow phrases like
"delivered to" or "received by". It is a safety net for printed output, not a guarantee.
"""

from __future__ import annotations

import re

NAME = "[name redacted]"
PHONE = "[phone redacted]"
EMAIL = "[email redacted]"

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Indian mobiles (optionally +91 / 0 prefixed) and landlines like 011-45593500 / 022 2345 6789.
_PHONE = re.compile(r"(?<![\d])(?:(?:\+91|0091|91)[\s-]?|0)?(?:[6-9]\d{4}[\s-]?\d{5}|\d{2,4}[\s-]\d{3,4}[\s-]?\d{4})(?![\d])")
_NAME_AFTER = re.compile(
    r"(?i)\b((?:delivered to|received by|signed by|handed over to|collected by)(?:\s*:)?"
    r"|(?:receiver|consignee)(?: name)?\s*:|recipient\s*:|name\s*:)\s*"
    r"([A-Za-z][A-Za-z.']*(?:\s+[A-Za-z][A-Za-z.']*){0,3})"
)
# Words after "delivered to" etc. that describe a role, not a person.
_NOT_A_NAME = {
    "self", "consignee", "customer", "receiver", "recipient", "security", "guard", "neighbour", "neighbor",
    "family", "relative", "reception", "receptionist", "office", "shop", "the", "a", "an", "addressee",
}


def _name(match: re.Match) -> str:
    words = match.group(2).split()
    if words and words[0].lower().strip(".") in _NOT_A_NAME:
        return match.group(0)
    return f"{match.group(1)} {NAME}"


def redact_personal(text: str | None) -> str | None:
    if not text:
        return text
    text = _EMAIL.sub(EMAIL, text)
    text = _PHONE.sub(PHONE, text)
    return _NAME_AFTER.sub(_name, text)

"""Keyword fallback that maps any courier's free-text status to our five statuses.

Adapters try their own exact codes first and fall back to `classify`.
Order matters: "undelivered" contains "delivered", and "RTO delivered" is a return.
"""

from __future__ import annotations

import re

from .schema import Status

_RETURNED = re.compile(r"\brto\b|\brts\b|return(ed)?\b|returning|in transit for return|return to origin|returned to (origin|shipper|seller)")
_FAILED = re.compile(
    r"undelivered|not delivered|non[- ]?delivery|\bndr\b|delivery attempt|attempt(ed)? (fail|unsuccess)"
    r"|failed|unsuccessful|consignee (not available|unavailable|refused)|refused|door locked|address (not found|incomplete)"
)
_DELIVERED = re.compile(r"\bdelivered\b")
_IN_TRANSIT = re.compile(
    r"transit|dispatch|out for delivery|picked|pickup|pick up|manifest|shipped|booked|in[- ]?scan|reached|arrived"
    r"|received|forwarded|connected|bagged|on the way|pending|delayed|on time"
)


def classify(text: str | None) -> Status:
    if not text:
        return Status.UNKNOWN
    t = " ".join(text.lower().split())
    if _RETURNED.search(t):
        return Status.RETURNED
    if _FAILED.search(t):
        return Status.FAILED
    if _DELIVERED.search(t):
        return Status.DELIVERED
    if _IN_TRANSIT.search(t):
        return Status.IN_TRANSIT
    return Status.UNKNOWN


def classify_payment(text: str | None) -> str:
    if not text:
        return "unknown"
    t = text.lower().replace("-", "").replace(" ", "")
    if "cod" in t or "cashondelivery" in t:
        return "cod"
    if "prepaid" in t or t in {"pp", "paid", "online"}:
        return "prepaid"
    return "unknown"

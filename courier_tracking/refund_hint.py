"""Refund hint: a suggestion for the merchant, never an action.

Rules:
- returned  -> the only status that gets a refund hint; wording depends on COD / prepaid / unknown
- failed    -> "Wait for the next delivery attempt, do not cancel yet."
- otherwise -> no refund action

Nothing here refunds, cancels or changes an order. Every merchant has its own refund
policy; the hint only says what the tracking data suggests.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .schema import Status, TrackingResult

DISCLAIMER = (
    "Suggestion only. This tool never refunds, cancels or changes an order. "
    "Check your own refund policy before acting."
)

Action = Literal["consider_refund", "no_refund_due", "check_payment_mode", "wait", "none", "check_manually"]


class RefundHint(BaseModel):
    action: Action
    message: str
    is_suggestion: Literal[True] = True
    disclaimer: str = DISCLAIMER


def _back_with_merchant(result: TrackingResult) -> bool:
    raw = (result.raw_status or "").lower()
    return any(k in raw for k in ("delivered", "returned to", "received"))


def refund_hint(result: TrackingResult) -> RefundHint:
    status, payment = result.status, result.payment_mode

    if status is Status.RETURNED:
        where = (
            "The parcel is back with the seller."
            if _back_with_merchant(result)
            else "The parcel is on its way back to the seller and has not arrived yet."
        )
        if payment == "cod":
            return RefundHint(
                action="no_refund_due",
                message=f"Returned to origin. {where} This was a COD order, so the customer paid nothing on "
                "delivery and there is normally nothing to refund (unless you took an advance or partial payment).",
            )
        if payment == "prepaid":
            return RefundHint(
                action="consider_refund",
                message=f"Returned to origin. {where} This was a prepaid order, so the customer has paid. "
                "Consider starting the refund under your policy (many merchants wait until the parcel is back "
                "and inspected).",
            )
        return RefundHint(
            action="check_payment_mode",
            message=f"Returned to origin. {where} {result.courier.title()} does not show whether the order was COD "
            "or prepaid. Check the order in your own system: prepaid means consider a refund under your policy; "
            "COD usually means nothing to refund.",
        )

    if status is Status.FAILED:
        return RefundHint(
            action="wait",
            message="Delivery attempt failed. Wait for the next delivery attempt, do not cancel yet.",
        )

    if status is Status.DELIVERED:
        return RefundHint(action="none", message="Delivered. No refund action suggested.")

    if status is Status.IN_TRANSIT:
        return RefundHint(action="none", message="In transit. No refund action suggested.")

    return RefundHint(
        action="check_manually",
        message=f"Status unclear (courier says: {result.raw_status or 'nothing'}). "
        "Check the courier page or contact the courier before taking any action.",
    )

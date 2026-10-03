"""The one JSON shape every courier adapter returns."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Status(str, Enum):
    DELIVERED = "delivered"
    IN_TRANSIT = "in_transit"
    RETURNED = "returned"  # returned to origin (RTO) or RTO in progress
    FAILED = "failed"  # delivery attempt failed, shipment still with courier
    UNKNOWN = "unknown"


PaymentMode = Literal["cod", "prepaid", "unknown"]


class TrackingEvent(BaseModel):
    timestamp: datetime | None = None
    location: str | None = None
    description: str
    raw_status: str | None = Field(
        default=None, description="Courier's own status code/text, kept for debugging."
    )


class TrackingResult(BaseModel):
    courier: str
    tracking_id: str
    status: Status
    raw_status: str | None = Field(
        default=None, description="Courier's own latest status, before mapping."
    )
    payment_mode: PaymentMode = "unknown"
    events: list[TrackingEvent] = Field(
        default_factory=list, description="Newest first."
    )
    last_updated: datetime | None = Field(
        default=None, description="Timestamp of the newest event."
    )
    source_url: str
    fetched_at: datetime


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_TRACKING_ID = "INVALID_TRACKING_ID"
    UNSUPPORTED_COURIER = "UNSUPPORTED_COURIER"
    COURIER_UNAVAILABLE = "COURIER_UNAVAILABLE"
    LAYOUT_CHANGED = "LAYOUT_CHANGED"


class ErrorResponse(BaseModel):
    error: ErrorCode
    message: str
    courier: str | None = None
    tracking_id: str | None = None


MAX_BATCH_ITEMS = 20


class BatchItem(BaseModel):
    courier: str
    tracking_id: str


class BatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


class BatchItemResult(BaseModel):
    courier: str
    tracking_id: str
    ok: bool
    result: TrackingResult | None = None
    error: ErrorResponse | None = None


class BatchResponse(BaseModel):
    results: list[BatchItemResult] = Field(description="Same order as the request items.")
    ok: int
    failed: int

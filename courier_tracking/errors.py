"""Typed errors. Each maps to one ErrorCode and one HTTP status in the API."""

from __future__ import annotations

from .schema import ErrorCode


class TrackingError(Exception):
    code: ErrorCode
    http_status: int = 500

    def __init__(self, message: str, *, courier: str | None = None, tracking_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.courier = courier
        self.tracking_id = tracking_id


class NotFoundError(TrackingError):
    """Courier answered, but has no shipment with this ID."""

    code = ErrorCode.NOT_FOUND
    http_status = 404


class InvalidTrackingIdError(TrackingError):
    """ID fails the courier's format check; we never send it upstream."""

    code = ErrorCode.INVALID_TRACKING_ID
    http_status = 422


class UnsupportedCourierError(TrackingError):
    code = ErrorCode.UNSUPPORTED_COURIER
    http_status = 404


class CourierUnavailableError(TrackingError):
    """Site down, timed out, rate limited us, or kept returning 5xx after retries."""

    code = ErrorCode.COURIER_UNAVAILABLE
    http_status = 503


class LayoutDriftError(TrackingError):
    """Response no longer has the shape the adapter expects."""

    code = ErrorCode.LAYOUT_CHANGED
    http_status = 502

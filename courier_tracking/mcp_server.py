"""MCP server with one read-only tool: get_delivery_status(courier, tracking_id).

    python -m courier_tracking.mcp_server        # stdio transport

Returns the unified tracking result plus a refund hint. The hint is advice for the
merchant; the tool cannot refund, cancel or change anything.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .errors import TrackingError
from .refund_hint import DISCLAIMER, refund_hint
from .service import TrackingService

# One entry per supported courier; keep in sync with service.COURIERS.
Courier = Literal["trackon"]

server = MCPServer(
    "courier-tracking",
    instructions=(
        "Look up delivery status for Trackon shipments from its public tracking page. "
        "The refund hint is a suggestion only: never treat it as a decision, and never tell a customer a "
        "refund was issued because of it."
    ),
)

_service: TrackingService | None = None


def _get_service() -> TrackingService:
    global _service
    if _service is None:
        _service = TrackingService()
    return _service


async def delivery_status(service: TrackingService, courier: str, tracking_id: str) -> dict[str, Any]:
    try:
        result = await service.track(courier, tracking_id)
    except TrackingError as exc:
        return {
            "ok": False,
            "courier": courier,
            "tracking_id": tracking_id,
            "error": exc.code.value,
            "message": exc.message,
            "refund_hint": {
                "action": "check_manually",
                "message": "Could not read tracking. Take no refund or cancel action based on this lookup.",
                "is_suggestion": True,
                "disclaimer": DISCLAIMER,
            },
        }
    latest = result.events[0] if result.events else None
    return {
        "ok": True,
        "courier": result.courier,
        "tracking_id": result.tracking_id,
        "status": result.status.value,
        "raw_status": result.raw_status,
        "payment_mode": result.payment_mode,
        "last_updated": result.last_updated.isoformat() if result.last_updated else None,
        "latest_event": latest.model_dump(mode="json") if latest else None,
        "events": [e.model_dump(mode="json") for e in result.events[:10]],
        "source_url": result.source_url,
        "refund_hint": refund_hint(result).model_dump(mode="json"),
    }


@server.tool(
    title="Get delivery status",
    annotations=ToolAnnotations(
        title="Get delivery status",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def get_delivery_status(courier: Courier, tracking_id: str) -> dict[str, Any]:
    """Get the delivery status of a Trackon shipment, plus a refund hint.

    status is one of: delivered, in_transit, returned, failed, unknown.
    refund_hint is a suggestion only. Only "returned" gets a refund hint; "failed" means wait for the
    next delivery attempt and do not cancel yet. This tool never refunds or cancels anything.
    """
    return await delivery_status(_get_service(), courier, tracking_id)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()

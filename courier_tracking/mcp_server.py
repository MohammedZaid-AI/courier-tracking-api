"""MCP server with one read-only tool: get_delivery_status(courier, tracking_id).

    courier-tracking-mcp                     # stdio; looks up the live Trackon page
    courier-tracking-mcp --offline           # stdio; answers from saved fixtures, no network
    COURIER_TRACKING_OFFLINE=1 courier-tracking-mcp    # same, for clients that drop extra arguments
    (python -m courier_tracking.mcp_server works too)

Returns the unified tracking result plus a refund hint. The hint is advice for the
merchant; the tool cannot refund, cancel or change anything.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

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

LIVE_SOURCE = "live: trackon.in public tracking page"

_service: TrackingService | None = None
_data_source = LIVE_SOURCE


def _get_service() -> TrackingService:
    global _service
    if _service is None:
        _service = TrackingService()
    return _service


async def delivery_status(
    service: TrackingService, courier: str, tracking_id: str, data_source: str = LIVE_SOURCE
) -> dict[str, Any]:
    try:
        result = await service.track(courier, tracking_id)
    except TrackingError as exc:
        return {
            "ok": False,
            "data_source": data_source,
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
        "data_source": data_source,
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


TOOL_DESCRIPTION = (
    "Read-only: get the delivery status of a Trackon shipment, plus a refund hint.\n\n"
    "status is one of: delivered, in_transit, returned, failed, unknown.\n"
    'refund_hint is a suggestion only. Only "returned" gets a refund hint; "failed" means wait for the '
    "next delivery attempt and do not cancel yet. This tool never refunds or cancels anything.\n"
    "Errors (unknown ID, bad format, site down, page changed) come back as ok=false with a typed error."
)


@server.tool(
    title="Get delivery status",
    description=TOOL_DESCRIPTION,
    annotations=ToolAnnotations(
        title="Get delivery status",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def get_delivery_status(
    courier: Annotated[Courier, Field(description='Courier name. Only "trackon" is supported.')],
    tracking_id: Annotated[
        str | int,
        Field(description="Trackon AWB / tracking number: 6 to 12 digits. Send it as a string to keep leading zeros."),
    ],
) -> dict[str, Any]:
    """See TOOL_DESCRIPTION (what MCP clients are shown)."""
    # Clients often send digit-only IDs as JSON numbers; accept them rather than fail validation.
    return await delivery_status(_get_service(), courier, str(tracking_id), _data_source)


OFFLINE_ENV = "COURIER_TRACKING_OFFLINE"


def offline_requested(argv: list[str] | None = None) -> bool:
    """--offline flag or COURIER_TRACKING_OFFLINE=1. The env var exists because some MCP clients
    do not forward extra command-line arguments to the server."""
    ap = argparse.ArgumentParser(prog="courier-tracking-mcp", description="MCP server over stdio.")
    ap.add_argument("--offline", action="store_true", help=f"answer from saved fixtures, never the network (or set {OFFLINE_ENV}=1)")
    args = ap.parse_args(argv)
    return args.offline or os.environ.get(OFFLINE_ENV, "").strip().lower() in {"1", "true", "yes"}


def main(argv: list[str] | None = None) -> None:
    global _service, _data_source
    if offline_requested(argv):
        from .offline import DATA_SOURCE, offline_service

        _service, _data_source = offline_service(), DATA_SOURCE
        # httpx would log the fixture requests with trackon.in URLs, which reads like a live call.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        mode = "OFFLINE: answers come from saved fixtures; no network calls"
    else:
        mode = "LIVE: lookups call trackon.in (at most 1 request/second)"
    # stdout carries the MCP protocol, so the mode banner goes to stderr.
    print(f"courier-tracking MCP server starting in {mode}", file=sys.stderr, flush=True)
    server.run("stdio")


if __name__ == "__main__":
    main()

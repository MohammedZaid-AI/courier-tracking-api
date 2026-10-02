"""FastAPI app: one JSON shape for every supported courier.

Run: uvicorn courier_tracking.api:app
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .errors import TrackingError
from .schema import ErrorResponse, TrackingResult
from .service import COURIERS, TrackingService

_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "NOT_FOUND or UNSUPPORTED_COURIER"},
    422: {"model": ErrorResponse, "description": "INVALID_TRACKING_ID"},
    502: {"model": ErrorResponse, "description": "LAYOUT_CHANGED: courier page changed, adapter needs an update"},
    503: {"model": ErrorResponse, "description": "COURIER_UNAVAILABLE: site down, slow or rate limiting us"},
}


def create_app(service: TrackingService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or TrackingService()
        try:
            yield
        finally:
            await app.state.service.aclose()

    app = FastAPI(
        title="Courier Tracking API",
        version=__version__,
        description="Unified JSON over public Indian courier tracking pages (currently Trackon). Demonstration project: see LIMITATIONS.md.",
        lifespan=lifespan,
    )

    @app.exception_handler(TrackingError)
    async def tracking_error(request: Request, exc: TrackingError) -> JSONResponse:
        body = ErrorResponse(error=exc.code, message=exc.message, courier=exc.courier, tracking_id=exc.tracking_id)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))

    @app.get("/health")
    async def health() -> dict:
        """Liveness only. Never calls courier sites."""
        return {"status": "ok", "version": __version__}

    @app.get("/couriers")
    async def couriers() -> list[dict]:
        return [
            {"courier": name, "display_name": cls.display_name, "tracking_id_format": cls.id_hint}
            for name, cls in COURIERS.items()
        ]

    @app.get("/track/{courier}/{tracking_id}", response_model=TrackingResult, responses=_ERROR_RESPONSES)
    async def track(courier: str, tracking_id: str, request: Request) -> TrackingResult:
        return await request.app.state.service.track(courier, tracking_id)

    return app


app = create_app()

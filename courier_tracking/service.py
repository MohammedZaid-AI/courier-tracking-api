"""Courier registry plus one shared polite client and a short result cache."""

from __future__ import annotations

import time
from collections.abc import Callable

from .adapters.base import CourierAdapter
from .adapters.trackon import TrackonAdapter
from .errors import TrackingError, UnsupportedCourierError
from .http import PoliteClient
from .schema import BatchItem, BatchItemResult, BatchResponse, ErrorResponse, TrackingResult

COURIERS: dict[str, type[CourierAdapter]] = {
    "trackon": TrackonAdapter,
}

CACHE_TTL_SECONDS = 300


class TrackingService:
    def __init__(
        self,
        client: PoliteClient | None = None,
        *,
        cache_ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.client = client or PoliteClient()
        self.adapters = {name: cls(self.client) for name, cls in COURIERS.items()}
        self.cache_ttl = cache_ttl
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, TrackingResult]] = {}

    def adapter(self, courier: str) -> CourierAdapter:
        key = courier.strip().lower()
        if key not in self.adapters:
            raise UnsupportedCourierError(
                f"Unsupported courier '{courier}'. Supported: {', '.join(sorted(self.adapters))}",
                courier=courier,
            )
        return self.adapters[key]

    async def track(self, courier: str, tracking_id: str) -> TrackingResult:
        adapter = self.adapter(courier)
        tid = adapter.normalize_id(tracking_id)
        key = (adapter.name, tid)
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < self.cache_ttl:
            return hit[1]
        result = await adapter.track(tid)
        self._cache[key] = (self._clock(), result)
        return result

    async def track_many(self, items: list[BatchItem]) -> BatchResponse:
        """Look up each item on its own: one bad item never fails the batch.

        Items run one after another, so the per-courier rate limit still applies;
        repeated items in one batch are looked up once.
        """
        seen: dict[tuple[str, str], BatchItemResult] = {}
        results = []
        for item in items:
            key = (item.courier.strip().lower(), item.tracking_id.strip().upper())
            if key not in seen:
                try:
                    found = await self.track(item.courier, item.tracking_id)
                    seen[key] = BatchItemResult(courier=item.courier, tracking_id=item.tracking_id, ok=True, result=found)
                except TrackingError as exc:
                    error = ErrorResponse(error=exc.code, message=exc.message, courier=exc.courier, tracking_id=exc.tracking_id)
                    seen[key] = BatchItemResult(courier=item.courier, tracking_id=item.tracking_id, ok=False, error=error)
            results.append(seen[key])
        ok = sum(r.ok for r in results)
        return BatchResponse(results=results, ok=ok, failed=len(results) - ok)

    async def aclose(self) -> None:
        await self.client.aclose()

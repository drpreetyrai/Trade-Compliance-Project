"""FastAPI web layer for the compliance router.

Exposes a small HTTP API plus a static dashboard:

  * ``GET  /``                — serves the monitoring dashboard (static HTML).
  * ``GET  /api/config``      — current in-memory rule configuration.
  * ``POST /api/orders``      — route one order, return the final result (JSON).
  * ``POST /api/orders/stream`` — route one order, streaming each graph-state
    transition as Server-Sent Events for the live dashboard feed.

The router itself stays LLM-free, deterministic, and fully in-memory; this
layer only adapts it to HTTP.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from .config import ComplianceConfig
from .models import TradeOrder
from .router import ComplianceRouter

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Trade Compliance Router", version="1.0.0")

# A single shared, in-memory router instance for the process lifetime.
router = ComplianceRouter(ComplianceConfig.from_env())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/config")
def get_config() -> dict:
    cfg = router.config
    return {
        "crypto_volatility_limit": cfg.crypto_volatility_limit,
        "equity_market_available": sorted(cfg.equity_market_available),
    }


@app.post("/api/orders")
def route_order(payload: dict) -> dict:
    """Route one order and return the final structured result (or 400-style error)."""
    try:
        order = TradeOrder(**payload)
    except ValidationError as exc:
        return {"error": "invalid_order", "detail": exc.errors()}
    result = router.process(order)
    return result.model_dump(mode="json")


@app.post("/api/orders/stream")
def stream_order(payload: dict) -> StreamingResponse:
    """Route one order, streaming each state transition as Server-Sent Events."""
    try:
        order = TradeOrder(**payload)
    except ValidationError as exc:
        # Capture eagerly: the `exc` name is cleared when the except block
        # exits, but the generator below runs lazily when the response streams.
        errors = exc.errors()

        def err_gen():
            yield _sse("error", {"error": "invalid_order", "detail": errors})

        return StreamingResponse(err_gen(), media_type="text/event-stream")

    def event_gen():
        try:
            for event in router.stream(order):
                yield _sse("transition", asdict(event))
            yield _sse("done", {"order_id": order.order_id})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("stream failed for order_id=%s", order.order_id)
            yield _sse("error", {"error": "stream_failed", "detail": str(exc)})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Events frame (``default=str`` guards odd values)."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()

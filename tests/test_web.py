"""Tests for the FastAPI web layer.

These call the endpoint functions directly rather than going through an HTTP
test client, which keeps them independent of starlette/httpx version skew while
still exercising the real request-handling and streaming logic.
"""

from __future__ import annotations

import asyncio

import pytest

from compliance_router import web


def _drain_sse(response):
    """Collect a StreamingResponse's SSE frames into (event, data) tuples.

    Starlette exposes ``body_iterator`` as an async iterator even when the
    response was built from a sync generator, so drain it via asyncio.
    """

    async def _collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return chunks

    frames = []
    for chunk in asyncio.run(_collect()):
        for block in chunk.strip().split("\n\n"):
            event, data = "message", None
            for line in block.splitlines():
                if line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: "):
                    data = line[len("data: "):]
            if data is not None:
                frames.append((event, data))
    return frames


def test_config_endpoint():
    body = web.get_config()
    assert body["crypto_volatility_limit"] == 100_000.0
    assert "AAPL" in body["equity_market_available"]


@pytest.mark.parametrize("order,expected_status,expected_node", [
    ({"order_id": "W1", "asset_class": "crypto", "symbol": "BTC",
      "quantity": 1, "price": 50_000}, "APPROVED", "crypto_compliance"),
    ({"order_id": "W2", "asset_class": "crypto", "symbol": "BTC",
      "quantity": 5, "price": 50_000}, "BLOCKED", "crypto_compliance"),
    ({"order_id": "W3", "asset_class": "equity", "symbol": "AAPL",
      "quantity": 1, "price": 1}, "APPROVED", "equity_compliance"),
    ({"order_id": "W4", "asset_class": "bond", "symbol": "X",
      "quantity": 1, "price": 1}, "BLOCKED", "dead_letter"),
])
def test_route_order_json(order, expected_status, expected_node):
    body = web.route_order(order)
    assert body["status"] == expected_status
    assert body["routed_to"] == expected_node


def test_route_order_invalid_json():
    body = web.route_order({
        "order_id": "B1", "asset_class": "crypto", "symbol": "BTC",
        "quantity": 0, "price": 100,
    })
    assert body["error"] == "invalid_order"


def test_stream_valid_order_emits_transitions_then_done():
    resp = web.stream_order({
        "order_id": "S1", "asset_class": "crypto", "symbol": "BTC",
        "quantity": 1, "price": 2_000,
    })
    events = [e for e, _ in _drain_sse(resp)]
    assert events == ["transition", "transition", "done"]


def test_stream_invalid_order_emits_error_event():
    """Regression: the SSE invalid-order path must emit an error frame, not
    silently die on a NameError when the generator runs lazily (the `exc`
    name is cleared once the except block exits)."""
    resp = web.stream_order({
        "order_id": "S2", "asset_class": "crypto", "symbol": "BTC",
        "quantity": 0, "price": 100,
    })
    frames = _drain_sse(resp)
    assert len(frames) == 1
    event, data = frames[0]
    assert event == "error"
    assert "invalid_order" in data

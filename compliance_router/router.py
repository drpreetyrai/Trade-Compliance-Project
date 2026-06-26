"""The compiled compliance graph and its public router API.

``ComplianceRouter`` wraps a LangGraph ``StateGraph`` compiled with an in-memory
``MemorySaver`` checkpointer. It exposes:

  * :meth:`stream` — a generator yielding structured :class:`StreamEvent`s as
    each node completes, intended to feed a real-time monitoring dashboard.
  * :meth:`process` — a convenience wrapper that drains the stream and returns
    the final :class:`ComplianceResult`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .config import ComplianceConfig
from .models import ComplianceResult, ComplianceStatus, TradeOrder, TradeState
from .nodes import (
    CRYPTO_COMPLIANCE,
    DEAD_LETTER,
    EQUITY_COMPLIANCE,
    INGEST,
    dead_letter,
    ingest,
    make_crypto_compliance,
    make_equity_compliance,
    route_by_asset,
    route_map,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamEvent:
    """A single state-transition event emitted as a node completes."""

    order_id: str
    sequence: int
    node: str
    status: str
    reason: str
    notional: Optional[float]
    timestamp: str


class ComplianceRouter:
    """Deterministic, in-memory trade compliance router."""

    def __init__(self, config: Optional[ComplianceConfig] = None) -> None:
        self._config = config or ComplianceConfig()
        self._checkpointer = MemorySaver()
        self._app = self._build()

    @property
    def config(self) -> ComplianceConfig:
        return self._config

    def _build(self):
        graph = StateGraph(TradeState)

        graph.add_node(INGEST, ingest)
        graph.add_node(CRYPTO_COMPLIANCE, make_crypto_compliance(self._config))
        graph.add_node(EQUITY_COMPLIANCE, make_equity_compliance(self._config))
        graph.add_node(DEAD_LETTER, dead_letter)

        graph.add_edge(START, INGEST)
        graph.add_conditional_edges(INGEST, route_by_asset, route_map())
        graph.add_edge(CRYPTO_COMPLIANCE, END)
        graph.add_edge(EQUITY_COMPLIANCE, END)
        graph.add_edge(DEAD_LETTER, END)

        # In-memory checkpointer — no database is used anywhere.
        return graph.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def stream(self, order: TradeOrder) -> Iterator[StreamEvent]:
        """Stream live state transitions for ``order`` as each node completes.

        Each trade executes on its own checkpointer thread (keyed by order id),
        giving fully isolated, in-memory execution state per order.
        """
        config = {"configurable": {"thread_id": order.order_id}}
        initial: TradeState = {
            "order_id": order.order_id,
            "asset_class": order.asset_class,
            "symbol": order.symbol,
            "quantity": order.quantity,
            "price": order.price,
        }

        logger.info(
            "routing order_id=%s asset_class=%s notional=%.2f",
            order.order_id,
            order.normalized_asset_class,
            order.notional,
        )

        sequence = 0
        for chunk in self._app.stream(initial, config, stream_mode="updates"):
            for node_name, delta in chunk.items():
                sequence += 1
                yield StreamEvent(
                    order_id=order.order_id,
                    sequence=sequence,
                    node=node_name,
                    status=delta.get("status", ""),
                    reason=delta.get("reason", ""),
                    notional=delta.get("notional"),
                    timestamp=self._now_iso(),
                )

    def process(self, order: TradeOrder) -> ComplianceResult:
        """Route ``order`` to completion and return the final result."""
        # Draining the stream guarantees the graph has run to END before we
        # read final state from the checkpointer.
        for _ in self.stream(order):
            pass

        config = {"configurable": {"thread_id": order.order_id}}
        final = self._app.get_state(config).values

        return ComplianceResult(
            order_id=order.order_id,
            asset_class=final.get("asset_class", order.normalized_asset_class),
            symbol=final.get("symbol", order.normalized_symbol),
            notional=final.get("notional", order.notional),
            status=ComplianceStatus(final["status"]),
            reason=final.get("reason", ""),
            routed_to=final.get("routed_to"),
        )

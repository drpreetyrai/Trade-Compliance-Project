"""Demo / CLI entry point: ``python -m compliance_router``.

Streams a batch of representative orders through the router and prints the live
state transitions, mimicking the feed a compliance monitoring dashboard would
consume.
"""

from __future__ import annotations

import logging
import sys
from typing import List, Tuple

from .config import ComplianceConfig
from .models import ComplianceStatus, TradeOrder
from .router import ComplianceRouter


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


# (raw order, expected terminal status) — exercises every routing branch.
SAMPLE_ORDERS: List[Tuple[dict, ComplianceStatus]] = [
    ({"order_id": "C1", "asset_class": "crypto", "symbol": "BTC",
      "quantity": 1, "price": 50_000}, ComplianceStatus.APPROVED),
    ({"order_id": "C2", "asset_class": "crypto", "symbol": "BTC",
      "quantity": 5, "price": 50_000}, ComplianceStatus.BLOCKED),
    ({"order_id": "E1", "asset_class": "equity", "symbol": "AAPL",
      "quantity": 100, "price": 180}, ComplianceStatus.APPROVED),
    ({"order_id": "E2", "asset_class": "equity", "symbol": "ZZZZ",
      "quantity": 100, "price": 10}, ComplianceStatus.BLOCKED),
    ({"order_id": "F1", "asset_class": "forex", "symbol": "EURUSD",
      "quantity": 1000, "price": 1.1}, ComplianceStatus.BLOCKED),
]


def main(argv: List[str] | None = None) -> int:
    _configure_logging()
    router = ComplianceRouter(ComplianceConfig.from_env())

    failures = 0
    for raw, expected in SAMPLE_ORDERS:
        try:
            order = TradeOrder(**raw)
        except Exception as exc:  # malformed order -> reject deterministically
            print(f"\n=== order {raw.get('order_id')} REJECTED (invalid): {exc}")
            failures += 1
            continue

        print(f"\n=== Streaming order {order.order_id} "
              f"({order.normalized_asset_class}) ===")
        terminal = None
        for event in router.stream(order):
            print(f"  #{event.sequence} [{event.node}] "
                  f"{event.status:<8} {event.reason}")
            terminal = event  # last event is the terminal compliance decision

        final_status = ComplianceStatus(terminal.status) if terminal else None
        marker = "OK" if final_status is expected else "MISMATCH"
        node = terminal.node if terminal else "?"
        print(f"  -> FINAL: {final_status.value if final_status else '?'} "
              f"via {node} [{marker}]")
        if final_status is not expected:
            failures += 1

    print(f"\nProcessed {len(SAMPLE_ORDERS)} orders, {failures} unexpected outcome(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

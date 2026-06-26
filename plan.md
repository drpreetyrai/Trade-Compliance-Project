# Plan: Financial Trade Compliance Router (LangGraph)

Low-latency, deterministic trade compliance router. No LLM on the decision path,
no database — all routing rules are explicit/programmatic and all state lives in-memory.

## 1. Project setup
- Single module `compliance_router.py`.
- Deps: `langgraph`, `langchain-core` (typing only). See `requirements.txt`.
- Python 3.11+.

## 2. Graph state (`TradeState` TypedDict)
- `order_id`, `asset_class`, `symbol`, `quantity`, `price`
- `notional` (computed = quantity * price)
- `status` ("PENDING" | "APPROVED" | "BLOCKED"), `reason`, `routed_to`

## 3. Nodes (deterministic, no LLM)
- `ingest` — normalize order, compute `notional`, set `status="PENDING"`.
- `crypto_compliance` — block if `notional > 100_000` (volatility limit), else approve.
- `equity_compliance` — market-availability check against in-memory allow-list.
- `dead_letter` — fallback: always BLOCKED for unrecognized asset class.

## 4. Routing (programmatic conditional edge)
- `route_by_asset(state)` returns next node by `asset_class`:
  - "crypto" -> `crypto_compliance`
  - "equity" -> `equity_compliance`
  - default  -> `dead_letter`
- `START -> ingest`; conditional edges from `ingest`; each compliance node -> `END`.

## 5. In-memory checkpointer
- `MemorySaver()` passed to `graph.compile(checkpointer=...)`.
- Per-trade `thread_id` in config for isolated state threads.

## 6. Real-time streaming
- `app.stream(order, config, stream_mode="updates")` — print each node's state
  delta as it completes (the compliance dashboard feed).

## 7. Demo driver
- Sample orders covering every path: crypto-pass, crypto-block, equity-pass,
  equity-block, unknown-asset (dead_letter).

## 8. Verification
- Assert final status per sample to prove all branches + fallback deterministically.

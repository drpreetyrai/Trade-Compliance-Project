"""Unit tests for the compliance router."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compliance_router import (
    ComplianceConfig,
    ComplianceRouter,
    ComplianceStatus,
    TradeOrder,
)
from compliance_router.nodes import (
    CRYPTO_COMPLIANCE,
    DEAD_LETTER,
    EQUITY_COMPLIANCE,
)


@pytest.fixture()
def router() -> ComplianceRouter:
    return ComplianceRouter(
        ComplianceConfig(
            crypto_volatility_limit=100_000.0,
            equity_market_available=frozenset({"AAPL", "MSFT"}),
        )
    )


def _order(**overrides) -> TradeOrder:
    base = dict(order_id="O1", asset_class="crypto", symbol="BTC",
                quantity=1, price=50_000)
    base.update(overrides)
    return TradeOrder(**base)


# --- Routing outcomes -------------------------------------------------------


def test_crypto_within_limit_is_approved(router: ComplianceRouter) -> None:
    result = router.process(_order(order_id="C1", quantity=1, price=50_000))
    assert result.status is ComplianceStatus.APPROVED
    assert result.routed_to == CRYPTO_COMPLIANCE


def test_crypto_over_limit_is_blocked(router: ComplianceRouter) -> None:
    result = router.process(_order(order_id="C2", quantity=5, price=50_000))
    assert result.status is ComplianceStatus.BLOCKED
    assert result.routed_to == CRYPTO_COMPLIANCE


def test_crypto_exactly_at_limit_is_approved(router: ComplianceRouter) -> None:
    # Boundary: notional == limit is allowed (strictly greater is blocked).
    result = router.process(_order(order_id="C3", quantity=1, price=100_000))
    assert result.status is ComplianceStatus.APPROVED


def test_equity_available_is_approved(router: ComplianceRouter) -> None:
    result = router.process(
        _order(order_id="E1", asset_class="equity", symbol="AAPL",
               quantity=100, price=180)
    )
    assert result.status is ComplianceStatus.APPROVED
    assert result.routed_to == EQUITY_COMPLIANCE


def test_equity_unavailable_is_blocked(router: ComplianceRouter) -> None:
    result = router.process(
        _order(order_id="E2", asset_class="equity", symbol="ZZZZ",
               quantity=10, price=10)
    )
    assert result.status is ComplianceStatus.BLOCKED


def test_unknown_asset_class_routes_to_dead_letter(router: ComplianceRouter) -> None:
    result = router.process(
        _order(order_id="F1", asset_class="forex", symbol="EURUSD",
               quantity=1000, price=1.1)
    )
    assert result.status is ComplianceStatus.BLOCKED
    assert result.routed_to == DEAD_LETTER


# --- Normalization & determinism -------------------------------------------


def test_asset_class_and_symbol_are_normalized(router: ComplianceRouter) -> None:
    result = router.process(
        _order(order_id="N1", asset_class="  Equity ", symbol=" aapl ",
               quantity=1, price=1)
    )
    assert result.symbol == "AAPL"
    assert result.routed_to == EQUITY_COMPLIANCE


def test_routing_is_deterministic(router: ComplianceRouter) -> None:
    order = _order(order_id="D1", quantity=5, price=50_000)
    first = router.process(order)
    second = router.process(order)
    assert first.status is second.status is ComplianceStatus.BLOCKED


# --- Streaming --------------------------------------------------------------


def test_stream_emits_ingest_then_terminal_node(router: ComplianceRouter) -> None:
    events = list(router.stream(_order(order_id="S1", quantity=1, price=1)))
    nodes = [e.node for e in events]
    assert nodes[0] == "ingest"
    assert nodes[-1] == CRYPTO_COMPLIANCE
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    dict(quantity=0),
    dict(price=-1),
    dict(order_id=""),
    dict(asset_class=""),
])
def test_invalid_orders_are_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        _order(**bad)


# --- Config -----------------------------------------------------------------


def test_config_rejects_nonpositive_limit() -> None:
    with pytest.raises(ValueError):
        ComplianceConfig(crypto_volatility_limit=0)


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYPTO_VOLATILITY_LIMIT", "250000")
    monkeypatch.setenv("EQUITY_MARKET_AVAILABLE", "spy, qqq")
    cfg = ComplianceConfig.from_env()
    assert cfg.crypto_volatility_limit == 250_000.0
    assert cfg.equity_market_available == frozenset({"SPY", "QQQ"})

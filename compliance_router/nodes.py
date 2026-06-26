"""Graph nodes and routing logic.

Every node and the router function are pure, deterministic Python — no LLM and
no I/O on the decision path. Nodes are constructed via a factory so the
in-memory :class:`ComplianceConfig` is bound by closure rather than read from
global state, which keeps them testable and thread-safe.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

from .config import ComplianceConfig
from .models import AssetClass, ComplianceStatus, TradeState

logger = logging.getLogger(__name__)

# Node name constants — single source of truth for wiring and routing.
INGEST = "ingest"
CRYPTO_COMPLIANCE = "crypto_compliance"
EQUITY_COMPLIANCE = "equity_compliance"
DEAD_LETTER = "dead_letter"


def ingest(state: TradeState) -> TradeState:
    """Normalize the raw order and compute derived fields."""
    notional = float(state.get("quantity", 0.0)) * float(state.get("price", 0.0))
    asset_class = str(state.get("asset_class", "")).strip().lower()
    symbol = str(state.get("symbol", "")).strip().upper()
    logger.debug("ingest order_id=%s notional=%.2f", state.get("order_id"), notional)
    return {
        "asset_class": asset_class,
        "symbol": symbol,
        "notional": notional,
        "status": ComplianceStatus.RECEIVED.value,
        "reason": "Order received and normalized; routing to compliance.",
    }


def make_crypto_compliance(config: ComplianceConfig) -> Callable[[TradeState], TradeState]:
    """Build the crypto volatility-limit node bound to ``config``."""

    limit = config.crypto_volatility_limit

    def crypto_compliance(state: TradeState) -> TradeState:
        notional = state["notional"]
        if notional > limit:
            return {
                "status": ComplianceStatus.BLOCKED.value,
                "reason": (
                    f"Crypto volatility limit exceeded: notional ${notional:,.2f} "
                    f"> ${limit:,.2f}."
                ),
                "routed_to": CRYPTO_COMPLIANCE,
            }
        return {
            "status": ComplianceStatus.APPROVED.value,
            "reason": (
                f"Crypto trade within volatility limit (notional ${notional:,.2f})."
            ),
            "routed_to": CRYPTO_COMPLIANCE,
        }

    return crypto_compliance


def make_equity_compliance(config: ComplianceConfig) -> Callable[[TradeState], TradeState]:
    """Build the equity market-availability node bound to ``config``."""

    universe = config.equity_market_available

    def equity_compliance(state: TradeState) -> TradeState:
        symbol = state["symbol"]
        if symbol in universe:
            return {
                "status": ComplianceStatus.APPROVED.value,
                "reason": f"Equity {symbol} is available for trading.",
                "routed_to": EQUITY_COMPLIANCE,
            }
        return {
            "status": ComplianceStatus.BLOCKED.value,
            "reason": f"Equity {symbol} is not available in the current market.",
            "routed_to": EQUITY_COMPLIANCE,
        }

    return equity_compliance


def dead_letter(state: TradeState) -> TradeState:
    """Fallback node: auto-block any unrecognized asset class."""
    logger.warning(
        "dead_letter order_id=%s asset_class=%s",
        state.get("order_id"),
        state.get("asset_class"),
    )
    return {
        "status": ComplianceStatus.BLOCKED.value,
        "reason": (
            f"Unrecognized asset class '{state.get('asset_class')}' "
            "— automatically blocked."
        ),
        "routed_to": DEAD_LETTER,
    }


def route_by_asset(state: TradeState) -> str:
    """Deterministic routing decision keyed on the normalized asset class."""
    asset_class = state.get("asset_class", "")
    if asset_class == AssetClass.CRYPTO.value:
        return CRYPTO_COMPLIANCE
    if asset_class == AssetClass.EQUITY.value:
        return EQUITY_COMPLIANCE
    return DEAD_LETTER


def route_map() -> Dict[str, str]:
    """Mapping of router return values to node names (identity, for clarity)."""
    return {
        CRYPTO_COMPLIANCE: CRYPTO_COMPLIANCE,
        EQUITY_COMPLIANCE: EQUITY_COMPLIANCE,
        DEAD_LETTER: DEAD_LETTER,
    }

"""Domain models for the trade compliance router.

External inputs (raw trade orders) are validated with Pydantic at the boundary
so malformed orders are rejected deterministically before they ever touch the
graph. The internal graph state is a lightweight ``TypedDict`` for minimal
per-step overhead on the latency-sensitive path.
"""

from __future__ import annotations

import enum
from typing import Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field, computed_field


class AssetClass(str, enum.Enum):
    """Recognized asset classes. Anything else routes to the dead-letter node."""

    CRYPTO = "crypto"
    EQUITY = "equity"


class ComplianceStatus(str, enum.Enum):
    """Lifecycle status of a trade as it moves through compliance."""

    RECEIVED = "RECEIVED"  # ingested/normalized, awaiting a compliance decision
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class TradeOrder(BaseModel):
    """A raw, externally-supplied trade order (validated at the boundary)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(min_length=1, description="Unique client order id.")
    asset_class: str = Field(min_length=1, description="Asset class, e.g. 'crypto'.")
    symbol: str = Field(min_length=1, description="Instrument symbol, e.g. 'BTC'.")
    quantity: float = Field(gt=0, description="Order quantity, must be positive.")
    price: float = Field(gt=0, description="Order price, must be positive.")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def notional(self) -> float:
        """Notional exposure of the order."""
        return self.quantity * self.price

    @property
    def normalized_asset_class(self) -> str:
        return self.asset_class.strip().lower()

    @property
    def normalized_symbol(self) -> str:
        return self.symbol.strip().upper()


class TradeState(TypedDict, total=False):
    """Internal graph execution state (kept lightweight for low latency)."""

    order_id: str
    asset_class: str
    symbol: str
    quantity: float
    price: float
    notional: float
    status: str
    reason: str
    routed_to: str


class ComplianceResult(BaseModel):
    """Final, structured outcome of routing a single trade through the graph."""

    order_id: str
    asset_class: str
    symbol: str
    notional: float
    status: ComplianceStatus
    reason: str
    routed_to: Optional[str] = None

    @property
    def approved(self) -> bool:
        return self.status is ComplianceStatus.APPROVED

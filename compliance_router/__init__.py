"""Low-latency, deterministic financial trade compliance router (LangGraph).

Public API:

    >>> from compliance_router import ComplianceRouter, TradeOrder
    >>> router = ComplianceRouter()
    >>> result = router.process(TradeOrder(
    ...     order_id="C1", asset_class="crypto", symbol="BTC",
    ...     quantity=1, price=50_000))
    >>> result.status
    <ComplianceStatus.APPROVED: 'APPROVED'>
"""

from __future__ import annotations

from .config import ComplianceConfig
from .models import (
    AssetClass,
    ComplianceResult,
    ComplianceStatus,
    TradeOrder,
)
from .router import ComplianceRouter, StreamEvent

__all__ = [
    "AssetClass",
    "ComplianceConfig",
    "ComplianceResult",
    "ComplianceRouter",
    "ComplianceStatus",
    "StreamEvent",
    "TradeOrder",
]

__version__ = "1.0.0"

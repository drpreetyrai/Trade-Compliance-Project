"""In-memory compliance configuration.

All configuration lives in-memory (no database). Values can be overridden via
environment variables so the same image can be promoted across environments
without code changes, but defaults are sane for local/demo use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import FrozenSet

# Sentinel default market universe. In production this set would be hydrated
# from an upstream market-data feed at startup and refreshed in-memory; it is
# never read from a database on the hot path.
_DEFAULT_EQUITY_UNIVERSE = frozenset(
    {"AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "META", "NVDA"}
)


@dataclass(frozen=True)
class ComplianceConfig:
    """Immutable, in-memory compliance rule configuration.

    Frozen so rules cannot be mutated mid-flight, which keeps routing
    deterministic and auditable for the lifetime of a router instance.
    """

    crypto_volatility_limit: float = 100_000.0
    equity_market_available: FrozenSet[str] = field(
        default_factory=lambda: _DEFAULT_EQUITY_UNIVERSE
    )

    def __post_init__(self) -> None:
        if self.crypto_volatility_limit <= 0:
            raise ValueError("crypto_volatility_limit must be positive")

    @classmethod
    def from_env(cls) -> "ComplianceConfig":
        """Build configuration from environment variables, falling back to defaults.

        Recognized variables:
          * ``CRYPTO_VOLATILITY_LIMIT`` — float notional ceiling for crypto.
          * ``EQUITY_MARKET_AVAILABLE`` — comma-separated tradable symbols.
        """
        limit_raw = os.getenv("CRYPTO_VOLATILITY_LIMIT")
        limit = float(limit_raw) if limit_raw else cls.crypto_volatility_limit

        universe_raw = os.getenv("EQUITY_MARKET_AVAILABLE")
        if universe_raw:
            universe = frozenset(
                s.strip().upper() for s in universe_raw.split(",") if s.strip()
            )
        else:
            universe = _DEFAULT_EQUITY_UNIVERSE

        return cls(crypto_volatility_limit=limit, equity_market_available=universe)

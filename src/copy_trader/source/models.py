"""
source/models.py

Normalized internal source position model per API-CONTRACTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class SourcePosition:
    """
    Normalized representation of a Hyperliquid wallet position.

    - size > 0 means long
    - size < 0 means short
    - size == 0 means flat

    entry_price may be None for newly opened positions with no fill yet.
    """

    symbol: str           # Binance-normalised symbol, e.g. "BTCUSDT"
    side: str             # "long" | "short" | "flat"
    size: Decimal         # signed quantity in base asset units (e.g. BTC)
    entry_price: Optional[Decimal]
    source_timestamp: datetime  # from Hyperliquid response top-level `time`

    def is_flat(self) -> bool:
        return self.size == Decimal(0)


@dataclass(frozen=True)
class SourceSnapshot:
    """
    The full result of one Hyperliquid poll cycle.

    positions: only symbols eligible for reconciliation (mapped + whitelisted).
    fetched_at: local UTC time the HTTP response was received.
    """

    positions: dict[str, SourcePosition]  # keyed by Binance symbol
    fetched_at: datetime
    wallet: str

    def get(self, symbol: str) -> Optional[SourcePosition]:
        return self.positions.get(symbol)

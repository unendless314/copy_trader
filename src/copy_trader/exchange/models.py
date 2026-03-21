"""
exchange/models.py

Normalized internal exchange position and price models per API-CONTRACTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ActualPosition:
    """
    Normalized Binance perpetual position.

    - size > 0 means long (positionAmt > 0)
    - size < 0 means short (positionAmt < 0)
    - size == 0 means flat
    """

    symbol: str
    side: str             # "long" | "short" | "flat"
    size: Decimal         # signed; matches Binance positionAmt semantics
    entry_price: Optional[Decimal]
    binance_timestamp: Optional[datetime]

    def is_flat(self) -> bool:
        return self.size == Decimal(0)


@dataclass(frozen=True)
class PriceSnapshot:
    """
    Reference and executable prices for one symbol.

    reference_price: Binance mark price (from /fapi/v1/premiumIndex).
    bid_price / ask_price: from /fapi/v1/ticker/bookTicker.

    Executable price is side-dependent:
      - buy  → ask_price
      - sell → bid_price
    """

    symbol: str
    reference_price: Decimal   # mark price
    bid_price: Decimal
    ask_price: Decimal
    fetched_at: datetime

    def executable_price_for_buy(self) -> Decimal:
        return self.ask_price

    def executable_price_for_sell(self) -> Decimal:
        return self.bid_price


@dataclass(frozen=True)
class SymbolFilters:
    """
    Binance trading-rule filters for one symbol, loaded from /fapi/v1/exchangeInfo.

    All sizes are in base asset units (e.g. BTC).
    Effective values are the stricter of LOT_SIZE and MARKET_LOT_SIZE.
    """

    symbol: str
    step_size: Decimal      # stricter of LOT_SIZE.stepSize and MARKET_LOT_SIZE.stepSize
    min_qty: Decimal        # stricter of minQty across both filters
    max_qty: Decimal        # stricter (lower) of maxQty across both filters
    min_notional: Decimal   # from MIN_NOTIONAL filter

"""
exchange/precision.py

Loads symbol trading-rule filters from Binance /fapi/v1/exchangeInfo
and computes the effective (strictest) filter values per API-CONTRACTS.md.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from copy_trader.exchange.models import SymbolFilters

logger = logging.getLogger(__name__)


class FilterLoadError(ValueError):
    """Raised when required symbol filters cannot be resolved from exchangeInfo."""


def parse_symbol_filters(exchange_info: dict[str, Any], symbol: str) -> SymbolFilters:
    """
    Extract and validate trading-rule filters for `symbol` from the exchangeInfo response.

    Filter combination rules (API-CONTRACTS.md):
      - effective step_size = stricter (larger) of LOT_SIZE.stepSize and MARKET_LOT_SIZE.stepSize
      - effective min_qty   = stricter (larger) of the two minQty values
      - effective max_qty   = stricter (smaller) of the two maxQty values
      - min_notional uses the MIN_NOTIONAL filter value

    Returns:
        SymbolFilters with pre-computed effective values.
    Raises:
        FilterLoadError if any required filter is missing.
    """
    symbols_data: list[dict] = exchange_info.get("symbols", [])
    sym_info = next((s for s in symbols_data if s.get("symbol") == symbol), None)
    if sym_info is None:
        raise FilterLoadError(f"Symbol '{symbol}' not found in exchangeInfo response.")

    filters_raw: list[dict] = sym_info.get("filters", [])
    filters_by_type: dict[str, dict] = {f["filterType"]: f for f in filters_raw}

    lot = _require_filter(filters_by_type, "LOT_SIZE", symbol)
    market_lot = _require_filter(filters_by_type, "MARKET_LOT_SIZE", symbol)
    min_notional_filter = _require_filter(filters_by_type, "MIN_NOTIONAL", symbol)

    lot_step = _d(lot, "stepSize", symbol, "LOT_SIZE")
    lot_min = _d(lot, "minQty", symbol, "LOT_SIZE")
    lot_max = _d(lot, "maxQty", symbol, "LOT_SIZE")

    mkt_step = _d(market_lot, "stepSize", symbol, "MARKET_LOT_SIZE")
    mkt_min = _d(market_lot, "minQty", symbol, "MARKET_LOT_SIZE")
    mkt_max = _d(market_lot, "maxQty", symbol, "MARKET_LOT_SIZE")

    min_notional_val = _d(min_notional_filter, "notional", symbol, "MIN_NOTIONAL")

    return SymbolFilters(
        symbol=symbol,
        step_size=max(lot_step, mkt_step),        # larger step = stricter
        min_qty=max(lot_min, mkt_min),             # larger min  = stricter
        max_qty=min(lot_max, mkt_max),             # smaller max = stricter
        min_notional=min_notional_val,
    )


def round_down_to_step(quantity: Decimal, step_size: Decimal) -> Decimal:
    """
    Round quantity toward zero to the nearest step_size multiple.

    Example: quantity=0.0173, step_size=0.001 → 0.017
    """
    if step_size <= 0:
        return quantity
    steps = (quantity.copy_abs() / step_size).to_integral_value(rounding="ROUND_DOWN")
    rounded = steps * step_size
    return rounded if quantity >= 0 else -rounded


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_filter(filters: dict[str, dict], filter_type: str, symbol: str) -> dict:
    f = filters.get(filter_type)
    if f is None:
        raise FilterLoadError(
            f"Required filter '{filter_type}' not found for symbol '{symbol}' in exchangeInfo."
        )
    return f


def _d(f: dict, key: str, symbol: str, filter_type: str) -> Decimal:
    value = f.get(key)
    if value is None:
        raise FilterLoadError(
            f"Filter '{filter_type}' for '{symbol}' missing required field '{key}'."
        )
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise FilterLoadError(
            f"Cannot parse field '{key}' in filter '{filter_type}' for '{symbol}': {value!r}"
        ) from exc

"""
strategy/risk_policy.py

Stepwise convergence and notional cap enforcement per DECISION-ENGINE.md §Stepwise Convergence
and CONFIG-SCHEMA.md risk fields.
"""

from __future__ import annotations

from decimal import Decimal

from copy_trader.config.models import RiskConfig
from copy_trader.exchange.models import PriceSnapshot, SymbolFilters
from copy_trader.exchange.precision import round_down_to_step


def apply_convergence_cap(
    raw_delta: Decimal,
    reference_price: Decimal,
    risk: RiskConfig,
    filters: SymbolFilters,
) -> Decimal:
    """
    Cap the proposed order size using the stricter of:
      1. max_single_rebalance_notional_usdt / reference_price → max qty
      2. abs(raw_delta) * max_delta_convergence_ratio

    Returns the capped, step-rounded quantity (always positive; sign is caller's concern).
    """
    abs_delta = abs(raw_delta)

    # Cap 1: notional cap
    notional_cap_qty = Decimal(str(risk.max_single_rebalance_notional_usdt)) / reference_price

    # Cap 2: fractional convergence cap
    convergence_cap_qty = abs_delta * Decimal(str(risk.max_delta_convergence_ratio))

    # Apply the stricter (smaller) cap
    capped = min(abs_delta, notional_cap_qty, convergence_cap_qty)

    # Round down to step size
    capped = round_down_to_step(capped, filters.step_size)

    return capped


def is_tradable(
    capped_qty: Decimal,
    reference_price: Decimal,
    risk: RiskConfig,
    filters: SymbolFilters,
) -> bool:
    """
    Return True if capped_qty satisfies all Binance minimum tradability requirements
    and the configured min_rebalance_notional threshold.

    Checks (in order per API-CONTRACTS.md §Market Order Tradability Calculation):
      4. quantity >= min_qty
      5. quantity <= max_qty
      6. abs(qty * mark_price) >= MIN_NOTIONAL
      + configured min_rebalance_notional_usdt
    """
    if capped_qty <= Decimal(0):
        return False
    if capped_qty < filters.min_qty:
        return False
    if capped_qty > filters.max_qty:
        return False

    notional = capped_qty * reference_price
    if notional < filters.min_notional:
        return False
    if notional < Decimal(str(risk.min_rebalance_notional_usdt)):
        return False

    return True


def exceeds_drift_threshold(
    abs_delta: Decimal,
    actual_size: Decimal,
    reference_price: Decimal,
    risk: RiskConfig,
) -> bool:
    """
    Return True if the delta is large enough to warrant rebalancing.

    Uses the stricter of:
      - min_rebalance_pct: abs_delta / abs(actual) >= min_rebalance_pct
      - min_rebalance_notional_usdt: abs_delta * mark_price >= min_rebalance_notional_usdt

    If actual_size is zero, only the notional threshold applies.
    """
    notional = abs_delta * reference_price
    notional_ok = notional >= Decimal(str(risk.min_rebalance_notional_usdt))

    if actual_size == Decimal(0):
        return notional_ok

    pct_drift = abs_delta / abs(actual_size)
    pct_ok = pct_drift >= Decimal(str(risk.min_rebalance_pct))

    return notional_ok or pct_ok

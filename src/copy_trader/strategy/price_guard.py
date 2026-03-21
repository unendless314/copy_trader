"""
strategy/price_guard.py

Price-deviation guard per SPEC.md §5 and CONFIG-SCHEMA.md.

Blocks execution when the Binance executable price deviates from the
mark price by more than max_deviation_bps basis points.

V1 rules:
  - reference_price = mark_price from /fapi/v1/premiumIndex
  - executable_price is side-dependent: buy→ask, sell→bid
  - if blocked, skip current cycle, retry next cycle, emit warning
  - do not auto-relax the threshold
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from copy_trader.config.models import PriceGuardConfig
from copy_trader.exchange.models import PriceSnapshot


@dataclass(frozen=True)
class PriceGuardResult:
    passed: bool
    deviation_bps: Decimal
    reference_price: Decimal
    executable_price: Decimal
    threshold_bps: int


def evaluate_price_guard(
    price_snapshot: PriceSnapshot,
    is_buy: bool,
    cfg: PriceGuardConfig,
) -> PriceGuardResult:
    """
    Evaluate whether the executable price is within the configured deviation limit.

    Args:
        price_snapshot: Current Binance mark + bid/ask prices.
        is_buy:         True if the intended order is a buy; False for sell.
        cfg:            PriceGuardConfig from the loaded AppConfig.

    Returns:
        PriceGuardResult with .passed indicating whether execution is allowed.
    """
    reference = price_snapshot.reference_price
    executable = (
        price_snapshot.executable_price_for_buy()
        if is_buy
        else price_snapshot.executable_price_for_sell()
    )

    if reference == Decimal(0):
        # Defensive: cannot compute BPS against zero reference; block.
        return PriceGuardResult(
            passed=False,
            deviation_bps=Decimal("99999"),
            reference_price=reference,
            executable_price=executable,
            threshold_bps=cfg.max_deviation_bps,
        )

    deviation_bps = abs((executable - reference) / reference * Decimal(10000))
    passed = not cfg.enabled or deviation_bps <= Decimal(str(cfg.max_deviation_bps))

    return PriceGuardResult(
        passed=passed,
        deviation_bps=deviation_bps,
        reference_price=reference,
        executable_price=executable,
        threshold_bps=cfg.max_deviation_bps,
    )

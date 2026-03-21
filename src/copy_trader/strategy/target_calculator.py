"""
strategy/target_calculator.py

Computes target_size from source_size and copy_ratio per DECISION-ENGINE.md.

copy_ratio is applied to the signed quantity (size) of the source position,
preserving direction. This is the API-CONTRACTS.md-specified behaviour:
  target_size = source_size * copy_ratio
where source_size is the Hyperliquid `szi` field (signed, in base asset units).
"""

from __future__ import annotations

from decimal import Decimal


def compute_target_size(source_size: Decimal, copy_ratio: float) -> Decimal:
    """
    Return the desired signed Binance position size.

    Args:
        source_size: Signed quantity from SourcePosition.size (positive=long, negative=short).
        copy_ratio:  Configured multiplier (must be > 0).

    Returns:
        Signed target size in the same base asset units as source_size.
    """
    return source_size * Decimal(str(copy_ratio))


def compute_delta(target_size: Decimal, actual_size: Decimal) -> Decimal:
    """
    Return the signed delta between target and actual.

    Positive delta means we need more exposure (buy more / cover more short).
    Negative delta means we have excess exposure (sell / short more).
    """
    return target_size - actual_size

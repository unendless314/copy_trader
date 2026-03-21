"""
config/validation.py

Cross-field validation rules from CONFIG-SCHEMA.md that cannot be
expressed as simple per-field pydantic constraints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from copy_trader.config.models import AppConfig


class ConfigValidationError(ValueError):
    """Raised when the loaded configuration fails validation."""


def validate_config(cfg: "AppConfig") -> None:
    """Run all cross-field validation rules. Raises ConfigValidationError on failure."""

    errors: list[str] = []

    # Rule: armed/live requires sqlite_enabled
    if cfg.runtime.mode.value in ("armed", "live") and not cfg.runtime.sqlite_enabled:
        errors.append(f"runtime.sqlite_enabled must be true when mode is '{cfg.runtime.mode.value}'")

    # Rule: freshness_timeout >= poll_interval
    if cfg.source.freshness_timeout_seconds < cfg.source.poll_interval_seconds:
        errors.append("source.freshness_timeout_seconds must be >= source.poll_interval_seconds")

    # Rule: position_mode must be ONEWAY in V1
    if cfg.binance.position_mode != "ONEWAY":
        errors.append("binance.position_mode must be 'ONEWAY' in V1")

    # Rule: order_type must be MARKET in V1
    if cfg.execution.order_type != "MARKET":
        errors.append("execution.order_type must be 'MARKET' in V1")

    # Rule: flip_behavior must be CLOSE_THEN_OPEN in V1
    if cfg.execution.flip_behavior != "CLOSE_THEN_OPEN":
        errors.append("execution.flip_behavior must be 'CLOSE_THEN_OPEN' in V1")

    # Rule: max_orders_per_cycle should be 1 in V1
    if cfg.risk.max_orders_per_cycle != 1:
        errors.append("risk.max_orders_per_cycle must be 1 in V1")

    # Rule: symbols whitelist must be non-empty
    if not cfg.copy_trade.symbols.whitelist:
        errors.append("copy_trade.symbols.whitelist must contain at least one symbol")

    # Note: observe -> live transition is enforced as operator workflow requirement
    # (see RUNTIME-STATE-MACHINE.md), not as startup technical guard.
    # See walkthrough.md for rationale.

    if errors:
        raise ConfigValidationError("Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

"""
strategy/decision_types.py

Decision type enumerations per DECISION-ENGINE.md.
"""

from __future__ import annotations

from enum import Enum


class DecisionType(str, Enum):
    # No-op
    NO_ACTION = "NO_ACTION"

    # Blockers / skips
    SKIP_SOURCE_STALE = "SKIP_SOURCE_STALE"
    SKIP_SYMBOL_DISABLED = "SKIP_SYMBOL_DISABLED"
    SKIP_COOLDOWN = "SKIP_COOLDOWN"
    SKIP_DATA_UNAVAILABLE = "SKIP_DATA_UNAVAILABLE"
    SKIP_BELOW_THRESHOLD = "SKIP_BELOW_THRESHOLD"
    SKIP_PRICE_GUARD = "SKIP_PRICE_GUARD"

    # Rebalance actions
    REBALANCE_INCREASE = "REBALANCE_INCREASE"
    REBALANCE_REDUCE = "REBALANCE_REDUCE"
    REBALANCE_CLOSE = "REBALANCE_CLOSE"
    REBALANCE_FLIP_CLOSE = "REBALANCE_FLIP_CLOSE"
    REBALANCE_FLIP_OPEN = "REBALANCE_FLIP_OPEN"

    # Error
    ERROR = "ERROR"

    def is_executable(self) -> bool:
        """Return True if this decision type should result in an order being placed."""
        return self in (
            DecisionType.REBALANCE_INCREASE,
            DecisionType.REBALANCE_REDUCE,
            DecisionType.REBALANCE_CLOSE,
            DecisionType.REBALANCE_FLIP_CLOSE,
            DecisionType.REBALANCE_FLIP_OPEN,
        )

    def is_skip(self) -> bool:
        return self.value.startswith("SKIP_")

    def counts_as_execution_failure(self) -> bool:
        """
        Return True if this outcome should increment the live execution failure counter.
        Per EPHEMERAL-STATE.md: NO_ACTION, SKIP_*, read failures, price-guard do NOT count.
        """
        return self is DecisionType.ERROR

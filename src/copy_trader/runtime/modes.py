"""
runtime/modes.py

Runtime mode definitions and allowed transition rules
per RUNTIME-STATE-MACHINE.md.
"""

from __future__ import annotations

from copy_trader.config.models import RuntimeMode


# Allowed state transitions (directed graph).
# observe -> live is intentionally excluded to force at least one armed stage.
ALLOWED_TRANSITIONS: dict[RuntimeMode, set[RuntimeMode]] = {
    RuntimeMode.observe: {RuntimeMode.armed},
    RuntimeMode.armed: {RuntimeMode.observe, RuntimeMode.live},
    RuntimeMode.live: {RuntimeMode.observe, RuntimeMode.armed},
}


class InvalidModeTransitionError(ValueError):
    """Raised when a disallowed mode transition is attempted."""


def validate_transition(current: RuntimeMode, target: RuntimeMode) -> None:
    """
    Assert that transitioning from current to target mode is allowed.

    Raises InvalidModeTransitionError if the transition is blocked.
    """
    if target == current:
        return  # no-op transition is always allowed
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidModeTransitionError(
            f"Mode transition '{current.value}' -> '{target.value}' is not allowed in V1. "
            f"Allowed targets from '{current.value}': "
            f"{sorted(m.value for m in allowed) or 'none'}."
        )


def mode_allows_sqlite(mode: RuntimeMode) -> bool:
    """Return True if this mode should write to SQLite."""
    return mode in (RuntimeMode.armed, RuntimeMode.live)


def mode_allows_execution(mode: RuntimeMode) -> bool:
    """Return True if this mode may place Binance orders."""
    return mode is RuntimeMode.live

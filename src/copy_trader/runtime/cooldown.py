"""
runtime/cooldown.py

Per-symbol cooldown manager per EPHEMERAL-STATE.md.

Rules:
- State is in-memory only; resets on restart.
- Cooldown is set only after a live Binance order is accepted.
- Cooldown is NOT set in observe/armed modes or when an order fails before acceptance.
"""

from __future__ import annotations

from datetime import datetime, timezone


class CooldownManager:
    """Tracks when each symbol is next eligible for a live rebalance."""

    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown_seconds = cooldown_seconds
        # symbol -> earliest datetime at which the symbol is eligible again
        self._cooldown_until: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_cooling_down(self, symbol: str) -> bool:
        """Return True if the symbol is still within its cooldown window."""
        until = self._cooldown_until.get(symbol)
        if until is None:
            return False
        return self._now() < until

    def record_execution(self, symbol: str) -> None:
        """
        Call this after a live Binance order is accepted to start the cooldown.
        Must NOT be called for skipped, blocked, or failed orders.
        """
        from datetime import timedelta

        self._cooldown_until[symbol] = self._now() + timedelta(seconds=self._cooldown_seconds)

    def time_remaining_seconds(self, symbol: str) -> float:
        """Return seconds remaining in cooldown (0.0 if not cooling)."""
        until = self._cooldown_until.get(symbol)
        if until is None:
            return 0.0
        remaining = (until - self._now()).total_seconds()
        return max(0.0, remaining)

    def clear(self, symbol: str) -> None:
        """Manually clear a symbol's cooldown (e.g. after a mode downgrade)."""
        self._cooldown_until.pop(symbol, None)

    def clear_all(self) -> None:
        """Clear all cooldowns."""
        self._cooldown_until.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now(tz=timezone.utc)

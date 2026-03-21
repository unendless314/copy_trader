"""
logging/events.py

JSON Lines structured event emitter per LOGGING-FORMAT.md.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from copy_trader.config.models import RuntimeMode

_root_logger = logging.getLogger("copy_trader")


def _now_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cycle_counter():
    n = 0
    while True:
        n += 1
        yield n


_counter = _cycle_counter()


class EventLogger:
    """Emits structured JSON Lines log events per LOGGING-FORMAT.md."""

    def __init__(self, runtime_mode: RuntimeMode) -> None:
        self._mode = runtime_mode
        self._cycle_id: str = "unset"

    def update_mode(self, new_mode: RuntimeMode) -> None:
        """
        Update the mode reported in all subsequent log events.
        Must be called by the loop immediately after any mode transition
        (including auto-downgrade) to keep the JSON Lines audit trail accurate.
        """
        self._mode = new_mode

    def new_cycle_id(self) -> str:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        n = next(_counter)
        self._cycle_id = f"{ts}-{n:03d}"
        return self._cycle_id

    # ------------------------------------------------------------------
    # Standard events
    # ------------------------------------------------------------------

    def cycle_started(self, cycle_id: str, mode: RuntimeMode) -> None:
        self._emit("INFO", "cycle_started", "runtime.loop",
                   message="Cycle started", cycle_id=cycle_id, runtime_mode=mode.value)

    def mode_changed(self, from_mode: RuntimeMode, to_mode: RuntimeMode, reason: str) -> None:
        self._emit("WARNING", "mode_changed", "runtime.loop",
                   message=f"Mode changed: {from_mode.value} → {to_mode.value}",
                   from_mode=from_mode.value, to_mode=to_mode.value, reason=reason)

    def decision(self, record: Any) -> None:
        """Emit a decision event from a DecisionRecord."""
        from copy_trader.strategy.reconciliation import DecisionRecord
        if not isinstance(record, DecisionRecord):
            return
        level = "WARNING" if record.decision_type.is_skip() else "INFO"
        self._emit(level, "decision", "strategy.reconciliation",
                   message="Decision computed",
                   symbol=record.symbol,
                   source_size=str(record.source_size),
                   target_size=str(record.target_size),
                   actual_size=str(record.actual_size),
                   delta_size=str(record.raw_delta_size),
                   decision=record.decision_type.value,
                   block_reason=record.block_reason,
                   reference_price=str(record.reference_price) if record.reference_price else None,
                   executable_price=str(record.executable_price) if record.executable_price else None,
                   price_deviation_bps=str(record.price_deviation_bps) if record.price_deviation_bps else None,
                   proposed_order_qty=str(record.capped_delta_size),
                   )

    def warning(self, warning_code: str, message: str, symbol: Optional[str] = None,
                reason: Optional[str] = None, **extra) -> None:
        self._emit("WARNING", "warning", "runtime",
                   message=message, warning_code=warning_code,
                   symbol=symbol, reason=reason, **extra)

    def error(self, error_code: str, message: str, symbol: Optional[str] = None,
              exception_type: Optional[str] = None, stacktrace: Optional[str] = None,
              **extra) -> None:
        self._emit("ERROR", "error", "runtime",
                   message=message, error_code=error_code,
                   symbol=symbol, exception_type=exception_type,
                   stacktrace=stacktrace, **extra)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, level: str, event_type: str, component: str,
              message: str, cycle_id: Optional[str] = None, **kwargs) -> None:
        record = {
            "ts": _now_utc(),
            "level": level,
            "event_type": event_type,
            "component": component,
            "cycle_id": cycle_id or self._cycle_id,
            "runtime_mode": self._mode.value,
            "message": message,
        }
        record.update({k: v for k, v in kwargs.items() if v is not None})

        line = json.dumps(record, default=str)
        py_level = getattr(logging, level, logging.INFO)
        _root_logger.log(py_level, line)

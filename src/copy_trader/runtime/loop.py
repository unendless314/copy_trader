"""
runtime/loop.py

Main polling loop and ephemeral runtime state container
per RUNTIME-STATE-MACHINE.md and EPHEMERAL-STATE.md.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from copy_trader.config.models import AppConfig, RuntimeMode
from copy_trader.execution.flip_handler import execute_decision_with_flip
from copy_trader.execution.models import (
    ExecutionError,
    ExecutionRejectError,
    LocalValidationError,
    UnknownStatusError,
)
from copy_trader.runtime.cooldown import CooldownManager
from copy_trader.runtime.modes import mode_allows_execution, mode_allows_sqlite
from copy_trader.strategy.decision_types import DecisionType

logger = logging.getLogger(__name__)



@dataclass
class RuntimeEphemeralState:
    """
    In-memory runtime state per EPHEMERAL-STATE.md.

    Resets on process restart. Must never be persisted to SQLite
    or used as authoritative trading state.
    """

    cooldown_until_by_symbol: dict = field(default_factory=dict)  # managed by CooldownManager
    consecutive_live_execution_failures: int = 0


class PollingLoop:
    """
    Drives the periodic reconciliation cycle.

    Wiring is injected via constructor to keep modules decoupled and testable.
    Concrete source/exchange/strategy/storage/execution dependencies are
    passed in from app/service.py.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._mode = cfg.runtime.mode
        self._ephemeral = RuntimeEphemeralState()
        self._cooldown = CooldownManager(cfg.execution.symbol_cooldown_seconds)
        self._running = False

        # Injected collaborators (set by app/service.py before calling run())
        self.source_reader = None
        self.binance_gateway = None
        self.decision_engine = None
        self.sqlite_store = None
        self.executor = None
        self.event_logger = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the polling loop. Runs until stop() is called or process exits."""
        self._running = True
        logger.info("Polling loop starting in mode=%s", self._mode.value)

        while self._running:
            try:
                await self._run_cycle()
            except Exception as exc:
                logger.exception("Unhandled exception in cycle: %s", exc)
            finally:
                await asyncio.sleep(self.cfg.source.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    @property
    def cooldown(self) -> CooldownManager:
        return self._cooldown

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self) -> None:
        """
        Execute one reconciliation cycle per RUNTIME-STATE-MACHINE.md:

        1. Load source snapshot
        2. Validate freshness
        3. Load Binance positions
        4. Load Binance reference and executable prices
        5. Normalize data
        6. Compute target and delta
        7. Evaluate thresholds and guards
        8. Produce a decision
        9. Persist to SQLite if mode is armed or live
        10. Execute only if mode is live and decision allows it
        """
        if self.event_logger:
            cycle_id = self.event_logger.new_cycle_id()
            self.event_logger.cycle_started(cycle_id, self._mode)
        else:
            cycle_id = "unset"

        # Steps 1–8: delegate to the orchestration in app/service.py
        # This loop owns mode gating only; domain logic lives in strategy/ and source/.
        decisions = await self._collect_decisions(cycle_id)

        for decision in decisions:
            # Step 9: persist (respect observability.persist_decisions flag)
            if (
                mode_allows_sqlite(self._mode)
                and self.sqlite_store
                and self.cfg.observability.persist_decisions
            ):
                try:
                    await self.sqlite_store.persist_decision(decision)
                except Exception as exc:
                    logger.warning("SQLite write failed (non-fatal): %s", exc)

            # Step 10: execute — only for actionable decision types
            if (
                mode_allows_execution(self._mode)
                and self.executor
                and decision.decision_type.is_executable()
            ):
                await self._execute(decision, cycle_id)

    async def _collect_decisions(self, cycle_id: str) -> list:
        """
        Fetch snapshots and run the decision engine.
        Returns a list of decision records (one per symbol).
        Placeholder until source/exchange/strategy are wired in Epic 6.
        """
        # TODO (Epic 3-6): plug in source_reader, binance_gateway, decision_engine
        return []

    async def _execute(self, decision, cycle_id: str) -> None:
        """
        Submit an order for a decision that passes all gates.
        Updates the auto-downgrade failure counter per ERROR-TAXONOMY.md.
        """
        if decision is None or not hasattr(decision, "decision_type"):
            return

        result = None
        exception_occurred = None

        try:
            result = await execute_decision_with_flip(self.executor, decision)
            
            if result.accepted:
                # Successful execution: reset failure counter and set cooldown
                self._ephemeral.consecutive_live_execution_failures = 0
                self._cooldown.record_execution(decision.symbol)
            else:
                self._handle_execution_failure(decision, result.error_message or "Execution not accepted")
        
        except LocalValidationError as exc:
            logger.error("Local validation error for %s: %s", decision.symbol, exc)
            exception_occurred = exc
            # Local issues do not trigger exchange failure / auto-downgrade
        except (ExecutionRejectError, UnknownStatusError, ExecutionError) as exc:
            logger.error("Execution exception for %s: %s", decision.symbol, exc, exc_info=True)
            self._handle_execution_failure(decision, exc)
            exception_occurred = exc
        except Exception as exc:
            logger.error("Unexpected execution error for %s: %s", decision.symbol, exc, exc_info=True)
            self._handle_execution_failure(decision, exc)
            exception_occurred = exc
        finally:
            if mode_allows_sqlite(self._mode) and self.sqlite_store and self.cfg.observability.persist_execution_results:
                try:
                    if result:
                        await self.sqlite_store.persist_execution_result(
                            cycle_id=cycle_id,
                            symbol=result.symbol,
                            action=result.side,
                            requested_size=result.requested_size,
                            submitted_size=result.submitted_size,
                            status=result.status,
                            exchange_order_id=result.exchange_order_id,
                            error_message=result.error_message,
                        )
                    elif exception_occurred:
                        if decision.decision_type == DecisionType.REBALANCE_FLIP_CLOSE:
                            is_buy = decision.actual_size < 0
                            side = "BUY" if is_buy else "SELL"
                            qty_str = str(min(abs(decision.actual_size), abs(decision.capped_delta_size)))
                        else:
                            is_buy = decision.capped_delta_size > 0
                            side = "BUY" if is_buy else "SELL"
                            qty_str = str(abs(decision.capped_delta_size))

                        db_status = "REJECTED" if isinstance(exception_occurred, ExecutionRejectError) else "ERROR"
                        if isinstance(exception_occurred, LocalValidationError):
                            db_status = "LOCAL_ERROR"
                        elif isinstance(exception_occurred, UnknownStatusError):
                            db_status = "UNKNOWN"

                        await self.sqlite_store.persist_execution_result(
                            cycle_id=cycle_id,
                            symbol=decision.symbol,
                            action=side,
                            requested_size=qty_str,
                            submitted_size=None,
                            status=db_status,
                            exchange_order_id=None,
                            error_message=str(exception_occurred),
                        )
                except Exception as db_exc:
                    logger.warning("Failed to persist execution result: %s", db_exc)

    def _handle_execution_failure(self, decision, error) -> None:
        """Increment failure counter and trigger auto-downgrade if threshold is reached."""
        self._ephemeral.consecutive_live_execution_failures += 1
        count = self._ephemeral.consecutive_live_execution_failures
        logger.error(
            "Live execution failure #%d for %s: %s",
            count,
            getattr(decision, "symbol", "?"),
            error,
        )

        threshold = self.cfg.runtime.auto_downgrade_threshold
        if self.cfg.runtime.auto_downgrade_enabled and count >= threshold:
            self._trigger_auto_downgrade()

    def _trigger_auto_downgrade(self) -> None:
        """Downgrade from live to armed per RUNTIME-STATE-MACHINE.md."""
        prev_count = self._ephemeral.consecutive_live_execution_failures
        self._mode = RuntimeMode.armed
        self._ephemeral.consecutive_live_execution_failures = 0

        # Sync the event logger BEFORE emitting the mode_changed event
        # so the event itself is tagged with the new mode (armed), not live.
        if self.event_logger:
            self.event_logger.update_mode(RuntimeMode.armed)
            self.event_logger.mode_changed(RuntimeMode.live, RuntimeMode.armed, "auto_downgrade")

        logger.critical(
            "AUTO-DOWNGRADE TRIGGERED: %d consecutive live execution failures. "
            "Switched from 'live' to 'armed'. "
            "Restart with runtime.mode=live after resolving the issue.",
            prev_count,
        )

        if self.cfg.observability.terminal_warnings:
            import sys
            print(f"⚠️  AUTO-DOWNGRADE TRIGGERED: {prev_count} consecutive live execution failures. Switched from 'live' to 'armed'.", file=sys.stderr)

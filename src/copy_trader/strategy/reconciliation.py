"""
strategy/reconciliation.py

Stateless reconciliation engine per DECISION-ENGINE.md.

The engine receives fresh source and Binance snapshots on every call.
It applies evaluation rules in the specified order and returns one
DecisionRecord per symbol. It never reads from SQLite and never stores state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from copy_trader.config.models import AppConfig, RuntimeMode
from copy_trader.exchange.models import ActualPosition, PriceSnapshot, SymbolFilters
from copy_trader.runtime.cooldown import CooldownManager
from copy_trader.source.models import SourcePosition
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.price_guard import PriceGuardResult, evaluate_price_guard
from copy_trader.strategy.risk_policy import (
    apply_convergence_cap,
    exceeds_drift_threshold,
    is_tradable,
)
from copy_trader.strategy.target_calculator import compute_delta, compute_target_size

logger = logging.getLogger(__name__)


@dataclass
class DecisionRecord:
    """
    Structured output of one reconciliation evaluation.
    Maps to the Decision Output Contract in DECISION-ENGINE.md.
    Also matches the reconciliation_decisions SQLite schema in SPEC.md.
    """

    cycle_id: str
    runtime_mode: str
    symbol: str

    source_size: Decimal
    target_size: Decimal
    actual_size: Decimal
    raw_delta_size: Decimal
    capped_delta_size: Decimal

    decision_type: DecisionType
    block_reason: Optional[str]

    reference_price: Optional[Decimal]
    executable_price: Optional[Decimal]
    price_deviation_bps: Optional[Decimal]

    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


class ReconciliationEngine:
    """
    Stateless per-symbol decision engine.

    All inputs are passed per call; no instance state is used in decisions.
    The engine never places orders — it only returns DecisionRecord objects.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def evaluate(
        self,
        symbol: str,
        source_position: Optional[SourcePosition],
        actual_position: ActualPosition,
        price_snapshot: Optional[PriceSnapshot],
        filters: SymbolFilters,
        cooldown: CooldownManager,
        is_source_fresh: bool,
        cycle_id: str,
        runtime_mode: RuntimeMode,
    ) -> DecisionRecord:
        """
        Apply DECISION-ENGINE.md evaluation rules in order and return a DecisionRecord.

        Evaluation order:
          1. Source freshness
          2. Symbol eligibility
          3. Runtime cooldown
          4. Delta calculation
          5. Tradability threshold
          6. Drift threshold
          7. Direction relationship
          8. Stepwise convergence limits
          9. Price guard
          10. Final action selection
        """
        cfg = self._cfg
        risk = cfg.risk

        source_size = source_position.size if source_position else Decimal(0)
        actual_size = actual_position.size
        reference_price = price_snapshot.reference_price if price_snapshot else None

        def _skip(reason: DecisionType, block_reason: str) -> DecisionRecord:
            return DecisionRecord(
                cycle_id=cycle_id,
                runtime_mode=runtime_mode.value,
                symbol=symbol,
                source_size=source_size,
                target_size=Decimal(0),
                actual_size=actual_size,
                raw_delta_size=Decimal(0),
                capped_delta_size=Decimal(0),
                decision_type=reason,
                block_reason=block_reason,
                reference_price=reference_price,
                executable_price=None,
                price_deviation_bps=None,
            )

        # --- Rule 1: Source freshness ---
        if not is_source_fresh:
            return _skip(DecisionType.SKIP_SOURCE_STALE, "source_timestamp_stale")

        # --- Rule 2: Symbol eligibility ---
        whitelist = set(cfg.copy_trade.symbols.whitelist)
        blacklist = set(cfg.copy_trade.symbols.blacklist)
        if symbol not in whitelist or symbol in blacklist:
            return _skip(DecisionType.SKIP_SYMBOL_DISABLED, "symbol_not_eligible")

        # --- Rule 3: Cooldown ---
        if cooldown.is_cooling_down(symbol):
            return _skip(DecisionType.SKIP_COOLDOWN, f"cooldown_active_{cooldown.time_remaining_seconds(symbol):.1f}s")

        # --- Rule 4: Delta calculation ---
        target_size = compute_target_size(source_size, cfg.copy_trade.copy_ratio)
        raw_delta = compute_delta(target_size, actual_size)

        # Early exit: delta is exactly zero → already perfectly aligned, no order needed.
        # Must be checked BEFORE is_tradable / convergence-cap to avoid incorrectly
        # returning SKIP_BELOW_THRESHOLD when both source and actual are flat.
        if raw_delta == Decimal(0):
            return DecisionRecord(
                cycle_id=cycle_id,
                runtime_mode=runtime_mode.value,
                symbol=symbol,
                source_size=source_size,
                target_size=target_size,
                actual_size=actual_size,
                raw_delta_size=Decimal(0),
                capped_delta_size=Decimal(0),
                decision_type=DecisionType.NO_ACTION,
                block_reason=None,
                reference_price=reference_price,
                executable_price=None,
                price_deviation_bps=None,
            )

        # --- Price snapshot guard (needed for rules 5, 9) ---
        if price_snapshot is None:
            return _skip(DecisionType.SKIP_DATA_UNAVAILABLE, "price_snapshot_missing")

        # --- Rule 5 + 8: Tradability + convergence cap ---
        # Determine order direction first (needed for price guard side selection)
        is_buy = raw_delta > Decimal(0)

        # apply_convergence_cap() returns an absolute executable quantity.
        # The signed order intent must be restored from raw_delta afterward.
        capped_qty_abs = apply_convergence_cap(
            raw_delta=raw_delta,
            reference_price=reference_price,
            risk=risk,
            filters=filters,
        )

        if not is_tradable(capped_qty_abs, reference_price, risk, filters):
            return DecisionRecord(
                cycle_id=cycle_id,
                runtime_mode=runtime_mode.value,
                symbol=symbol,
                source_size=source_size,
                target_size=target_size,
                actual_size=actual_size,
                raw_delta_size=raw_delta,
                capped_delta_size=Decimal(0),
                decision_type=DecisionType.SKIP_BELOW_THRESHOLD,
                block_reason="not_tradable_after_cap",
                reference_price=reference_price,
                executable_price=None,
                price_deviation_bps=None,
            )

        capped_qty = capped_qty_abs if raw_delta > Decimal(0) else -capped_qty_abs

        # --- Rule 6: Drift threshold ---
        if not exceeds_drift_threshold(abs(raw_delta), actual_size, reference_price, risk):
            return DecisionRecord(
                cycle_id=cycle_id,
                runtime_mode=runtime_mode.value,
                symbol=symbol,
                source_size=source_size,
                target_size=target_size,
                actual_size=actual_size,
                raw_delta_size=raw_delta,
                capped_delta_size=capped_qty,
                decision_type=DecisionType.SKIP_BELOW_THRESHOLD,
                block_reason="below_drift_threshold",
                reference_price=reference_price,
                executable_price=None,
                price_deviation_bps=None,
            )

        # --- Rule 9: Price guard ---
        pg_result: PriceGuardResult = evaluate_price_guard(price_snapshot, is_buy, cfg.binance.price_guard)
        executable_price = pg_result.executable_price

        if not pg_result.passed:
            return DecisionRecord(
                cycle_id=cycle_id,
                runtime_mode=runtime_mode.value,
                symbol=symbol,
                source_size=source_size,
                target_size=target_size,
                actual_size=actual_size,
                raw_delta_size=raw_delta,
                capped_delta_size=capped_qty,
                decision_type=DecisionType.SKIP_PRICE_GUARD,
                block_reason=f"deviation_{pg_result.deviation_bps:.2f}_bps_exceeds_{pg_result.threshold_bps}_bps",
                reference_price=reference_price,
                executable_price=executable_price,
                price_deviation_bps=pg_result.deviation_bps,
            )

        # --- Rule 7 + 10: Direction relationship → final action ---
        decision_type = self._select_action(target_size, actual_size, raw_delta)

        return DecisionRecord(
            cycle_id=cycle_id,
            runtime_mode=runtime_mode.value,
            symbol=symbol,
            source_size=source_size,
            target_size=target_size,
            actual_size=actual_size,
            raw_delta_size=raw_delta,
            capped_delta_size=capped_qty,
            decision_type=decision_type,
            block_reason=None,
            reference_price=reference_price,
            executable_price=executable_price,
            price_deviation_bps=pg_result.deviation_bps,
        )

    # ------------------------------------------------------------------
    # Internal: action selection (Rule 7 logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _select_action(
        target_size: Decimal,
        actual_size: Decimal,
        raw_delta: Decimal,
    ) -> DecisionType:
        """
        Determine the action category from DECISION-ENGINE.md Rule Table.

        This is called only after all blockers have passed.
        Flip detection is based purely on the current sign of target vs actual.
        """
        ZERO = Decimal(0)

        # Rule 1: Already aligned (should be caught by drift threshold, but guard here too)
        if raw_delta == ZERO:
            return DecisionType.NO_ACTION

        target_long = target_size > ZERO
        target_short = target_size < ZERO
        target_flat = target_size == ZERO

        actual_long = actual_size > ZERO
        actual_short = actual_size < ZERO
        actual_flat = actual_size == ZERO

        # Rule 3: Reduce to flat
        if target_flat and not actual_flat:
            return DecisionType.REBALANCE_CLOSE

        # Rule 2: Flat to new position
        if actual_flat and not target_flat:
            return DecisionType.REBALANCE_INCREASE

        # Rule 6: Opposite direction → flip required
        if (actual_long and target_short) or (actual_short and target_long):
            # Phase 1: current position still has old direction → close first
            # Phase 2 (FLIP_OPEN) is detected when actual is flat on a subsequent cycle
            # (Per EPHEMERAL-STATE.md: flip phase is not tracked via a flag)
            return DecisionType.REBALANCE_FLIP_CLOSE

        # Same direction
        if abs(target_size) > abs(actual_size):
            return DecisionType.REBALANCE_INCREASE   # Rule 4
        else:
            return DecisionType.REBALANCE_REDUCE     # Rule 5

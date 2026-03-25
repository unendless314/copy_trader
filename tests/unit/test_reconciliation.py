"""
tests/unit/test_reconciliation.py

Unit tests for the stateless reconciliation engine.
Covers all DECISION-ENGINE.md rule scenarios.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from copy_trader.config.models import AppConfig, RuntimeMode
from copy_trader.exchange.models import ActualPosition, PriceSnapshot, SymbolFilters
from copy_trader.runtime.cooldown import CooldownManager
from copy_trader.source.models import SourcePosition
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.reconciliation import ReconciliationEngine

SYMBOL = "BTCUSDT"
NOW = datetime.now(tz=timezone.utc)


def _make_cfg(**overrides) -> AppConfig:
    base = {
        "runtime": {"mode": "observe"},
        "copy_trade": {"copy_ratio": 0.01},
        "risk": {
            "max_single_rebalance_notional_usdt": 10000,
            "max_delta_convergence_ratio": 1.0,
            "min_rebalance_pct": 0.001,
            "min_rebalance_notional_usdt": 1,
        },
        "binance": {"price_guard": {"enabled": False}},
    }
    base.update(overrides)
    return AppConfig.model_validate(base)


def _source(size: str) -> SourcePosition:
    sz = Decimal(size)
    return SourcePosition(
        symbol=SYMBOL,
        side="long" if sz > 0 else ("short" if sz < 0 else "flat"),
        size=sz,
        entry_price=Decimal("80000"),
        source_timestamp=NOW,
    )


def _actual(size: str) -> ActualPosition:
    sz = Decimal(size)
    return ActualPosition(
        symbol=SYMBOL,
        side="long" if sz > 0 else ("short" if sz < 0 else "flat"),
        size=sz,
        entry_price=None,
        binance_timestamp=NOW,
    )


def _price(reference: str = "80000") -> PriceSnapshot:
    ref = Decimal(reference)
    return PriceSnapshot(
        symbol=SYMBOL,
        reference_price=ref,
        bid_price=ref - Decimal("1"),
        ask_price=ref + Decimal("1"),
        fetched_at=NOW,
    )


def _filters() -> SymbolFilters:
    return SymbolFilters(
        symbol=SYMBOL,
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("1000"),
        min_notional=Decimal("5"),
    )


def _evaluate(source_size: str, actual_size: str, cfg: AppConfig | None = None) -> DecisionType:
    cfg = cfg or _make_cfg()
    engine = ReconciliationEngine(cfg)
    cooldown = CooldownManager(30)
    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source(source_size),
        actual_position=_actual(actual_size),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=cooldown,
        is_source_fresh=True,
        cycle_id="test-001",
        runtime_mode=RuntimeMode.observe,
    )
    return rec.decision_type


# ---------------------------------------------------------------------------
# Blocker tests
# ---------------------------------------------------------------------------


def test_skip_source_stale():
    cfg = _make_cfg()
    engine = ReconciliationEngine(cfg)
    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source("10"),
        actual_position=_actual("0"),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=CooldownManager(30),
        is_source_fresh=False,
        cycle_id="test",
        runtime_mode=RuntimeMode.observe,
    )
    assert rec.decision_type == DecisionType.SKIP_SOURCE_STALE


def test_skip_cooldown():
    cfg = _make_cfg()
    engine = ReconciliationEngine(cfg)
    cooldown = CooldownManager(30)
    cooldown.record_execution(SYMBOL)

    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source("10"),
        actual_position=_actual("0"),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=cooldown,
        is_source_fresh=True,
        cycle_id="test",
        runtime_mode=RuntimeMode.live,
    )
    assert rec.decision_type == DecisionType.SKIP_COOLDOWN


# ---------------------------------------------------------------------------
# DECISION-ENGINE.md scenario tests
# ---------------------------------------------------------------------------


def test_scenario_a_small_long_drift():
    """Source 10 BTC, ratio 0.01 → target 0.10 BTC, actual 0.08 → INCREASE."""
    cfg = _make_cfg(**{"copy_trade": {"copy_ratio": 0.01}})
    # source_size in the engine is szi * copy_ratio for target
    # Let's set source_size=10, so target=0.10, actual=0.08
    cfg2 = AppConfig.model_validate({
        "runtime": {"mode": "observe"},
        "copy_trade": {"copy_ratio": 0.01},
        "risk": {
            "max_single_rebalance_notional_usdt": 10000,
            "max_delta_convergence_ratio": 1.0,
            "min_rebalance_pct": 0.001,
            "min_rebalance_notional_usdt": 1,
        },
        "binance": {"price_guard": {"enabled": False}},
    })
    assert _evaluate("10", "0.08", cfg2) == DecisionType.REBALANCE_INCREASE


def test_scenario_b_overexposed_long():
    """Source 10 BTC, ratio 0.01 → target 0.10 BTC, actual 0.14 → REDUCE."""
    assert _evaluate("10", "0.14") == DecisionType.REBALANCE_REDUCE


def test_reduce_keeps_negative_capped_delta():
    cfg = _make_cfg(
        **{
            "copy_trade": {"copy_ratio": 0.01},
            "risk": {
                "max_single_rebalance_notional_usdt": 1000,
                "max_delta_convergence_ratio": 1.0,
                "min_rebalance_pct": 0.001,
                "min_rebalance_notional_usdt": 1,
            },
        }
    )
    engine = ReconciliationEngine(cfg)

    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source("10"),
        actual_position=_actual("0.14"),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=CooldownManager(30),
        is_source_fresh=True,
        cycle_id="test",
        runtime_mode=RuntimeMode.observe,
    )

    assert rec.decision_type == DecisionType.REBALANCE_REDUCE
    assert rec.raw_delta_size < 0
    assert rec.capped_delta_size < 0


def test_short_overexposed_reduce_keeps_positive_capped_delta():
    engine = ReconciliationEngine(_make_cfg())

    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source("-10"),
        actual_position=_actual("-0.14"),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=CooldownManager(30),
        is_source_fresh=True,
        cycle_id="test",
        runtime_mode=RuntimeMode.observe,
    )

    assert rec.decision_type == DecisionType.REBALANCE_REDUCE
    assert rec.raw_delta_size > 0
    assert rec.capped_delta_size > 0


def test_short_to_flat_close_keeps_positive_capped_delta():
    engine = ReconciliationEngine(_make_cfg())

    rec = engine.evaluate(
        symbol=SYMBOL,
        source_position=_source("0"),
        actual_position=_actual("-0.05"),
        price_snapshot=_price(),
        filters=_filters(),
        cooldown=CooldownManager(30),
        is_source_fresh=True,
        cycle_id="test",
        runtime_mode=RuntimeMode.observe,
    )

    assert rec.decision_type == DecisionType.REBALANCE_CLOSE
    assert rec.raw_delta_size > 0
    assert rec.capped_delta_size > 0


def test_scenario_c_source_flat_binance_long():
    """Source flat→ target 0, actual 0.05 → CLOSE."""
    assert _evaluate("0", "0.05") == DecisionType.REBALANCE_CLOSE


def test_scenario_d_flip_long_to_short_phase1():
    """Source flips to short: target -0.10, actual +0.08 → FLIP_CLOSE."""
    assert _evaluate("-10", "0.08") == DecisionType.REBALANCE_FLIP_CLOSE


def test_flat_to_new_long():
    """Actual flat, target long → INCREASE (Rule 2)."""
    assert _evaluate("10", "0") == DecisionType.REBALANCE_INCREASE


def test_no_action_already_aligned():
    """source 0, actual 0 → NO_ACTION (delta=0)."""
    assert _evaluate("0", "0") == DecisionType.NO_ACTION

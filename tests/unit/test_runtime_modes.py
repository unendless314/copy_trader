"""
tests/unit/test_runtime_modes.py

Unit tests for mode transition rules and cooldown manager.
"""

from __future__ import annotations

import time

import pytest

from copy_trader.config.models import RuntimeMode
from copy_trader.runtime.cooldown import CooldownManager
from copy_trader.runtime.modes import (
    InvalidModeTransitionError,
    mode_allows_execution,
    mode_allows_sqlite,
    validate_transition,
)


# ---------------------------------------------------------------------------
# Mode transition tests
# ---------------------------------------------------------------------------


def test_observe_to_armed_allowed():
    validate_transition(RuntimeMode.observe, RuntimeMode.armed)


def test_armed_to_live_allowed():
    validate_transition(RuntimeMode.armed, RuntimeMode.live)


def test_live_to_armed_allowed():
    validate_transition(RuntimeMode.live, RuntimeMode.armed)


def test_observe_to_live_blocked():
    with pytest.raises(InvalidModeTransitionError):
        validate_transition(RuntimeMode.observe, RuntimeMode.live)


def test_same_mode_is_noop():
    validate_transition(RuntimeMode.live, RuntimeMode.live)  # should not raise


def test_mode_allows_sqlite():
    assert not mode_allows_sqlite(RuntimeMode.observe)
    assert mode_allows_sqlite(RuntimeMode.armed)
    assert mode_allows_sqlite(RuntimeMode.live)


def test_mode_allows_execution():
    assert not mode_allows_execution(RuntimeMode.observe)
    assert not mode_allows_execution(RuntimeMode.armed)
    assert mode_allows_execution(RuntimeMode.live)


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


def test_cooldown_initially_false():
    cm = CooldownManager(30)
    assert not cm.is_cooling_down("BTCUSDT")


def test_cooldown_active_after_execution():
    cm = CooldownManager(30)
    cm.record_execution("BTCUSDT")
    assert cm.is_cooling_down("BTCUSDT")


def test_cooldown_zero_seconds_not_cooling():
    cm = CooldownManager(0)
    cm.record_execution("BTCUSDT")
    # 0-second cooldown expires immediately
    assert not cm.is_cooling_down("BTCUSDT")


def test_cooldown_per_symbol_independent():
    cm = CooldownManager(60)
    cm.record_execution("BTCUSDT")
    assert cm.is_cooling_down("BTCUSDT")
    assert not cm.is_cooling_down("ETHUSDT")


def test_cooldown_clear():
    cm = CooldownManager(60)
    cm.record_execution("BTCUSDT")
    cm.clear("BTCUSDT")
    assert not cm.is_cooling_down("BTCUSDT")

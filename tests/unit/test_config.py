"""
tests/unit/test_config.py

Unit tests for config loading, validation, and cross-field rules.

Note on exception handling:
  AppConfig.model_validate() is called by Pydantic and wraps any ValueError
  raised inside model_validators (including ConfigValidationError) in a
  pydantic.ValidationError. Tests that exercise model_validate() directly
  must therefore catch pydantic.ValidationError, not ConfigValidationError.
  Only load_config() helpers that raise ConfigValidationError outside of
  model_validate (e.g. _require_env) can be caught as ConfigValidationError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError as PydanticValidationError

from copy_trader.config.loader import load_config
from copy_trader.config.models import AppConfig, RuntimeMode
from copy_trader.config.validation import ConfigValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


def _write_env(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(
        "BINANCE_API_KEY=test_key\n"
        "BINANCE_API_SECRET=test_secret\n"
        "HYPERLIQUID_TARGET_WALLET=0xdeadbeef\n"
    )
    return p




# ---------------------------------------------------------------------------
# Test: load_config happy path
# ---------------------------------------------------------------------------


def test_load_config_defaults(tmp_path, monkeypatch):
    # Explicitly set all three vars in the process environment so the test is
    # not affected by shell state or load_dotenv(override=False) ambiguity.
    monkeypatch.setenv("BINANCE_API_KEY", "test_key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test_secret")
    monkeypatch.setenv("HYPERLIQUID_TARGET_WALLET", "0xdeadbeef")

    data = {"runtime": {"mode": "observe"}}
    config_path = _write_yaml(tmp_path, data)
    # Pass a non-existent env file so load_dotenv is a no-op;
    # the vars above come directly from monkeypatch (os.environ).
    env_path = tmp_path / ".env.empty"
    env_path.write_text("")

    cfg = load_config(config_path, env_path)

    assert cfg.runtime.mode == RuntimeMode.observe
    assert cfg.copy_trade.copy_ratio == pytest.approx(0.01)
    assert cfg.binance_api_key == "test_key"
    assert cfg.hyperliquid_wallet == "0xdeadbeef"
    assert cfg.runtime.auto_downgrade_enabled is True
    assert cfg.runtime.auto_downgrade_threshold == 3


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_missing_env_var(tmp_path, monkeypatch):
    """_require_env raises ConfigValidationError directly, not via model_validate.
    We must delete the var from os.environ to prevent load_dotenv(override=False)
    from silently succeeding when the shell has the var already set."""
    monkeypatch.delenv("HYPERLIQUID_TARGET_WALLET", raising=False)
    # Keep API key/secret set so only the wallet lookup fails
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "s")

    config_path = _write_yaml(tmp_path, {})
    env_path = tmp_path / ".env"
    # The .env file also omits HYPERLIQUID_TARGET_WALLET
    env_path.write_text("BINANCE_API_KEY=k\nBINANCE_API_SECRET=s\n")

    with pytest.raises(ConfigValidationError, match="HYPERLIQUID_TARGET_WALLET"):
        load_config(config_path, env_path)


# ---------------------------------------------------------------------------
# Test: validate_config cross-field rules via model_validate
# (These raise pydantic.ValidationError which wraps the ConfigValidationError message.)
# ---------------------------------------------------------------------------


def test_armed_mode_requires_sqlite_enabled():
    with pytest.raises(PydanticValidationError, match="sqlite_enabled"):
        AppConfig.model_validate({
            "runtime": {"mode": "armed", "sqlite_enabled": False},
        })


def test_freshness_timeout_must_be_gte_poll_interval():
    with pytest.raises(PydanticValidationError, match="freshness_timeout"):
        AppConfig.model_validate({
            "source": {"poll_interval_seconds": 30, "freshness_timeout_seconds": 10},
        })


def test_position_mode_must_be_oneway():
    with pytest.raises(PydanticValidationError, match="ONEWAY"):
        AppConfig.model_validate({
            "binance": {"position_mode": "HEDGE"},
        })


def test_valid_live_mode():
    cfg = AppConfig.model_validate({"runtime": {"mode": "live", "sqlite_enabled": True}})
    assert cfg.runtime.mode == RuntimeMode.live
    assert cfg.runtime.sqlite_enabled is True


def test_auto_downgrade_threshold_must_be_positive():
    """auto_downgrade_threshold Field(ge=1) is enforced by Pydantic directly."""
    with pytest.raises(PydanticValidationError):
        AppConfig.model_validate({
            "runtime": {"auto_downgrade_threshold": 0},
        })


def test_auto_downgrade_disabled_does_not_require_threshold():
    """Disabling auto_downgrade is valid regardless of threshold."""
    cfg = AppConfig.model_validate({
        "runtime": {"auto_downgrade_enabled": False, "auto_downgrade_threshold": 1},
    })
    assert cfg.runtime.auto_downgrade_enabled is False

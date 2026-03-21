"""
config/loader.py

Loads config.yaml and .env, resolves secrets, and returns a validated AppConfig.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from copy_trader.config.models import AppConfig
from copy_trader.config.validation import ConfigValidationError  # re-export for callers


def load_config(config_path: str | Path, env_path: str | Path | None = None, overrides: dict | None = None) -> AppConfig:
    """
    Load and validate configuration.

    Args:
        config_path: Path to config.yaml.
        env_path:    Path to .env file (optional; defaults to .env in cwd).

    Returns:
        A fully validated AppConfig instance with secrets resolved from the environment.

    Raises:
        FileNotFoundError: if config_path does not exist.
        ConfigValidationError: if any validation rule fails.
        ValueError: if pydantic parsing fails.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Load .env first so os.getenv picks up the values
    _load_dotenv(env_path)

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if overrides:
        for k, v in overrides.items():
            if k not in raw:
                raw[k] = {}
            if isinstance(v, dict) and isinstance(raw[k], dict):
                raw[k].update(v)
            else:
                raw[k] = v

    cfg = AppConfig.model_validate(raw)

    # Resolve secrets from environment after pydantic validation
    cfg.binance_api_key = _require_env(cfg.binance.api_key_env)
    cfg.binance_api_secret = _require_env(cfg.binance.api_secret_env)
    cfg.hyperliquid_wallet = _require_env(cfg.source.wallet_address_env)

    return cfg


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_dotenv(env_path: str | Path | None) -> None:
    """Load .env if it exists.  Missing .env is not an error (env vars may already be set)."""
    if env_path is not None:
        load_dotenv(Path(env_path), override=False)
    else:
        load_dotenv(override=False)


def _require_env(var_name: str) -> str:
    """Return the value of an environment variable or raise ConfigValidationError."""
    value = os.getenv(var_name)
    if not value:
        raise ConfigValidationError(
            f"Required environment variable '{var_name}' is not set or empty. "
            f"Check your .env file or shell environment."
        )
    return value

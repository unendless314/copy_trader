"""
config/models.py

Typed configuration models built on pydantic v2.
All fields map 1-to-1 to the CONFIG-SCHEMA.md contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class RuntimeMode(str, Enum):
    observe = "observe"
    armed = "armed"
    live = "live"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class RuntimeConfig(BaseModel):
    mode: RuntimeMode = RuntimeMode.observe
    log_level: LogLevel = LogLevel.INFO
    sqlite_enabled: bool = True
    sqlite_path: str = "./data/copy_trading.db"
    auto_downgrade_enabled: bool = True
    auto_downgrade_threshold: int = Field(3, ge=1, description="Consecutive live execution failures before live→armed downgrade")


class SourceConfig(BaseModel):
    kind: str = "hyperliquid_wallet"
    wallet_address_env: str = "HYPERLIQUID_TARGET_WALLET"
    rest_url: str = "https://api.hyperliquid.xyz/info"
    poll_interval_seconds: int = 10
    freshness_timeout_seconds: int = 30
    request_timeout_seconds: int = 10


class LeverageConfig(BaseModel):
    default: int = Field(2, ge=1)


class PriceGuardConfig(BaseModel):
    enabled: bool = True
    reference_price: str = "mark_price"  # "mark_price" | "mid_price"
    max_deviation_bps: int = Field(15, ge=1)


class BinanceConfig(BaseModel):
    api_key_env: str = "BINANCE_API_KEY"
    api_secret_env: str = "BINANCE_API_SECRET"
    testnet: bool = False
    position_mode: str = "ONEWAY"
    leverage: LeverageConfig = LeverageConfig()
    price_guard: PriceGuardConfig = PriceGuardConfig()


class AllowedSidesConfig(BaseModel):
    long: bool = True
    short: bool = True


class SymbolsConfig(BaseModel):
    whitelist: list[str] = Field(default_factory=lambda: ["BTCUSDT"])
    blacklist: list[str] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=lambda: {"BTC": "BTCUSDT"})


class CopyTradeConfig(BaseModel):
    copy_ratio: float = Field(0.01, gt=0)
    allowed_sides: AllowedSidesConfig = AllowedSidesConfig()
    symbols: SymbolsConfig = SymbolsConfig()


class RiskConfig(BaseModel):
    max_symbol_notional_usdt: float = Field(1000.0, gt=0)
    max_total_notional_usdt: float = Field(1000.0, gt=0)
    max_single_rebalance_notional_usdt: float = Field(300.0, gt=0)
    max_delta_convergence_ratio: float = Field(0.30, gt=0, le=1)
    min_rebalance_pct: float = Field(0.02, gt=0, le=1)
    min_rebalance_notional_usdt: float = Field(100.0, gt=0)
    max_orders_per_cycle: int = Field(1, ge=1)


class ExecutionConfig(BaseModel):
    order_type: str = "MARKET"          # V1 fixed
    symbol_cooldown_seconds: int = Field(30, ge=0)
    flip_behavior: str = "CLOSE_THEN_OPEN"  # V1 fixed
    skip_on_price_guard: bool = True


class ObservabilityConfig(BaseModel):
    terminal_warnings: bool = True
    persist_source_snapshots: bool = True
    persist_binance_positions: bool = True
    persist_decisions: bool = True
    persist_execution_results: bool = True


class AppConfig(BaseModel):
    """Root configuration object assembled from config.yaml."""

    runtime: RuntimeConfig = RuntimeConfig()
    source: SourceConfig = SourceConfig()
    binance: BinanceConfig = BinanceConfig()
    copy_trade: CopyTradeConfig = CopyTradeConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    observability: ObservabilityConfig = ObservabilityConfig()

    # Cross-field resolved secrets (populated by the loader, not from YAML)
    binance_api_key: Optional[str] = Field(None, exclude=True)
    binance_api_secret: Optional[str] = Field(None, exclude=True)
    hyperliquid_wallet: Optional[str] = Field(None, exclude=True)

    @model_validator(mode="after")
    def _validate_cross_field_rules(self) -> "AppConfig":
        from copy_trader.config.validation import validate_config

        validate_config(self)
        return self

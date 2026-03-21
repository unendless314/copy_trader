# Configuration Schema

## Purpose

This document defines the initial configuration contract for the standalone copy-trading program.

The design goals are:

- keep V1 configuration explicit and readable
- separate strategy policy from secrets
- support one wallet and one live symbol in V1
- leave room for later multi-symbol expansion

## File Split

- `config.yaml`
  Holds runtime mode, strategy behavior, and risk controls.
- `.env`
  Holds secrets and sensitive identifiers.

Configuration is loaded only at startup. Changes require process restart.

## `config.yaml`

```yaml
runtime:
  mode: observe
  log_level: INFO
  sqlite_enabled: true
  sqlite_path: ./data/copy_trading.db
  auto_downgrade_enabled: true
  auto_downgrade_threshold: 3

source:
  kind: hyperliquid_wallet
  wallet_address_env: HYPERLIQUID_TARGET_WALLET
  rest_url: https://api.hyperliquid.xyz/info
  poll_interval_seconds: 10
  freshness_timeout_seconds: 30
  request_timeout_seconds: 10

binance:
  api_key_env: BINANCE_API_KEY
  api_secret_env: BINANCE_API_SECRET
  testnet: false
  position_mode: ONEWAY
  leverage:
    default: 2
  price_guard:
    enabled: true
    reference_price: mark_price
    max_deviation_bps: 15

copy_trade:
  copy_ratio: 0.01
  allowed_sides:
    long: true
    short: true
  symbols:
    whitelist:
      - BTCUSDT
    blacklist: []
    mapping:
      BTC: BTCUSDT

risk:
  max_symbol_notional_usdt: 1000
  max_total_notional_usdt: 1000
  max_single_rebalance_notional_usdt: 300
  max_delta_convergence_ratio: 0.30
  min_rebalance_pct: 0.02
  min_rebalance_notional_usdt: 100
  max_orders_per_cycle: 1

execution:
  order_type: MARKET
  symbol_cooldown_seconds: 30
  flip_behavior: CLOSE_THEN_OPEN
  skip_on_price_guard: true

observability:
  terminal_warnings: true
  persist_source_snapshots: true
  persist_binance_positions: true
  persist_decisions: true
  persist_execution_results: true
```

## Field Definitions

### `runtime`

- `mode`
  Enum: `observe`, `armed`, `live`
- `log_level`
  Example: `DEBUG`, `INFO`, `WARNING`
- `sqlite_enabled`
  Whether SQLite observation storage is enabled
  In V1, this must be `true` in `armed` and `live`
- `sqlite_path`
  Local path to the SQLite database
- `auto_downgrade_enabled`
  Whether the system may automatically downgrade from `live` to `armed` on repeated execution failures.
  Default: `true`. Set to `false` to disable the safety net (not recommended for production use).
- `auto_downgrade_threshold`
  Number of consecutive live execution failures required to trigger the automatic downgrade.
  Default: `3`. Must be a positive integer.
  Counts only deterministic execution rejects, unknown execution status, and execution-path exceptions.
  Does not count SKIP_* outcomes, price-guard blocks, or SQLite failures.

### `source`

- `kind`
  V1 fixed value: `hyperliquid_wallet`
- `wallet_address_env`
  Name of the environment variable holding the source wallet address
- `rest_url`
  Hyperliquid endpoint for wallet state queries
- `poll_interval_seconds`
  Default polling interval
- `freshness_timeout_seconds`
  Snapshot age limit before source is considered stale
- `request_timeout_seconds`
  HTTP timeout for source requests

### `binance`

- `api_key_env`
  Environment variable containing Binance API key
- `api_secret_env`
  Environment variable containing Binance API secret
- `testnet`
  Whether Binance testnet is used
- `position_mode`
  V1 fixed value: `ONEWAY`
- `leverage.default`
  Fixed leverage applied to the configured live symbol(s)
- `price_guard.enabled`
  Enables price-deviation protection
- `price_guard.reference_price`
  Suggested V1 values: `mark_price`, `mid_price`
- `price_guard.max_deviation_bps`
  Maximum allowed deviation before skipping execution
  In V1, price guard uses Binance reference prices only

### `copy_trade`

- `copy_ratio`
  Multiplier applied to source position quantity
  Format in V1: decimal number only, for example `0.01`
- `allowed_sides.long`
  Whether long exposure is allowed
- `allowed_sides.short`
  Whether short exposure is allowed
- `symbols.whitelist`
  Allowed Binance symbols for reconciliation
- `symbols.blacklist`
  Explicitly blocked symbols
- `symbols.mapping`
  Source asset to Binance symbol mapping

## `risk`

- `max_symbol_notional_usdt`
  Hard cap for a single symbol exposure
- `max_total_notional_usdt`
  Hard cap across all open copied exposure
- `max_single_rebalance_notional_usdt`
  Max notional submitted by one rebalance action
- `max_delta_convergence_ratio`
  Max fraction of current delta allowed in one rebalance
- `min_rebalance_pct`
  Minimum percentage drift before rebalancing
- `min_rebalance_notional_usdt`
  Minimum notional drift before rebalancing
- `max_orders_per_cycle`
  Safety limit for orders created in one loop

## `execution`

- `order_type`
  V1 fixed value: `MARKET`
- `symbol_cooldown_seconds`
  Minimum wait time after action before rechecking tradable execution
- `flip_behavior`
  V1 fixed value: `CLOSE_THEN_OPEN`
- `skip_on_price_guard`
  If true, price-guard failures only block the current cycle

## `observability`

- `terminal_warnings`
  Show warning conditions in terminal output
- `persist_source_snapshots`
  Store source snapshots in SQLite
- `persist_binance_positions`
  Store Binance position snapshots in SQLite
- `persist_decisions`
  Store reconciliation decisions in SQLite
- `persist_execution_results`
  Store order results in SQLite

## `.env`

```dotenv
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
HYPERLIQUID_TARGET_WALLET=0xd6e56265890b76413d1d527eb9b75e334c0c5b42
```

## Validation Rules

- `runtime.mode` must be one of `observe`, `armed`, `live`
- if `runtime.mode` is `armed` or `live`, `runtime.sqlite_enabled` must be `true`
- if `runtime.auto_downgrade_enabled` is `true`, `runtime.auto_downgrade_threshold` must be greater than `0`
- `source.poll_interval_seconds` must be greater than `0`
- `source.freshness_timeout_seconds` must be greater than or equal to `source.poll_interval_seconds`
- `binance.position_mode` must be `ONEWAY` in V1
- `binance.leverage.default` must be a positive integer
- `copy_trade.copy_ratio` must be greater than `0`
- `risk.max_delta_convergence_ratio` must be between `0` and `1`
- `risk.min_rebalance_pct` must be between `0` and `1`
- `risk.max_orders_per_cycle` should be `1` in V1
- `execution.order_type` must be `MARKET` in V1
- `execution.flip_behavior` must be `CLOSE_THEN_OPEN` in V1

## Resolved Decisions

- `copy_ratio` accepts decimal numbers only, such as `0.01`
- `sqlite_enabled` is mandatory in `armed` and `live`
- price guard uses Binance reference prices only in V1
- automatic downgrade is limited to `live -> armed` and defaults to `3` consecutive execution failures

## Open Questions

- None at the configuration-schema level for V1

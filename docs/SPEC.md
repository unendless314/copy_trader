# Technical Specification

## System Boundary

The selected implementation is a standalone program. This repository is used as a planning workspace and reference source only. The runtime system must not depend on Hummingbot strategy lifecycle assumptions.

Supporting contracts:

- API details are defined in `API-CONTRACTS.md`
- runtime-only in-memory state is defined in `EPHEMERAL-STATE.md`
- failure classes are defined in `ERROR-TAXONOMY.md`
- structured event schema is defined in `LOGGING-FORMAT.md`

## Runtime Modes

- `observe`
  Fetch source and Binance positions, compute targets and deltas, log intended actions, do not persist SQLite, do not trade.
- `armed`
  Fetch and compute normally, persist observations to SQLite, do not trade.
- `live`
  Fetch and compute normally, persist observations to SQLite, allow Binance order execution.

Mode transitions must be explicit and operator-controlled.

V1 exception:

- limited automatic downgrade from `live` to `armed` is allowed as documented in `RUNTIME-STATE-MACHINE.md` and `ERROR-TAXONOMY.md`

## Core Modules

### 1. Source Reader

Responsibilities:

- Query Hyperliquid wallet position snapshots
- Validate freshness and response shape
- Normalize source positions

Inputs:

- source wallet address
- source endpoint configuration

Outputs:

- normalized source snapshot

### 2. Binance Gateway

Responsibilities:

- Fetch current Binance perpetual positions
- Fetch executable prices and reference prices
- Submit market orders
- Apply exchange precision and trading-rule constraints

### 3. Target Calculator

Responsibilities:

- Use source position quantity as the primary sizing basis
- Apply `copy_ratio`
- Enforce fixed Binance leverage policy
- Enforce symbol and global risk caps

Formula:

- `target_size = source_size * copy_ratio`

Sizing basis clarification:

- `source_size` is the signed Hyperliquid position quantity
- notional is used only for risk limits, tradability checks, and convergence caps

## 4. Reconciliation Engine

Responsibilities:

- Compute `raw_delta_size = target_size - actual_size`
- Ignore non-tradable or sub-threshold deltas
- Handle flips using close-then-open
- Apply stepwise convergence for oversized deltas
- Remain stateless across cycles for position logic

Allowed runtime-only control state:

- per-symbol cooldown in memory only
- global live execution failure counter in memory only

Disallowed:

- any persisted decision state used for live logic
- flip phase flags persisted across cycles

Trigger policy:

- post-cap executable delta must satisfy Binance tradability rules
- raw delta must exceed configured drift threshold

## 5. Price Guard

Responsibilities:

- Compare Binance executable price against reference price
- Block execution when deviation exceeds configured basis-point limits

V1 design:

- use price-deviation protection
- do not implement full order-book slippage simulation

If blocked:

- skip current cycle
- retry next cycle
- emit warning
- do not auto-relax thresholds

## 6. Source Freshness Guard

Responsibilities:

- detect stale source data
- block new rebalancing while stale
- keep current Binance positions unchanged
- emit repeated warnings until freshness returns

## 7. Observability Layer

Responsibilities:

- write structured logs
- store snapshots, decisions, warnings, and execution results in SQLite

Constraint:

- SQLite is an observation store only
- live decision logic must not depend on SQLite state
- SQLite write failures must not block trading logic in V1; they should generate warnings only
- JSON Lines is the authoritative structured log format in V1

## Configuration Model

See `CONFIG-SCHEMA.md` for the initial configuration contract and example file.

### YAML

Holds:

- runtime mode
- symbol whitelist / blacklist
- `copy_ratio`
- fixed Binance leverage
- `poll_interval`
- `cooldown_seconds`
- drift thresholds
- price-deviation thresholds
- `max_symbol_notional`
- `max_total_notional`
- `max_single_rebalance_notional`
- `max_delta_convergence_ratio`
- source freshness timeout

### `.env`

Holds:

- Binance API credentials
- Hyperliquid target wallet address
- any private endpoint credentials if introduced later

Configuration is loaded only at startup. Runtime hot reload is out of scope for V1.

## Initial Defaults

- one source wallet
- one symbol: `BTCUSDT`
- one-way mode
- poll interval: `10s`
- symbol cooldown: `30s`
- market orders only
- fixed leverage from config
- logs plus terminal warnings

## Data Model

### Source Position

- `symbol`
- `side`
- `size`
- `entry_price`
- `source_timestamp`

Contract note:

- `source_timestamp` must come from the Hyperliquid response, not local wall-clock fallback

### Actual Position

- `symbol`
- `side`
- `size`
- `entry_price`
- `binance_timestamp`

### Decision Record

- `cycle_id`
- `runtime_mode`
- `symbol`
- `source_size`
- `target_size`
- `actual_size`
- `raw_delta_size`
- `capped_delta_size`
- `decision`
- `block_reason`
- `reference_price`
- `executable_price`
- `price_deviation_bps`
- `created_at`

## Execution Rules

- Use market orders only in V1
- Use close-then-open for flips
- Apply stricter of:
  - `max_single_rebalance_notional`
  - `max_delta_convergence_ratio`
- Skip if source is stale
- Skip if price guard fails
- Skip if below tradability or drift threshold
- Determine flip phase from fresh Binance snapshots, not persisted flags
- Use the same reconciliation logic on first startup as on any later cycle

Minimum tradable size rule:

- proposed size must pass effective market-order quantity filters
- proposed size must pass minimum notional checks
- if any tradability rule fails after rounding and caps, outcome is `SKIP_BELOW_THRESHOLD`

## Failure Handling

- Exchange or source failure must not mutate internal target logic
- Each cycle starts from fresh source and fresh actual positions
- Temporary failures should degrade to warnings and skipped actions
- No automatic flattening because of stale source in V1

## Planned SQLite Tables

### `source_snapshots`

- `id`
- `wallet`
- `symbol`
- `side`
- `size`
- `entry_price`
- `source_timestamp`
- `created_at`

### `binance_positions`

- `id`
- `symbol`
- `side`
- `size`
- `entry_price`
- `fetched_at`

### `reconciliation_decisions`

- `id`
- `cycle_id`
- `runtime_mode`
- `symbol`
- `source_size`
- `target_size`
- `actual_size`
- `raw_delta_size`
- `capped_delta_size`
- `decision`
- `block_reason`
- `reference_price`
- `executable_price`
- `price_deviation_bps`
- `created_at`

### `execution_results`

- `id`
- `cycle_id`
- `symbol`
- `action`
- `requested_size`
- `submitted_size`
- `status`
- `exchange_order_id`
- `error_message`
- `created_at`

Field semantics:

- `raw_delta_size`: signed pre-cap delta
- `capped_delta_size`: signed post-cap executable delta
- `execution_results.action`: actual submitted Binance side

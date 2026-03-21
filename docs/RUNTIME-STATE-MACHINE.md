# Runtime State Machine

## Purpose

This document defines the runtime behavior of the standalone copy-trading program.

The goal is to keep runtime control explicit, low-risk, and easy to inspect.

## Core Principle

Trading permission must be controlled by a single explicit runtime mode.

V1 modes:

- `observe`
- `armed`
- `live`

No other hidden flags should override order permission.

V1 exception:

- documented automatic downgrade from `live` to `armed` is allowed for repeated execution-safety failures

## Mode Semantics

### `observe`

Behavior:

- fetch source snapshots
- fetch Binance positions and prices
- compute targets and deltas
- evaluate risk and price guards
- print and log intended actions
- do not write SQLite
- do not place orders

Use case:

- first startup
- strategy validation
- config sanity check

### `armed`

Behavior:

- do everything `observe` does
- persist snapshots, decisions, and warnings to SQLite
- do not place orders

Use case:

- dry run with historical inspection
- debugging decision quality before live trading

### `live`

Behavior:

- do everything `armed` does
- place Binance orders when all execution conditions pass

Use case:

- production trading after operator confirmation

## Allowed Transitions

Recommended transitions:

- `observe -> armed`
- `armed -> live`
- `live -> armed`
- `armed -> observe`
- `live -> observe`

Disallowed shortcut for V1:

- `observe -> live`

This forces at least one inspection stage before live trading.

## Downgrade Policy

V1 should support both manual downgrade and limited automatic downgrade.

### Manual Downgrade

Manual downgrade must always be available.

Supported examples:

- `live -> armed`
- `live -> observe`
- `armed -> observe`

Manual downgrade should be applied through config change plus restart, keeping mode control explicit.

### Automatic Downgrade

Automatic downgrade should be limited and conservative.

V1 recommendation:

- only allow automatic downgrade from `live` to `armed`
- do not auto-upgrade under any condition
- do not auto-downgrade because of observability-only failures such as SQLite write errors
- do not auto-downgrade because of price-guard blocks

Automatic downgrade should only react to repeated execution-safety problems.

V1 threshold:

- keep one global in-memory counter of consecutive live execution failures
- trigger `live -> armed` after `3` consecutive counted failures
- reset the counter only after a live order is accepted unambiguously by Binance

Counted failures:

- deterministic order rejects
- unknown execution status after order submission
- execution-path internal exceptions

Ignored for the counter:

- all `SKIP_*` outcomes
- source or Binance read-side failures
- price-guard blocks
- SQLite failures

## Startup Policy

Recommended startup rule:

- default mode is `observe`
- operator must explicitly change config and restart to enter `armed`
- operator must explicitly change config and restart to enter `live`
- there is no special-case bootstrap cycle; first run uses the same reconciliation logic as every later cycle

## Cycle Workflow

Each loop should follow the same order:

1. Load source snapshot
2. Validate freshness
3. Load Binance positions
4. Load Binance reference and executable prices
5. Normalize data
6. Compute target and delta
7. Evaluate thresholds and guards
8. Produce a decision
9. Persist to SQLite if mode is `armed` or `live`
10. Execute only if mode is `live` and decision allows execution

## Decision Outcomes

Each cycle should end in one of these outcomes per symbol:

- `NO_ACTION`
- `SKIP_SOURCE_STALE`
- `SKIP_BELOW_THRESHOLD`
- `SKIP_PRICE_GUARD`
- `SKIP_COOLDOWN`
- `REBALANCE_INCREASE`
- `REBALANCE_REDUCE`
- `REBALANCE_CLOSE`
- `REBALANCE_FLIP_CLOSE`
- `REBALANCE_FLIP_OPEN`
- `ERROR`

## Kill Behavior

V1 recommendation:

- no separate kill-switch state machine yet
- use `runtime.mode = observe` as the soft safe mode
- use process stop as the hard stop

If a hard kill switch is added later, it should block execution but preserve logging and snapshot collection.

## Failure Rules

- source stale: no new execution
- Binance request failure: no execution for that cycle
- SQLite failure in `observe`: ignore and continue
- SQLite failure in `armed` or `live`: continue running, warn loudly, and keep trading logic active

Rationale:

- the primary purpose of the system is copy trading, not data retention
- SQLite is important for observability, but missing records are preferable to halted execution
- SQLite must remain a non-authoritative side channel in V1

V1 auto-downgrade triggers in `live`:

- deterministic order rejects
- unknown execution status after submission
- repeated internal execution exceptions on the execution path

If automatic downgrade is triggered:

- switch from `live` to `armed`
- emit strong terminal warnings
- keep source and Binance observation running
- require explicit operator action to return to `live`

## Recommendation for V1

Use the simplest possible operator flow:

1. start in `observe`
2. confirm source and Binance readings look correct
3. switch to `armed`
4. inspect SQLite records and logs
5. switch to `live`

This keeps operational discipline without adding a complicated orchestration layer.

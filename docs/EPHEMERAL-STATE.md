# Ephemeral State Contract

## Purpose

This document defines the small amount of runtime-only state allowed in V1.

The system remains **stateless for trading decisions across cycles**:

- every cycle recomputes target and delta from fresh source and Binance snapshots
- SQLite is never used as authoritative live state
- no residual bucket, pending-intent table, or replay log is maintained

V1 still allows a narrow set of **ephemeral control state** to support cooldown and limited runtime safety behavior.

## Design Rule

Only runtime control concerns may keep in-memory state.

Allowed ephemeral state in V1:

- symbol cooldown timestamps
- live-mode consecutive execution failure counter

Disallowed state in V1:

- target position cache
- previous-cycle delta cache
- residual position bucket
- flip phase flags persisted across cycles
- any SQLite-backed decision state used by live trading logic

## Storage Location

Ephemeral state must live in process memory only.

Suggested implementation location:

- `runtime/loop.py` owns the runtime state container
- `runtime/cooldown.py` provides symbol cooldown helpers

Suggested structure:

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RuntimeEphemeralState:
    cooldown_until_by_symbol: dict[str, datetime] = field(default_factory=dict)
    consecutive_live_execution_failures: int = 0
```

## Restart Behavior

All ephemeral state resets on process restart.

Consequences:

- symbol cooldowns are cleared
- live execution failure counters are cleared
- no recovery logic runs from SQLite
- next cycle behaves like any other fresh cycle using current source and Binance snapshots only

This is intentional and consistent with the stateless reconciliation model.

## Cooldown Contract

Cooldown is tracked **per symbol**, not globally.

Field:

- `cooldown_until_by_symbol[symbol] = timestamp`

Behavior:

- set only after a live Binance order is accepted for that symbol
- evaluated before tradability, drift, or price-guard checks
- if `now < cooldown_until`, decision outcome is `SKIP_COOLDOWN`
- if cooldown expires, the symbol is evaluated normally on the next cycle

Cooldown must not be set in:

- `observe`
- `armed`
- cycles where the order was blocked before submission
- cycles where the order submission failed before exchange acceptance

## Flip Handling Contract

Flip handling must not use a persisted phase flag across cycles.

V1 flip progression is determined only from fresh Binance position state:

1. If `actual_size` still has the old direction and `target_size` has the opposite direction, emit `REBALANCE_FLIP_CLOSE`.
2. After the next fresh Binance snapshot shows the symbol is flat or operationally flat, emit `REBALANCE_FLIP_OPEN` if the target still requires the opposite direction.

Operationally flat means:

- remaining position is below the Binance tradability threshold, or
- remaining position is below the configured drift threshold

This keeps flip handling deterministic after restart and avoids hidden multi-step state.

## Live Execution Failure Counter

V1 keeps one global in-memory counter:

- `consecutive_live_execution_failures`

This counter exists only for limited automatic downgrade from `live` to `armed`.

Increment the counter when:

- a cycle attempts order execution in `live`, and
- the result is a deterministic reject, execution exception, or unknown execution status

Reset the counter when:

- a live order is accepted by Binance and the response is unambiguous

Do not increment the counter for:

- `NO_ACTION`
- `SKIP_*`
- source-read failures
- Binance read-only API failures
- price-guard blocks
- SQLite write failures

## First-Run and Restart Policy

There is no special startup state.

On first run or after restart:

- if Binance is flat and source target is non-zero, the engine may emit `REBALANCE_INCREASE`
- if Binance still holds an old position opposite to the target, the engine may emit `REBALANCE_FLIP_CLOSE`
- if Binance is already flat and target points to the new side, the engine may emit `REBALANCE_FLIP_OPEN`

No bootstrap mode, recovery mode, or state migration is required in V1.

# Decision Engine Rules

## Purpose

This document defines how the standalone copy-trading program converts source and Binance snapshots into executable decisions.

The goal is to make decisions:

- deterministic
- stateless
- easy to debug
- consistent with the risk-first design

V1 clarification:

- position logic is stateless across cycles
- limited runtime-only control state is allowed for cooldown and live safety counters
- see `EPHEMERAL-STATE.md`

## Inputs

Per symbol, the decision engine receives:

- `source_size`
- `actual_size`
- `copy_ratio`
- Binance trading constraints
- risk limits
- cooldown state
- source freshness state
- price guard result
- runtime mode

Derived values:

- `target_size = source_size * copy_ratio`
- `raw_delta_size = target_size - actual_size`
- `capped_delta_size = signed executable delta after convergence/notional caps`

Sizing basis clarification:

- `source_size` is the signed source position quantity
- V1 does not apply `copy_ratio` to source notional

## Normalized Position Semantics

- positive size = long
- negative size = short
- zero size = flat

The engine must reason only about **net size**.

## Evaluation Order

The engine should evaluate rules in this order:

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

This order matters. Earlier blockers short-circuit later checks.

## Hard Blockers

These conditions always prevent execution in the current cycle:

- source is stale
- symbol is not whitelisted
- symbol is blacklisted
- cooldown is active
- Binance position fetch failed
- Binance price fetch failed
- delta is not tradable
- delta does not exceed drift threshold
- price guard failed

Possible outcomes:

- `SKIP_SOURCE_STALE`
- `SKIP_SYMBOL_DISABLED`
- `SKIP_COOLDOWN`
- `SKIP_DATA_UNAVAILABLE`
- `SKIP_BELOW_THRESHOLD`
- `SKIP_PRICE_GUARD`

## Decision Categories

When execution is allowed, the engine may choose one of:

- `REBALANCE_INCREASE`
- `REBALANCE_REDUCE`
- `REBALANCE_CLOSE`
- `REBALANCE_FLIP_CLOSE`
- `REBALANCE_FLIP_OPEN`
- `NO_ACTION`

## Rule Table

### Rule 1: Already Aligned

Condition:

- `target_size == actual_size`, or
- absolute delta is below tradability or drift threshold

Outcome:

- `NO_ACTION` or `SKIP_BELOW_THRESHOLD`

### Rule 2: Flat to New Position

Condition:

- `actual_size == 0`
- `target_size != 0`
- tradability and drift thresholds pass

Outcome:

- `REBALANCE_INCREASE`

Execution intent:

- open a new position toward `target_size`

### Rule 3: Reduce to Flat

Condition:

- `actual_size != 0`
- `target_size == 0`
- tradability and drift thresholds pass

Outcome:

- `REBALANCE_CLOSE`

Execution intent:

- reduce current position toward zero

### Rule 4: Same Direction, Need More Exposure

Condition:

- `sign(actual_size) == sign(target_size)`
- `abs(target_size) > abs(actual_size)`
- tradability and drift thresholds pass

Outcome:

- `REBALANCE_INCREASE`

Execution intent:

- add exposure in the same direction

### Rule 5: Same Direction, Need Less Exposure

Condition:

- `sign(actual_size) == sign(target_size)`
- `abs(target_size) < abs(actual_size)`
- tradability and drift thresholds pass

Outcome:

- `REBALANCE_REDUCE`

Execution intent:

- reduce exposure without flipping direction

### Rule 6: Opposite Direction, Flip Required

Condition:

- `actual_size != 0`
- `target_size != 0`
- `sign(actual_size) != sign(target_size)`

Outcome:

- phase 1: `REBALANCE_FLIP_CLOSE`
- phase 2: `REBALANCE_FLIP_OPEN`

Execution intent:

- first close the current position toward zero
- only after close is sufficiently completed, open the reverse-side position

## Flip Handling

V1 uses explicit close-then-open.

### Flip Phase 1: Close Current Side

Condition:

- current position still has the old direction

Action:

- submit a reducing order toward zero

Result:

- enter cooldown
- next cycle re-evaluates fresh snapshots

### Flip Phase 2: Open New Side

Condition:

- current position is flat, or residual position is small enough to be treated as operationally flat
- target still points to opposite direction

Action:

- submit opening order toward the new target

Operationally flat in V1 means:

- remaining position is below Binance tradability threshold, or
- remaining position is below configured drift threshold

This prevents tiny residual amounts from blocking the reverse-side open decision.

## Stepwise Convergence

For `REBALANCE_INCREASE`, `REBALANCE_REDUCE`, and `REBALANCE_CLOSE`, the requested action size must be capped by:

- `max_single_rebalance_notional_usdt`
- `max_delta_convergence_ratio`

The engine must apply the stricter cap.

This means the requested order size may be smaller than the full delta.

Important signed-quantity rule:

- `apply_convergence_cap()` operates on absolute quantity only
- the caller must restore the sign from `raw_delta_size`
- final order side is derived from the signed post-cap delta, not from the decision label alone

After caps are applied, the requested order size must still pass Binance market-order tradability rules.

Tradability validation order:

1. round toward zero to the effective market-order step size
2. validate effective minimum quantity
3. validate effective maximum quantity
4. validate minimum notional using reference mark price

If any check fails, the outcome is `SKIP_BELOW_THRESHOLD`.

## Decision Output Contract

Each decision should produce a structured record with at least:

- `decision_type`
- `symbol`
- `source_size`
- `target_size`
- `actual_size`
- `raw_delta_size`
- `capped_delta_size`
- `block_reason`
- `reference_price`
- `executable_price`
- `runtime_mode`
- `created_at`

Signed field semantics:

- `raw_delta_size`: signed pre-cap delta
- `capped_delta_size`: signed post-cap executable delta

## Example Scenarios

### Scenario A: Small BTC Long Drift

- source size: `10 BTC`
- copy ratio: `0.01`
- target size: `0.10 BTC`
- actual size: `0.08 BTC`

If thresholds pass:

- outcome: `REBALANCE_INCREASE`

### Scenario B: Overexposed BTC Long

- source size: `10 BTC`
- copy ratio: `0.01`
- target size: `0.10 BTC`
- actual size: `0.14 BTC`

If thresholds pass:

- outcome: `REBALANCE_REDUCE`
- `raw_delta_size < 0`, so execution side is `SELL`

### Scenario C: Source Flat, Binance Still Long

- target size: `0`
- actual size: `0.05 BTC`

If thresholds pass:

- outcome: `REBALANCE_CLOSE`
- `raw_delta_size < 0`, so execution side is `SELL`

### Scenario C2: Source Flat, Binance Still Short

- target size: `0`
- actual size: `-0.05 BTC`

If thresholds pass:

- outcome: `REBALANCE_CLOSE`
- `raw_delta_size > 0`, so execution side is `BUY`

### Scenario D: Source Flips from Long to Short

- target size: `-0.10 BTC`
- actual size: `0.08 BTC`

Cycle 1:

- outcome: `REBALANCE_FLIP_CLOSE`
- side opposes current actual position

Later cycle after close:

- outcome: `REBALANCE_FLIP_OPEN`

### Scenario E: Overexposed BTC Short

- source size: `-10 BTC`
- copy ratio: `0.01`
- target size: `-0.10 BTC`
- actual size: `-0.14 BTC`

If thresholds pass:

- outcome: `REBALANCE_REDUCE`
- `raw_delta_size > 0`, so execution side is `BUY`

## Notes for Implementation

- the decision engine should not submit orders directly
- it should only return the intended action and its reason
- execution modules apply the action afterward
- every cycle must recompute from fresh source and actual states

## V1 Recommendations

- keep one decision per symbol per cycle
- keep `max_orders_per_cycle = 1`
- use decision logs heavily
- do not hide skipped actions; record them explicitly

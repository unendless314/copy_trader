# Logging Format

## Purpose

This document defines the structured logging contract for V1.

The goal is to make logs:

- machine-readable
- easy to grep
- aligned with SQLite records
- sufficient for operator debugging without replaying code

## Output Format

V1 uses **JSON Lines** for structured logs.

Rules:

- one JSON object per line
- UTF-8 text file or stdout stream
- timestamps in UTC ISO8601 format
- decimal values serialized as strings to avoid float drift

Plain-text terminal warnings may exist as a secondary view, but the authoritative structured format is JSON Lines.

## Required Fields on Every Event

Every log event must include:

- `ts`
- `level`
- `event_type`
- `component`
- `cycle_id`
- `runtime_mode`
- `message`

Optional on some events but recommended whenever relevant:

- `symbol`
- `wallet`
- `exception_type`
- `stacktrace`

## Standard Event Types

V1 standardizes these event types:

- `cycle_started`
- `source_snapshot`
- `binance_position_snapshot`
- `price_snapshot`
- `decision`
- `execution_submitted`
- `execution_result`
- `warning`
- `error`
- `mode_changed`

## Log Levels

- `DEBUG`: payload details, normalized fields, filter calculations
- `INFO`: normal cycle progress and decisions
- `WARNING`: blocked actions, stale source, SQLite failures, repeated read failures
- `ERROR`: execution rejects, unknown execution status, fatal runtime issues

## Decision Event Schema

`event_type = "decision"`

Required fields:

- `symbol`
- `source_size`
- `target_size`
- `actual_size`
- `delta_size`
- `decision`
- `block_reason`
- `cooldown_active`
- `tradable`
- `drift_pass`

Recommended fields:

- `reference_price`
- `executable_price`
- `price_deviation_bps`
- `proposed_order_qty`
- `applied_convergence_ratio`
- `applied_notional_cap_usdt`

Example:

```json
{
  "ts": "2026-03-18T08:00:00Z",
  "level": "INFO",
  "event_type": "decision",
  "component": "strategy.reconciliation",
  "cycle_id": "20260318T080000Z-001",
  "runtime_mode": "observe",
  "symbol": "BTCUSDT",
  "message": "Decision computed",
  "source_size": "-0.25",
  "target_size": "-0.0025",
  "actual_size": "0",
  "delta_size": "-0.0025",
  "decision": "REBALANCE_INCREASE",
  "block_reason": null,
  "cooldown_active": false,
  "tradable": true,
  "drift_pass": true,
  "reference_price": "84250.1",
  "executable_price": "84251.0",
  "price_deviation_bps": "0.11",
  "proposed_order_qty": "0.002"
}
```

## Warning Event Schema

`event_type = "warning"`

Required fields:

- `warning_code`
- `message`

Recommended fields:

- `symbol`
- `reason`
- `count`

Typical warning codes:

- `SOURCE_STALE`
- `PRICE_GUARD_BLOCKED`
- `SQLITE_WRITE_FAILED`
- `UNMAPPED_SOURCE_SYMBOL`
- `READ_RETRY_BACKOFF`
- `AUTO_DOWNGRADE_TRIGGERED`

## Error Event Schema

`event_type = "error"`

Required fields:

- `error_code`
- `message`

Recommended fields:

- `symbol`
- `http_status`
- `exchange_code`
- `exception_type`
- `stacktrace`
- `execution_status`

## Execution Submitted Event Schema

`event_type = "execution_submitted"`

Required fields:

- `symbol`
- `decision`
- `order_side`
- `requested_qty`
- `reduce_only`

Recommended fields:

- `client_order_id`
- `reference_price`
- `executable_price`

## Execution Result Event Schema

`event_type = "execution_result"`

Required fields:

- `symbol`
- `decision`
- `order_side`
- `requested_qty`
- `status`

Recommended fields:

- `client_order_id`
- `binance_order_id`
- `executed_qty`
- `avg_price`
- `reduce_only`
- `latency_ms`
- `http_status`
- `exchange_code`
- `execution_status`

`status` should use one of:

- `ACCEPTED`
- `REJECTED`
- `UNKNOWN`

## Cycle Identity

Every cycle must have one `cycle_id`.

Rules:

- generated once at cycle start
- reused across all symbol-level events in that cycle
- independent of SQLite IDs

Suggested format:

- UTC timestamp plus monotonic suffix

Example:

- `20260318T080000Z-001`

## Relationship to SQLite

SQLite is an observation sink, not the source of truth.

Rules:

- structured logs should be emitted regardless of SQLite status
- SQLite tables should mirror core log fields where practical
- SQLite insertion failure must generate a warning event, not a gap in runtime decision logging

## Sensitive Data Policy

Never log:

- API secrets
- signed request payload secrets
- full credential headers

Wallet address may be logged because it is an operational identifier in this system.

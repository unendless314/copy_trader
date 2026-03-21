# Error Taxonomy

## Purpose

This document defines how V1 classifies operational failures and what the runtime should do in response.

The goal is to keep behavior deterministic and conservative.

## Classification Principles

- read-side failures block the current cycle but must not mutate target logic
- execution-side failures are more serious than data-read failures
- SQLite failures are observability issues, not trading-authority issues
- only repeated execution-safety failures may auto-downgrade `live` to `armed`

## Error Classes

### 1. Fatal Configuration or Authentication Errors

Examples:

- invalid config
- missing required environment variables
- unsupported Binance position mode
- invalid API key
- invalid API signature
- permission denied by exchange credentials

Runtime behavior:

- log error loudly
- stop process
- require operator intervention

These must not be downgraded to warnings because the system is misconfigured or unauthorized.

### 2. Retryable Read-Side Errors

Examples:

- Hyperliquid timeout
- Hyperliquid 5xx
- Binance read request timeout
- Binance rate limit on read endpoints
- temporary DNS or network failure
- malformed or incomplete response payload from a read endpoint

Runtime behavior:

- current cycle result becomes `SKIP_DATA_UNAVAILABLE`
- no order execution for that cycle
- continue loop
- apply bounded backoff before the next cycle when repeated

Backoff policy for V1:

- exponential or stepped backoff is acceptable
- maximum delay cap: `60` seconds
- backoff applies only to the poll scheduler, not to intra-cycle retries

### 3. Deterministic Execution Rejects

Examples:

- quantity below minimum after rounding
- insufficient margin
- invalid symbol
- invalid price or quantity precision
- reduce-only or position-side conflict
- locally valid decision but exchange rejects order parameters

Runtime behavior:

- current cycle logs `ERROR`
- no immediate retry inside the same cycle
- increment live execution failure counter if in `live`
- continue observation on later cycles

### 4. Unknown Execution Status

Examples:

- submit order request times out after reaching exchange
- exchange returns a transport-level or server-side response that does not confirm whether the order was accepted
- internal exception occurs after submission attempt but before the client records a stable result

Runtime behavior:

- treat the cycle as execution-unsafe
- do not submit a second order in the same cycle
- refresh Binance position/order state on the next cycle
- increment live execution failure counter if in `live`

### 5. Internal Runtime Exceptions

Examples:

- uncaught exception during decision translation
- executor-side logic error
- serialization or parsing bug after data fetch

Runtime behavior:

- log stack trace
- mark current cycle as `ERROR`
- if the exception occurs in execution path, increment live execution failure counter
- continue loop only if the process can return to a known-safe state

If the process state is no longer trustworthy, exit instead of limping forward.

### 6. Observability-Only Failures

Examples:

- SQLite insert failure
- SQLite lock timeout
- log file write failure while terminal logging still works

Runtime behavior:

- warn loudly
- continue runtime
- do not block trading
- do not increment live execution failure counter
- do not auto-downgrade

## Automatic Downgrade Policy

Automatic downgrade is limited to:

- `live -> armed`

V1 downgrade counter:

- one global in-memory counter
- name: `consecutive_live_execution_failures`

Counter increment conditions:

- deterministic execution reject
- unknown execution status
- execution-path internal exception

Counter reset condition:

- a live order is accepted unambiguously by Binance

Counter ignore conditions:

- `NO_ACTION`
- all `SKIP_*` outcomes
- read-side API failures
- price-guard failures
- SQLite failures

Downgrade threshold in V1:

- trigger automatic downgrade after `3` consecutive counted failures

Post-downgrade behavior:

- switch runtime mode from `live` to `armed`
- emit strong terminal warning
- continue source and Binance observation
- require explicit config change plus restart to return to `live`

## Source Staleness Policy

Source staleness is not an error class that halts the process.

Runtime behavior:

- emit `SKIP_SOURCE_STALE`
- place no new orders
- keep current Binance position unchanged
- keep looping until source freshness returns

V1 must not auto-flatten because of stale source data.

## Repeated Price Guard Blocks

Repeated price-guard blocks are warnings, not execution failures.

Runtime behavior:

- emit `SKIP_PRICE_GUARD`
- do not increment the live execution failure counter
- do not auto-downgrade solely because of price-guard blocks

This avoids punishing the system for intentionally conservative behavior.

## Operator Recovery Guidance

### After Fatal Error

- fix credentials, config, or environment
- restart in `observe`
- verify readings
- move to `armed`, then `live`

### After Automatic Downgrade

- inspect the last three execution attempts
- confirm the cause is resolved
- restart with `runtime.mode = live` only after validation

### After Repeated Read-Side Failures

- inspect endpoint health
- inspect network and rate-limit conditions
- keep the system in its current mode until source and Binance reads are stable

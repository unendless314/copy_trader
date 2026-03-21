# Product Requirements Document

## Overview

Build a standalone personal-use copy-trading program that follows a Hyperliquid vault wallet and synchronizes its **net position state** to Binance perpetual. The system does not attempt exact fill-by-fill replication. It targets reliable exposure tracking with strong operator control and bounded risk.

## Problem

Fill-by-fill copy trading is too fragile for this use case. Source orders may be fragmented, delayed, or partially observed. Binance minimum order constraints, network instability, and execution drift make exact trade replication difficult to trust and expensive to maintain.

## Product Goal

Replicate the source wallet's effective position exposure on Binance perpetual using periodic snapshot reconciliation.

## V1 Scope

- One source wallet
- Source market: Hyperliquid perpetual
- Target market: Binance perpetual
- One-way position mode only
- Long and short supported
- BTCUSDT only
- Market-order execution only
- Fixed copy ratio
- Fixed Binance leverage from config
- Config-driven risk limits
- Runtime modes: `observe`, `armed`, `live`
- Structured logs and SQLite observation storage

## Out of Scope

- Exact fill replication
- Open-order replication
- Hedge mode
- Multi-wallet orchestration
- Multi-symbol live scope in V1
- Automatic hot reload of configuration
- External alert channels in V1

## User Needs

- As an operator, I need a simple system that is predictable and easy to inspect.
- As an operator, I need to control all risk-critical parameters from config.
- As an operator, I need to delay live trading until I confirm the system is behaving correctly.
- As an operator, I need logs and historical records to review skipped actions, warnings, and executions.

## Core Functional Requirements

- Poll Hyperliquid source positions every 10 seconds by default.
- Poll Binance actual positions on the same cycle.
- Compute `target_position = source_position * copy_ratio`.
- Reconcile only when the delta is tradable and exceeds drift thresholds.
- Use close-then-open behavior for direction flips.
- Apply price-deviation guards before market execution.
- Use risk-first stepwise convergence when delta is too large.
- Suspend new actions when source data is stale.
- Never force-close positions because of temporary source staleness in V1.

## Non-Functional Requirements

- Stateless reconciliation on every cycle
- Config changes require restart
- Logs must be sufficient for operational debugging
- SQLite must be optional for observability, not required for decision correctness
- SQLite write failures must degrade to warnings rather than halt trading in V1
- System behavior must remain deterministic under restart

## Success Criteria

- BTCUSDT target exposure converges toward the configured source ratio within defined tolerance.
- The system survives fragmented source behavior without requiring every source fill event.
- Operators can safely use `observe` and `armed` modes before enabling `live`.
- Warnings clearly explain why a rebalance was skipped or blocked.

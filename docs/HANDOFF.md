# Handoff Note

## Purpose

This document is the current execution handoff for the standalone copy-trading program in the `copy_trader/` repository, with docs now located under `docs/`.

It is intended for the next engineer who needs to continue from the current state without re-discovering what is already implemented, what has been validated, and what is still not ready for production rollout.

---

## Current Status — as of 2026-03-20

**Milestone B (Live Execution + Testnet Validation) is complete.**

The program is no longer just a read-only prototype. The current codebase now includes:

- real Hyperliquid source reads
- real Binance read-side API calls for positions, prices, and exchange filters
- deterministic per-symbol reconciliation decisions
- live execution wiring for Binance Futures `MARKET` orders
- flip-close handling for direction changes
- SQLite persistence for source snapshots, Binance positions, decisions, and execution results
- live-mode auto-downgrade on repeated execution failures
- `--dry-run` override to `observe`
- `once` running a full single `PollingLoop._run_cycle()` path
- signed delta semantics locked down across decision, execution, and SQLite persistence

### Verified Today

- Run from the repository root: `pytest -q tests/unit tests/integration`
- Result: `43 passed`

### Testnet Validation Completed

The current workspace contains evidence that Binance Futures Testnet validation was performed successfully.

Validated behaviors:

- `observe` with `run`: fetches data and emits logs without writes or orders
- `armed` with `run`: writes snapshots and decisions to SQLite without placing orders
- `live` with `run` on Binance Testnet: submits real testnet `MARKET` orders
- `execution_results`: stores accepted and rejected execution outcomes
- cooldown: subsequent cycles emit `SKIP_COOLDOWN` after an accepted order
- auto-downgrade: repeated execution failures downgrade the runtime from `live` to `armed`
- flip path: `REBALANCE_FLIP_CLOSE` path has been exercised and persisted

Local evidence present in the working tree:

- SQLite DB under `data/copy_trading.db`
- `execution_results` rows including accepted `NEW` orders and forced `REJECTED` failures
- decision history rows including `REBALANCE_INCREASE`, `REBALANCE_FLIP_CLOSE`, and `SKIP_COOLDOWN`

Schema reset note:

- SQLite schema is currently managed with a drop-and-recreate policy
- if `reconciliation_decisions` changes, delete the old DB before restart instead of attempting migration

---

## What Works Right Now

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp config.example.yaml config.yaml
cp .env.example .env

python -m copy_trader.main check-config --config config.yaml
python -m copy_trader.main once --config config.yaml
python -m copy_trader.main run --config config.yaml
```

Note: Use `python` after activating the venv; if running without the venv, use `python3` instead.

### Command Behavior

- `check-config`: validates config and exits
- `once`: runs a full single cycle, including decision persistence and execution gating
- `run`: runs the continuous polling loop

### Mode Behavior

- `runtime.mode: observe`
  reads APIs, computes decisions, emits JSON logs, no SQLite writes, no orders
- `runtime.mode: armed`
  writes SQLite snapshots / decisions / execution metadata where applicable, no live orders
- `runtime.mode: live`
  enables executor submission and execution-result persistence

### Effective Safety Controls In The Current Build

- `--dry-run` forces `observe` mode before config validation
- `armed` mode exercises the runtime loop without sending live orders
- SQLite remains non-authoritative for decision logic; it is not read by the trading decision path
- `execution_results` captures accepted and failed execution attempts
- auto-downgrade moves `live -> armed` after repeated execution failures
- cooldown prevents immediate repeated execution after accepted orders

---

## Important Operating Truths

These points matter and should not be misrepresented in later docs or commits:

- `observe -> armed -> live` is currently an **operator workflow requirement**, not a startup-enforced transition rule.
- SQLite is **non-authoritative for decision logic**: trading decisions must never read from SQLite.
- SQLite is **operationally required in armed/live modes**: `runtime.sqlite_enabled=true` is enforced at startup. Write failures degrade to warnings only (per SPEC.md).
- The decision engine is still stateless and must not read from SQLite.
- Mode changes still effectively require restart via config changes.

---

## Completed Epics

| Epic | Title | Status |
|---|---|---|
| 1 | Project Bootstrap | ✅ Done |
| 2 | Configuration & Runtime Wiring | ✅ Done |
| 3 | Hyperliquid Source Reader | ✅ Done |
| 4 | Binance Read-Only Gateway | ✅ Done |
| 5 | Decision Engine | ✅ Done |
| 6 | Observe Mode End-to-End | ✅ Done |
| 7 | SQLite Observability Layer | ✅ Done for current V1 needs |
| 8 | Armed Mode | ✅ Done |
| 9 | Live Execution | ✅ Done |
| 10 | Safety Hardening | ⚠️ Partially done |
| 11 | Testing & Acceptance | ⚠️ Unit + integration tests done, production rollout not done |

---

## Remaining Scope

### Still To Do

- production rollout checklist and runbook
- operator recovery documentation after auto-downgrade
- production configuration review and hardening
- optional additional integration coverage around real-world edge cases

### Explicitly Not Done Yet

- formal production deployment sign-off
- production credential / environment preparation
- production config tuning
- production-sized risk review

### Not In V1 Scope

- multi-wallet support
- multi-symbol live trading
- hedge mode
- hot-reload config
- external alert integrations

---

## Guidance For The Next Engineer

### Do Not Re-Open These Design Decisions

- The reconciliation engine is stateless.
- SQLite is observational only.
- Cooldowns and auto-downgrade counters are ephemeral only.
- Binance one-way mode (`positionSide=BOTH`) is fixed for V1.
- `MARKET` order type is fixed for V1.
- `observe -> armed -> live` should remain an operational procedure, not be retrofitted onto SQLite state.

### Files That Matter Most

- `src/copy_trader/app/service.py`
- `src/copy_trader/runtime/loop.py`
- `src/copy_trader/execution/executor.py`
- `src/copy_trader/execution/flip_handler.py`
- `src/copy_trader/storage/sqlite_store.py`
- `src/copy_trader/strategy/reconciliation.py`
- `src/copy_trader/config/loader.py`
- `src/copy_trader/config/validation.py`

### Files That Reflect Recent Validation

- `tests/integration/test_executor.py`
- `tests/integration/test_loop_execution.py`
- `tests/integration/test_sqlite_store.py`
- `walkthrough.md`

---

## Production Caution

The current workspace appears to include environment-specific runtime artifacts from testnet validation:

- `config.yaml`
- `.env`
- `data/copy_trading.db`

Treat these as local operational artifacts, not as generic defaults.

In particular:

- `binance.testnet: true` in the current config is appropriate for validation, not production rollout
- `auto_downgrade_threshold: 1` is useful for aggressive test validation, not necessarily the right production setting
- any future production deployment should start from a deliberate config review rather than reusing this workspace state blindly

Production configuration is intentionally left for a later owner.

---

## Recommended Next Sequence

1. Leave the current implementation stable unless a concrete defect is found.
2. Write a short operator runbook for:
   - `observe`
   - `armed`
   - `live`
   - auto-downgrade recovery
3. Prepare a production-specific config review:
   - risk limits
   - threshold values
   - logging expectations
   - testnet/mainnet separation
4. If desired, add narrower tests around:
   - unaccepted 2xx Binance order statuses
   - local validation failures
   - flip-close quantity persistence
5. Only after that should anyone consider a production go-live decision.

---

## Bottom Line

The system is now in a **working, testnet-validated live-execution state**.

It should be described as:

- implemented
- testnet validated
- operationally usable for further supervised testing

It should **not** yet be described as:

- production deployed
- production signed off
- production-configured by default

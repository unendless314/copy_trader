# Walkthrough: Epic 9 (Live Execution)

## Changes Made
- Created `execution/models.py` with `ExecutionResult` and error taxonomy (`ExecutionRejectError`, `UnknownStatusError`, etc.).
- Implemented `BinanceExecutor` in `execution/executor.py` for placing `MARKET` orders using FAPI HMAC-SHA256 request signing.
- Added `execution/flip_handler.py` to securely manage `REBALANCE_FLIP_CLOSE` actions, allowing the closing leg of a flip to run first.
- Updated `runtime/loop.py` and `app/service.py` pointing the `BinanceExecutor` into the execution layer.
- Implemented loop tracking of `consecutive_live_execution_failures` to appropriately enforce `auto_downgrade_threshold` safety mechanics.
- Added `--dry-run` flag support via `cli.py` and aligned `once` command logic. 

### Code Review Fixes (2026-03-19)
- **Executor Status Check:** Tightened `BinanceExecutor.submit()` to only accept `NEW`, `FILLED`, or `PARTIALLY_FILLED` statuses with a valid `orderId`. Other end-states (e.g., REJECTED, EXPIRED) returned with HTTP 200 are now accurately marked as `accepted=False` to avoid incorrect loop progression.
- **SQLite Persistence on Error:** Refactored `runtime/loop.py`'s exception path to persist explicitly rejected or network-failed executions into SQLite. Even if the network times out or rejects, the error log drops onto `execution_results`.
- **`--dry-run` Pre-validation Override:** Enhanced `--dry-run` to inject its `observe` mode override into `loader.py` *before* the configuration is validated, successfully checking pure observation-only configurations.
- **Startup Safety Enforcement:** Reverted the strict technical startup guard that previously blocked `live` mode at startup. Following the constraint that SQLite must remain observational only, the transition `observe -> armed -> live` is now officially an operator workflow/runbook requirement rather than a SQLite-history-enforced technical block across process restarts.

## What Was Tested
- Added `tests/integration/test_executor.py` mock testing HTTP execution paths.
- Added `tests/integration/test_loop_execution.py` verifying the loop gracefully handles auto-downgrade when continuous failures occur.
- Added `tests/integration/test_sqlite_store.py` validating that execution results correctly match SQLite persistence schema.
- All 43 (35 existing + 8 new) unit and integration tests are passing.

## Validation Results
- **`observe` with run**: Verified JSON logs emit correct decisions without SQLite or executor side effects.
- **`armed` with run**: Verified snapshots and decisions successfully record to the `copy_trading.db` SQLite store.
- **`live` on testnet with tiny size**: End-to-end execution placed a successful live MARKET order for 0.004 BTC on Binance Testnet.
- **`execution_results`**: Confirmed `NEW` execution result rows with valid exchange `orderId` written to the DB.
- **`cooldown`**: Confirmed immediate post-execution cycle correctly blocked via `SKIP_COOLDOWN`.
- **`auto-downgrade`**: Validated tracking of live cycle failures triggers an automatic `RuntimeMode.armed` downgrade upon meeting the 1 sequence threshold.
- **`flip path`**: Verified cross-zero size differentials emit `REBALANCE_FLIP_CLOSE` executing stepwise convergence to flatten a conflicting direction. All integration tests are verified 43/43 passing.

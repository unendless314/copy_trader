# Operator Runbook

## 1. Purpose and Scope

This runbook describes how to operate the standalone copy-trading program in production and supervised testing environments.

**What this program does:** watches a Hyperliquid source wallet and replicates its perpetual futures positions on Binance Futures, using a stateless reconciliation engine, SQLite for observability, and three runtime modes to enforce operator-controlled trading permission.

**Who this is for:** engineers or traders who have been handed an existing deployment and need to run, monitor, or recover it without re-discovering design decisions.

**V1 constraints:**
- One symbol at a time (BTCUSDT fixed in config)
- One-way position mode only (`positionSide=BOTH`)
- Market orders only
- No hot-reload; mode changes require config edit plus restart

---

## 2. Pre-Flight Checklist

Run this before starting the program or before switching modes.

### Environment Files

| Item | Expected State | How to Verify |
|---|---|---|
| `.env` exists | `cp .env.example .env` has been done | `ls -la .env` |
| `BINANCE_API_KEY` | Set, non-empty | `grep BINANCE_API_KEY .env` |
| `BINANCE_API_SECRET` | Set, non-empty | `grep BINANCE_API_SECRET .env` |
| `HYPERLIQUID_TARGET_WALLET` | Source wallet address set | `grep HYPERLIQUID_TARGET_WALLET .env` |

### Config File (`config.yaml`)

| Item | Expected State | Risk if Wrong |
|---|---|---|
| `binance.testnet` | `true` for testnet validation, `false` for production | Order goes to wrong network |
| `runtime.mode` | Start with `observe` | Premature live trading |
| `runtime.auto_downgrade_enabled` | `true` in production | Failures not contained |
| `runtime.auto_downgrade_threshold` | `3` (recommended for production) | Too aggressive if `1` |
| `runtime.sqlite_enabled` | `true` | No observability if `false` |
| `runtime.sqlite_path` | `./data/copy_trading.db` | DB may fill wrong disk |
| `copy_trade.symbols.whitelist` | Only intended symbols | Wrong symbol traded |
| `risk.max_total_notional_usdt` | Within account risk tolerance | Excessive exposure |
| `risk.max_single_rebalance_notional_usdt` | Within account risk tolerance | Excessive per-cycle exposure |
| `execution.symbol_cooldown_seconds` | `30` or higher | Order spam |

### Binance Read Access

Before enabling `armed` or `live`, verify the API key can read positions:

```bash
python -m copy_trader.main check-config --config config.yaml
```

If this passes, the config is valid and environment variables are set. Note: `check-config` does not call Binance API; it only validates schema and env vars. Binance read access is only exercised when running `once` or `run`.

### Source Connectivity

Confirm Hyperliquid info API is reachable. `SKIP_SOURCE_STALE` is emitted when the source snapshot exceeds `freshness_timeout_seconds` without update — it is a freshness issue, not a position-flat issue. If the source wallet has no open positions, the program proceeds normally and emits `NO_ACTION` or a close decision.

### SQLite Path

Confirm the `data/` directory exists and is writable:

```bash
mkdir -p data && chmod 755 data
```

If SQLite write fails in `armed` or `live`, the program logs a warning and continues without trading halt. This is by design.

### SQLite Schema Reset Policy

This project currently uses a drop-and-recreate SQLite strategy for schema changes.

- when `reconciliation_decisions` columns change, do not reuse the old DB
- delete the old `copy_trading.db` before restart, or point `runtime.sqlite_path` at a new file
- startup now validates the expected schema and fails fast on mismatch instead of attempting a partial upgrade

---

## 3. `once` vs `run`

### `once`

Runs a single reconciliation cycle, produces a decision, persists if `armed` or `live`, and exits.

```bash
python -m copy_trader.main once --config config.yaml
```

Use when:
- Validating a config change before running continuously
- Checking decision output without committing to a loop
- Debugging a specific cycle

### `run`

Runs the continuous polling loop.

```bash
python -m copy_trader.main run --config config.yaml
```

Polling interval is controlled by `source.poll_interval_seconds` (default 10s).

Use when:
- Actively supervising the system
- In production

### Dry Run

Override any mode to `observe` without editing config:

```bash
python -m copy_trader.main run --config config.yaml --dry-run
```

This is useful for watching the loop without risking any writes or orders.

---

## 4. observe → armed → live Operator Procedure

This is a **required operational workflow**, not a technically enforced transition. The program does not block `observe → live` shortcuts, but you should follow the sequence every time.

### Step 1: Start in `observe`

```yaml
runtime:
  mode: observe
```

```bash
python -m copy_trader.main run --config config.yaml
```

Watch logs for 3–5 cycles. Confirm:
- Source wallet position is detected correctly
- Binance position is detected correctly
- Decision outcomes are `NO_ACTION` or match your expectation
- No unexpected `ERROR` outcomes
- If you see repeated `SKIP_SOURCE_STALE`, the source API is unreachable or the info endpoint is timing out (not a position-flat issue)

### Step 2: Promote to `armed`

Edit `config.yaml`:

```yaml
runtime:
  mode: armed
```

```bash
# Restart
python -m copy_trader.main run --config config.yaml
```

Watch logs for 3–5 cycles. Confirm:
- SQLite records appear in `data/copy_trading.db`
- `reconciliation_decisions` table has rows with correct decision strings and signed delta fields
- `execution_results` table exists but has no live orders yet
- No `ERROR` outcomes

To inspect SQLite:

```bash
sqlite3 data/copy_trading.db ".schema"
sqlite3 data/copy_trading.db "SELECT * FROM reconciliation_decisions ORDER BY created_at DESC LIMIT 10;"
```

### Step 3: Promote to `live`

Edit `config.yaml`:

```yaml
runtime:
  mode: live
```

```bash
# Restart
python -m copy_trader.main run --config config.yaml
```

Confirm:
- `execution_results` table starts getting rows where `status IN ('NEW', 'FILLED', 'PARTIALLY_FILLED')` and `exchange_order_id IS NOT NULL`
- Binance Testnet (or mainnet) receives actual orders
- `SKIP_COOLDOWN` appears after an accepted order

---

## 5. Auto-Downgrade Recovery

### What Triggers It

Auto-downgrade (`live → armed`) occurs after `auto_downgrade_threshold` consecutive live execution failures. Only these count toward the counter:

- Deterministic order rejects (insufficient margin, below minimum, invalid params)
- Unknown execution status (timeout, ambiguous exchange response)
- Execution-path internal exceptions

These do **not** count:
- `SKIP_*` outcomes
- Read-side API failures
- Price-guard blocks
- SQLite failures

### How to Recognize It

The terminal emits a strong warning:

```
WARNING: Auto-downgrade triggered: live -> armed. Fix the root cause before restarting in live mode.
```

The program continues running in `armed` mode. Orders stop being placed.

### Recovery Procedure

1. **Do not immediately restart in `live` mode.**

2. Inspect the last execution attempts:
   ```bash
   sqlite3 data/copy_trading.db "SELECT * FROM execution_results ORDER BY created_at DESC LIMIT 10;"
   ```

3. Identify the failure class from `ERROR-TAXONOMY.md`:
   - If deterministic reject → fix config, risk params, or account state
   - If unknown status → check network, API keys, rate limits
   - If internal exception → review logs for stack traces

4. Once root cause is confirmed resolved:

   - Edit `config.yaml` to stay in `armed` for at least one supervised cycle
   - Verify no new failures
   - Then edit `config.yaml` to `runtime.mode: live` and restart

### Counter Reset

The failure counter resets to 0 only when a live order is **unambiguously accepted** by Binance (status `NEW`, `FILLED`, or `PARTIALLY_FILLED` with a valid `orderId`).

---

## 6. Emergency Handling Checklist

### If You See Unexpected Orders

1. **Immediately** change `runtime.mode` to `observe` in `config.yaml`
2. Restart: `python -m copy_trader.main run --config config.yaml`
3. Confirm orders stop
4. Inspect `execution_results` and logs to understand the trigger
   - verify `raw_delta_size` sign matches `capped_delta_size`
   - verify `execution_results.action` matches the signed executable delta
5. Do not return to `armed` or `live` until root cause is found

### If the Program Crashes

1. Check if it exited cleanly or with an exception
2. Review recent logs (stdout/stderr)
3. Check SQLite for the state at time of crash:
   ```bash
   sqlite3 data/copy_trading.db "SELECT * FROM execution_results ORDER BY created_at DESC LIMIT 5;"
   sqlite3 data/copy_trading.db "SELECT * FROM reconciliation_decisions ORDER BY created_at DESC LIMIT 5;"
   ```
4. If crash was in execution path, treat as potential live order ambiguity
5. Start in `observe` to re-establish clean state before promoting

### If Auto-Downgrade Triggers Repeatedly

1. Do not keep restarting in `live` mode
2. Leave in `armed` and collect `execution_results` for analysis
3. Common causes:
   - Insufficient margin → reduce risk params or fund account
   - Position mode mismatch → ensure `positionSide=BOTH` on Binance
   - API key permissions → verify FuturesEnableReading and FuturesEnableTrading
   - Rate limiting → increase `source.poll_interval_seconds`

### If Source Data Goes Stale

- Program emits `SKIP_SOURCE_STALE`
- No orders placed
- Observation continues
- This is normal behavior; no action required unless it persists

### If Binance Read Fails

- Program emits `SKIP_DATA_UNAVAILABLE`
- No orders placed
- Loop continues
- If persistent, check API key validity and account status

### Hard Stop

There is no separate kill-switch state. To hard-stop:

```bash
# Find the process
ps aux | grep copy_trader

# Kill it
kill <PID>
```

Or use `Ctrl+C` if running in the foreground.

---

## 7. Testnet vs Production Cautions

### Testnet Configuration

```yaml
binance:
  testnet: true
```

Testnet orders use Binance Testnet infrastructure, not real funds. Use this for:
- Initial validation
- Decision quality verification
- Auto-downgrade recovery drills

Testnet has separate wallet and API key requirements. Ensure `BINANCE_API_KEY` and `BINANCE_API_SECRET` are from [testnet.binance.vision](https://testnet.binance.vision/).

### Production Configuration

```yaml
binance:
  testnet: false
```

Before switching to production:

1. Run through `observe → armed → live` sequence on testnet first
2. Review all `risk.*` parameters against actual account size
3. Set `auto_downgrade_threshold` to a value you are comfortable with (default 3)
4. Use a fresh API key with only Futures trading permissions
5. Confirm `sqlite_path` points to a durable location
6. Set up log rotation or external log collection

### Testnet → Production Checklist

| Item | Testnet | Production |
|---|---|---|
| `binance.testnet` | `true` | `false` |
| API Keys | Testnet keys | Mainnet keys |
| Position size | Small (validation) | Reviewed risk params |
| `auto_downgrade_threshold` | Can be `1` for fast testing | `3` recommended |
| Logs | Console ok | External collection recommended |
| Backup | Optional | `copy_trading.db` should be backed up |

### Never Do These in Production

- Reuse testnet `config.yaml` without changing `binance.testnet: false`
- Set `runtime.mode: live` without running `observe` and `armed` first
- Ignore auto-downgrade warnings and immediately restart in `live`
- Set `runtime.auto_downgrade_enabled: false` in production
- Use the same API key for testnet and production

---

## Quick Reference

```bash
# Validate config
python -m copy_trader.main check-config --config config.yaml

# Single cycle
python -m copy_trader.main once --config config.yaml

# Continuous loop
python -m copy_trader.main run --config config.yaml

# Force observe (no writes, no orders)
python -m copy_trader.main run --config config.yaml --dry-run

# Inspect SQLite
sqlite3 data/copy_trading.db "SELECT * FROM reconciliation_decisions ORDER BY created_at DESC LIMIT 10;"
sqlite3 data/copy_trading.db "SELECT * FROM execution_results ORDER BY created_at DESC LIMIT 10;"
sqlite3 data/copy_trading.db "SELECT * FROM source_snapshots ORDER BY created_at DESC LIMIT 5;"
```

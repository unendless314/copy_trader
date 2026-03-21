# Production Configuration Review

## Purpose

This document captures the delta between the distributed config template (`config.example.yaml`) and the operational artifact left by testnet validation (`config.yaml`), identifies which values are production-safe and which require deliberate review, and lists open questions that must be resolved by the account owner before go-live.

---

## Config Delta Summary

Only two values differ between `config.example.yaml` and `config.yaml`:

| Path | config.example.yaml | config.yaml | Risk Implication |
|---|---|---|---|
| `binance.testnet` | `false` | `true` | Live orders go to wrong network if not changed |
| `runtime.auto_downgrade_threshold` | `3` | `1` | Overly aggressive downgrade in production |

All other values are identical.

---

## Risk Assessment by Section

### runtime

| Parameter | Current Value | Assessment | Recommendation |
|---|---|---|---|
| `mode` | `observe` | Correct default | Keep `observe` until ready |
| `auto_downgrade_threshold` | `1` (local) / `3` (example) | **Local value is too aggressive for production.** Threshold 1 means any single ambiguous execution result triggers downgrade, which can happen in flaky network conditions. | Use `3` for production |
| `auto_downgrade_enabled` | `true` | Correct — must remain on | Keep |
| `sqlite_enabled` | `true` | Correct | Keep |
| `sqlite_path` | `./data/copy_trading.db` | Local working directory. No durability guarantee if host crashes. | Consider mounting a persistent volume; add to backup list |

### binance

| Parameter | Current Value | Assessment | Recommendation |
|---|---|---|---|
| `testnet` | `true` (local) | **Wrong for production.** `false` is the correct production value. | Must flip to `false` before go-live |
| `position_mode` | `ONEWAY` | Correct for V1 | Keep |
| `leverage.default` | `2` | No validation that this matches account max leverage | Confirm on Binance Futures settings page |
| `price_guard.max_deviation_bps` | `15` (15 bps = 0.15%) | Reasonable starting point for small copiers. If the account owner is sensitive to fill quality, consider tightening to `10` (0.10%). Do not set too tight without active monitoring — price guard blocks are not counted as execution failures but will suppress rebalancing. |

### risk

All `risk.*` values are identical between example and local config. They were validated at testnet scale only. **None have been validated at production account scale.**

> **Important — Runtime Enforcement Scope:** Among the threshold controls in this section, the runtime actively enforces `max_single_rebalance_notional_usdt`, `max_delta_convergence_ratio`, `min_rebalance_pct`, and `min_rebalance_notional_usdt`. The remaining two — `max_symbol_notional_usdt` and `max_total_notional_usdt` — are defined in the config model but **not enforced at runtime**; do not rely on them as active production risk caps. `copy_ratio` is under `copy_trade.*` and is an operational sizing input, not a protective cap.

| Parameter | Runtime Enforced? | Current Value | Production Concern |
|---|---|---|---|
| `max_symbol_notional_usdt` | No | `1000` | Defined in config model but not enforced at runtime. **Do not rely on this as a cap.** |
| `max_total_notional_usdt` | No | `1000` | Defined in config model but not enforced at runtime. **Do not rely on this as a cap.** |
| `max_single_rebalance_notional_usdt` | **Yes** | `300` | Per-cycle notional cap (one of two active caps). Take the stricter of this and `max_delta_convergence_ratio` per cycle. |
| `max_delta_convergence_ratio` | **Yes** | `0.30` (30%) | Per-cycle fractional cap (the other active cap). Take the stricter of this and `max_single_rebalance_notional_usdt` per cycle. |
| `min_rebalance_pct` | **Yes** | `0.02` (2%) | Drift percentage threshold. Used with `min_rebalance_notional_usdt` — rebalance only if delta exceeds **either** threshold. |
| `min_rebalance_notional_usdt` | **Yes** | `100` | Minimum delta notional to trigger rebalance. For small accounts $100 may be too high and suppress all rebalancing; for large accounts it may be too low and trigger excessive small orders. |
| `copy_ratio` | No | `0.01` (1%) | Configured source size ratio. Confirmed as intentional; not enforced as a runtime cap. |

### source

All values are identical to example. No production-specific concerns, but the source wallet address must be verified as the correct production source.

---

## Recommended Production Baseline

Starting from `config.example.yaml`, apply these changes for production:

```yaml
runtime:
  mode: observe          # stays observe; change only after observe+armed validation
  auto_downgrade_threshold: 3    # changed from example default (already correct in template)

binance:
  testnet: false         # changed from local artifact; critical for production
  # leverage.default: confirm against account MAX leverage before go-live

risk:
  # Review all risk.* values with actual account size and risk tolerance.
  # Note: max_symbol_notional_usdt and max_total_notional_usdt are NOT enforced
  # at runtime — treat them as documentation intent only.
  # Active caps are max_single_rebalance_notional_usdt and max_delta_convergence_ratio,
  # which are applied together (take the stricter per cycle).
  max_single_rebalance_notional_usdt: <account-owner-decision>
  max_delta_convergence_ratio:    <account-owner-decision>
  min_rebalance_pct:              <account-owner-decision>
  min_rebalance_notional_usdt:    <account-owner-decision>
```

---

## Open Questions for Account Owner

These cannot be answered by the engineering team and must be resolved before production go-live:

1. **Account size and leverage**
   - What is the total USDT balance in the Binance Futures account?
   - What is the account's maximum allowed leverage?
   - Does `leverage.default: 2` exceed the account limit?

2. **Risk tolerance — must review before go-live**
   - `max_single_rebalance_notional_usdt`: maximum notional per single rebalance cycle. The actual order cap is the **stricter** of this and `max_delta_convergence_ratio * delta`.
   - `max_delta_convergence_ratio`: maximum fraction of the delta to execute per cycle (0.30 = 30%). Set lower for more gradual convergence.
   - `min_rebalance_pct`: minimum delta as a percentage of source size (0.02 = 2%). Rebalance only triggers if delta exceeds **either** this or `min_rebalance_notional_usdt`.
   - `min_rebalance_notional_usdt`: minimum delta notional to trigger rebalance. $100 may be too high for small accounts (suppresses all rebalancing) or too low for large accounts (triggers excessive small orders).
   - `price_guard.max_deviation_bps`: reject if executable price deviates more than this from reference price. Default 15 bps is reasonable; tighten to 10 bps if fill quality is critical.

3. **Source wallet**
   - Is `HYPERLIQUID_TARGET_WALLET` the correct production source wallet?
   - Has the source wallet been audited to confirm it trades only intended strategies?

4. **External log collection**
   - Are console logs sufficient, or is there a requirement to persist logs to a file with rotation?
   - Is there a centralized log aggregation system to integrate with?

5. **SQLite backup**
   - Is `copy_trading.db` included in the host backup schedule?
   - Is there a retention policy for the SQLite file?
   - If the DB is lost, is the operational history acceptable to lose?

6. **Auto-downgrade threshold**
   - Is `3` the right balance, or does the account owner prefer tighter/looser containment?
   - Is `auto_downgrade_enabled: true` acceptable, or does the operator want to receive alerts instead of automatic downgrade?

7. **Notification on auto-downgrade**
   - If the system auto-downgrades while no operator is watching, is there an alert mechanism?
   - Is Telegram/Slack/email alerting required for production?

---

## Deployment Pre-Check

Before starting in production, confirm:

- [ ] `binance.testnet: false` is set
- [ ] `runtime.mode: observe` on first startup
- [ ] `runtime.auto_downgrade_threshold: 3` (or your chosen value)
- [ ] All `risk.*` values reviewed against account size
- [ ] `leverage.default` confirmed against Binance account settings
- [ ] `sqlite_path` on a persistent, backed-up volume
- [ ] Log output captured or rotated
- [ ] Go through `observe → armed → live` sequence before enabling live trading

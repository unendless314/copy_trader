# copy_trader

A standalone personal-use copy-trading program.  
Follows a Hyperliquid vault wallet and synchronises its net position exposure to Binance perpetual using periodic snapshot reconciliation.

## Quick Start

### 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure

```bash
cp config.example.yaml config.yaml
cp .env.example .env
# Edit config.yaml: set runtime.mode, copy_ratio, risk limits
# Edit .env: add your Binance API credentials and Hyperliquid wallet address
```

### 3. Run

```bash
python -m copy_trader.main --config config.yaml
```

Optional CLI commands (after `pip install -e .`):

```bash
copy-trader run          --config config.yaml   # same as above
copy-trader check-config --config config.yaml   # validate config only, then exit
copy-trader once         --config config.yaml   # run one cycle, then exit
```

## Runtime Modes

| Mode      | Fetches data | Writes SQLite | Places orders |
|-----------|:-----------:|:-------------:|:-------------:|
| `observe` | ✅           | ❌             | ❌             |
| `armed`   | ✅           | ✅             | ❌             |
| `live`    | ✅           | ✅             | ✅             |

**Recommended operator flow:** `observe` → `armed` → `live`.
Jumping directly from `observe` to `live` should be avoided for safety. This is an operator runbook requirement, not currently technically enforced at startup.

## Project Structure

```
src/copy_trader/
  config/       YAML + .env loading, validation, typed models
  runtime/      Runtime modes, main poll loop, cooldown manager
  source/       Hyperliquid wallet snapshot reader
  exchange/     Binance position/price fetch and order submission
  strategy/     Target calculator, decision engine, price guard, risk policy
  execution/    Order executor, flip handler
  storage/      SQLite observation store (non-authoritative)
  logging/      JSON Lines structured logging
  app/          App service wiring
  main.py       Entry point
  cli.py        CLI argument parsing
tests/
  unit/
  integration/
```

## Key Design Decisions

- **Stateless reconciliation:** every cycle computes deltas from fresh API snapshots; SQLite is never read by trading logic.
- **Ephemeral-only state:** cooldown timestamps and auto-downgrade counters live in process memory and reset on restart.
- **Risk-first:** price guard, drift threshold, stepwise convergence, and max notional caps all gate execution before any order is submitted.
- **Explicit mode control:** trading permission is gated by a single `runtime.mode` config value; mode changes require restart.

## Documentation

Full specification lives in `docs/`:

- `PRD.md` – product requirements
- `SPEC.md` – technical specification
- `DECISION-ENGINE.md` – reconciliation rule table
- `RUNTIME-STATE-MACHINE.md` – mode semantics and cycle workflow
- `API-CONTRACTS.md` – Hyperliquid and Binance API contracts
- `EPHEMERAL-STATE.md` – in-memory state contract
- `ERROR-TAXONOMY.md` – failure classification and auto-downgrade policy
- `LOGGING-FORMAT.md` – JSON Lines log schema
- `CONFIG-SCHEMA.md` – full config field definitions and validation rules
- `HANDOFF.md` – epic breakdown and delivery roadmap

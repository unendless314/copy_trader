# Project Skeleton Proposal

## Goal

This document proposes a minimal standalone project layout for the copy-trading program.

The layout is designed for:

- simple local operation
- clean separation between source, decision, execution, and observability
- easy testing
- low framework coupling

## Proposed Structure

```text
copy_trader/
  pyproject.toml
  README.md
  .env.example
  config.example.yaml
  src/
    copy_trader/
      __init__.py
      main.py
      cli.py
      config/
        __init__.py
        loader.py
        models.py
        validation.py
      runtime/
        __init__.py
        modes.py
        loop.py
        cooldown.py
      source/
        __init__.py
        hyperliquid_reader.py
        models.py
        normalization.py
      exchange/
        __init__.py
        binance_client.py
        models.py
        precision.py
        pricing.py
      strategy/
        __init__.py
        target_calculator.py
        reconciliation.py
        price_guard.py
        risk_policy.py
        decision_types.py
      execution/
        __init__.py
        executor.py
        flip_handler.py
      storage/
        __init__.py
        sqlite_store.py
        schema.py
      logging/
        __init__.py
        setup.py
        events.py
      app/
        __init__.py
        service.py
  tests/
    unit/
      test_config.py
      test_hyperliquid_reader.py
      test_target_calculator.py
      test_reconciliation.py
      test_price_guard.py
      test_runtime_modes.py
    integration/
      test_binance_gateway.py
      test_sqlite_store.py
```

## Module Responsibilities

### `config/`

- load YAML and `.env`
- validate types and required fields
- expose typed settings to the app

### `runtime/`

- define runtime modes
- control per-cycle execution order
- manage cooldown state

### `source/`

- fetch Hyperliquid wallet snapshots
- normalize source symbols and sizes
- validate source freshness

### `exchange/`

- fetch Binance positions
- fetch price references
- apply precision and minimum-trade logic
- submit market orders

### `strategy/`

- compute target position from source size and copy ratio
- evaluate thresholds
- apply price guard
- decide increase, reduce, close, or flip

### `execution/`

- convert decisions into executable exchange actions
- enforce close-then-open for flips

### `storage/`

- persist snapshots
- persist decisions
- persist order results

### `logging/`

- define structured log format
- standardize warning and error events

### `app/`

- wire all modules together
- expose one service object that drives the loop

## Entry Point Recommendation

Suggested entry command:

```bash
python -m copy_trader.main --config config.yaml
```

Optional later commands:

- `copy-trader run --config config.yaml`
- `copy-trader check-config --config config.yaml`
- `copy-trader once --config config.yaml`

## V1 Implementation Order

1. `config/`
2. `source/`
3. `exchange/` read-only position and price fetch
4. `strategy/` target and reconciliation logic
5. `runtime/` observe loop
6. `storage/` SQLite observation layer
7. `execution/` live order placement

## Design Constraints

- keep runtime mode as the only execution gate
- keep reconciliation stateless
- keep SQLite observational, not authoritative
- keep source reader independent from Binance logic
- keep BTCUSDT as the only active live symbol in V1

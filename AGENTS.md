# Repository Guidelines

## Project Structure & Module Organization

This repository uses a `src/` layout. Application code lives under `src/copy_trader/`, split by responsibility: `config/` for YAML and `.env` loading, `source/` for Hyperliquid reads, `exchange/` for Binance access, `strategy/` for reconciliation logic, `execution/` for order handling, `storage/` for SQLite persistence, `runtime/` for loop control, and `app/` for service wiring. Tests live in `tests/unit/` and `tests/integration/`. Operational and design docs are under `docs/`.

## Build, Test, and Development Commands

Use Python 3.13.x.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m copy_trader.main --config config.yaml
copy-trader check-config --config config.yaml
pytest -q
ruff check src tests
```

- `pip install -e ".[dev]"`: installs the package plus test and lint tools.
- `python -m copy_trader.main --config config.yaml`: runs the main program.
- `copy-trader check-config --config config.yaml`: validates config without starting the loop.
- `pytest -q`: runs all tests.
- `ruff check src tests`: runs import/order and basic lint checks.

## Coding Style & Naming Conventions

Follow PEP 8 with 4-space indentation and a maximum line length of 120 characters. Module and file names use `snake_case`; classes use `PascalCase`; functions, variables, and test fixtures use `snake_case`. Keep reconciliation and runtime logic deterministic and avoid reading SQLite in decision paths. Prefer small, typed functions and explicit models over loosely structured dicts.

## Testing Guidelines

The test stack is `pytest`, `pytest-asyncio`, `pytest-cov`, and `respx`. Name tests as `test_*.py` and keep unit tests in `tests/unit/` and cross-module or persistence flows in `tests/integration/`. Run focused checks with commands such as `pytest -q tests/unit` or `pytest -q tests/integration`. Add tests for any change that affects decision logic, execution gating, config validation, or SQLite persistence.

## Commit & Pull Request Guidelines

This workspace does not currently include `.git` history, so existing commit conventions cannot be inferred directly. Use short, imperative commit messages such as `Fix cooldown downgrade handling` or `Add integration coverage for flip close`. Pull requests should describe the behavioral change, list validation performed, note config or runbook impacts, and include log snippets or command output when operator-facing behavior changes.

## Security & Configuration Tips

Do not commit live credentials or populated `.env` files. Treat `config.yaml` and `data/copy_trading.db` as local operational artifacts. Validate mode changes carefully: `observe -> armed -> live` remains the expected operator sequence.

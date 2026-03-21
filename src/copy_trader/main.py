"""
main.py

Entry point for the standalone copy-trading program.

Usage:
    python -m copy_trader.main --config config.yaml
    copy-trader run --config config.yaml
    copy-trader check-config --config config.yaml
    copy-trader once --config config.yaml
"""

from __future__ import annotations

import asyncio
import sys

from copy_trader.cli import parse_args
from copy_trader.config.loader import ConfigValidationError, load_config
from copy_trader.config.models import RuntimeMode
from copy_trader.logging.setup import configure_logging


def run_cli(args) -> None:
    overrides = {}
    if args.dry_run:
        overrides["runtime"] = {"mode": "observe"}

    try:
        cfg = load_config(args.config, env_path=args.env, overrides=overrides)
    except (FileNotFoundError, ConfigValidationError, ValueError) as exc:
        # Fatal config errors: print clearly and exit
        print(f"[FATAL] Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    configure_logging(
        log_level=cfg.runtime.log_level.value,
    )

    if args.command == "check-config":
        print(f"Configuration valid. Mode: {cfg.runtime.mode.value}")
        sys.exit(0)

    from copy_trader.app.service import CopyTraderService

    service = CopyTraderService(cfg)

    if args.command == "once":
        asyncio.run(_run_once(service))
    else:
        asyncio.run(service.start())


async def _run_once(service) -> None:
    """Initialize and run exactly one reconciliation cycle, then exit."""
    from copy_trader.exchange.binance_client import BinanceClient
    from copy_trader.runtime.modes import mode_allows_sqlite

    cfg = service._cfg
    await service._exchange.preload_filters(cfg.copy_trade.symbols.whitelist)

    if mode_allows_sqlite(cfg.runtime.mode) and cfg.runtime.sqlite_enabled:
        from copy_trader.storage.sqlite_store import SQLiteStore
        service._store = SQLiteStore(cfg.runtime.sqlite_path)
        await service._store.initialize()
        service._loop.sqlite_store = service._store

    service._loop._collect_decisions = service._collect_decisions
    await service._loop._run_cycle()
    print("One-shot cycle complete.")


if __name__ == "__main__":
    args = parse_args()
    run_cli(args)

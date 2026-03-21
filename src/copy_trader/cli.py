"""
cli.py

Command-line argument parsing.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copy-trader",
        description="Hyperliquid → Binance perpetual copy trader",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    def _add_config(p):
        p.add_argument("--config", required=True, metavar="PATH", help="Path to config.yaml")
        p.add_argument("--env", default=None, metavar="PATH", help="Path to .env file (default: .env in cwd)")
        p.add_argument("--dry-run", action="store_true", help="Override mode to 'observe' (no execution or DB writes)")

    run_p = sub.add_parser("run", help="Start the copy trader (default command)")
    _add_config(run_p)

    check_p = sub.add_parser("check-config", help="Validate config then exit")
    _add_config(check_p)

    once_p = sub.add_parser("once", help="Run one cycle then exit")
    _add_config(once_p)

    # Support bare `python -m copy_trader.main --config ...` without subcommand
    parser.add_argument("--config", default=None, metavar="PATH")
    parser.add_argument("--env", default=None, metavar="PATH")
    parser.add_argument("--dry-run", action="store_true")

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Default to "run" if no subcommand given
    if args.command is None:
        args.command = "run"
    if args.config is None:
        parser.error("--config is required")
    return args


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `copy-trader` script installed by pyproject.toml."""
    from copy_trader.main import run_cli
    args = parse_args(argv)
    run_cli(args)

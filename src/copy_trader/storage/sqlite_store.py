"""
storage/sqlite_store.py

Write-only SQLite observation store per SPEC.md and ERROR-TAXONOMY.md.

Key constraints:
- SQLite is non-authoritative: trading logic must never read from here.
- Write failures must not block trading; they generate warnings only.
- All writes are synchronous (sqlite3 stdlib) run in a thread pool to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from copy_trader.exchange.models import ActualPosition
from copy_trader.source.models import SourcePosition
from copy_trader.storage.schema import ALL_SCHEMAS
from copy_trader.strategy.reconciliation import DecisionRecord

logger = logging.getLogger(__name__)


class SQLiteStore:
    """
    Async wrapper around a synchronous SQLite3 database.

    All blocking DB calls are offloaded to the default thread-pool executor
    to avoid stalling the asyncio event loop.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create tables if they do not exist. Call once at startup."""
        await asyncio.get_event_loop().run_in_executor(None, self._sync_initialize)

    def _sync_initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self._db_path), timeout=30.0)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA busy_timeout=30000;")
        for ddl in ALL_SCHEMAS:
            con.execute(ddl)
        con.commit()
        con.close()

    def _get_connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._db_path), timeout=30.0)
        con.execute("PRAGMA busy_timeout=30000;")
        return con

    # ------------------------------------------------------------------
    # Insert APIs (silent on failure per ERROR-TAXONOMY.md §6)
    # ------------------------------------------------------------------

    async def persist_source_snapshot(self, pos: SourcePosition, wallet: str) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._sync_insert_source_snapshot, pos, wallet)
        except Exception as exc:
            logger.warning("SQLite write failed (source_snapshot): %s", exc)

    async def persist_binance_position(self, pos: ActualPosition) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._sync_insert_binance_position, pos)
        except Exception as exc:
            logger.warning("SQLite write failed (binance_position): %s", exc)

    async def persist_decision(self, record: DecisionRecord) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._sync_insert_decision, record)
        except Exception as exc:
            logger.warning("SQLite write failed (reconciliation_decision): %s", exc)

    async def persist_execution_result(
        self,
        cycle_id: str,
        symbol: str,
        action: str,
        requested_size: str,
        submitted_size: str | None,
        status: str,
        exchange_order_id: str | None,
        error_message: str | None,
    ) -> None:
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                self._sync_insert_execution_result,
                cycle_id,
                symbol,
                action,
                requested_size,
                submitted_size,
                status,
                exchange_order_id,
                error_message,
            )
        except Exception as exc:
            logger.warning("SQLite write failed (execution_result): %s", exc)

    # ------------------------------------------------------------------
    # Synchronous implementations (run in thread pool)
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    def _sync_insert_source_snapshot(self, pos: SourcePosition, wallet: str) -> None:
        con = self._get_connection()
        try:
            con.execute(
                "INSERT INTO source_snapshots "
                "(wallet, symbol, side, size, entry_price, source_timestamp, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    wallet,
                    pos.symbol,
                    pos.side,
                    str(pos.size),
                    str(pos.entry_price) if pos.entry_price else None,
                    pos.source_timestamp.isoformat(),
                    self._now(),
                ),
            )
            con.commit()
        finally:
            con.close()

    def _sync_insert_binance_position(self, pos: ActualPosition) -> None:
        con = self._get_connection()
        try:
            con.execute(
                "INSERT INTO binance_positions (symbol, side, size, entry_price, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (
                    pos.symbol,
                    pos.side,
                    str(pos.size),
                    str(pos.entry_price) if pos.entry_price else None,
                    pos.binance_timestamp.isoformat() if pos.binance_timestamp else self._now(),
                ),
            )
            con.commit()
        finally:
            con.close()

    def _sync_insert_decision(self, record: DecisionRecord) -> None:
        con = self._get_connection()
        try:
            con.execute(
                "INSERT INTO reconciliation_decisions "
                "(cycle_id, runtime_mode, symbol, source_size, target_size, actual_size, "
                "delta_size, decision, block_reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.cycle_id,
                    record.runtime_mode,
                    record.symbol,
                    str(record.source_size),
                    str(record.target_size),
                    str(record.actual_size),
                    str(record.raw_delta_size),
                    record.decision_type.value,
                    record.block_reason,
                    self._now(),
                ),
            )
            con.commit()
        finally:
            con.close()

    def _sync_insert_execution_result(
        self,
        cycle_id,
        symbol,
        action,
        requested_size,
        submitted_size,
        status,
        exchange_order_id,
        error_message,
    ) -> None:
        con = self._get_connection()
        try:
            con.execute(
                "INSERT INTO execution_results "
                "(cycle_id, symbol, action, requested_size, submitted_size, "
                "status, exchange_order_id, error_message, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cycle_id,
                    symbol,
                    action,
                    requested_size,
                    submitted_size,
                    status,
                    exchange_order_id,
                    error_message,
                    self._now(),
                ),
            )
            con.commit()
        finally:
            con.close()

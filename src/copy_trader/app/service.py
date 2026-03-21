"""
app/service.py

Application service: wires all modules together and drives the polling loop.
This is the top-level object that main.py creates and runs.
"""

from __future__ import annotations

import asyncio
import logging

from copy_trader.config.models import AppConfig
from copy_trader.exchange.binance_client import BinanceClient
from copy_trader.exchange.models import ActualPosition
from copy_trader.execution.executor import BinanceExecutor
from copy_trader.logging.events import EventLogger
from copy_trader.runtime.cooldown import CooldownManager
from copy_trader.runtime.loop import PollingLoop
from copy_trader.runtime.modes import mode_allows_sqlite
from copy_trader.source.hyperliquid_reader import HyperliquidReader, SourceReadError
from copy_trader.source.normalization import SourceNormalizationError
from copy_trader.storage.sqlite_store import SQLiteStore
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.reconciliation import DecisionRecord, ReconciliationEngine

logger = logging.getLogger(__name__)


class CopyTraderService:
    """
    Wires source, exchange, strategy, storage, logging, and runtime together.

    Implements the cycle orchestration that loop.py delegates to (_collect_decisions).
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._source = HyperliquidReader(cfg)
        self._exchange = BinanceClient(cfg)
        self._engine = ReconciliationEngine(cfg)
        self._event_logger = EventLogger(cfg.runtime.mode)
        self._loop = PollingLoop(cfg)

        # Inject collaborators into loop
        self._loop.source_reader = self._source
        self._loop.binance_gateway = self._exchange
        self._loop.decision_engine = self._engine
        self._loop.event_logger = self._event_logger
        self._loop.executor = BinanceExecutor(cfg)

        self._store: SQLiteStore | None = None
        if mode_allows_sqlite(self._cfg.runtime.mode) and self._cfg.runtime.sqlite_enabled:
            self._store = SQLiteStore(self._cfg.runtime.sqlite_path)


    async def start(self) -> None:
        """Initialize and run until interrupted."""
        logger.info("CopyTraderService starting, mode=%s", self._cfg.runtime.mode.value)

        # Preload Binance trading filters (fatal if this fails)
        symbols = self._cfg.copy_trade.symbols.whitelist
        await self._exchange.preload_filters(symbols)

        # Initialize SQLite if enabled and perform startup safety checks
        if self._store:
            await self._store.initialize()
            self._loop.sqlite_store = self._store

        # Override _collect_decisions to use real collaborators
        self._loop._collect_decisions = self._collect_decisions

        await self._loop.run()

    async def _collect_decisions(self, cycle_id: str) -> list:
        """
        Full cycle: fetch → normalize → decide (per RUNTIME-STATE-MACHINE.md steps 1-8).
        """
        cfg = self._cfg
        decisions = []

        # Step 1-2: Fetch and validate source snapshot
        try:
            snapshot = await self._source.fetch()
            is_fresh = self._source.is_fresh(snapshot, cfg.source.freshness_timeout_seconds)
        except (SourceReadError, SourceNormalizationError) as exc:
            self._event_logger.warning(
                "READ_RETRY_BACKOFF",
                f"Source read failed, skipping cycle: {exc}",
            )
            # Emit SKIP_DATA_UNAVAILABLE for every symbol: upholds one-outcome-per-symbol
            # contract and keeps SQLite history hole-free. Also emit as decision log events.
            synthetic = [
                _make_skip_record(
                    symbol=sym,
                    cycle_id=cycle_id,
                    runtime_mode=self._loop.mode.value,
                    reason=DecisionType.SKIP_DATA_UNAVAILABLE,
                    block_reason=f"source_read_failed: {type(exc).__name__}",
                )
                for sym in cfg.copy_trade.symbols.whitelist
            ]
            for rec in synthetic:
                self._event_logger.decision(rec)
            return synthetic

        # Persist source snapshots if allowed
        if self._store and cfg.observability.persist_source_snapshots:
            for pos in snapshot.positions.values():
                await self._store.persist_source_snapshot(pos, snapshot.wallet)

        for symbol in cfg.copy_trade.symbols.whitelist:
            try:
                # Steps 3-4: Fetch Binance position and prices
                actual = await self._exchange.fetch_position(symbol)
                price = await self._exchange.fetch_price(symbol)
                filters = self._exchange.get_filters(symbol)

                # Persist Binance snapshot if allowed
                if self._store and cfg.observability.persist_binance_positions:
                    await self._store.persist_binance_position(actual)

                # Steps 5-8: Run decision engine
                source_pos = snapshot.get(symbol)
                record = self._engine.evaluate(
                    symbol=symbol,
                    source_position=source_pos,
                    actual_position=actual,
                    price_snapshot=price,
                    filters=filters,
                    cooldown=self._loop.cooldown,
                    is_source_fresh=is_fresh,
                    cycle_id=cycle_id,
                    runtime_mode=self._loop.mode,
                )

                self._event_logger.decision(record)
                decisions.append(record)

            except Exception as exc:
                self._event_logger.error(
                    "CYCLE_SYMBOL_ERROR",
                    f"Error processing {symbol}: {exc}",
                    symbol=symbol,
                    exception_type=type(exc).__name__,
                )
                # Emit synthetic record to maintain one-outcome-per-symbol contract
                synthetic_rec = _make_skip_record(
                    symbol=symbol,
                    cycle_id=cycle_id,
                    runtime_mode=self._loop.mode.value,
                    reason=DecisionType.SKIP_DATA_UNAVAILABLE,
                    block_reason=f"cycle_error: {type(exc).__name__}",
                )
                self._event_logger.decision(synthetic_rec)
                decisions.append(synthetic_rec)

        return decisions


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def _make_skip_record(
    symbol: str,
    cycle_id: str,
    runtime_mode: str,
    reason: DecisionType,
    block_reason: str,
) -> DecisionRecord:
    """
    Build a synthetic DecisionRecord for failure cases where no engine evaluation
    was possible. Upholds the one-outcome-per-symbol contract per DECISION-ENGINE.md.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    return DecisionRecord(
        cycle_id=cycle_id,
        runtime_mode=runtime_mode,
        symbol=symbol,
        source_size=Decimal(0),
        target_size=Decimal(0),
        actual_size=Decimal(0),
        raw_delta_size=Decimal(0),
        capped_delta_size=Decimal(0),
        decision_type=reason,
        block_reason=block_reason,
        reference_price=None,
        executable_price=None,
        price_deviation_bps=None,
        created_at=datetime.now(tz=timezone.utc),
    )

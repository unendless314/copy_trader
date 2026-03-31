from __future__ import annotations

import importlib.util
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "pnl_report.py"
    spec = importlib.util.spec_from_file_location("pnl_report", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_load_trades_uses_only_accepted_execution_rows_and_prefers_executable_price():
    module = _load_module()
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE execution_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            requested_size TEXT NOT NULL,
            submitted_size TEXT,
            status TEXT NOT NULL,
            exchange_order_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE reconciliation_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id TEXT NOT NULL,
            runtime_mode TEXT NOT NULL,
            symbol TEXT NOT NULL,
            source_size TEXT NOT NULL,
            target_size TEXT NOT NULL,
            actual_size TEXT NOT NULL,
            raw_delta_size TEXT NOT NULL,
            capped_delta_size TEXT NOT NULL,
            decision TEXT NOT NULL,
            block_reason TEXT,
            reference_price TEXT,
            executable_price TEXT,
            price_deviation_bps TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    conn.execute(
        """
        INSERT INTO execution_results
        (cycle_id, symbol, action, requested_size, submitted_size, status, exchange_order_id, error_message, created_at)
        VALUES
        ('c1', 'BTCUSDT', 'BUY', '0.01', '0.01', 'NEW', '1001', NULL, '2026-03-31T01:00:00+00:00'),
        ('c2', 'BTCUSDT', 'SELL', '0.02', NULL, 'REJECTED', NULL, 'rejected', '2026-03-31T02:00:00+00:00'),
        ('c3', 'BTCUSDT', 'SELL', '0.03', '0.03', 'FILLED', '1003', NULL, '2026-03-31T03:00:00+00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO reconciliation_decisions
        (cycle_id, runtime_mode, symbol, source_size, target_size, actual_size, raw_delta_size, capped_delta_size,
         decision, block_reason, reference_price, executable_price, price_deviation_bps, created_at)
        VALUES
        ('c1', 'live', 'BTCUSDT', '0', '0', '0', '0.01', '0.01', 'REBALANCE_INCREASE', NULL, '70000', '69990', NULL, '2026-03-31T01:00:00+00:00'),
        ('c2', 'live', 'BTCUSDT', '0', '0', '0', '-0.02', '-0.02', 'REBALANCE_REDUCE', NULL, '70100', '70095', NULL, '2026-03-31T02:00:00+00:00'),
        ('c3', 'live', 'BTCUSDT', '0', '0', '0', '-0.03', '-0.03', 'REBALANCE_REDUCE', NULL, '70200', NULL, NULL, '2026-03-31T03:00:00+00:00')
        """
    )

    trades, skipped_rows = module.load_trades(conn, "BTCUSDT")

    assert skipped_rows == 0
    assert len(trades) == 2
    assert [trade.cycle_id for trade in trades] == ["c1", "c3"]
    assert trades[0].price == Decimal("69990")
    assert trades[0].price_source == "executable_price"
    assert trades[1].price == Decimal("70200")
    assert trades[1].price_source == "reference_price"


def test_compute_pnl_handles_short_inventory_fifo():
    module = _load_module()
    trades = [
        module.TradeRecord(
            cycle_id="c1",
            timestamp=module.datetime.fromisoformat("2026-03-31T01:00:00+00:00"),
            side="SELL",
            qty=Decimal("0.010"),
            price=Decimal("70000"),
            amount=Decimal("700"),
            execution_status="NEW",
            order_id="1",
            price_source="executable_price",
        ),
        module.TradeRecord(
            cycle_id="c2",
            timestamp=module.datetime.fromisoformat("2026-03-31T02:00:00+00:00"),
            side="BUY",
            qty=Decimal("0.006"),
            price=Decimal("69000"),
            amount=Decimal("414"),
            execution_status="NEW",
            order_id="2",
            price_source="executable_price",
        ),
        module.TradeRecord(
            cycle_id="c3",
            timestamp=module.datetime.fromisoformat("2026-03-31T03:00:00+00:00"),
            side="BUY",
            qty=Decimal("0.004"),
            price=Decimal("68000"),
            amount=Decimal("272"),
            execution_status="NEW",
            order_id="3",
            price_source="executable_price",
        ),
    ]

    pnl = module.compute_pnl(trades, mark_price=Decimal("67500"))

    assert pnl["realized_pnl"] == Decimal("14.000")
    assert pnl["net_open_qty"] == Decimal("0")
    assert pnl["open_short_qty"] == Decimal("0")
    assert pnl["open_long_qty"] == Decimal("0")
    assert pnl["unrealized_pnl"] == Decimal("0")

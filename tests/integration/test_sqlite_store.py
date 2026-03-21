import sqlite3
import pytest
from pathlib import Path
from copy_trader.storage.sqlite_store import SQLiteStore


@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_store.db"


@pytest.fixture
async def store(temp_db_path):
    store = SQLiteStore(temp_db_path)
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_persist_execution_result(store, temp_db_path):
    await store.persist_execution_result(
        cycle_id="cycle-42",
        symbol="BTCUSDT",
        action="BUY",
        requested_size="1.5",
        submitted_size="1.5",
        status="NEW",
        exchange_order_id="12345678",
        error_message=None
    )
    
    # SQLite observation store is normally write-only, but for tests we verify directly:
    con = sqlite3.connect(str(temp_db_path))
    cur = con.cursor()
    cur.execute("SELECT cycle_id, symbol, action, requested_size, submitted_size, status, exchange_order_id, error_message FROM execution_results")
    rows = cur.fetchall()
    
    assert len(rows) == 1
    row = rows[0]
    
    assert row[0] == "cycle-42"
    assert row[1] == "BTCUSDT"
    assert row[2] == "BUY"
    assert row[3] == "1.5"
    assert row[4] == "1.5"
    assert row[5] == "NEW"
    assert row[6] == "12345678"
    assert row[7] is None


@pytest.mark.asyncio
async def test_persist_execution_result_with_error(store, temp_db_path):
    await store.persist_execution_result(
        cycle_id="cycle-43",
        symbol="BTCUSDT",
        action="SELL",
        requested_size="0.5",
        submitted_size=None,
        status="FAILED",
        exchange_order_id=None,
        error_message="Margin is insufficient"
    )
    
    con = sqlite3.connect(str(temp_db_path))
    cur = con.cursor()
    cur.execute("SELECT cycle_id, action, status, error_message FROM execution_results WHERE cycle_id = 'cycle-43'")
    row = cur.fetchone()
    
    assert row[0] == "cycle-43"
    assert row[1] == "SELL"
    assert row[2] == "FAILED"
    assert row[3] == "Margin is insufficient"

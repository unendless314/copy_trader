"""
storage/schema.py

SQLite schema definitions per SPEC.md §Planned SQLite Tables.
Schema is created at startup by sqlite_store.py.
"""

CREATE_SOURCE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS source_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            TEXT NOT NULL,
    entry_price     TEXT,
    source_timestamp TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""

CREATE_BINANCE_POSITIONS = """
CREATE TABLE IF NOT EXISTS binance_positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            TEXT NOT NULL,
    entry_price     TEXT,
    fetched_at      TEXT NOT NULL
);
"""

CREATE_RECONCILIATION_DECISIONS = """
CREATE TABLE IF NOT EXISTS reconciliation_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        TEXT NOT NULL,
    runtime_mode    TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    source_size     TEXT NOT NULL,
    target_size     TEXT NOT NULL,
    actual_size     TEXT NOT NULL,
    raw_delta_size  TEXT NOT NULL,
    capped_delta_size TEXT NOT NULL,
    decision        TEXT NOT NULL,
    block_reason    TEXT,
    reference_price TEXT,
    executable_price TEXT,
    price_deviation_bps TEXT,
    created_at      TEXT NOT NULL
);
"""

CREATE_EXECUTION_RESULTS = """
CREATE TABLE IF NOT EXISTS execution_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id            TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    action              TEXT NOT NULL,
    requested_size      TEXT NOT NULL,
    submitted_size      TEXT,
    status              TEXT NOT NULL,
    exchange_order_id   TEXT,
    error_message       TEXT,
    created_at          TEXT NOT NULL
);
"""

ALL_SCHEMAS = [
    CREATE_SOURCE_SNAPSHOTS,
    CREATE_BINANCE_POSITIONS,
    CREATE_RECONCILIATION_DECISIONS,
    CREATE_EXECUTION_RESULTS,
]

EXPECTED_TABLE_COLUMNS = {
    "source_snapshots": [
        "id",
        "wallet",
        "symbol",
        "side",
        "size",
        "entry_price",
        "source_timestamp",
        "created_at",
    ],
    "binance_positions": [
        "id",
        "symbol",
        "side",
        "size",
        "entry_price",
        "fetched_at",
    ],
    "reconciliation_decisions": [
        "id",
        "cycle_id",
        "runtime_mode",
        "symbol",
        "source_size",
        "target_size",
        "actual_size",
        "raw_delta_size",
        "capped_delta_size",
        "decision",
        "block_reason",
        "reference_price",
        "executable_price",
        "price_deviation_bps",
        "created_at",
    ],
    "execution_results": [
        "id",
        "cycle_id",
        "symbol",
        "action",
        "requested_size",
        "submitted_size",
        "status",
        "exchange_order_id",
        "error_message",
        "created_at",
    ],
}

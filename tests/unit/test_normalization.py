"""
tests/unit/test_normalization.py

Unit tests for Hyperliquid source normalization.
"""

from __future__ import annotations

from datetime import timezone
from decimal import Decimal

import pytest

from copy_trader.source.normalization import SourceNormalizationError, normalize_snapshot

SYMBOL_MAPPING = {"BTC": "BTCUSDT"}
WHITELIST = {"BTCUSDT"}

# Realistic Hyperliquid clearinghouseState response
SAMPLE_RESPONSE = {
    "time": 1710748800000,  # 2024-03-18T08:00:00Z in ms
    "assetPositions": [
        {
            "position": {
                "coin": "BTC",
                "szi": "0.25",
                "entryPx": "84000.0",
                "positionValue": "21000.0",
                "leverage": {"value": 2},
            }
        }
    ],
}


def test_normalize_basic_long():
    snap = normalize_snapshot(SAMPLE_RESPONSE, "0xwallet", SYMBOL_MAPPING, WHITELIST)
    assert "BTCUSDT" in snap.positions
    pos = snap.positions["BTCUSDT"]
    assert pos.size == Decimal("0.25")
    assert pos.side == "long"
    assert pos.entry_price == Decimal("84000.0")
    assert pos.source_timestamp.tzinfo == timezone.utc


def test_normalize_short_position():
    raw = dict(SAMPLE_RESPONSE)
    raw["assetPositions"] = [
        {"position": {"coin": "BTC", "szi": "-0.10", "entryPx": "85000.0"}}
    ]
    snap = normalize_snapshot(raw, "0xwallet", SYMBOL_MAPPING, WHITELIST)
    pos = snap.positions["BTCUSDT"]
    assert pos.size == Decimal("-0.10")
    assert pos.side == "short"


def test_missing_time_raises():
    raw = {k: v for k, v in SAMPLE_RESPONSE.items() if k != "time"}
    with pytest.raises(SourceNormalizationError, match="time"):
        normalize_snapshot(raw, "0xwallet", SYMBOL_MAPPING, WHITELIST)


def test_empty_positions_treats_as_flat():
    raw = {"time": 1710748800000, "assetPositions": []}
    snap = normalize_snapshot(raw, "0xwallet", SYMBOL_MAPPING, WHITELIST)
    pos = snap.positions.get("BTCUSDT")
    assert pos is not None
    assert pos.size == Decimal(0)
    assert pos.side == "flat"


def test_unmapped_symbol_is_skipped():
    raw = {
        "time": 1710748800000,
        "assetPositions": [
            {"position": {"coin": "ETH", "szi": "1.0", "entryPx": "3000.0"}}
        ],
    }
    snap = normalize_snapshot(raw, "0xwallet", SYMBOL_MAPPING, WHITELIST)
    # ETH is not in mapping, BTCUSDT absent → treated as flat
    assert snap.positions["BTCUSDT"].size == Decimal(0)


def test_source_timestamp_from_hl_time_not_local():
    """Ensure source_timestamp comes from Hyperliquid `time`, not local datetime.now()."""
    snap = normalize_snapshot(SAMPLE_RESPONSE, "0xwallet", SYMBOL_MAPPING, WHITELIST)
    pos = snap.positions["BTCUSDT"]
    # 1710748800000 ms → 2024-03-18T08:00:00Z
    assert pos.source_timestamp.year == 2024
    assert pos.source_timestamp.month == 3

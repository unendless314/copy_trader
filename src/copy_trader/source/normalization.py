"""
source/normalization.py

Converts raw Hyperliquid API response into internal SourceSnapshot.
Implements the normalization rules from API-CONTRACTS.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from copy_trader.source.models import SourcePosition, SourceSnapshot

logger = logging.getLogger(__name__)


class SourceNormalizationError(ValueError):
    """Raised when required response fields are missing or unparseable."""


def normalize_snapshot(
    raw: dict[str, Any],
    wallet: str,
    symbol_mapping: dict[str, str],  # e.g. {"BTC": "BTCUSDT"}
    whitelist: set[str],
    fetched_at: datetime | None = None,
) -> SourceSnapshot:
    """
    Parse and normalize a raw clearinghouseState response.

    Args:
        raw:            Full JSON response body from Hyperliquid.
        wallet:         Source wallet address (for logging/storage).
        symbol_mapping: Maps Hyperliquid asset symbols to Binance symbols.
        whitelist:      Set of allowed Binance symbols.
        fetched_at:     UTC time the response was received (defaults to now).

    Returns:
        SourceSnapshot with only whitelisted, mapped positions.

    Raises:
        SourceNormalizationError: if top-level required fields are missing.
    """
    if fetched_at is None:
        fetched_at = datetime.now(tz=timezone.utc)

    # --- source_timestamp from Hyperliquid's own `time` field ---
    raw_time = raw.get("time")
    if raw_time is None:
        raise SourceNormalizationError(
            "Hyperliquid response missing required top-level field 'time'. "
            "Cannot determine source_timestamp; skipping snapshot."
        )
    source_timestamp = _parse_hl_timestamp(raw_time)

    # --- parse positions ---
    asset_positions = raw.get("assetPositions", [])
    positions: dict[str, SourcePosition] = {}

    for entry in asset_positions:
        pos_data = (entry or {}).get("position", {})
        coin = pos_data.get("coin")
        if not coin:
            logger.warning("Skipping position entry with missing 'coin' field: %s", entry)
            continue

        binance_symbol = symbol_mapping.get(coin)
        if binance_symbol is None:
            logger.warning("Unmapped source symbol '%s' — skipping (add to symbols.mapping)", coin)
            continue

        if binance_symbol not in whitelist:
            continue

        size = _parse_decimal(pos_data.get("szi"), field_name="szi", symbol=coin)
        entry_price = _parse_decimal_optional(pos_data.get("entryPx"), field_name="entryPx", symbol=coin)
        side = _derive_side(size)

        positions[binance_symbol] = SourcePosition(
            symbol=binance_symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            source_timestamp=source_timestamp,
        )

    # Symbols in whitelist but absent from the response are treated as flat
    for binance_symbol in whitelist:
        if binance_symbol not in positions:
            # Determine which HL asset maps to this symbol (reverse lookup)
            hl_asset = _reverse_map(symbol_mapping, binance_symbol)
            if hl_asset:
                positions[binance_symbol] = SourcePosition(
                    symbol=binance_symbol,
                    side="flat",
                    size=Decimal(0),
                    entry_price=None,
                    source_timestamp=source_timestamp,
                )

    return SourceSnapshot(positions=positions, fetched_at=fetched_at, wallet=wallet)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_side(size: Decimal) -> str:
    if size > 0:
        return "long"
    if size < 0:
        return "short"
    return "flat"


def _parse_hl_timestamp(raw_time: Any) -> datetime:
    """
    Hyperliquid returns `time` as a Unix millisecond integer.
    """
    try:
        ms = int(raw_time)
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError) as exc:
        raise SourceNormalizationError(
            f"Cannot parse Hyperliquid 'time' field: {raw_time!r} ({exc})"
        ) from exc


def _parse_decimal(value: Any, field_name: str, symbol: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise SourceNormalizationError(
            f"Cannot parse required field '{field_name}' for '{symbol}': {value!r}"
        ) from exc


def _parse_decimal_optional(value: Any, field_name: str, symbol: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        logger.warning("Cannot parse optional field '%s' for '%s': %r — using None", field_name, symbol, value)
        return None


def _reverse_map(mapping: dict[str, str], target: str) -> str | None:
    for src, dst in mapping.items():
        if dst == target:
            return src
    return None

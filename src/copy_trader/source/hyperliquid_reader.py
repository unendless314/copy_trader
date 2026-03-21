"""
source/hyperliquid_reader.py

Hyperliquid wallet position reader per API-CONTRACTS.md (Hyperliquid section).

Endpoint: POST https://api.hyperliquid.xyz/info
Request body: {"type": "clearinghouseState", "user": "<wallet_address>"}
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from copy_trader.config.models import AppConfig
from copy_trader.source.models import SourceSnapshot
from copy_trader.source.normalization import SourceNormalizationError, normalize_snapshot

logger = logging.getLogger(__name__)

_HL_REQUEST_TYPE = "clearinghouseState"


class SourceReadError(RuntimeError):
    """Raised for retryable read-side failures (timeouts, 5xx, malformed response)."""


class HyperliquidReader:
    """
    Fetches and normalises Hyperliquid wallet positions.

    Usage:
        reader = HyperliquidReader(cfg)
        snapshot = await reader.fetch()
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._wallet = cfg.hyperliquid_wallet
        self._url = cfg.source.rest_url
        self._timeout = cfg.source.request_timeout_seconds
        self._symbol_mapping: dict[str, str] = cfg.copy_trade.symbols.mapping
        self._whitelist: set[str] = set(cfg.copy_trade.symbols.whitelist)

    async def fetch(self) -> SourceSnapshot:
        """
        Perform one Hyperliquid poll.

        Returns:
            SourceSnapshot for all whitelisted symbols.

        Raises:
            SourceReadError: for retryable HTTP / network failures.
            SourceNormalizationError: if required response fields are missing.
        """
        raw = await self._request()
        fetched_at = datetime.now(tz=timezone.utc)
        return normalize_snapshot(
            raw=raw,
            wallet=self._wallet,
            symbol_mapping=self._symbol_mapping,
            whitelist=self._whitelist,
            fetched_at=fetched_at,
        )

    def is_fresh(self, snapshot: SourceSnapshot, freshness_timeout_seconds: int) -> bool:
        """
        Return True if snapshot.source_timestamp is within the freshness window.

        Per EPHEMERAL-STATE.md: freshness is checked against the Hyperliquid
        server-provided timestamp, not the local fetched_at time.
        """
        if not snapshot.positions:
            return False
        # Use source_timestamp from any position (they all share the same top-level time)
        any_pos = next(iter(snapshot.positions.values()))
        age = datetime.now(tz=timezone.utc) - any_pos.source_timestamp
        return age <= timedelta(seconds=freshness_timeout_seconds)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _request(self) -> dict[str, Any]:
        payload = {"type": _HL_REQUEST_TYPE, "user": self._wallet}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            raise SourceReadError(f"Hyperliquid request timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise SourceReadError(
                f"Hyperliquid returned HTTP {exc.response.status_code}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise SourceReadError(f"Hyperliquid network error: {exc}") from exc
        except Exception as exc:
            raise SourceReadError(f"Unexpected error fetching Hyperliquid positions: {exc}") from exc

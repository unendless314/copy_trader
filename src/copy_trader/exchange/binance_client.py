"""
exchange/binance_client.py

Binance Futures read-only gateway: positions, prices, trading rules.
Order submission is handled separately in execution/executor.py.

Endpoints used (per API-CONTRACTS.md):
  - GET /fapi/v3/positionRisk          — actual positions
  - GET /fapi/v1/premiumIndex          — mark price (reference)
  - GET /fapi/v1/ticker/bookTicker     — best bid/ask (executable price)
  - GET /fapi/v1/exchangeInfo          — symbol filters
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from copy_trader.config.models import AppConfig
from copy_trader.exchange.models import ActualPosition, PriceSnapshot, SymbolFilters
from copy_trader.exchange.precision import FilterLoadError, parse_symbol_filters

logger = logging.getLogger(__name__)

_FAPI_MAINNET = "https://fapi.binance.com"
_FAPI_TESTNET = "https://testnet.binancefuture.com"


class ExchangeReadError(RuntimeError):
    """Retryable read-side failures from Binance (timeouts, 5xx, rate limits)."""


class BinanceClient:
    """
    Async Binance Futures read gateway.

    Authentication uses HMAC-SHA256 signed requests where required.
    positionRisk requires API key + signature; price and exchangeInfo endpoints do not.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._api_key = cfg.binance_api_key
        self._api_secret = cfg.binance_api_secret
        self._base_url = _FAPI_TESTNET if cfg.binance.testnet else _FAPI_MAINNET
        self._timeout = 10  # seconds

        # Cache exchange info filters (loaded once at startup via preload_filters)
        self._filters: dict[str, SymbolFilters] = {}

    # ------------------------------------------------------------------
    # Public: read-only endpoints
    # ------------------------------------------------------------------

    async def fetch_position(self, symbol: str) -> ActualPosition:
        """
        Fetch the current one-way perpetual position for a symbol.

        Returns flat ActualPosition if the symbol has no open position.
        Raises ExchangeReadError for retryable failures.
        """
        params = {"symbol": symbol}
        data = await self._signed_get("/fapi/v3/positionRisk", params)

        fetched_at = datetime.now(tz=timezone.utc)

        # /fapi/v3/positionRisk returns a list; filter to BOTH side (one-way mode)
        entry = self._find_oneway_position(data, symbol)
        if entry is None:
            return ActualPosition(
                symbol=symbol, side="flat", size=Decimal(0),
                entry_price=None, binance_timestamp=fetched_at,
            )

        size = Decimal(str(entry.get("positionAmt", "0")))
        entry_price_raw = entry.get("entryPrice")
        entry_price = Decimal(str(entry_price_raw)) if entry_price_raw else None

        update_time_ms = entry.get("updateTime")
        binance_ts = (
            datetime.fromtimestamp(int(update_time_ms) / 1000.0, tz=timezone.utc)
            if update_time_ms else fetched_at
        )

        side = "long" if size > 0 else ("short" if size < 0 else "flat")
        return ActualPosition(
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            binance_timestamp=binance_ts,
        )

    async def fetch_price(self, symbol: str) -> PriceSnapshot:
        """
        Fetch mark price and best bid/ask for a symbol.
        Raises ExchangeReadError for retryable failures.
        """
        fetched_at = datetime.now(tz=timezone.utc)

        mark_data = await self._public_get("/fapi/v1/premiumIndex", {"symbol": symbol})
        book_data = await self._public_get("/fapi/v1/ticker/bookTicker", {"symbol": symbol})

        mark_price = Decimal(str(mark_data["markPrice"]))
        bid_price = Decimal(str(book_data["bidPrice"]))
        ask_price = Decimal(str(book_data["askPrice"]))

        return PriceSnapshot(
            symbol=symbol,
            reference_price=mark_price,
            bid_price=bid_price,
            ask_price=ask_price,
            fetched_at=fetched_at,
        )

    async def preload_filters(self, symbols: list[str]) -> None:
        """
        Load and cache SymbolFilters for the given symbols.
        Call once at startup before the main loop begins.
        """
        data = await self._public_get("/fapi/v1/exchangeInfo", {})
        for sym in symbols:
            try:
                self._filters[sym] = parse_symbol_filters(data, sym)
                logger.info("Loaded filters for %s: %s", sym, self._filters[sym])
            except FilterLoadError as exc:
                logger.error("Failed to load filters for %s: %s", sym, exc)
                raise ExchangeReadError(f"Cannot load trading filters for {sym}: {exc}") from exc

    def get_filters(self, symbol: str) -> SymbolFilters:
        """Return cached SymbolFilters. preload_filters() must have been called first."""
        filters = self._filters.get(symbol)
        if filters is None:
            raise ExchangeReadError(
                f"Filters for '{symbol}' not loaded. Call preload_filters() first."
            )
        return filters

    # ------------------------------------------------------------------
    # Internal: HTTP helpers
    # ------------------------------------------------------------------

    async def _public_get(self, path: str, params: dict) -> Any:
        url = self._base_url + path
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return r.json()
        except httpx.TimeoutException as exc:
            raise ExchangeReadError(f"Binance GET {path} timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ExchangeReadError(
                f"Binance GET {path} returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ExchangeReadError(f"Binance network error on {path}: {exc}") from exc

    async def _signed_get(self, path: str, params: dict) -> Any:
        """HMAC-SHA256 signed GET request (required for account-level endpoints)."""
        import hashlib
        import hmac
        import time
        import urllib.parse

        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature

        url = self._base_url + path
        headers = {"X-MBX-APIKEY": self._api_key}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, params=params, headers=headers)
                r.raise_for_status()
                return r.json()
        except httpx.TimeoutException as exc:
            raise ExchangeReadError(f"Binance signed GET {path} timed out: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ExchangeReadError(
                f"Binance signed GET {path} returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise ExchangeReadError(f"Binance network error on {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_oneway_position(data: list[dict], symbol: str) -> dict | None:
        """Find the BOTH (one-way mode) position entry for symbol."""
        for entry in data:
            if entry.get("symbol") == symbol and entry.get("positionSide") == "BOTH":
                return entry
        return None

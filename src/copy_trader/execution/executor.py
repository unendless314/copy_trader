"""
execution/executor.py

Executes a DecisionRecord as a standard MARKET order on Binance Futures. 
"""

import hashlib
import hmac
import logging
import time
import urllib.parse
from decimal import Decimal

import httpx

from copy_trader.config.models import AppConfig
from copy_trader.execution.models import (
    ExecutionError,
    ExecutionRejectError,
    ExecutionResult,
    LocalValidationError,
    UnknownStatusError,
)
from copy_trader.strategy.reconciliation import DecisionRecord

logger = logging.getLogger(__name__)

_FAPI_MAINNET = "https://fapi.binance.com"
_FAPI_TESTNET = "https://testnet.binancefuture.com"


class BinanceExecutor:
    """
    Translates a reconciliation decision into an active Binance trade.
    Uses the ONE-WAY (positionSide=BOTH) model per config limits.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._api_key = cfg.binance_api_key
        self._api_secret = cfg.binance_api_secret
        self._base_url = _FAPI_TESTNET if cfg.binance.testnet else _FAPI_MAINNET
        self._timeout = 10  # seconds

    async def submit(self, decision: DecisionRecord) -> ExecutionResult:
        """
        Map positive capped_delta to BUY, negative to SELL.
        Always execute as MARKET orders.

        Raises:
            LocalValidationError on pre-flight checks (e.g., zero quantity).
            ExecutionRejectError on explicit exchange rejection (e.g. 400).
            UnknownStatusError on timeout.
            ExecutionError on generic network failures.
        """
        if decision.capped_delta_size == Decimal(0):
            raise LocalValidationError(f"Cannot execute order for {decision.symbol}: quantity is 0")

        is_buy = decision.capped_delta_size > 0
        side = "BUY" if is_buy else "SELL"
        qty_str = str(abs(decision.capped_delta_size))

        params = {
            "symbol": decision.symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty_str,
            "positionSide": "BOTH",
        }

        try:
            # We use `params` which translates to query parameters,
            # which is an expected way to pass arguments in Binance FAPI.
            data = await self._signed_post("/fapi/v1/order", params)

            status = data.get("status", "NEW")
            order_id = data.get("orderId")
            
            # Binance successful synchronous end-states for MARKET are usually NEW or FILLED
            accepted = status in ("NEW", "FILLED", "PARTIALLY_FILLED") and order_id is not None

            return ExecutionResult(
                accepted=accepted,
                status=status,
                symbol=decision.symbol,
                side=side,
                requested_size=qty_str,
                submitted_size=qty_str,
                exchange_order_id=str(order_id) if order_id else None,
                error_message=None if accepted else f"Order returned unaccepted status: {status}",
            )

        except httpx.HTTPStatusError as exc:
            msg = exc.response.text
            try:
                err_data = exc.response.json()
                msg = err_data.get("msg", msg)
            except Exception:
                pass
            raise ExecutionRejectError(f"Binance rejected order: {msg}") from exc

        except httpx.TimeoutException as exc:
            raise UnknownStatusError(f"Timeout while waiting for Binance response: {exc}") from exc

        except httpx.RequestError as exc:
            raise ExecutionError(f"Network error submitting to Binance: {exc}") from exc

    async def _signed_post(self, path: str, params: dict) -> dict:
        """Submits a signed POST request required for trade endpoints."""
        if not self._api_key or not self._api_secret:
            raise LocalValidationError("Binance API credentials not fully configured")

        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)

        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        
        url = f"{self._base_url}{path}?{query}&signature={signature}"
        headers = {
            "X-MBX-APIKEY": self._api_key,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(url, headers=headers)
            r.raise_for_status()
            return r.json()

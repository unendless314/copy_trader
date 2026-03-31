import pytest
import respx
import httpx
from decimal import Decimal

from copy_trader.config.models import AppConfig
from copy_trader.execution.executor import BinanceExecutor
from copy_trader.execution.flip_handler import execute_decision_with_flip
from copy_trader.execution.models import (
    ExecutionError,
    ExecutionRejectError,
    ExecutionResult,
    LocalValidationError,
    UnknownStatusError,
)
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.reconciliation import DecisionRecord


@pytest.fixture
def cfg():
    c = AppConfig()
    c.binance_api_key = "test_key"
    c.binance_api_secret = "test_secret"
    c.binance.testnet = True
    return c


@pytest.fixture
def executor(cfg):
    return BinanceExecutor(cfg)


def _make_decision(size: str) -> DecisionRecord:
    return DecisionRecord(
        cycle_id="test_cycle",
        runtime_mode="live",
        symbol="BTCUSDT",
        source_size=Decimal("0.5"),
        target_size=Decimal("0.5"),
        actual_size=Decimal("0"),
        raw_delta_size=Decimal(size),
        capped_delta_size=Decimal(size),
        decision_type=DecisionType.REBALANCE_INCREASE,
        block_reason=None,
        reference_price=Decimal("50000"),
        executable_price=Decimal("50000"),
        price_deviation_bps=Decimal(0)
    )


@respx.mock
@pytest.mark.asyncio
async def test_submit_success(executor):
    respx.post("https://testnet.binancefuture.com/fapi/v1/order").mock(
        return_value=httpx.Response(200, json={
            "orderId": 12345,
            "status": "NEW"
        })
    )
    
    decision = _make_decision("0.1")
    result = await executor.submit(decision)
    
    assert result.accepted is True
    assert result.side == "BUY"
    assert result.requested_size == "0.1"
    assert result.submitted_size == "0.1"
    assert result.exchange_order_id == "12345"
    assert result.error_message is None


@respx.mock
@pytest.mark.asyncio
async def test_submit_negative_delta_sends_sell(executor):
    route = respx.post("https://testnet.binancefuture.com/fapi/v1/order").mock(
        return_value=httpx.Response(200, json={
            "orderId": 12345,
            "status": "NEW"
        })
    )

    decision = _make_decision("-0.1")
    result = await executor.submit(decision)

    assert result.accepted is True
    assert result.side == "SELL"
    assert result.submitted_size == "0.1"
    assert route.calls[0].request.url.params["side"] == "SELL"


@respx.mock
@pytest.mark.asyncio
async def test_submit_reject(executor):
    respx.post("https://testnet.binancefuture.com/fapi/v1/order").mock(
        return_value=httpx.Response(400, json={"code": -2010, "msg": "Margin is insufficient"})
    )
    decision = _make_decision("0.1")
    
    with pytest.raises(ExecutionRejectError, match="Margin is insufficient"):
        await executor.submit(decision)


@respx.mock
@pytest.mark.asyncio
async def test_submit_timeout(executor):
    respx.post("https://testnet.binancefuture.com/fapi/v1/order").mock(
        side_effect=httpx.TimeoutException("timeout simulated")
    )
    decision = _make_decision("0.1")
    
    with pytest.raises(UnknownStatusError, match="timeout simulated"):
        await executor.submit(decision)


@pytest.mark.asyncio
async def test_zero_quantity_local_validation(executor):
    decision = _make_decision("0")
    
    with pytest.raises(LocalValidationError, match="quantity is 0"):
        await executor.submit(decision)


class CaptureExecutor:
    def __init__(self):
        self.decision = None

    async def submit(self, decision):
        self.decision = decision
        return ExecutionResult(
            accepted=True,
            status="NEW",
            symbol=decision.symbol,
            side="BUY" if decision.capped_delta_size > 0 else "SELL",
            requested_size=str(abs(decision.capped_delta_size)),
            submitted_size="0",
            exchange_order_id="captured",
            error_message=None,
        )


@pytest.mark.asyncio
async def test_flip_close_short_position_submits_buy():
    executor = CaptureExecutor()
    decision = DecisionRecord(
        cycle_id="test_cycle",
        runtime_mode="live",
        symbol="BTCUSDT",
        source_size=Decimal("0.5"),
        target_size=Decimal("0.5"),
        actual_size=Decimal("-0.3"),
        raw_delta_size=Decimal("0.8"),
        capped_delta_size=Decimal("0.2"),
        decision_type=DecisionType.REBALANCE_FLIP_CLOSE,
        block_reason=None,
        reference_price=Decimal("50000"),
        executable_price=Decimal("50000"),
        price_deviation_bps=Decimal(0),
    )

    result = await execute_decision_with_flip(executor, decision)

    assert executor.decision is not None
    assert executor.decision.capped_delta_size > 0
    assert result.side == "BUY"

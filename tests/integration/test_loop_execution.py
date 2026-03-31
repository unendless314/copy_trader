import pytest
from decimal import Decimal

from copy_trader.config.models import AppConfig, RuntimeMode
from copy_trader.execution.models import ExecutionRejectError, ExecutionResult
from copy_trader.runtime.loop import PollingLoop
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.reconciliation import DecisionRecord


class MockExecutor:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def submit(self, decision):
        self.calls += 1
        if self.error:
            raise self.error
        return ExecutionResult(
            accepted=True, status="NEW", symbol="BTCUSDT",
            side="BUY", requested_size="0.1", submitted_size="0.1",
            exchange_order_id="123", error_message=None
        )


class MockEventLogger:
    def update_mode(self, mode):
        pass
    def mode_changed(self, f, t, r):
        pass
    def error(self, *args, **kwargs):
        pass
    def warning(self, *args, **kwargs):
        pass


def _make_decision() -> DecisionRecord:
    return DecisionRecord(
        cycle_id="test",
        runtime_mode="live",
        symbol="BTCUSDT",
        source_size=Decimal("0.5"),
        target_size=Decimal("0.5"),
        actual_size=Decimal("0"),
        raw_delta_size=Decimal("0.5"),
        capped_delta_size=Decimal("0.5"),
        decision_type=DecisionType.REBALANCE_INCREASE,
        block_reason=None,
        reference_price=Decimal("50000"),
        executable_price=Decimal("50000"),
        price_deviation_bps=Decimal(0)
    )


@pytest.mark.asyncio
async def test_loop_auto_downgrade():
    cfg = AppConfig()
    cfg.runtime.mode = RuntimeMode.live
    cfg.runtime.auto_downgrade_threshold = 2
    
    loop = PollingLoop(cfg)
    loop.event_logger = MockEventLogger()
    loop.executor = MockExecutor(error=ExecutionRejectError("mocked rejection"))

    decision = _make_decision()
    
    # First execution failure -> stays live
    await loop._execute(decision, "cycle-1")
    assert loop.mode == RuntimeMode.live
    
    # Second execution failure -> downgrades to armed
    await loop._execute(decision, "cycle-2")
    assert loop.mode == RuntimeMode.armed


@pytest.mark.asyncio
async def test_loop_successful_execution_resets_counter():
    cfg = AppConfig()
    cfg.runtime.mode = RuntimeMode.live
    cfg.runtime.auto_downgrade_threshold = 2
    
    loop = PollingLoop(cfg)
    loop.event_logger = MockEventLogger()
    
    decision = _make_decision()

    # Give it a failing executor first
    loop.executor = MockExecutor(error=ExecutionRejectError("mocked rejection"))
    await loop._execute(decision, "cycle-1")
    assert loop.mode == RuntimeMode.live
    assert loop._ephemeral.consecutive_live_execution_failures == 1
    
    # Now swap to a successful executor
    loop.executor = MockExecutor()
    await loop._execute(decision, "cycle-2")
    
    # Counter should reset to 0
    assert loop.mode == RuntimeMode.live
    assert loop._ephemeral.consecutive_live_execution_failures == 0

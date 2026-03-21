"""
execution/flip_handler.py

Handles the two-step close-then-open mechanic for direction flips.
"""

from decimal import Decimal
import logging

from copy_trader.execution.executor import BinanceExecutor
from copy_trader.execution.models import ExecutionResult, LocalValidationError
from copy_trader.strategy.decision_types import DecisionType
from copy_trader.strategy.reconciliation import DecisionRecord

logger = logging.getLogger(__name__)


async def execute_decision_with_flip(executor: BinanceExecutor, decision: DecisionRecord) -> ExecutionResult:
    """
    Wrapper around BinanceExecutor.submit that intercepts REBALANCE_FLIP_CLOSE.
    Overrides the quantity/side to safely close the existing actual position
    without immediately opening the new target direction.
    """
    if decision.decision_type == DecisionType.REBALANCE_FLIP_CLOSE:
        logger.info(
            "Flip close intercepted for %s. Actual: %s, Target: %s", 
            decision.symbol, decision.actual_size, decision.target_size
        )
        
        # We must close the current position.
        # So we submit an order opposing actual_size.
        actual_size = decision.actual_size
        if actual_size == Decimal(0):
            raise LocalValidationError("Cannot flip close a flat position")
            
        close_qty = abs(actual_size)
        
        # We cap the close quantity to the strategy's capped_delta_size to respect
        # the max_single_rebalance_notional_usdt risk limit (convergence cap).
        # We just want the direction to oppose the current actual position.
        max_allowed_qty = abs(decision.capped_delta_size)
        
        if close_qty > max_allowed_qty:
            logger.info(
                "Flip close for %s capped by risk policy from %s to %s",
                decision.symbol, close_qty, max_allowed_qty
            )
            close_qty = max_allowed_qty

        # Construct a synthetic decision purely for executor submission
        sign = -1 if actual_size > 0 else 1
        synthetic_delta = close_qty * sign
        
        synthetic_decision = DecisionRecord(
            cycle_id=decision.cycle_id,
            runtime_mode=decision.runtime_mode,
            symbol=decision.symbol,
            source_size=decision.source_size,
            target_size=decision.target_size,
            actual_size=decision.actual_size,
            raw_delta_size=synthetic_delta,
            capped_delta_size=synthetic_delta,
            decision_type=decision.decision_type,
            block_reason=decision.block_reason,
            reference_price=decision.reference_price,
            executable_price=decision.executable_price,
            price_deviation_bps=decision.price_deviation_bps,
        )
        return await executor.submit(synthetic_decision)

    # Standard execution logic
    return await executor.submit(decision)

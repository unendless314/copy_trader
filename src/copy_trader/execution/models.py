"""
execution/models.py

Data contracts and error types for order execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ExecutionResult:
    """
    Standardized result for an order submission attempt.
    Must map to the execution_results SQLite table schema.
    """
    accepted: bool
    status: str
    symbol: str
    side: str
    requested_size: str
    submitted_size: Optional[str]
    exchange_order_id: Optional[str]
    error_message: Optional[str]
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(tz=timezone.utc)


class ExecutionError(Exception):
    """Base exception for all execution errors."""


class ExecutionRejectError(ExecutionError):
    """Exchange rejected the order (e.g. margin insufficient, invalid size)."""


class UnknownStatusError(ExecutionError):
    """The order was submitted but the result is unclear (timeout after send)."""

class LocalValidationError(ExecutionError):
    """Pre-submit local validation error (e.g. quantity is zero)."""

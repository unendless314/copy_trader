"""
logging/setup.py

Configures Python logging to emit JSON Lines to stdout (and optionally a file).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


class _PassthroughFormatter(logging.Formatter):
    """
    Formatter that emits the message as-is.
    EventLogger already builds JSON Lines strings; we just forward them.
    """

    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def configure_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """
    Set up root copy_trader logger with a stdout handler (and optional file handler).

    Should be called once at startup before any log events are emitted.
    """
    root = logging.getLogger("copy_trader")
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.handlers.clear()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(_PassthroughFormatter())
    root.addHandler(stdout_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(_PassthroughFormatter())
        root.addHandler(file_handler)

    root.propagate = False

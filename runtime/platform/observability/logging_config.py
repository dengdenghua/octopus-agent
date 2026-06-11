"""
runtime.platform.observability.logging_config · centralized logging setup.

Call ``configure_logging()`` once at process start (CLI entry point,
FastAPI lifespan, etc.) to establish consistent formatting and
level control across all ``runtime.*`` loggers.

Environment variables
---------------------
OCTOPUS_LOG_LEVEL   default INFO · one of DEBUG/INFO/WARNING/ERROR
OCTOPUS_LOG_FORMAT  default ``%(asctime)s [%(levelname)s] %(name)s: %(message)s``
"""

from __future__ import annotations

import logging
import os
import sys

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DEFAULT_LEVEL = "INFO"

_NOISY_LOGGERS = (
    "uvicorn.access",
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "multipart",
)


def configure_logging() -> None:
    """Apply project-wide logging configuration.

    Safe to call multiple times — subsequent calls are no-ops if the
    root logger already has handlers (prevents duplicate output in
    tests that call ``configure_logging()`` per fixture setup).
    """
    level_name = os.environ.get("OCTOPUS_LOG_LEVEL", _DEFAULT_LEVEL).upper()
    fmt = os.environ.get("OCTOPUS_LOG_FORMAT", _DEFAULT_FORMAT)

    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(level)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

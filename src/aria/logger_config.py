"""Logging configuration for the Aria chatbot."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

from .exceptions import InputValidationError

DEFAULT_LOG_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
DEFAULT_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
ARIA_LOGGER_NAME: Final[str] = "aria"
CONSOLE_HANDLER_NAME: Final[str] = "aria-console"
FILE_HANDLER_NAME: Final[str] = "aria-file"

_CONFIGURED: bool = False


def configure_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure and return the root Aria logger.

    The function is idempotent for console handlers. A file handler is added
    only when ``log_file`` is supplied and no Aria file handler exists yet.
    """
    global _CONFIGURED

    logger = logging.getLogger(ARIA_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        DEFAULT_LOG_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT,
    )

    if not _CONFIGURED:
        console_handler = logging.StreamHandler()
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        _CONFIGURED = True

    has_file_handler = any(
        handler.get_name() == FILE_HANDLER_NAME for handler in logger.handlers
    )

    if log_file is not None and not has_file_handler:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.set_name(FILE_HANDLER_NAME)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``aria`` namespace."""
    if not name or not name.strip():
        raise InputValidationError("Logger name must be non-empty.")

    if name == ARIA_LOGGER_NAME or name.startswith(f"{ARIA_LOGGER_NAME}."):
        return logging.getLogger(name)

    return logging.getLogger(f"{ARIA_LOGGER_NAME}.{name}")
"""Unit tests for Aria logging configuration."""

from __future__ import annotations

import logging
import unittest

from aria.exceptions import InputValidationError
from aria.logger_config import configure_logging, get_logger


class LoggerConfigTests(unittest.TestCase):
    """Tests for logger configuration helpers."""

    def test_get_logger_namespaces_names(self) -> None:
        self.assertEqual(get_logger("chatbot").name, "aria.chatbot")
        self.assertEqual(get_logger("aria.chatbot").name, "aria.chatbot")

    def test_get_logger_rejects_blank_name(self) -> None:
        with self.assertRaises(InputValidationError):
            get_logger("   ")

    def test_configure_logging_returns_aria_logger(self) -> None:
        logger = configure_logging(level=logging.INFO)
        self.assertEqual(logger.name, "aria")


if __name__ == "__main__":
    unittest.main()
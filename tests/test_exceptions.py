"""Unit tests for Aria custom exceptions."""

from __future__ import annotations

import unittest

from aria.exceptions import AriaError, ConfigurationError, IntentConfigurationError


class ExceptionHierarchyTests(unittest.TestCase):
    """Tests for the custom exception hierarchy."""

    def test_intent_configuration_error_is_configuration_error(self) -> None:
        self.assertTrue(issubclass(IntentConfigurationError, ConfigurationError))

    def test_configuration_error_is_aria_error(self) -> None:
        self.assertTrue(issubclass(ConfigurationError, AriaError))


if __name__ == "__main__":
    unittest.main()
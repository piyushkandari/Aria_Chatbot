"""Unit tests for Aria domain models."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from aria.exceptions import InputValidationError, IntentConfigurationError
from aria.models import Category, Intent, Message, Role


class IntentTests(unittest.TestCase):
    """Tests for Intent validation."""

    def test_valid_question_intent(self) -> None:
        intent = Intent(
            name="question.name",
            category=Category.QUESTION,
            patterns=(r"\bwhat is your name\b",),
            responses=("My name is Aria.",),
        )
        self.assertEqual(intent.category, Category.QUESTION)
        self.assertEqual(intent.priority, 100)

    def test_unknown_intent_can_have_no_patterns(self) -> None:
        intent = Intent(
            name="fallback.unknown",
            category=Category.UNKNOWN,
            patterns=(),
            responses=("Try again.",),
            escalation_responses=("Type help.",),
        )
        self.assertEqual(intent.category, Category.UNKNOWN)

    def test_question_intent_requires_patterns(self) -> None:
        with self.assertRaises(IntentConfigurationError):
            Intent(
                name="bad.intent",
                category=Category.QUESTION,
                patterns=(),
                responses=("x",),
            )

    def test_intent_requires_response(self) -> None:
        with self.assertRaises(IntentConfigurationError):
            Intent(
                name="bad.intent",
                category=Category.GREETING,
                patterns=("hi",),
                responses=(),
            )


class MessageTests(unittest.TestCase):
    """Tests for Message validation."""

    def test_message_rejects_blank_text(self) -> None:
        with self.assertRaises(InputValidationError):
            Message(role=Role.USER, text="   ")

    def test_message_converts_naive_timestamp_to_utc(self) -> None:
        timestamp = datetime(2024, 1, 1, 12, 0, 0)
        message = Message(role=Role.USER, text="hello", timestamp=timestamp)
        self.assertEqual(message.timestamp.tzinfo, timezone.utc)

    def test_message_rejects_invalid_role(self) -> None:
        with self.assertRaises(InputValidationError):
            Message(role="user", text="hello")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
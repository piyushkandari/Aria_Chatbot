"""Unit tests for the Aria context manager."""

from __future__ import annotations

import unittest

from aria.context_manager import DEFAULT_MAX_TURNS, ContextManager
from aria.exceptions import InputValidationError
from aria.models import Category, Role


class ConstructionTests(unittest.TestCase):
    """Tests for ContextManager construction."""

    def test_default_max_turns(self) -> None:
        cm = ContextManager()
        self.assertEqual(cm.max_turns, DEFAULT_MAX_TURNS)
        self.assertEqual(len(cm), 0)
        self.assertFalse(cm.has_history())

    def test_custom_max_turns(self) -> None:
        cm = ContextManager(max_turns=3)
        self.assertEqual(cm.max_turns, 3)

    def test_reject_zero(self) -> None:
        with self.assertRaises(InputValidationError):
            ContextManager(max_turns=0)

    def test_reject_negative(self) -> None:
        with self.assertRaises(InputValidationError):
            ContextManager(max_turns=-1)

    def test_reject_float(self) -> None:
        with self.assertRaises(InputValidationError):
            ContextManager(max_turns=2.5)  # type: ignore[arg-type]

    def test_reject_bool(self) -> None:
        with self.assertRaises(InputValidationError):
            ContextManager(max_turns=True)  # type: ignore[arg-type]

    def test_reject_string(self) -> None:
        with self.assertRaises(InputValidationError):
            ContextManager(max_turns="5")  # type: ignore[arg-type]


class RecordingTests(unittest.TestCase):
    """Tests for recording user and bot messages."""

    def setUp(self) -> None:
        self.cm = ContextManager(max_turns=5)

    def test_add_user_message(self) -> None:
        msg = self.cm.add_user_message("hello", category=Category.GREETING)
        self.assertIs(msg.role, Role.USER)
        self.assertEqual(msg.text, "hello")
        self.assertIs(msg.category, Category.GREETING)
        self.assertEqual(len(self.cm), 1)
        self.assertTrue(self.cm.has_history())

    def test_add_user_message_strips_whitespace(self) -> None:
        msg = self.cm.add_user_message("   hi   ")
        self.assertEqual(msg.text, "hi")

    def test_add_user_message_rejects_empty(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.add_user_message("    ")

    def test_add_user_message_rejects_non_string(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.add_user_message(123)  # type: ignore[arg-type]

    def test_add_bot_message_attaches_to_open_turn(self) -> None:
        self.cm.add_user_message("hi")
        self.cm.add_bot_message("hello back")
        self.assertEqual(len(self.cm), 1)
        self.assertEqual(len(self.cm.messages), 2)

    def test_add_bot_message_after_complete_turn_starts_new_turn(self) -> None:
        self.cm.add_user_message("hi")
        self.cm.add_bot_message("hello")
        self.cm.add_bot_message("unsolicited")
        self.assertEqual(len(self.cm), 2)

    def test_add_bot_message_with_no_history_creates_own_turn(self) -> None:
        self.cm.add_bot_message("hello")
        self.assertEqual(len(self.cm), 1)
        self.assertEqual(len(self.cm.messages), 1)

    def test_add_bot_message_rejects_empty(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.add_bot_message("")

    def test_messages_property_is_ordered(self) -> None:
        self.cm.add_user_message("first")
        self.cm.add_bot_message("reply1")
        self.cm.add_user_message("second")
        self.cm.add_bot_message("reply2")
        texts = [m.text for m in self.cm.messages]
        self.assertEqual(texts, ["first", "reply1", "second", "reply2"])


class PruningTests(unittest.TestCase):
    """Tests for sliding-window pruning."""

    def test_old_turns_are_dropped(self) -> None:
        cm = ContextManager(max_turns=2)
        for index in range(4):
            cm.add_user_message(f"u{index}")
            cm.add_bot_message(f"b{index}")
        self.assertEqual(len(cm), 2)
        user_texts = [m.text for m in cm.messages if m.role is Role.USER]
        self.assertEqual(user_texts, ["u2", "u3"])

    def test_turn_at_capacity_is_kept(self) -> None:
        cm = ContextManager(max_turns=3)
        for index in range(3):
            cm.add_user_message(f"u{index}")
            cm.add_bot_message(f"b{index}")
        self.assertEqual(len(cm), 3)

    def test_prune_does_not_touch_facts(self) -> None:
        cm = ContextManager(max_turns=1)
        cm.remember_fact("name", "Alice")
        cm.add_user_message("u1")
        cm.add_user_message("u2")
        self.assertEqual(cm.get_fact("name"), "Alice")


class LastMessageTests(unittest.TestCase):
    """Tests for last_* lookups."""

    def setUp(self) -> None:
        self.cm = ContextManager()

    def test_last_user_message_none_when_empty(self) -> None:
        self.assertIsNone(self.cm.last_user_message())

    def test_last_user_message_returns_latest(self) -> None:
        self.cm.add_user_message("first")
        self.cm.add_bot_message("ok")
        self.cm.add_user_message("second")
        msg = self.cm.last_user_message()
        assert msg is not None
        self.assertEqual(msg.text, "second")

    def test_last_bot_message_returns_latest(self) -> None:
        self.cm.add_user_message("u")
        self.cm.add_bot_message("b1")
        self.cm.add_user_message("u2")
        self.cm.add_bot_message("b2")
        msg = self.cm.last_bot_message()
        assert msg is not None
        self.assertEqual(msg.text, "b2")

    def test_last_user_question_none_if_no_questions(self) -> None:
        self.cm.add_user_message("hi", category=Category.GREETING)
        self.assertIsNone(self.cm.last_user_question())

    def test_last_user_question_skips_non_questions(self) -> None:
        self.cm.add_user_message("hello", category=Category.GREETING)
        self.cm.add_bot_message("hi")
        self.cm.add_user_message(
            "what time is it", category=Category.QUESTION
        )
        self.cm.add_bot_message("noon")
        self.cm.add_user_message("thanks", category=Category.UNKNOWN)
        msg = self.cm.last_user_question()
        assert msg is not None
        self.assertEqual(msg.text, "what time is it")


class FactTests(unittest.TestCase):
    """Tests for user fact storage."""

    def setUp(self) -> None:
        self.cm = ContextManager()

    def test_remember_and_get(self) -> None:
        self.cm.remember_fact("name", "Alice")
        self.assertEqual(self.cm.get_fact("name"), "Alice")
        self.assertTrue(self.cm.has_fact("name"))

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.cm.get_fact("name"))
        self.assertFalse(self.cm.has_fact("name"))

    def test_reject_blank_key(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.remember_fact("   ", "x")

    def test_reject_blank_value(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.remember_fact("name", "   ")

    def test_facts_are_immutable_view(self) -> None:
        self.cm.remember_fact("name", "Alice")
        view = self.cm.facts
        with self.assertRaises(TypeError):
            view["name"] = "Bob"  # type: ignore[index]

    def test_overwrite_fact(self) -> None:
        self.cm.remember_fact("name", "Alice")
        self.cm.remember_fact("name", "Bob")
        self.assertEqual(self.cm.get_fact("name"), "Bob")


class RepeatDetectionTests(unittest.TestCase):
    """Tests for count_prior_user_messages / is_repeated."""

    def setUp(self) -> None:
        self.cm = ContextManager(max_turns=10)

    def test_count_zero_when_empty(self) -> None:
        self.assertEqual(self.cm.count_prior_user_messages("hello"), 0)

    def test_count_matches_ignoring_case(self) -> None:
        self.cm.add_user_message("Hello")
        self.assertEqual(self.cm.count_prior_user_messages("hello"), 1)
        self.assertEqual(self.cm.count_prior_user_messages("HELLO"), 1)

    def test_count_matches_ignoring_whitespace(self) -> None:
        self.cm.add_user_message("what   time    is  it")
        self.assertEqual(
            self.cm.count_prior_user_messages("what time is it"), 1
        )

    def test_count_multiple_occurrences(self) -> None:
        self.cm.add_user_message("hi")
        self.cm.add_user_message("hi")
        self.cm.add_user_message("bye")
        self.assertEqual(self.cm.count_prior_user_messages("hi"), 2)
        self.assertEqual(self.cm.count_prior_user_messages("bye"), 1)

    def test_count_with_category_filter(self) -> None:
        self.cm.add_user_message("hello", category=Category.GREETING)
        self.cm.add_user_message("hello", category=Category.QUESTION)
        self.assertEqual(
            self.cm.count_prior_user_messages("hello"), 2
        )
        self.assertEqual(
            self.cm.count_prior_user_messages(
                "hello", category=Category.QUESTION
            ),
            1,
        )

    def test_count_blank_returns_zero(self) -> None:
        self.assertEqual(self.cm.count_prior_user_messages("   "), 0)

    def test_count_rejects_non_string(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.count_prior_user_messages(123)  # type: ignore[arg-type]

    def test_is_repeated_false_when_not_seen(self) -> None:
        self.assertFalse(
            self.cm.is_repeated("hi", category=Category.QUESTION)
        )

    def test_is_repeated_true_when_seen_before(self) -> None:
        self.cm.add_user_message("hi", category=Category.QUESTION)
        self.assertTrue(
            self.cm.is_repeated("hi", category=Category.QUESTION)
        )

    def test_is_repeated_with_higher_threshold(self) -> None:
        self.cm.add_user_message("hi", category=Category.QUESTION)
        self.assertFalse(
            self.cm.is_repeated("hi", category=Category.QUESTION, threshold=2)
        )
        self.cm.add_user_message("hi", category=Category.QUESTION)
        self.assertTrue(
            self.cm.is_repeated("hi", category=Category.QUESTION, threshold=2)
        )

    def test_is_repeated_rejects_bad_threshold(self) -> None:
        with self.assertRaises(InputValidationError):
            self.cm.is_repeated("hi", threshold=0)


class ClearTests(unittest.TestCase):
    """Tests for ContextManager.clear."""

    def test_clear_resets_everything(self) -> None:
        cm = ContextManager()
        cm.add_user_message("hi")
        cm.add_bot_message("hello")
        cm.remember_fact("name", "Alice")
        cm.clear()
        self.assertEqual(len(cm), 0)
        self.assertEqual(cm.messages, ())
        self.assertFalse(cm.has_history())
        self.assertIsNone(cm.get_fact("name"))


if __name__ == "__main__":
    unittest.main()
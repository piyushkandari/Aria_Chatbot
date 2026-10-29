"""Integration tests for the Aria chatbot.

End-to-end tests through the Chatbot facade with the real intents.json.
These exercise multi-turn conversations and edge cases that per-module
unit tests cannot cover, and serve as the regression suite for behaviour
that spans matcher → memory → generator → facade.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aria.chatbot import Chatbot
from aria.exceptions import InputValidationError, SessionError
from aria.models import Category
from aria.pattern_matcher import load_intents_from_json

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "intents.json"
)
_FIXED_TIME = datetime(2025, 1, 1, 12, 30, 0)


def _fixed_clock() -> datetime:
    return _FIXED_TIME


def _make_bot(**kwargs) -> Chatbot:
    intents = load_intents_from_json(_CONFIG_PATH)
    kwargs.setdefault("rng", random.Random(0))
    kwargs.setdefault("clock", _fixed_clock)
    return Chatbot(intents, **kwargs)


# --------------------------------------------------------------------- #
# Full multi-turn conversations
# --------------------------------------------------------------------- #


class FullConversationTests(unittest.TestCase):
    """Multi-turn conversations exercised end to end."""

    def test_classic_flow(self) -> None:
        bot = _make_bot()
        self.assertIs(bot.respond("hello").category, Category.GREETING)
        self.assertIs(
            bot.respond("what can you do").category, Category.QUESTION
        )
        name_reply = bot.respond("my name is Alice")
        self.assertIn("Alice", name_reply.text)
        self.assertEqual(bot.context.get_fact("name"), "Alice")
        follow_up = bot.respond("what did i just ask")
        self.assertIn("my name is Alice", follow_up.text)
        self.assertIs(bot.respond("bye").category, Category.FAREWELL)
        self.assertTrue(bot.ended)

    def test_unknown_streak_escalates(self) -> None:
        bot = _make_bot()
        r1 = bot.respond("xyzabc")
        r2 = bot.respond("qwerty")
        self.assertEqual(r1.unknown_streak, 1)
        self.assertEqual(r2.unknown_streak, 2)
        lowered = r2.text.lower()
        self.assertTrue(
            "still not sure" in lowered
            or "may need a hint" in lowered
            or "simpler question" in lowered,
            f"expected escalation response, got {r2.text!r}",
        )

    def test_unknown_streak_resets_on_known(self) -> None:
        bot = _make_bot()
        bot.respond("xyzabc")
        bot.respond("qwerty")
        r3 = bot.respond("hello")
        self.assertEqual(r3.unknown_streak, 0)
        r4 = bot.respond("asdf")
        self.assertEqual(r4.unknown_streak, 1)

    def test_name_persists_across_turns(self) -> None:
        bot = _make_bot()
        bot.respond("my name is Alice")
        bot.respond("what can you do")
        bot.respond("what time is it")
        self.assertEqual(bot.context.get_fact("name"), "Alice")

    def test_name_can_change(self) -> None:
        bot = _make_bot()
        bot.respond("my name is Alice")
        bot.respond("my name is Bob")
        self.assertEqual(bot.context.get_fact("name"), "Bob")

    def test_repeat_question_uses_repeat_template(self) -> None:
        bot = _make_bot()
        bot.respond("what time is it")
        r = bot.respond("what time is it")
        self.assertTrue(r.is_repeat)
        lowered = r.text.lower()
        self.assertTrue("asked" in lowered or "as i said" in lowered)

    def test_greeting_repeat_does_not_flag_repeat(self) -> None:
        # Only QUESTION-category intents participate in repeat detection.
        bot = _make_bot()
        bot.respond("hello")
        r = bot.respond("hello")
        self.assertFalse(r.is_repeat)

    def test_how_are_you_repeat_works(self) -> None:
        bot = _make_bot()
        bot.respond("my name is Alice")
        first = bot.respond("how are you")
        self.assertNotIn("again", first.text.lower())
        second = bot.respond("how are you")
        self.assertTrue(second.is_repeat)
        self.assertIn("again", second.text.lower())

    def test_farewell_mid_conversation(self) -> None:
        bot = _make_bot()
        bot.respond("hello")
        bot.respond("my name is Alice")
        r = bot.respond("bye")
        self.assertTrue(r.ended)
        self.assertTrue(bot.ended)


# --------------------------------------------------------------------- #
# Single-input edge cases
# --------------------------------------------------------------------- #


class EdgeCaseTests(unittest.TestCase):
    """Individual edge-case inputs must not crash and must be classified."""

    def test_empty_string(self) -> None:
        with self.assertRaises(InputValidationError):
            _make_bot().respond("")

    def test_whitespace_only(self) -> None:
        with self.assertRaises(InputValidationError):
            _make_bot().respond("   ")

    def test_tab_only(self) -> None:
        with self.assertRaises(InputValidationError):
            _make_bot().respond("\t\t")

    def test_newline_only(self) -> None:
        with self.assertRaises(InputValidationError):
            _make_bot().respond("\n\n")

    def test_non_string(self) -> None:
        with self.assertRaises(InputValidationError):
            _make_bot().respond(123)  # type: ignore[arg-type]

    def test_punctuation_only(self) -> None:
        r = _make_bot().respond("!@#$%^&*()")
        self.assertIs(r.category, Category.UNKNOWN)

    def test_special_chars_around_hello(self) -> None:
        r = _make_bot().respond("!!!hello!!!")
        self.assertIs(r.category, Category.GREETING)

    def test_emoji_input(self) -> None:
        r = _make_bot().respond("👋👋")
        self.assertIs(r.category, Category.UNKNOWN)

    def test_unicode_word_is_not_hello(self) -> None:
        # "héllo" is a different word from "hello" — should fall through.
        r = _make_bot().respond("héllo")
        self.assertIs(r.category, Category.UNKNOWN)

    def test_unicode_word_inside_name(self) -> None:
        # \w matches Unicode word chars in Python 3; Jöhn is extractable.
        bot = _make_bot()
        bot.respond("my name is Jöhn")
        self.assertEqual(bot.context.get_fact("name"), "Jöhn")

    def test_uppercase_hello(self) -> None:
        r = _make_bot().respond("HELLO THERE")
        self.assertIs(r.category, Category.GREETING)

    def test_uppercase_name_is_captured_verbatim(self) -> None:
        bot = _make_bot()
        bot.respond("MY NAME IS ALICE")
        self.assertEqual(bot.context.get_fact("name"), "ALICE")

    def test_double_space_inside_time_question(self) -> None:
        # Whitespace normalization makes this match "what time is it".
        r = _make_bot().respond("what  time  is  it")
        self.assertEqual(r.intent, "question.time_date")

    def test_tab_and_newline_inside_input(self) -> None:
        r = _make_bot().respond("what\t time\n is  it")
        self.assertEqual(r.intent, "question.time_date")

    def test_double_space_in_name_command(self) -> None:
        bot = _make_bot()
        bot.respond("my name is  Alice")
        self.assertEqual(bot.context.get_fact("name"), "Alice")

    def test_incomplete_name_command(self) -> None:
        # "my name is" with no name → no pattern matches → UNKNOWN.
        r = _make_bot().respond("my name is")
        self.assertIs(r.category, Category.UNKNOWN)

    def test_greeting_within_long_input(self) -> None:
        # Word boundaries still find "hello" at position 0.
        r = _make_bot().respond("hello " + "a" * 5000)
        self.assertIs(r.category, Category.GREETING)

    def test_very_long_gibberish(self) -> None:
        r = _make_bot().respond("a" * 5000)
        self.assertIs(r.category, Category.UNKNOWN)

    def test_multiple_matches_priority_decides(self) -> None:
        # "hi" matches greeting (priority 10); "what time is it" matches
        # question.time_date (priority 50). Question wins.
        r = _make_bot().respond("hi what time is it")
        self.assertEqual(r.intent, "question.time_date")

    def test_newline_separated_intents(self) -> None:
        r = _make_bot().respond("hello\nhow are you")
        self.assertEqual(r.intent, "question.how_are_you")

    def test_long_name_extraction(self) -> None:
        bot = _make_bot()
        long_name = "a" * 100
        bot.respond(f"my name is {long_name}")
        self.assertEqual(bot.context.get_fact("name"), long_name)


# --------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------- #


class SessionLifecycleTests(unittest.TestCase):
    """Session start / end edge cases."""

    def test_farewell_as_first_message(self) -> None:
        bot = _make_bot()
        r = bot.respond("bye")
        self.assertTrue(r.ended)
        self.assertEqual(len(bot.context), 1)

    def test_respond_after_farewell_raises(self) -> None:
        bot = _make_bot()
        bot.respond("bye")
        with self.assertRaises(SessionError):
            bot.respond("hello")

    def test_double_farewell_raises(self) -> None:
        bot = _make_bot()
        bot.respond("bye")
        with self.assertRaises(SessionError):
            bot.respond("bye")

    def test_context_readable_after_end(self) -> None:
        bot = _make_bot()
        bot.respond("hello")
        bot.respond("bye")
        msgs = bot.context.messages
        self.assertEqual(len(msgs), 4)
        self.assertEqual(
            [m.role.value for m in msgs], ["user", "bot", "user", "bot"]
        )


# --------------------------------------------------------------------- #
# Transcript integration
# --------------------------------------------------------------------- #


class TranscriptIntegrationTests(unittest.TestCase):
    """Transcript content after a realistic conversation."""

    def test_full_conversation_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot = _make_bot(transcript_dir=Path(tmp))
            bot.respond("hello")
            bot.respond("my name is Alice")
            bot.respond("what time is it")
            bot.respond("what time is it")
            bot.respond("bye")
            assert bot.transcript_path is not None
            data = json.loads(bot.transcript_path.read_text(encoding="utf-8"))
            self.assertTrue(data["ended_with_farewell"])
            self.assertEqual(data["facts"].get("name"), "Alice")
            self.assertEqual(len(data["messages"]), 10)  # 5 turns × 2

    def test_categories_preserved_in_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot = _make_bot(transcript_dir=Path(tmp))
            bot.respond("hello")
            bot.respond("what time is it")
            bot.respond("bye")
            assert bot.transcript_path is not None
            data = json.loads(bot.transcript_path.read_text(encoding="utf-8"))
            user_msgs = [m for m in data["messages"] if m["role"] == "user"]
            self.assertEqual(
                [m["category"] for m in user_msgs],
                ["greeting", "question", "farewell"],
            )

    def test_escalation_is_what_gets_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot = _make_bot(transcript_dir=Path(tmp))
            bot.respond("xyzabc")
            bot.respond("qwerty")
            bot.respond("bye")
            assert bot.transcript_path is not None
            data = json.loads(bot.transcript_path.read_text(encoding="utf-8"))
            bot_unknowns = [
                m
                for m in data["messages"]
                if m["role"] == "bot" and m["category"] == "unknown"
            ]
            self.assertEqual(len(bot_unknowns), 2)
            # Second unknown turn must use escalation, not the normal pool.
            lowered = bot_unknowns[1]["text"].lower()
            self.assertTrue(
                "still not sure" in lowered
                or "may need a hint" in lowered
                or "simpler question" in lowered
            )

    def test_transcript_records_normalized_text(self) -> None:
        # Whitespace normalization is visible in the saved transcript.
        with tempfile.TemporaryDirectory() as tmp:
            bot = _make_bot(transcript_dir=Path(tmp))
            bot.respond("my  name  is   Alice")
            bot.respond("bye")
            assert bot.transcript_path is not None
            data = json.loads(bot.transcript_path.read_text(encoding="utf-8"))
            user_texts = [
                m["text"] for m in data["messages"] if m["role"] == "user"
            ]
            self.assertIn("my name is Alice", user_texts)


# --------------------------------------------------------------------- #
# Stress / no-crash tests
# --------------------------------------------------------------------- #


class StressTests(unittest.TestCase):
    """No-crash tests, not performance tests."""

    def test_sliding_window_caps_at_max_turns(self) -> None:
        bot = _make_bot(max_turns=5)
        for i in range(30):
            bot.respond("hello")
            bot.respond(f"asdf{i}")
        self.assertEqual(len(bot.context), 5)

    def test_rapid_known_unknown_alternation(self) -> None:
        bot = _make_bot()
        for i in range(20):
            bot.respond("hello")
            r = bot.respond(f"asdf{i}")
            self.assertEqual(r.unknown_streak, 1)


if __name__ == "__main__":
    unittest.main()
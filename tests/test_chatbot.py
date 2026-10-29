"""Unit tests for the Chatbot facade."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from aria.chatbot import Chatbot, ChatbotReply
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


class FlowTests(unittest.TestCase):
    """Tests for the main respond() loop."""

    def test_hello_returns_greeting(self) -> None:
        bot = _make_bot()
        reply = bot.respond("hello")
        self.assertIsInstance(reply, ChatbotReply)
        self.assertIs(reply.category, Category.GREETING)
        self.assertFalse(reply.ended)
        self.assertFalse(bot.ended)

    def test_farewell_ends_session(self) -> None:
        bot = _make_bot()
        reply = bot.respond("bye")
        self.assertIs(reply.category, Category.FAREWELL)
        self.assertTrue(reply.ended)
        self.assertTrue(bot.ended)

    def test_respond_after_end_raises(self) -> None:
        bot = _make_bot()
        bot.respond("bye")
        with self.assertRaises(SessionError):
            bot.respond("hello")

    def test_empty_input_rejected(self) -> None:
        bot = _make_bot()
        with self.assertRaises(InputValidationError):
            bot.respond("    ")

    def test_non_string_input_rejected(self) -> None:
        bot = _make_bot()
        with self.assertRaises(InputValidationError):
            bot.respond(123)  # type: ignore[arg-type]

    def test_unknown_returns_fallback(self) -> None:
        bot = _make_bot()
        reply = bot.respond("asdfgh")
        self.assertIs(reply.category, Category.UNKNOWN)
        self.assertEqual(reply.unknown_streak, 1)
        self.assertFalse(reply.ended)

    def test_unknown_streak_increments(self) -> None:
        bot = _make_bot()
        r1 = bot.respond("asdfgh")
        r2 = bot.respond("qwerty")
        self.assertEqual(r1.unknown_streak, 1)
        self.assertEqual(r2.unknown_streak, 2)

    def test_unknown_streak_resets_on_known(self) -> None:
        bot = _make_bot()
        bot.respond("asdfgh")
        reply = bot.respond("hello")
        self.assertEqual(reply.unknown_streak, 0)

    def test_remembers_name(self) -> None:
        bot = _make_bot()
        bot.respond("my name is Alice")
        self.assertEqual(bot.context.get_fact("name"), "Alice")

    def test_last_question_followup(self) -> None:
        bot = _make_bot()
        bot.respond("what time is it")
        reply = bot.respond("what did i just ask")
        self.assertIn("what time is it", reply.text)

    def test_repeat_uses_repeat_responses(self) -> None:
        bot = _make_bot()
        bot.respond("what time is it")
        reply = bot.respond("what time is it")
        self.assertTrue(reply.is_repeat)
        lowered = reply.text.lower()
        self.assertTrue(
            "asked" in lowered or "as i said" in lowered,
            f"expected repeat template, got {reply.text!r}",
        )

    def test_non_repeat_does_not_flag_repeat(self) -> None:
        bot = _make_bot()
        reply = bot.respond("what time is it")
        self.assertFalse(reply.is_repeat)

    def test_reply_carries_timestamp(self) -> None:
        bot = _make_bot()
        reply = bot.respond("hello")
        self.assertEqual(reply.timestamp, _FIXED_TIME)

    def test_context_records_both_messages(self) -> None:
        bot = _make_bot()
        bot.respond("hello")
        messages = bot.context.messages
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role.value, "user")
        self.assertEqual(messages[1].role.value, "bot")


class TranscriptTests(unittest.TestCase):
    """Tests for transcript saving."""

    def test_saves_on_farewell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dir_ = Path(tmp)
            bot = _make_bot(transcript_dir=dir_)
            bot.respond("hello")
            bot.respond("bye")
            self.assertIsNotNone(bot.transcript_path)
            assert bot.transcript_path is not None
            self.assertTrue(bot.transcript_path.exists())
            data = json.loads(bot.transcript_path.read_text())
            self.assertTrue(data["ended_with_farewell"])
            self.assertEqual(len(data["messages"]), 4)

    def test_no_save_when_dir_not_set(self) -> None:
        bot = _make_bot()
        bot.respond("bye")
        self.assertIsNone(bot.transcript_path)

    def test_save_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dir_ = Path(tmp)
            bot = _make_bot(transcript_dir=dir_)
            bot.respond("hello")
            p1 = bot.save_transcript(dir_)
            p2 = bot.save_transcript(dir_)
            self.assertEqual(p1, p2)

    def test_save_includes_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dir_ = Path(tmp)
            bot = _make_bot(transcript_dir=dir_)
            bot.respond("my name is Alice")
            bot.respond("bye")
            assert bot.transcript_path is not None
            data = json.loads(bot.transcript_path.read_text())
            self.assertEqual(data["facts"].get("name"), "Alice")


if __name__ == "__main__":
    unittest.main()
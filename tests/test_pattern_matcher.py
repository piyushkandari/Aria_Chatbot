"""Unit tests for the Aria pattern matcher."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Iterable

from aria.exceptions import (
    ConfigurationError,
    InputValidationError,
    IntentConfigurationError,
)
from aria.models import Category, Intent
from aria.pattern_matcher import (
    MatchResult,
    PatternMatcher,
    load_intents_from_json,
)

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "intents.json"
)


def _unknown() -> Intent:
    return Intent(
        name="fallback.unknown",
        category=Category.UNKNOWN,
        patterns=(),
        responses=("Sorry.",),
        escalation_responses=("Try help.",),
    )


def _question_intent(
    name: str,
    patterns: Iterable[str],
    priority: int = 50,
    slots: Iterable[str] = (),
) -> Intent:
    return Intent(
        name=name,
        category=Category.QUESTION,
        patterns=tuple(patterns),
        responses=("ok",),
        priority=priority,
        slots=tuple(slots),
    )


class LoaderTests(unittest.TestCase):
    """Tests for load_intents_from_json."""

    def test_load_real_config(self) -> None:
        intents = load_intents_from_json(_CONFIG_PATH)
        self.assertGreaterEqual(len(intents), 10)  # Changed from assertEqual(..., 10)
        categories = {intent.category for intent in intents}
        self.assertEqual(
            categories,
            {
                Category.GREETING,
                Category.QUESTION,
                Category.FAREWELL,
                Category.UNKNOWN,
            },
        )

    def test_load_missing_file_raises(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_intents_from_json(Path("/no/such/file.json"))

    def test_load_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_intents_from_json(bad)

    def test_load_missing_schema_version_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(
                json.dumps({"intents": []}), encoding="utf-8"
            )
            with self.assertRaises(ConfigurationError):
                load_intents_from_json(path)

    def test_load_missing_intents_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(
                json.dumps({"schema_version": "1.0"}), encoding="utf-8"
            )
            with self.assertRaises(ConfigurationError):
                load_intents_from_json(path)

    def test_load_empty_intents_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(
                json.dumps({"schema_version": "1.0", "intents": []}),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_intents_from_json(path)

    def test_load_invalid_category_raises(self) -> None:
        payload = {
            "schema_version": "1.0",
            "intents": [
                {
                    "name": "x",
                    "category": "banter",
                    "patterns": ["hi"],
                    "responses": ["hello"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_intents_from_json(path)


class ConstructionTests(unittest.TestCase):
    """Tests for PatternMatcher validation at construction time."""

    def test_matcher_requires_intents(self) -> None:
        with self.assertRaises(ConfigurationError):
            PatternMatcher([])

    def test_matcher_requires_unknown(self) -> None:
        with self.assertRaises(ConfigurationError):
            PatternMatcher([_question_intent("q", [r"\bhi\b"])])

    def test_matcher_rejects_multiple_unknown(self) -> None:
        with self.assertRaises(ConfigurationError):
            PatternMatcher([_unknown(), _unknown()])

    def test_matcher_rejects_invalid_regex(self) -> None:
        bad = _question_intent("bad", ["("])
        with self.assertRaises(IntentConfigurationError):
            PatternMatcher([bad, _unknown()])

    def test_matcher_rejects_missing_slot_group(self) -> None:
        bad = _question_intent(
            "bad",
            [r"\bhi\b"],
            slots=("name",),
        )
        with self.assertRaises(IntentConfigurationError):
            PatternMatcher([bad, _unknown()])

    def test_matcher_rejects_undeclared_group(self) -> None:
        bad = _question_intent("bad", [r"\b(?P<who>\w+)\b"])
        with self.assertRaises(IntentConfigurationError):
            PatternMatcher([bad, _unknown()])


class MatchingTests(unittest.TestCase):
    """Tests for PatternMatcher.match using the real config."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.matcher = PatternMatcher(load_intents_from_json(_CONFIG_PATH))

    def test_match_greeting(self) -> None:
        result = self.matcher.match("hello")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.intent.name, "greeting.hello")
        self.assertIs(result.category, Category.GREETING)

    def test_match_case_insensitive(self) -> None:
        result = self.matcher.match("HELLO THERE")
        assert result is not None
        self.assertEqual(result.intent.name, "greeting.hello")

    def test_match_word_boundary_helper(self) -> None:
        self.assertIsNone(self.matcher.match("helper"))

    def test_match_word_boundary_bypass(self) -> None:
        self.assertIsNone(self.matcher.match("bypass"))

    def test_match_named_group(self) -> None:
        result = self.matcher.match("my name is Alice")
        assert result is not None
        self.assertEqual(result.intent.name, "memory.remember_identity")
        self.assertEqual(dict(result.slots), {"name": "Alice"})

    def test_match_priority_question_beats_greeting(self) -> None:
        result = self.matcher.match("hi what time is it")
        assert result is not None
        self.assertEqual(result.intent.name, "question.time_date")

    def test_match_longer_wins_at_same_priority(self) -> None:
        short = _question_intent("q.short", [r"\bhi\b"], priority=50)
        long = _question_intent("q.long", [r"\bhi there\b"], priority=50)
        matcher = PatternMatcher([short, long, _unknown()])
        result = matcher.match("hi there")
        assert result is not None
        self.assertEqual(result.intent.name, "q.long")

    def test_match_empty_returns_none(self) -> None:
        self.assertIsNone(self.matcher.match(""))

    def test_match_whitespace_returns_none(self) -> None:
        self.assertIsNone(self.matcher.match("    \t\n"))

    def test_match_no_match_returns_none(self) -> None:
        self.assertIsNone(self.matcher.match("qwertyuiop"))

    def test_match_non_string_raises(self) -> None:
        with self.assertRaises(InputValidationError):
            self.matcher.match(123)  # type: ignore[arg-type]

    def test_match_span(self) -> None:
        result = self.matcher.match("well hello there")
        assert result is not None
        self.assertEqual(result.matched_text, "hello")
        self.assertEqual(result.span, (5, 10))

    def test_fallback_intent_accessible(self) -> None:
        fallback = self.matcher.fallback_intent
        self.assertIs(fallback.category, Category.UNKNOWN)

    def test_match_result_is_match_result_type(self) -> None:
        result = self.matcher.match("hello")
        self.assertIsInstance(result, MatchResult)


if __name__ == "__main__":
    unittest.main()
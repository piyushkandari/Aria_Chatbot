"""Unit tests for the Aria response generator."""

from __future__ import annotations

import random
import unittest
from datetime import datetime

from aria.exceptions import (
    InputValidationError,
    ResponseGenerationError,
)
from aria.models import Category, Intent
from aria.response_generator import (
    BUILTIN_PLACEHOLDERS,
    UNKNOWN_ESCALATION_THRESHOLD,
    GeneratedResponse,
    ResponseGenerator,
)

_FIXED_TIME = datetime(2025, 1, 1, 12, 30, 0)


def _fixed_clock() -> datetime:
    return _FIXED_TIME


def _intent(
    name: str,
    category: Category,
    responses: tuple[str, ...],
    patterns: tuple[str, ...] = (r"\bplaceholder\b",),
    slots: tuple[str, ...] = (),
    escalation: tuple[str, ...] = (),
    priority: int = 50,
) -> Intent:
    return Intent(
        name=name,
        category=category,
        patterns=patterns,
        responses=responses,
        slots=slots,
        escalation_responses=escalation,
        priority=priority,
    )


def _question_intent(
    name: str,
    responses: tuple[str, ...],
    slots: tuple[str, ...] = (),
) -> Intent:
    return _intent(name, Category.QUESTION, responses, slots=slots)


def _unknown_intent(
    responses: tuple[str, ...],
    escalation: tuple[str, ...] = (),
) -> Intent:
    return _intent(
        "fallback.unknown",
        Category.UNKNOWN,
        responses,
        patterns=(),
        escalation=escalation,
        priority=0,
    )


class ValidationTests(unittest.TestCase):
    """Template validation at construction time."""

    def test_reject_unknown_placeholder(self) -> None:
        bad = _question_intent("q", ("Hello, {who}!",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])

    def test_reject_positional_placeholder(self) -> None:
        bad = _question_intent("q", ("Value: {0}",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])

    def test_reject_format_spec(self) -> None:
        bad = _question_intent("q", ("Name: {name:>10}",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])

    def test_reject_conversion(self) -> None:
        bad = _question_intent("q", ("Name: {name!r}",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])

    def test_reject_unclosed_brace(self) -> None:
        bad = _question_intent("q", ("Hello, {name",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])

    def test_allow_slot_placeholder(self) -> None:
        good = _question_intent(
            "memory.remember_name",
            ("Nice to meet you, {name}.",),
            slots=("name",),
        )
        ResponseGenerator([good])  # should not raise

    def test_allow_builtin_placeholders(self) -> None:
        for placeholder in sorted(BUILTIN_PLACEHOLDERS):
            with self.subTest(placeholder=placeholder):
                intent = _question_intent(
                    f"q.{placeholder}", (f"X {placeholder} Y",)
                )
                ResponseGenerator([intent])  # should not raise

    def test_allow_escaped_braces(self) -> None:
        good = _question_intent("q", ("Literal {{brace}}",))
        ResponseGenerator([good])  # should not raise

    def test_reject_duplicate_intent_name(self) -> None:
        a = _question_intent("dup", ("a",))
        b = _question_intent("dup", ("b",))
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([a, b])

    def test_reject_non_intent_in_constructor(self) -> None:
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator(["not an intent"])  # type: ignore[list-item]


class GenerateTests(unittest.TestCase):
    """Tests for ResponseGenerator.generate."""

    def setUp(self) -> None:
        self.gen = ResponseGenerator(
            [self._intent()], rng=random.Random(0), clock=_fixed_clock
        )

    @staticmethod
    def _intent() -> Intent:
        return _question_intent("q", ("hello",))

    def _generator(self, intents: list[Intent]) -> ResponseGenerator:
        return ResponseGenerator(
            intents, rng=random.Random(0), clock=_fixed_clock
        )

    def test_simple_response(self) -> None:
        intent = _question_intent("q.simple", ("hello",))
        gen = self._generator([intent])
        result = gen.generate(intent)
        self.assertIsInstance(result, GeneratedResponse)
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.template, "hello")
        self.assertEqual(result.intent_name, "q.simple")
        self.assertIs(result.category, Category.QUESTION)

    def test_fills_time_and_date(self) -> None:
        intent = _question_intent(
            "q.time", ("It is {time} on {date}.",)
        )
        gen = self._generator([intent])
        result = gen.generate(intent)
        self.assertEqual(result.text, "It is 12:30 on 2025-01-01.")

    def test_slot_overrides_fact(self) -> None:
        intent = _question_intent(
            "memory.remember_name",
            ("Hi {name}",),
            slots=("name",),
        )
        gen = self._generator([intent])
        result = gen.generate(
            intent, slots={"name": "Alice"}, facts={"name": "Bob"}
        )
        self.assertEqual(result.text, "Hi Alice")

    def test_fact_used_when_slot_absent(self) -> None:
        intent = _question_intent("q.fact", ("Hi {name}",))
        gen = self._generator([intent])
        result = gen.generate(intent, facts={"name": "Alice"})
        self.assertEqual(result.text, "Hi Alice")

    def test_empty_slot_falls_through_to_fact(self) -> None:
        intent = _question_intent(
            "memory.remember_name",
            ("Hi {name}",),
            slots=("name",),
        )
        gen = self._generator([intent])
        result = gen.generate(
            intent, slots={"name": ""}, facts={"name": "Alice"}
        )
        self.assertEqual(result.text, "Hi Alice")

    def test_skips_unrenderable_template(self) -> None:
        intent = _question_intent(
            "q.multi", ("Hi {name}", "Hello there", "Hi again {name}")
        )
        gen = self._generator([intent])
        for _ in range(10):
            result = gen.generate(intent)
            self.assertEqual(result.text, "Hello there")

    def test_raises_when_no_template_renderable(self) -> None:
        intent = _question_intent("q.strict", ("Hi {name}",))
        gen = self._generator([intent])
        with self.assertRaises(ResponseGenerationError):
            gen.generate(intent)

    def test_uses_last_question(self) -> None:
        intent = _question_intent(
            "memory.last_question",
            ("You asked: {last_question}",),
        )
        gen = self._generator([intent])
        result = gen.generate(intent, last_question="what time is it")
        self.assertEqual(result.text, "You asked: what time is it")

    def test_skips_last_question_template_when_missing(self) -> None:
        intent = _question_intent(
            "q.mixed", ("You asked: {last_question}", "You asked something.")
        )
        gen = self._generator([intent])
        result = gen.generate(intent)
        self.assertEqual(result.text, "You asked something.")

    def test_repeated_placeholder_in_one_template(self) -> None:
        intent = _question_intent("q.rep", ("{name}, meet {name}",))
        gen = self._generator([intent])
        result = gen.generate(intent, facts={"name": "Alice"})
        self.assertEqual(result.text, "Alice, meet Alice")

    def test_escaped_braces_in_output(self) -> None:
        intent = _question_intent("q.esc", ("Use {{braces}} carefully",))
        gen = self._generator([intent])
        result = gen.generate(intent)
        self.assertEqual(result.text, "Use {braces} carefully")

    def test_lazy_validates_new_intent(self) -> None:
        gen = ResponseGenerator(
            [_question_intent("q", ("hi",))],
            rng=random.Random(0),
            clock=_fixed_clock,
        )
        new = _question_intent("q.new", ("hello",))
        result = gen.generate(new)
        self.assertEqual(result.text, "hello")

    def test_lazy_validation_raises_for_bad_new_intent(self) -> None:
        gen = ResponseGenerator(
            [_question_intent("q", ("hi",))],
            rng=random.Random(0),
            clock=_fixed_clock,
        )
        bad = _question_intent("q.bad", ("Hello {who}",))
        with self.assertRaises(ResponseGenerationError):
            gen.generate(bad)


class VariationTests(unittest.TestCase):
    """Tests for template variation."""

    def test_seeded_rng_is_deterministic(self) -> None:
        intent = _question_intent("q", ("a", "b", "c"))
        gen_a = ResponseGenerator(
            [intent], rng=random.Random(42), clock=_fixed_clock
        )
        gen_b = ResponseGenerator(
            [intent], rng=random.Random(42), clock=_fixed_clock
        )
        seq_a = [gen_a.generate(intent).text for _ in range(9)]
        seq_b = [gen_b.generate(intent).text for _ in range(9)]
        self.assertEqual(seq_a, seq_b)

    def test_distribution_covers_all_templates(self) -> None:
        intent = _question_intent("q", ("a", "b", "c", "d", "e"))
        gen = ResponseGenerator(
            [intent], rng=random.Random(7), clock=_fixed_clock
        )
        seen = {gen.generate(intent).text for _ in range(200)}
        self.assertEqual(seen, {"a", "b", "c", "d", "e"})


class EscalationTests(unittest.TestCase):
    """Tests for unknown-fallback escalation."""

    def setUp(self) -> None:
        self.intent = _unknown_intent(
            responses=("Sorry?", "Try again."),
            escalation=("Still lost — type 'help'.",),
        )
        self.gen = ResponseGenerator(
            [self.intent], rng=random.Random(0), clock=_fixed_clock
        )

    def test_streak_zero_uses_normal(self) -> None:
        for _ in range(20):
            result = self.gen.generate(self.intent, unknown_streak=0)
            self.assertIn(result.text, ("Sorry?", "Try again."))

    def test_streak_one_uses_normal(self) -> None:
        for _ in range(20):
            result = self.gen.generate(self.intent, unknown_streak=1)
            self.assertIn(result.text, ("Sorry?", "Try again."))

    def test_streak_at_threshold_uses_escalation(self) -> None:
        self.assertGreaterEqual(UNKNOWN_ESCALATION_THRESHOLD, 2)
        for _ in range(10):
            result = self.gen.generate(
                self.intent,
                unknown_streak=UNKNOWN_ESCALATION_THRESHOLD,
            )
            self.assertEqual(result.text, "Still lost — type 'help'.")

    def test_no_escalation_falls_back_to_normal(self) -> None:
        intent = _unknown_intent(responses=("Sorry?",))
        gen = ResponseGenerator(
            [intent], rng=random.Random(0), clock=_fixed_clock
        )
        result = gen.generate(intent, unknown_streak=5)
        self.assertEqual(result.text, "Sorry?")

    def test_non_unknown_ignores_escalation(self) -> None:
        intent = _intent(
            "q.x",
            Category.QUESTION,
            responses=("normal",),
            escalation=("escalated",),
        )
        gen = ResponseGenerator(
            [intent], rng=random.Random(0), clock=_fixed_clock
        )
        result = gen.generate(intent, unknown_streak=5)
        self.assertEqual(result.text, "normal")


class ArgumentValidationTests(unittest.TestCase):
    """Tests for generate() argument validation."""

    def setUp(self) -> None:
        self.intent = _question_intent("q", ("hi",))
        self.gen = ResponseGenerator(
            [self.intent], rng=random.Random(0), clock=_fixed_clock
        )

    def test_reject_non_intent(self) -> None:
        with self.assertRaises(InputValidationError):
            self.gen.generate("q")  # type: ignore[arg-type]

    def test_reject_negative_streak(self) -> None:
        with self.assertRaises(InputValidationError):
            self.gen.generate(self.intent, unknown_streak=-1)

    def test_reject_bool_streak(self) -> None:
        with self.assertRaises(InputValidationError):
            self.gen.generate(self.intent, unknown_streak=True)  # type: ignore[arg-type]

    def test_reject_float_streak(self) -> None:
        with self.assertRaises(InputValidationError):
            self.gen.generate(self.intent, unknown_streak=1.5)  # type: ignore[arg-type]


class RepeatResponseTests(unittest.TestCase):
    """Tests for repeat_responses pool selection."""

    def setUp(self) -> None:
        self.intent = Intent(
            name="q.repeat",
            category=Category.QUESTION,
            patterns=(r"\bhi\b",),
            responses=("normal",),
            repeat_responses=("again {time}",),
        )
        self.gen = ResponseGenerator(
            [self.intent], rng=random.Random(0), clock=_fixed_clock
        )

    def test_non_repeat_uses_normal(self) -> None:
        result = self.gen.generate(self.intent, is_repeat=False)
        self.assertEqual(result.text, "normal")

    def test_repeat_uses_repeat_pool(self) -> None:
        result = self.gen.generate(self.intent, is_repeat=True)
        self.assertEqual(result.text, "again 12:30")

    def test_repeat_falls_back_when_repeat_responses_empty(self) -> None:
        intent = _question_intent("q.no_rep", ("normal",))
        gen = ResponseGenerator(
            [intent], rng=random.Random(0), clock=_fixed_clock
        )
        result = gen.generate(intent, is_repeat=True)
        self.assertEqual(result.text, "normal")

    def test_repeat_validation_rejects_bad_placeholder(self) -> None:
        bad = Intent(
            name="q.bad",
            category=Category.QUESTION,
            patterns=(r"\bhi\b",),
            responses=("ok",),
            repeat_responses=("Oops {who}",),
        )
        with self.assertRaises(ResponseGenerationError):
            ResponseGenerator([bad])


if __name__ == "__main__":
    unittest.main()
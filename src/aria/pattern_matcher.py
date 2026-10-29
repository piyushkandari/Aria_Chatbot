"""Regex-based pattern matching engine for the Aria chatbot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .exceptions import (
    ConfigurationError,
    InputValidationError,
    IntentConfigurationError,
)
from .logger_config import get_logger
from .models import Category, Intent

_LOGGER = get_logger("pattern_matcher")


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The best intent match for a given user input."""

    intent: Intent
    slots: Mapping[str, str]
    matched_text: str
    span: tuple[int, int]

    @property
    def category(self) -> Category:
        """Return the category of the matched intent."""
        return self.intent.category


@dataclass(frozen=True, slots=True)
class _CompiledIntent:
    """Internal: an intent with its precompiled regex patterns."""

    intent: Intent
    patterns: tuple[re.Pattern[str], ...]


class PatternMatcher:
    """Match user text against precompiled intent regexes.

    Rules:
    1. Highest priority matching intent wins.
    2. Among intents with equal priority, the longest matched span wins.
    3. Among equal priority and equal length, the earliest intent in
       configuration order wins.
    """

    def __init__(self, intents: Sequence[Intent]) -> None:
        """Compile and validate intents for matching."""
        if not intents:
            raise ConfigurationError(
                "PatternMatcher requires at least one intent."
            )

        compiled = tuple(self._compile(intent) for intent in intents)
        unknown_count = sum(
            1 for ci in compiled if ci.intent.category is Category.UNKNOWN
        )
        if unknown_count == 0:
            raise ConfigurationError(
                "Configuration must include exactly one UNKNOWN intent."
            )
        if unknown_count > 1:
            raise ConfigurationError(
                "Configuration must not include more than one UNKNOWN intent."
            )

        self._compiled: tuple[_CompiledIntent, ...] = compiled
        _LOGGER.debug(
            "PatternMatcher initialised with %d intents", len(self._compiled)
        )

    @staticmethod
    def _compile(intent: Intent) -> _CompiledIntent:
        compiled_patterns: list[re.Pattern[str]] = []
        for pattern_str in intent.patterns:
            try:
                compiled_patterns.append(
                    re.compile(pattern_str, re.IGNORECASE)
                )
            except re.error as exc:
                raise IntentConfigurationError(
                    f"Invalid regex {pattern_str!r} in intent "
                    f"{intent.name!r}: {exc}"
                ) from exc

        declared_slots = set(intent.slots)

        for slot in intent.slots:
            if not any(slot in p.groupindex for p in compiled_patterns):
                raise IntentConfigurationError(
                    f"Slot {slot!r} declared in intent {intent.name!r} "
                    f"has no matching named group in any pattern."
                )

        for pattern in compiled_patterns:
            for group_name in pattern.groupindex:
                if group_name not in declared_slots:
                    raise IntentConfigurationError(
                        f"Pattern in intent {intent.name!r} declares named "
                        f"group {group_name!r} not listed in 'slots'."
                    )

        return _CompiledIntent(
            intent=intent, patterns=tuple(compiled_patterns)
        )

    @property
    def fallback_intent(self) -> Intent:
        """Return the configured UNKNOWN intent used as the fallback."""
        for ci in self._compiled:
            if ci.intent.category is Category.UNKNOWN:
                return ci.intent
        raise ConfigurationError("No UNKNOWN intent found.")

    def match(self, text: str) -> MatchResult | None:
        """Return the best MatchResult for ``text`` or ``None`` on no match."""
        if not isinstance(text, str):
            raise InputValidationError("Input text must be a string.")
        if not text.strip():
            return None

        best: MatchResult | None = None
        for compiled in self._compiled:
            for pattern in compiled.patterns:
                found = pattern.search(text)
                if found is None:
                    continue

                candidate = MatchResult(
                    intent=compiled.intent,
                    slots=MappingProxyType(dict(found.groupdict())),
                    matched_text=found.group(0),
                    span=found.span(),
                )

                if self._is_better(candidate, best):
                    best = candidate

        if best is not None:
            _LOGGER.debug(
                "Match: intent=%s category=%s priority=%d span=%s",
                best.intent.name,
                best.category.value,
                best.intent.priority,
                best.span,
            )
        else:
            _LOGGER.debug("No match for input of length %d", len(text))
        return best

    @staticmethod
    def _is_better(candidate: MatchResult, current: MatchResult | None) -> bool:
        if current is None:
            return True
        if candidate.intent.priority != current.intent.priority:
            return candidate.intent.priority > current.intent.priority
        return len(candidate.matched_text) > len(current.matched_text)


def load_intents_from_json(path: Path | str) -> tuple[Intent, ...]:
    """Load and validate intents from a JSON configuration file."""
    config_path = path if isinstance(path, Path) else Path(path)

    if not config_path.exists():
        raise ConfigurationError(
            f"Intents config file not found: {config_path}"
        )

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(
            f"Failed to read intents config {config_path}: {exc}"
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {config_path}: {exc.msg} at line {exc.lineno}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigurationError("Top-level config must be a JSON object.")
    if "schema_version" not in data:
        raise ConfigurationError(
            "Config missing required 'schema_version' field."
        )
    if "intents" not in data:
        raise ConfigurationError("Config missing required 'intents' field.")

    intents_raw = data["intents"]
    if not isinstance(intents_raw, list):
        raise ConfigurationError("'intents' must be a JSON list.")
    if not intents_raw:
        raise ConfigurationError("'intents' list must not be empty.")

    intents: list[Intent] = [
        _intent_from_dict(item, index)
        for index, item in enumerate(intents_raw)
    ]

    _LOGGER.info("Loaded %d intents from %s", len(intents), config_path)
    return tuple(intents)


def _intent_from_dict(data: object, index: int) -> Intent:
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Intent at index {index} must be a JSON object."
        )

    for field_name in ("name", "category", "responses"):
        if field_name not in data:
            raise ConfigurationError(
                f"Intent at index {index} missing required field "
                f"{field_name!r}."
            )

    try:
        category = Category(data["category"])
    except ValueError as exc:
        raise ConfigurationError(
            f"Invalid category {data['category']!r} at intent index {index}."
        ) from exc

    patterns = data.get("patterns", [])
    if not isinstance(patterns, list) or not all(
        isinstance(item, str) for item in patterns
    ):
        raise ConfigurationError(
            f"'patterns' at intent index {index} must be a list of strings."
        )

    responses = data["responses"]
    if not isinstance(responses, list) or not all(
        isinstance(item, str) for item in responses
    ):
        raise ConfigurationError(
            f"'responses' at intent index {index} must be a list of strings."
        )

    slots = data.get("slots", [])
    if not isinstance(slots, list) or not all(
        isinstance(item, str) for item in slots
    ):
        raise ConfigurationError(
            f"'slots' at intent index {index} must be a list of strings."
        )

    escalation = data.get("escalation_responses", [])
    if not isinstance(escalation, list) or not all(
        isinstance(item, str) for item in escalation
    ):
        raise ConfigurationError(
            f"'escalation_responses' at intent index {index} must be a "
            f"list of strings."
        )

    repeat = data.get("repeat_responses", [])
    if not isinstance(repeat, list) or not all(
        isinstance(item, str) for item in repeat
    ):
        raise ConfigurationError(
            f"'repeat_responses' at intent index {index} must be a list "
            f"of strings."
        )

    fallback = data.get("fallback_responses", [])
    if not isinstance(fallback, list) or not all(
        isinstance(item, str) for item in fallback
    ):
        raise ConfigurationError(
            f"'fallback_responses' at intent index {index} must be a list "
            f"of strings."
        )

    priority = data.get("priority", 100)
    if not isinstance(priority, int) or isinstance(priority, bool) \
            or priority < 0:
        raise ConfigurationError(
            f"'priority' at intent index {index} must be a non-negative int."
        )

    try:
        return Intent(
            name=data["name"],
            category=category,
            patterns=tuple(patterns),
            responses=tuple(responses),
            priority=priority,
            slots=tuple(slots),
            escalation_responses=tuple(escalation),
            repeat_responses=tuple(repeat),
            fallback_responses=tuple(fallback),
        )
    except (IntentConfigurationError, InputValidationError) as exc:
        raise ConfigurationError(
            f"Invalid intent at index {index}: {exc}"
        ) from exc
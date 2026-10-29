"""Response generation for the Aria chatbot.

Given a matched intent, its extracted slots, remembered user facts, and a
small amount of derived context (time, date, previous question), pick a
response template and fill in its placeholders.

The generator is stateless with respect to the conversation: repeat
detection, unknown streaks, and memory lookups are the chatbot facade's
job (Phase 5). The generator receives that information as arguments.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Final, Iterable, Mapping

from .exceptions import InputValidationError, ResponseGenerationError
from .logger_config import get_logger
from .models import Category, Intent

_LOGGER = get_logger("response_generator")

BUILTIN_PLACEHOLDERS: Final[frozenset[str]] = frozenset(
    {"name", "company", "time", "date", "last_question"}
)
"""Placeholders the generator can fill without an intent declaring a slot.

``time`` and ``date`` are computed from the injected clock; ``name`` and
``company`` are resolved from slots or facts; ``last_question`` is passed
by the caller and only present when not ``None``.
"""

UNKNOWN_ESCALATION_THRESHOLD: Final[int] = 2
"""Consecutive unknowns required to switch to escalation responses."""

TIME_FORMAT: Final[str] = "%H:%M"
DATE_FORMAT: Final[str] = "%Y-%m-%d"


@dataclass(frozen=True, slots=True)
class GeneratedResponse:
    """A rendered response ready to be sent back to the user."""

    text: str
    template: str
    intent_name: str
    category: Category


class ResponseGenerator:
    """Pick and fill response templates for matched intents."""

    def __init__(
        self,
        intents: Iterable[Intent],
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Validate intents and prepare a generator.

        Args:
            intents: All intents the generator may be asked to render.
                Their templates are validated eagerly.
            rng: Optional ``random.Random`` instance. Inject a seeded one
                for deterministic tests.
            clock: Callable returning ``datetime`` for ``{time}`` and
                ``{date}``. Defaults to ``datetime.now`` (local time).
        """
        self._rng: random.Random = rng if rng is not None else random.Random()
        self._clock: Callable[[], datetime] = clock or datetime.now
        self._validated: set[str] = set()
        self._validate_intents(intents)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def _validate_intents(self, intents: Iterable[Intent]) -> None:
        seen: set[str] = set()
        for intent in intents:
            if not isinstance(intent, Intent):
                raise ResponseGenerationError(
                    f"Expected Intent, got {type(intent).__name__}."
                )
            if intent.name in seen:
                raise ResponseGenerationError(
                    f"Duplicate intent name {intent.name!r}."
                )
            seen.add(intent.name)
            self._validate_intent(intent)
        _LOGGER.debug("Validated %d intents", len(seen))

    def _validate_intent(self, intent: Intent) -> None:
        allowed = BUILTIN_PLACEHOLDERS | frozenset(intent.slots)
        for template in (
            intent.responses
            + intent.escalation_responses
            + intent.repeat_responses
            + intent.fallback_responses
        ):
            used = self._extract_placeholders(template)
            unknown = used - allowed
            if unknown:
                raise ResponseGenerationError(
                    f"Intent {intent.name!r} template {template!r} uses "
                    f"unsupported placeholders {sorted(unknown)}. "
                    f"Allowed: {sorted(allowed)}."
                )
        self._validated.add(intent.name)

    @staticmethod
    def _extract_placeholders(template: str) -> set[str]:
        """Return the bare placeholder names used in ``template``."""
        try:
            parsed = list(string.Formatter().parse(template))
        except ValueError as exc:
            raise ResponseGenerationError(
                f"Malformed template {template!r}: {exc}"
            ) from exc

        names: set[str] = set()
        for _literal, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if format_spec or conversion:
                raise ResponseGenerationError(
                    f"Template {template!r} uses a format spec or "
                    f"conversion for {{{field_name}}}; only bare "
                    f"placeholders are supported."
                )
            if not field_name.isidentifier():
                raise ResponseGenerationError(
                    f"Template {template!r} uses non-identifier "
                    f"placeholder {field_name!r}."
                )
            names.add(field_name)
        return names

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #

    def generate(
        self,
        intent: Intent,
        slots: Mapping[str, str] | None = None,
        facts: Mapping[str, str] | None = None,
        last_question: str | None = None,
        unknown_streak: int = 0,
        is_repeat: bool = False,
    ) -> GeneratedResponse:
        """Render a response for ``intent``.

        Args:
            intent: The matched intent. If not seen at construction time,
                its templates are validated lazily.
            slots: Slot values extracted by the matcher for this turn.
                These override ``facts`` in the rendering data.
            facts: Remembered user facts (for example, ``name``).
            last_question: The user's previous question, when available.
            unknown_streak: Consecutive UNKNOWN matches including this
                turn. Used only when ``intent.category`` is UNKNOWN.
            is_repeat: True when this turn repeats an earlier question.
                Only used when ``intent.repeat_responses`` is non-empty.

        Raises:
            InputValidationError: On invalid arguments.
            ResponseGenerationError: If no template can be rendered
                (for example, all require ``{name}`` but it is unset).
        """
        if not isinstance(intent, Intent):
            raise InputValidationError("intent must be an Intent instance.")
        if isinstance(unknown_streak, bool) or not isinstance(unknown_streak, int):
            raise InputValidationError("unknown_streak must be an integer.")
        if unknown_streak < 0:
            raise InputValidationError("unknown_streak must be >= 0.")
        if not isinstance(is_repeat, bool):
            raise InputValidationError("is_repeat must be a boolean.")

        if intent.name not in self._validated:
            self._validate_intent(intent)

        data = self._build_data(slots, facts, last_question)
        pool = self._select_pool(intent, unknown_streak, is_repeat)
        candidates = list(pool)
        self._rng.shuffle(candidates)

        for template in candidates:
            try:
                rendered = template.format(**data)
            except (KeyError, IndexError, ValueError):
                continue
            _LOGGER.debug(
                "Rendered intent=%s template=%r", intent.name, template
            )
            return GeneratedResponse(
                text=rendered,
                template=template,
                intent_name=intent.name,
                category=intent.category,
            )

        if intent.fallback_responses:
            fallbacks = list(intent.fallback_responses)
            self._rng.shuffle(fallbacks)
            for template in fallbacks:
                try:
                    rendered = template.format(**data)
                except (KeyError, IndexError, ValueError):
                    continue
                _LOGGER.debug(
                    "Rendered fallback intent=%s template=%r",
                    intent.name,
                    template,
                )
                return GeneratedResponse(
                    text=rendered,
                    template=template,
                    intent_name=intent.name,
                    category=intent.category,
                )

        raise ResponseGenerationError(
            f"No renderable response for intent {intent.name!r}; "
            f"data keys: {sorted(data)}."
        )

    def _build_data(
        self,
        slots: Mapping[str, str] | None,
        facts: Mapping[str, str] | None,
        last_question: str | None,
    ) -> dict[str, str]:
        """Merge facts, slots, and derived context into a render dict."""
        now = self._clock()
        data: dict[str, str] = {
            "time": now.strftime(TIME_FORMAT),
            "date": now.strftime(DATE_FORMAT),
        }
        if facts:
            for key, value in facts.items():
                if key and value:
                    data[key] = value
        if slots:
            for key, value in slots.items():
                if key and value:
                    data[key] = value
        if last_question:
            data["last_question"] = last_question
        return data

    @staticmethod
    def _select_pool(
        intent: Intent,
        unknown_streak: int,
        is_repeat: bool,
    ) -> tuple[str, ...]:
        if (
            intent.category is Category.UNKNOWN
            and unknown_streak >= UNKNOWN_ESCALATION_THRESHOLD
            and intent.escalation_responses
        ):
            return intent.escalation_responses
        if is_repeat and intent.repeat_responses:
            return intent.repeat_responses
        return intent.responses
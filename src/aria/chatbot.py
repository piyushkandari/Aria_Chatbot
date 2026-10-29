"""Chatbot facade: the single entry point for one conversation session.

Wires together the pattern matcher, context manager, and response
generator, owns the unknown-streak and end-of-session state, and
serialises transcripts.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .context_manager import DEFAULT_MAX_TURNS, ContextManager
from .exceptions import (
    InputValidationError,
    ResponseGenerationError,
    SessionError,
    TranscriptError,
)
from .logger_config import get_logger
from .models import Category, Intent
from .pattern_matcher import PatternMatcher
from .response_generator import ResponseGenerator

_LOGGER = get_logger("chatbot")


@dataclass(frozen=True, slots=True)
class ChatbotReply:
    """A single bot reply with the metadata callers need."""

    text: str
    category: Category
    intent: str
    is_repeat: bool
    unknown_streak: int
    ended: bool
    timestamp: datetime


class Chatbot:
    """One conversation session."""

    def __init__(
        self,
        intents: Iterable[Intent],
        max_turns: int = DEFAULT_MAX_TURNS,
        rng: random.Random | None = None,
        clock: object = None,
        transcript_dir: Path | None = None,
    ) -> None:
        """Create a chatbot session.

        Args:
            intents: Parsed intents (typically from
                ``load_intents_from_json``).
            max_turns: Sliding-window size for conversation memory.
            rng: Optional seeded ``random.Random`` for deterministic output.
            clock: Optional callable returning ``datetime``; used for
                transcript filenames and rendered ``{time}``/``{date}``.
                Defaults to ``datetime.now`` (local time).
            transcript_dir: If provided, transcripts are saved here on
                farewell and when :meth:`save_transcript` is called.
        """
        intents = tuple(intents)
        self._intents = intents
        self._matcher = PatternMatcher(intents)
        self._context = ContextManager(max_turns=max_turns)
        self._clock = clock or datetime.now
        self._generator = ResponseGenerator(
            intents, rng=rng, clock=self._clock
        )
        self._transcript_dir = Path(transcript_dir) if transcript_dir else None
        self._unknown_streak = 0
        self._ended = False
        self._started_at: datetime | None = None
        self._saved_path: Path | None = None
        _LOGGER.debug("Chatbot created with %d intents", len(intents))

    # ------------------------------------------------------------------ #
    # Read-only properties
    # ------------------------------------------------------------------ #

    @property
    def ended(self) -> bool:
        """True if the session has ended (typically after a farewell)."""
        return self._ended

    @property
    def context(self) -> ContextManager:
        """The conversation memory for this session."""
        return self._context

    @property
    def transcript_path(self) -> Path | None:
        """Path to the saved transcript, or None if not yet saved."""
        return self._saved_path

    # ------------------------------------------------------------------ #
    # Respond
    # ------------------------------------------------------------------ #

    def respond(self, text: str) -> ChatbotReply:
        """Process ``text`` and return the bot reply.

        Raises:
            SessionError: If the session has already ended.
            InputValidationError: If ``text`` is not a non-empty string.
            ResponseGenerationError: If no template for the matched intent
                can be rendered given the current facts/slots.
        """
        if self._ended:
            raise SessionError("Session has already ended.")
        if not isinstance(text, str) or not text.strip():
            raise InputValidationError("Message text must be non-empty.")
        text = re.sub(r"\s+", " ", text.strip())

        if self._started_at is None:
            self._started_at = self._clock()

        match = self._matcher.match(text)
        if match is None:
            intent = self._matcher.fallback_intent
            slots: dict[str, str] = {}
        else:
            intent = match.intent
            slots = dict(match.slots)

        if intent.category is Category.UNKNOWN:
            self._unknown_streak += 1
        else:
            self._unknown_streak = 0

        is_repeat = (
            intent.category is Category.QUESTION
            and self._context.is_repeated(text, category=Category.QUESTION)
        )

        # Remember any extracted facts (name, company, etc.) before generating.
        for key, value in slots.items():
            if value:
                self._context.remember_fact(key, value)

        last_question: str | None = None
        if intent.name == "memory.last_question":
            prev = self._context.last_user_question()
            if prev is not None:
                last_question = prev.text

        try:
            generated = self._generator.generate(
                intent,
                slots=slots,
                facts=self._context.facts,
                last_question=last_question,
                unknown_streak=self._unknown_streak,
                is_repeat=is_repeat,
            )
        except ResponseGenerationError:
            _LOGGER.exception(
                "Generation failed for intent %r", intent.name
            )
            raise

        # Record only after generation so is_repeat / last_question see
        # prior turns, not the current one.
        self._context.add_user_message(
            text, category=intent.category, intent=intent.name
        )
        self._context.add_bot_message(
            generated.text, category=intent.category, intent=intent.name
        )

        ended_now = intent.category is Category.FAREWELL
        if ended_now:
            self._ended = True
            if self._transcript_dir is not None:
                try:
                    self.save_transcript(self._transcript_dir)
                except TranscriptError:
                    _LOGGER.exception(
                        "Transcript save failed on farewell; session continues"
                    )

        return ChatbotReply(
            text=generated.text,
            category=intent.category,
            intent=intent.name,
            is_repeat=is_repeat,
            unknown_streak=self._unknown_streak,
            ended=ended_now,
            timestamp=self._clock(),
        )

    # ------------------------------------------------------------------ #
    # Transcript
    # ------------------------------------------------------------------ #

    def save_transcript(self, directory: Path) -> Path:
        """Write the conversation transcript as JSON; idempotent.

        Returns:
            Path to the transcript file.

        Raises:
            TranscriptError: If the directory cannot be created or the
                file cannot be written.
        """
        if self._saved_path is not None:
            return self._saved_path

        directory = Path(directory)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TranscriptError(
                f"Could not create transcript dir {directory}: {exc}"
            ) from exc

        now = self._clock()
        filename = f"transcript_{now.strftime('%Y%m%dT%H%M%S_%f')}.json"
        path = directory / filename

        data = {
            "session_started": (self._started_at or now).isoformat(),
            "session_ended": now.isoformat() if self._ended else None,
            "ended_with_farewell": self._ended,
            "messages": [
                {
                    "role": msg.role.value,
                    "text": msg.text,
                    "timestamp": msg.timestamp.isoformat(),
                    "category": msg.category.value if msg.category else None,
                    "intent": msg.intent,
                }
                for msg in self._context.messages
            ],
            "facts": dict(self._context.facts),
        }

        try:
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            raise TranscriptError(
                f"Could not write transcript to {path}: {exc}"
            ) from exc

        _LOGGER.info("Transcript saved to %s", path)
        self._saved_path = path
        return path
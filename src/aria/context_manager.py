"""Conversation memory for the Aria chatbot.

The context manager is intentionally dumb storage: it records turns and
user facts, and exposes lookups that the chatbot facade (Phase 5) turns
into decisions. It does not call the pattern matcher and does not pick
responses.

Not thread-safe. One instance per session; the web layer (Phase 7) will
create one per session_id.
"""

from __future__ import annotations

from collections import deque
from types import MappingProxyType
from typing import Mapping

from .exceptions import InputValidationError
from .logger_config import get_logger
from .models import Category, Message, Role

_LOGGER = get_logger("context_manager")

DEFAULT_MAX_TURNS: int = 10
"""Default number of user-bot exchanges to retain."""


def _normalize(text: str) -> str:
    """Normalize text for equality comparison (case + whitespace)."""
    return " ".join(text.lower().split())


class ContextManager:
    """Sliding-window conversation memory plus user facts.

    A *turn* is one user message and (optionally) the bot reply that
    follows it. The manager keeps at most ``max_turns`` recent turns;
    older ones are dropped automatically.
    """

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        """Create a context manager with the given window size.

        Raises:
            InputValidationError: If ``max_turns`` is not an int >= 1.
        """
        if isinstance(max_turns, bool) or not isinstance(max_turns, int):
            raise InputValidationError("max_turns must be an integer.")
        if max_turns < 1:
            raise InputValidationError("max_turns must be at least 1.")

        self._max_turns: int = max_turns
        self._turns: deque[list[Message]] = deque(maxlen=max_turns)
        self._facts: dict[str, str] = {}

        _LOGGER.debug("ContextManager initialised with max_turns=%d", max_turns)

    # ------------------------------------------------------------------ #
    # Read-only views
    # ------------------------------------------------------------------ #

    @property
    def max_turns(self) -> int:
        """Maximum number of turns retained in the sliding window."""
        return self._max_turns

    @property
    def messages(self) -> tuple[Message, ...]:
        """All retained messages, oldest first, as an immutable tuple."""
        return tuple(msg for turn in self._turns for msg in turn)

    @property
    def facts(self) -> Mapping[str, str]:
        """Read-only view of remembered user facts."""
        return MappingProxyType(dict(self._facts))

    def __len__(self) -> int:
        """Return the number of retained turns."""
        return len(self._turns)

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"ContextManager(max_turns={self._max_turns}, "
            f"turns={len(self._turns)}, facts={sorted(self._facts)})"
        )

    # ------------------------------------------------------------------ #
    # Turn recording
    # ------------------------------------------------------------------ #

    def has_history(self) -> bool:
        """Return True if any turn has been recorded."""
        return bool(self._turns)

    def add_user_message(
        self,
        text: str,
        category: Category | None = None,
        intent: str | None = None,
    ) -> Message:
        """Record a user message, starting a new turn.

        The caller (chatbot facade) is expected to have already matched
        the message and to pass the resulting ``category`` / ``intent``
        so later lookups such as :meth:`last_user_question` can filter
        by category.

        Raises:
            InputValidationError: If ``text`` is empty or not a string.
        """
        if not isinstance(text, str) or not text.strip():
            raise InputValidationError("User message text must be non-empty.")

        message = Message(
            role=Role.USER,
            text=text.strip(),
            category=category,
            intent=intent,
        )
        self._turns.append([message])
        _LOGGER.debug("Recorded user message (turn %d)", len(self._turns))
        return message

    def add_bot_message(
        self,
        text: str,
        category: Category | None = None,
        intent: str | None = None,
    ) -> Message:
        """Record a bot message, attaching it to the latest open turn.

        A turn is "open" if its last message is a user message. If the
        latest turn is already complete (or there is no turn yet), a new
        turn is started with just the bot message.

        Raises:
            InputValidationError: If ``text`` is empty or not a string.
        """
        if not isinstance(text, str) or not text.strip():
            raise InputValidationError("Bot message text must be non-empty.")

        message = Message(
            role=Role.BOT,
            text=text.strip(),
            category=category,
            intent=intent,
        )

        last_turn = self._turns[-1] if self._turns else None
        is_open = (
            last_turn is not None
            and len(last_turn) == 1
            and last_turn[0].role is Role.USER
        )
        if is_open:
            last_turn.append(message)
        else:
            self._turns.append([message])

        _LOGGER.debug("Recorded bot message")
        return message

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #

    def last_user_message(self) -> Message | None:
        """Return the most recent user message, or None."""
        for turn in reversed(self._turns):
            for msg in turn:
                if msg.role is Role.USER:
                    return msg
        return None

    def last_user_question(self) -> Message | None:
        """Return the most recent user message tagged as a question."""
        for turn in reversed(self._turns):
            for msg in turn:
                if msg.role is Role.USER and msg.category is Category.QUESTION:
                    return msg
        return None

    def last_bot_message(self) -> Message | None:
        """Return the most recent bot message, or None."""
        for turn in reversed(self._turns):
            for msg in reversed(turn):
                if msg.role is Role.BOT:
                    return msg
        return None

    def count_prior_user_messages(
        self,
        text: str,
        category: Category | None = None,
    ) -> int:
        """Count prior user messages equal to ``text`` (normalized).

        Comparison is case- and whitespace-insensitive. If ``category``
        is given, only user messages with that category are counted.

        The caller should invoke this *before* calling
        :meth:`add_user_message` for the current turn, so the incoming
        message is not counted against itself.

        Raises:
            InputValidationError: If ``text`` is not a string.
        """
        if not isinstance(text, str):
            raise InputValidationError("Text must be a string.")

        normalized = _normalize(text)
        if not normalized:
            return 0

        count = 0
        for turn in self._turns:
            for msg in turn:
                if msg.role is not Role.USER:
                    continue
                if category is not None and msg.category is not category:
                    continue
                if _normalize(msg.text) == normalized:
                    count += 1
        return count

    def is_repeated(
        self,
        text: str,
        category: Category | None = None,
        threshold: int = 1,
    ) -> bool:
        """Return True if ``text`` has been seen at least ``threshold`` times.

        Raises:
            InputValidationError: If ``threshold`` is not an int >= 1.
        """
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise InputValidationError("threshold must be an integer.")
        if threshold < 1:
            raise InputValidationError("threshold must be at least 1.")

        return (
            self.count_prior_user_messages(text, category) >= threshold
        )

    # ------------------------------------------------------------------ #
    # User facts
    # ------------------------------------------------------------------ #

    def remember_fact(self, key: str, value: str) -> None:
        """Store a user fact (for example, ``name`` = ``"Alice"``).

        Raises:
            InputValidationError: If ``key`` or ``value`` is empty.
        """
        if not isinstance(key, str) or not key.strip():
            raise InputValidationError("Fact key must be non-empty.")
        if not isinstance(value, str) or not value.strip():
            raise InputValidationError("Fact value must be non-empty.")

        self._facts[key.strip()] = value.strip()
        _LOGGER.debug("Remembered fact %r", key.strip())

    def get_fact(self, key: str) -> str | None:
        """Return the fact value for ``key``, or None if not set."""
        if not isinstance(key, str):
            raise InputValidationError("Fact key must be a string.")
        return self._facts.get(key)

    def has_fact(self, key: str) -> bool:
        """Return True if ``key`` has been remembered."""
        return key in self._facts

    # ------------------------------------------------------------------ #
    # Reset
    # ------------------------------------------------------------------ #

    def clear(self) -> None:
        """Drop all turns and facts from memory."""
        self._turns.clear()
        self._facts.clear()
        _LOGGER.debug("ContextManager cleared")
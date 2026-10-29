"""Domain models for the Aria chatbot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .exceptions import InputValidationError, IntentConfigurationError


class Category(str, Enum):
    """Supported intent categories."""

    GREETING = "greeting"
    QUESTION = "question"
    FAREWELL = "farewell"
    UNKNOWN = "unknown"


class Role(str, Enum):
    """Message author roles."""

    USER = "user"
    BOT = "bot"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class Intent:
    """A configured intent with regex patterns and response templates."""

    name: str
    category: Category
    patterns: tuple[str, ...]
    responses: tuple[str, ...]
    priority: int = 100
    slots: tuple[str, ...] = ()
    escalation_responses: tuple[str, ...] = ()
    repeat_responses: tuple[str, ...] = ()
    fallback_responses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate intent configuration."""
        if not self.name or not self.name.strip():
            raise IntentConfigurationError("Intent name must be non-empty.")

        if not isinstance(self.category, Category):
            raise IntentConfigurationError(
                f"Invalid category for intent {self.name!r}."
            )

        if self.priority < 0:
            raise IntentConfigurationError(
                f"Priority must be non-negative for intent {self.name!r}."
            )

        if not self.responses:
            raise IntentConfigurationError(
                f"Intent {self.name!r} must have at least one response."
            )

        if self.category is not Category.UNKNOWN and not self.patterns:
            raise IntentConfigurationError(
                f"Intent {self.name!r} must have at least one pattern."
            )

        for pattern in self.patterns:
            if not isinstance(pattern, str) or not pattern:
                raise IntentConfigurationError(
                    f"Intent {self.name!r} has an empty pattern."
                )

        for response in self.responses:
            if not isinstance(response, str) or not response:
                raise IntentConfigurationError(
                    f"Intent {self.name!r} has an empty response."
                )

        for response in self.escalation_responses:
            if not isinstance(response, str) or not response:
                raise IntentConfigurationError(
                    f"Intent {self.name!r} has an empty escalation response."
                )

        for response in self.repeat_responses:
            if not isinstance(response, str) or not response:
                raise IntentConfigurationError(
                    f"Intent {self.name!r} has an empty repeat response."
                )

        for response in self.fallback_responses:
            if not isinstance(response, str) or not response:
                raise IntentConfigurationError(
                    f"Intent {self.name!r} has an empty fallback response."
                )


@dataclass(frozen=True, slots=True)
class Message:
    """A single conversation message."""

    role: Role
    text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    category: Category | None = None
    intent: str | None = None

    def __post_init__(self) -> None:
        """Validate message data and normalize timestamps to UTC."""
        if not isinstance(self.role, Role):
            raise InputValidationError("Message role must be a Role enum.")

        if not isinstance(self.text, str):
            raise InputValidationError("Message text must be a string.")

        if not self.text.strip():
            raise InputValidationError("Message text must not be empty.")

        if not isinstance(self.timestamp, datetime):
            raise InputValidationError("Message timestamp must be a datetime.")

        if self.category is not None and not isinstance(self.category, Category):
            raise InputValidationError("Message category must be a Category enum.")

        if self.intent is not None and not isinstance(self.intent, str):
            raise InputValidationError("Message intent must be a string.")

        if self.timestamp.tzinfo is None:
            object.__setattr__(
                self,
                "timestamp",
                self.timestamp.replace(tzinfo=timezone.utc),
            )
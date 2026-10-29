"""Custom exceptions for the Aria chatbot."""

from __future__ import annotations


class AriaError(Exception):
    """Base class for all Aria exceptions."""


class ConfigurationError(AriaError):
    """Raised when configuration is invalid."""


class IntentConfigurationError(ConfigurationError):
    """Raised when an intent definition is invalid."""


class InputValidationError(AriaError):
    """Raised when user input or model data fails validation."""


class PatternMatchError(AriaError):
    """Raised when pattern matching cannot be performed."""


class ResponseGenerationError(AriaError):
    """Raised when a response cannot be generated."""


class SessionError(AriaError):
    """Raised when a session operation fails."""


class TranscriptError(AriaError):
    """Raised when transcript saving fails."""
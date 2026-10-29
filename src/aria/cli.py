"""Interactive CLI for the Aria chatbot."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable

from .chatbot import Chatbot
from .context_manager import DEFAULT_MAX_TURNS
from .exceptions import (
    AriaError,
    ConfigurationError,
    InputValidationError,
    TranscriptError,
)
from .logger_config import configure_logging, get_logger
from .pattern_matcher import load_intents_from_json

_LOGGER = get_logger("cli")

DEFAULT_CONFIG_PATH: Path = Path("config/intents.json")

InputFn = Callable[[str], str]
OutputFn = Callable[..., None]


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="aria",
        description="Aria — rule-based chatbot CLI",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to intents config (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Conversation memory window (default: {DEFAULT_MAX_TURNS})",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional path to also write logs to",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--transcript-dir",
        type=Path,
        default=None,
        help="If set, save conversation transcripts on farewell or exit",
    )
    return parser


def run(
    argv: list[str] | None = None,
    input_fn: InputFn | None = None,
    output_fn: OutputFn | None = None,
    error_fn: OutputFn | None = None,
) -> int:
    """Run the interactive CLI. Returns a process exit code.

    The ``input_fn`` / ``output_fn`` / ``error_fn`` hooks make this
    function fully unit-testable; production callers omit them.
    """
    input_fn = input_fn or input
    output_fn = output_fn or print
    error_fn = error_fn or (
        lambda *args, **kwargs: print(*args, file=sys.stderr, **kwargs)
    )

    args = build_parser().parse_args(argv)
    configure_logging(getattr(logging, args.log_level), args.log_file)

    try:
        intents = load_intents_from_json(args.config)
    except ConfigurationError as exc:
        error_fn(f"error: {exc}")
        return 2

    try:
        bot = Chatbot(
            intents,
            max_turns=args.max_turns,
            transcript_dir=args.transcript_dir,
        )
    except AriaError as exc:
        error_fn(f"error: could not initialise chatbot: {exc}")
        return 2

    output_fn("Aria ready. Type 'bye' to exit.")

    while not bot.ended:
        try:
            raw = input_fn("you> ")
        except EOFError:
            output_fn("")
            break
        except KeyboardInterrupt:
            output_fn("")
            break

        user_text = raw.strip() if isinstance(raw, str) else ""
        if not user_text:
            output_fn("aria> (please type something)")
            continue

        try:
            reply = bot.respond(user_text)
        except InputValidationError as exc:
            error_fn(f"aria> error: {exc}")
            continue
        except AriaError as exc:
            _LOGGER.exception("Chatbot failure")
            error_fn(f"aria> error: {exc}")
            continue

        output_fn(f"aria> {reply.text}")

    if bot.transcript_path is not None:
        output_fn(f"Transcript saved to {bot.transcript_path}")
    elif args.transcript_dir is not None and bot.context.messages:
        try:
            path = bot.save_transcript(args.transcript_dir)
            output_fn(f"Transcript saved to {path}")
        except TranscriptError as exc:
            error_fn(f"error: could not save transcript: {exc}")

    return 0
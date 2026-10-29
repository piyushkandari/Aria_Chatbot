"""Unit tests for the Aria CLI."""

from __future__ import annotations

import unittest
from pathlib import Path

from aria.cli import build_parser, run

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "intents.json"
)


def _input_from(lines: list[str]):
    iterator = iter(lines)

    def _fn(_prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration:
            raise EOFError

    return _fn


class ParserTests(unittest.TestCase):
    """Tests for build_parser."""

    def test_defaults(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.log_level, "INFO")
        self.assertIsNone(args.transcript_dir)

    def test_invalid_level_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--log-level", "TRACE"])


class RunTests(unittest.TestCase):
    """Tests for run()."""

    def test_hello_bye_returns_zero(self) -> None:
        output: list[str] = []
        rc = run(
            ["--config", str(_CONFIG_PATH), "--log-level", "ERROR"],
            input_fn=_input_from(["hello", "bye"]),
            output_fn=output.append,
            error_fn=output.append,
        )
        self.assertEqual(rc, 0)
        joined = "\n".join(output)
        self.assertIn("Aria ready", joined)
        self.assertTrue(any(line.startswith("aria>") for line in output))

    def test_missing_config_returns_2(self) -> None:
        errors: list[str] = []
        rc = run(
            ["--config", "/no/such/file.json", "--log-level", "ERROR"],
            input_fn=_input_from(["hello"]),
            output_fn=lambda *a, **k: None,
            error_fn=errors.append,
        )
        self.assertEqual(rc, 2)
        self.assertTrue(errors)

    def test_eof_exits_cleanly(self) -> None:
        output: list[str] = []
        rc = run(
            ["--config", str(_CONFIG_PATH), "--log-level", "ERROR"],
            input_fn=_input_from([]),
            output_fn=output.append,
            error_fn=output.append,
        )
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
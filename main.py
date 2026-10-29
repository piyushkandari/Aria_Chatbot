"""Entry point for `python main.py`.

Adds `src/` to sys.path so the package can be imported without
`pip install -e .` or `PYTHONPATH`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from aria.cli import run  # noqa: E402  (import after sys.path tweak)

if __name__ == "__main__":
    sys.exit(run())
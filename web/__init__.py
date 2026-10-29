"""Web layer for the Aria chatbot.

The core ``aria`` package lives under ``src/`` and must never import from
this package. This package may import from ``aria``, and is the only
place in the project where FastAPI/Uvicorn are used.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `uvicorn web.api:app --reload` from the project root without
# requiring `PYTHONPATH=src`. This shim exists only so the command in
# the brief works verbatim; it does not affect the core package.
_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

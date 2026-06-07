"""Pytest collection-time sys.path setup.

Both `src/` (for `agent`, `ambient`, `soldier`, etc.) and `scripts/` (for
`feeds.*`, `demo_script`, `worker_config`) need to be importable as top-level
modules from the tests directory.

We append rather than insert at position 0 so we don't shadow installed
packages (notably `livekit.agents`, which was being broken when
`scripts/` was inserted at position 0 by an in-test sys.path mutation).
"""
from __future__ import annotations

import sys
from pathlib import Path

_AGENT_PY_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _AGENT_PY_DIR / "src"
_SCRIPTS_DIR = _AGENT_PY_DIR / "scripts"

for path in (_SRC_DIR, _SCRIPTS_DIR):
    s = str(path)
    if s not in sys.path:
        sys.path.append(s)

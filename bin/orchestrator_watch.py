#!/usr/bin/env python3
"""One shift-watcher tick — the entry the systemd user timer calls.

See `agents/conductors/batch/_orchestrator.py` for what a tick does, and
`skills/batch/batch.md` "The watcher" for installing the timer (the human's
act; no session installs it).
"""
import sys
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BATCH.parents[1] / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))

from _orchestrator import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

"""Suite-wide isolation for tests that drive bin/pyauto-brain.

In a remote session (CLAUDE_CODE_REMOTE=true) the dispatcher runs PyAutoMind's
session bootstrap before every verb. That bootstrap honours a declared
PYAUTO_ROOT and registers a `.claude/` hook there, so a test pointing
PYAUTO_ROOT at a tmp fixture would have the fixture rewritten under it (an
extra `.claude` sibling) and pay the bootstrap's cost on every subprocess.
Tests never want the real bootstrap; tests/test_session_bootstrap_dispatch.py
removes this variable explicitly to exercise it against a stub.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_session_bootstrap(monkeypatch):
    monkeypatch.setenv("PYAUTO_SKIP_BOOTSTRAP", "1")

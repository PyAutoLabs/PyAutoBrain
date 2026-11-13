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


@pytest.fixture(autouse=True)
def _no_real_heart_lane(monkeypatch):
    """`batch brief --new` runs the keep-Heart-green lane (PyAutoBrain#625),
    which reads the live Heart and writes a state file. Off in tests unless a
    test asks for it (`--green`, with a saved `--heart-json` and `--home`)."""
    monkeypatch.setenv("PYAUTO_HEART_GREEN", "off")


@pytest.fixture(autouse=True)
def _no_real_github(monkeypatch):
    """The shift watcher's GitHub seams never reach GitHub from a test
    (PyAutoBrain#610 Witness 5: the suite passes offline). A test that passes
    its own `run=` still exercises the real function against that fake."""
    import sys

    orch = sys.modules.get("_orchestrator")
    digest = sys.modules.get("_digest")
    if orch is not None:
        real_state, real_comment = orch.gh_pr_state, orch.gh_comment
        monkeypatch.setattr(orch, "gh_pr_state", lambda url, run=None:
                            real_state(url, run=run) if run else None)
        monkeypatch.setattr(orch, "gh_comment", lambda issue, body, run=None:
                            real_comment(issue, body, run=run) if run else
                            {"posted": False, "retry": False, "error": "offline (tests)"})
        real_login = orch.gh_login
        monkeypatch.setattr(orch, "gh_login", lambda run=None:
                            real_login(run=run) if run else None)
        # PyAutoBrain#622: the status comment's edit and the steering read.
        real_edit, real_read = orch.gh_comment_edit, orch.gh_issue_comments
        monkeypatch.setattr(orch, "gh_comment_edit", lambda url, body, run=None:
                            real_edit(url, body, run=run) if run else
                            {"edited": False, "error": "offline (tests)"})
        monkeypatch.setattr(orch, "gh_issue_comments", lambda issue, since, run=None:
                            real_read(issue, since, run=run) if run else None)
        monkeypatch.delenv(orch.MENTION_ENV, raising=False)
        monkeypatch.delenv(orch.GH_TOKEN_ENV, raising=False)
    if digest is not None:
        real_health = digest.pr_health
        monkeypatch.setattr(digest, "pr_health", lambda url, run=None:
                            real_health(url, run=run) if run else "UNKNOWN")

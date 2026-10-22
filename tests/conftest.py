import pytest


@pytest.fixture(autouse=True)
def _no_session_bootstrap(monkeypatch):
    # In a remote session (CLAUDE_CODE_REMOTE=true) every bin/pyauto-brain verb
    # runs the Mind's session bootstrap, which installs hooks into $PYAUTO_ROOT —
    # here a tmp fixture the test then scans. Tests opt out; the one test of the
    # bootstrap itself drops this variable from its subprocess env.
    monkeypatch.setenv("PYAUTO_SKIP_BOOTSTRAP", "1")

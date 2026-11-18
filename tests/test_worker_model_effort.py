"""Spawned workers and close-outs start as Opus at medium effort (PyAutoBrain#672)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrator_digest import orch  # noqa: E402

PR = "https://github.com/example-org/PyAutoBrain/pull/1"


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def test_the_worker_defaults_are_opus_at_medium_and_closeouts_follow():
    assert orch.WORKER_MODEL == "opus"
    assert orch.WORKER_EFFORT == "medium"
    assert orch.CLOSEOUT_MODEL == orch.WORKER_MODEL


def test_the_worker_argv_carries_model_and_effort_with_the_prompt_last(tmp_path: Path):
    argv = orch.session_command("t1", "draft/x/t1.md", tmp_path / "shift.md",
                                tmp_path / "leases", "auto")
    assert argv[:10] == ["claude", "--bg", "--name", "shift:t1", "--model", "opus",
                         "--effort", "medium", "--permission-mode", "auto"]
    assert "Use the start-dev skill. draft/x/t1.md --auto" in argv[-1]


def test_the_closeout_argv_carries_model_and_effort_with_the_prompt_last(tmp_path: Path):
    argv = orch.closeout_command("t1", PR, "draft/x/t1.md", tmp_path / "b.md",
                                 tmp_path / "leases", "auto")
    assert _flag(argv, "--model") == "opus"
    assert _flag(argv, "--effort") == "medium"
    assert PR in argv[-1]

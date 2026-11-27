"""Shift env travels on the argv (PyAutoBrain#724).

`claude --bg` hosts a session on a spare the background daemon pre-spawned,
and a spare keeps the environment of whoever started the daemon. In shift
2026-11-26-pm2 three workers ran with pm's `PYAUTO_SHIFT_LEDGER_DIR`, and a
Mind op was stranded in pm's ledger. So every worker, update and close-out
argv carries this shift's variables in `--settings '{"env": …}'`, which the
session applies itself, and every ledger reader refuses a ledger whose slot
is not the brief's. Fictional fixtures only; no session is started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from _shift_fixtures import BATCH, BRAIN  # noqa: F401 — sets sys.path
import _mind_writer as mw  # noqa: E402
import _orchestrator as orch  # noqa: E402

PR = "https://github.com/o/r/pull/1"


@pytest.fixture(autouse=True)
def _no_caller_git_config(monkeypatch):
    """The argv tests read the process env; start them with no `GIT_CONFIG_*`."""
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)


def _settings_env(argv: list[str]) -> dict:
    """The `env` of the argv's one `--settings` JSON."""
    assert argv.count("--settings") == 1, argv[:-1]
    return json.loads(argv[argv.index("--settings") + 1])["env"]


def _paths(tmp_path, slot_name: str):
    home = tmp_path / "home"
    brief = tmp_path / "mind" / "batches" / f"{slot_name}.md"
    lease_dir = orch.slot_dir(brief, home) / "leases"
    return brief, lease_dir


def _assert_this_shift(argv: list[str], brief, lease_dir) -> None:
    env = _settings_env(argv)
    assert env["PYAUTO_SHIFT_WORKER"] == "1"
    assert env["PYAUTO_SHIFT_LEDGER_DIR"] == str(lease_dir.parent / mw.LEDGER_DIR)
    assert env["PYAUTO_SHIFT_BRIEF"] == str(brief)
    # Settings env replaces values, never appends: the lock is index 0.
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    assert env["GIT_CONFIG_VALUE_0"] == str(orch.WORKER_HOOKS)
    assert orch.KICK_ENV in env
    # The prompt is still the last element, after the settings.
    assert argv.index("--settings") < len(argv) - 2
    assert not argv[-1].startswith("{")


# --- (a) every launch argv carries this shift's env ---------------------------------

def test_worker_argv_carries_this_shifts_env(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    argv = orch.session_command("t1", "draft/x/t1.md", brief, lease_dir, "auto")
    _assert_this_shift(argv, brief, lease_dir)
    assert "Use the start-dev skill" in argv[-1]


def test_closeout_argv_carries_this_shifts_env(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    argv = orch.closeout_command("t1", PR, "draft/x/t1.md", brief, lease_dir, "auto")
    assert "shift-close:t1" in argv
    _assert_this_shift(argv, brief, lease_dir)
    assert PR in argv[-1]


def test_update_argv_carries_this_shifts_env(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    argv = orch.closeout_command("t1", PR, "draft/x/t1.md", brief, lease_dir, "auto",
                                 update_after=["https://github.com/a/b/pull/2"])
    assert "shift-update:t1" in argv
    _assert_this_shift(argv, brief, lease_dir)
    assert PR in argv[-1]


def test_settings_env_carries_no_secret(tmp_path, monkeypatch):
    monkeypatch.setenv(orch.GH_TOKEN_ENV, "ghp_fictional_secret")
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    env = orch.shift_env(lease_dir, brief)
    assert set(env) == {"PYAUTO_SHIFT_WORKER", "PYAUTO_SHIFT_LEDGER_DIR",
                        "PYAUTO_SHIFT_BRIEF", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0",
                        "GIT_CONFIG_VALUE_0", orch.KICK_ENV}
    assert "ghp_fictional_secret" not in json.dumps(env)


def test_settings_env_keeps_the_callers_git_config_and_locks_after_it(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    env = orch.shift_env(lease_dir, brief, base={"GIT_CONFIG_COUNT": "1",
                                                 "GIT_CONFIG_KEY_0": "safe.directory",
                                                 "GIT_CONFIG_VALUE_0": "/srv/x"})
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]) == ("safe.directory", "/srv/x")
    assert (env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_VALUE_1"]) == (
        "core.hooksPath", str(orch.WORKER_HOOKS))


def test_settings_env_without_caller_git_config_locks_at_index_0(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    env = orch.shift_env(lease_dir, brief, base={})
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]) == (
        "core.hooksPath", str(orch.WORKER_HOOKS))
    assert "GIT_CONFIG_KEY_1" not in env


def test_settings_env_drops_a_secret_from_copied_git_config(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    env = orch.shift_env(lease_dir, brief, base={
        orch.GH_TOKEN_ENV: "ghp_fictional_secret", "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": "ghp_fictional_secret"})
    assert "ghp_fictional_secret" not in json.dumps(env)
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_1"] == "core.hooksPath"


def test_worker_env_names_the_brief_and_keeps_its_appended_lock(tmp_path):
    brief, lease_dir = _paths(tmp_path, "2026-11-26-pm2")
    env = orch.worker_env(lease_dir, base={"GIT_CONFIG_COUNT": "1",
                                           "PYAUTO_SHIFT_BRIEF": "/old/2026-11-26-pm.md"},
                          brief_path=brief)
    assert env["PYAUTO_SHIFT_BRIEF"] == str(brief)
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_1"] == "core.hooksPath"


# --- (b) a pm -> pm2 replay: a stale process env never names the shift -------------

class _FakeClaude:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        return SimpleNamespace(returncode=0, stderr="",
                               stdout=f"backgrounded · {len(self.calls):08x} · x\n")


def test_pm2_dispatch_names_pm2_even_from_a_pm_environment(tmp_path, monkeypatch):
    pm_brief, pm_leases = _paths(tmp_path, "2026-11-26-pm")
    pm2_brief, pm2_leases = _paths(tmp_path, "2026-11-26-pm2")
    # The watcher (or the daemon a pm worker started) still holds pm's values.
    monkeypatch.setenv("PYAUTO_SHIFT_LEDGER_DIR", str(pm_leases.parent / mw.LEDGER_DIR))
    monkeypatch.setenv("PYAUTO_SHIFT_BRIEF", str(pm_brief))
    monkeypatch.delenv("INVOCATION_ID", raising=False)       # no systemd scope wrap
    claude = _FakeClaude()
    sp = orch.RealSpawner(pm2_brief, "auto", run=claude, public_names=lambda u: "")
    sp.spawn("t1", "draft/x/t1.md", pm2_leases)
    sp.spawn_closeout("t1", PR, "draft/x/t1.md", pm2_leases)
    sp.spawn_closeout("t2", PR, "draft/x/t2.md", pm2_leases,
                      update_after=["https://github.com/a/b/pull/2"])
    assert len(claude.calls) == 3
    for argv, kw in claude.calls:
        _assert_this_shift(argv, pm2_brief, pm2_leases)
        assert kw["env"]["PYAUTO_SHIFT_BRIEF"] == str(pm2_brief)
        assert kw["env"]["PYAUTO_SHIFT_LEDGER_DIR"] == str(pm2_leases.parent / mw.LEDGER_DIR)
        assert "2026-11-26-pm/" not in argv[argv.index("--settings") + 1]


# --- (c) the one ledger reader refuses another shift's ledger -----------------------

LEDGER = "/wt/.orchestrator/2026-11-26-pm/ledger"


def test_ledger_helper_refuses_a_slot_mismatch():
    with pytest.raises(mw.ShiftEnvMismatch) as e:
        mw.shift_ledger_dir({"PYAUTO_SHIFT_LEDGER_DIR": LEDGER,
                             "PYAUTO_SHIFT_BRIEF": "/mind/batches/2026-11-26-pm2.md"})
    assert LEDGER in str(e.value) and "2026-11-26-pm2.md" in str(e.value)


def test_ledger_helper_passes_a_match_and_an_unset_brief():
    env = {"PYAUTO_SHIFT_LEDGER_DIR": LEDGER,
           "PYAUTO_SHIFT_BRIEF": "/mind/batches/2026-11-26-pm.md"}
    assert str(mw.shift_ledger_dir(env)) == LEDGER
    assert str(mw.shift_ledger_dir({"PYAUTO_SHIFT_LEDGER_DIR": LEDGER})) == LEDGER
    assert mw.shift_ledger_dir({}) is None
    assert mw.shift_ledger_dir({"PYAUTO_SHIFT_LEDGER_DIR": "  ",
                                "PYAUTO_SHIFT_BRIEF": "/b/x.md"}) is None


# --- (d) the CLIs exit non-zero on a mismatch ---------------------------------------

def _mismatch_env(tmp_path) -> dict:
    slot = tmp_path / ".orchestrator" / "2026-11-26-pm"
    (slot / mw.LEDGER_DIR).mkdir(parents=True)
    env = dict(os.environ)
    env.update({"PYAUTO_SHIFT_WORKER": "1",
                "PYAUTO_SHIFT_LEDGER_DIR": str(slot / mw.LEDGER_DIR),
                "PYAUTO_SHIFT_BRIEF": str(tmp_path / "2026-11-26-pm2.md")})
    return env


def test_shift_ledger_cli_refuses_a_mismatch(tmp_path):
    env = _mismatch_env(tmp_path)
    res = subprocess.run([sys.executable, str(BRAIN / "bin" / "shift_ledger.py"),
                          "--task", "t1", "remove", "active/x.md",
                          "--mind", str(tmp_path / "no-mind")],
                         env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode != 0
    assert "2026-11-26-pm2" in res.stderr and env["PYAUTO_SHIFT_LEDGER_DIR"] in res.stderr
    assert not list((tmp_path / ".orchestrator" / "2026-11-26-pm" / "ledger").iterdir())


def test_merge_slot_cli_refuses_a_mismatch(tmp_path):
    env = _mismatch_env(tmp_path)
    res = subprocess.run([sys.executable, str(BRAIN / "bin" / "merge_slot.py"),
                          "take", PR, "--task", "t1"],
                         env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
    assert "2026-11-26-pm2" in res.stderr and "do not merge" in res.stderr


def _release_queued(tmp_path, brief: str | None) -> subprocess.CompletedProcess:
    from _helpers import hermetic_worktree_env, source_worktree
    ledger = tmp_path / ".orchestrator" / "2026-11-26-pm" / mw.LEDGER_DIR
    mw.queue_op(ledger, {"op": "drop-section", "path": "active.md", "section": "task-x"})
    env = {**hermetic_worktree_env(tmp_path), "PYAUTO_SHIFT_LEDGER_DIR": str(ledger)}
    if brief:
        env["PYAUTO_SHIFT_BRIEF"] = brief
    return source_worktree("_worktree_release_queued task-x", env)


def test_worktree_release_guard_fails_closed_on_another_shifts_ledger(tmp_path):
    res = _release_queued(tmp_path, str(tmp_path / "2026-11-26-pm2.md"))
    assert res.returncode == 1                       # not found: the claim stays
    assert "2026-11-26-pm2" in res.stderr and "PYAUTO_SHIFT_LEDGER_DIR" in res.stderr


def test_worktree_release_guard_reads_its_own_shifts_ledger(tmp_path):
    assert _release_queued(tmp_path, str(tmp_path / "2026-11-26-pm.md")).returncode == 0
    assert _release_queued(tmp_path / "b", None).returncode == 0

"""PyAutoBrain#634: fixes from the first live shift with real workers (2026-11-14-pm).

1. Task titles link to the work (PR, else the work repo's issue, else plain);
   the Mind prompt link follows the prompt's moves and is pinned to a sha.
2. Every `claude --bg` launch from inside a systemd unit runs in its own
   transient scope, so the daemon it may start leaves the unit's cgroup.
3. Each task reads outcome-first, in plain words, with the detail below.
4. Organ-repo workers run the tenant firewall before they push.
5. An unattended close-out retires the task's live `queue.md` entry.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_closeout as co  # noqa: E402
import test_orchestrator_digest as t  # noqa: E402
from test_orchestrator_digest import _digest, orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

PR = "https://github.com/o/r/pull/7"
WORK_ISSUE = "https://github.com/o/r/issues/6"
MIND_ISSUE = "https://github.com/example-org/example-mind/issues/1"


def git(cwd, *args):
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert res.returncode == 0, (args, res.stderr)
    return res.stdout.strip()


def _commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", msg)


@pytest.fixture
def moved_mind(tmp_path):
    """A Mind clone whose `origin/main` holds a prompt moved draft/ → active/
    → complete/ (renamed), and an `active.md` claim for a second task."""
    if shutil.which("git") is None:
        pytest.skip("needs git")
    bare, mind = tmp_path / "mind.git", tmp_path / "mind"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(mind))
    body = "# Task t1\n\n" + "".join(f"line {i}\n" for i in range(30))
    (mind / "draft" / "bug" / "x").mkdir(parents=True)
    (mind / "draft" / "bug" / "x" / "t1.md").write_text(body)
    (mind / "draft" / "bug" / "x" / "t2.md").write_text("# t2\n")
    (mind / "active.md").write_text("# Active\n")
    _commit(mind, "seed")
    (mind / "active").mkdir()
    git(mind, "mv", "draft/bug/x/t1.md", "active/t1.md")
    git(mind, "mv", "draft/bug/x/t2.md", "active/t2.md")
    (mind / "active.md").write_text(
        "# Active\n\n## t2-claim\n- issue: " + WORK_ISSUE + "\n- prompt: active/t2.md\n")
    _commit(mind, "claim")
    (mind / "complete" / "2026" / "11").mkdir(parents=True)
    git(mind, "mv", "active/t1.md", "complete/2026/11/t-one.md")
    (mind / "complete" / "2026" / "11" / "t-one.md").write_text("## What shipped\n\n- x\n\n" + body)
    _commit(mind, "close")
    git(mind, "push", "-q", "origin", "HEAD:main")
    git(mind, "fetch", "-q", "origin")
    return mind


# --- 1. links ----------------------------------------------------------------------

def test_titles_link_to_the_pr_else_the_work_issue_else_plain_and_mind_links_never_die(
        moved_mind):
    head = git(moved_mind, "rev-parse", "origin/main")
    links = _digest.MindLinks(moved_mind, MIND_ISSUE)
    # The prompt is found where it is now (renamed under complete/), pinned to a sha.
    assert links.prompt_url("draft/bug/x/t1.md") == (
        f"https://github.com/example-org/example-mind/blob/{head}/complete/2026/11/t-one.md")
    assert links.prompt_url("draft/bug/x/never.md") == ""     # never on main: no link
    counters = {"picks": {"t1": {"title": "One", "prompt": "draft/bug/x/t1.md"},
                          "t2": {"title": "Two", "prompt": "draft/bug/x/t2.md"},
                          "t3": {"title": "Three", "prompt": "draft/bug/x/t3.md"}},
                "outcomes": {"t1": {"prs": [PR], "merged": [PR], "issues": []}}}
    assert _digest.work_link("t1", counters, links) == PR
    assert _digest.work_link("t2", counters, links) == WORK_ISSUE     # its claim's issue
    assert _digest.work_link("t3", counters, links) == ""             # neither: plain
    line = _digest._line("t1", counters, "glance", lambda u: "HEALTHY", links)
    assert line.startswith(f"- **Merged** — [One]({PR})\n")
    assert f"[Mind prompt](https://github.com/example-org/example-mind/blob/{head}/" in line
    assert "blob/main" not in line
    assert _digest._line("t3", counters, "glance", lambda u: "x", links).startswith(
        "- **Not started** — Three\n")
    # No Mind checkout (a scratch slot, CI): links come only from the .done.
    assert _digest.MindLinks(None, MIND_ISSUE).prompt_url("draft/bug/x/t1.md") == ""


# --- 2. the daemon leaves the unit's cgroup -------------------------------------------

FAKE_CLAUDE = """#!/bin/sh
# A fake `claude --bg`: start a detached "daemon" that outlives this client.
setsid sleep 30 </dev/null >/dev/null 2>&1 &
echo $! > "$FAKE_DAEMON_PID"
echo "backgrounded · deadbeef · shift:$1"
"""


class Run:
    """`subprocess.run`, recorded; the first call can be made to fail."""

    def __init__(self, fail_first: str = ""):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if self.fail_first and len(self.calls) == 1:
            return subprocess.CompletedProcess(argv, 1, "", self.fail_first)
        return subprocess.CompletedProcess(argv, 0, "backgrounded · 0123abcd · x\n", "")


def test_sessions_launch_in_their_own_scope_inside_a_unit_and_plain_elsewhere(
        tmp_path, monkeypatch):
    found = lambda name: "/usr/bin/" + name  # noqa: E731
    argv = ["claude", "--bg", "x"]
    wrapped = orch.scope_command(argv, "t1", {"INVOCATION_ID": "abc"}, which=found)
    assert wrapped[:4] == ["systemd-run", "--user", "--scope", "--quiet"] and wrapped[-3:] == argv
    assert orch.scope_command(argv, "t1", {}, which=found) == argv              # not in a unit
    assert orch.scope_command(argv, "t1", {"INVOCATION_ID": "a"}, which=lambda n: None) == argv

    # Workers and close-outs take the same route (the spawn env carries the unit's id).
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr(orch.shutil, "which", found)
    run = Run()
    sp = orch.RealSpawner(tmp_path / "b.md", "auto", run=run)
    sp.spawn("t1", "draft/x/t1.md", tmp_path)
    sp.spawn_closeout("t1", PR, "draft/x/t1.md", tmp_path)
    assert [c[:3] for c in run.calls] == [["systemd-run", "--user", "--scope"]] * 2
    i = run.calls[0].index("claude")
    assert run.calls[0][i - 1] == "--" and run.calls[0][i:i + 4] == ["claude", "--bg", "--name",
                                                                   "shift:t1"]
    # systemd-run could not make the scope (no user bus): launched plain, once.
    run = Run(fail_first="Failed to connect to bus: No such file or directory")
    orch.RealSpawner(tmp_path / "b.md", "auto", run=run).spawn("t1", "draft/x/t1.md", tmp_path)
    assert run.calls[0][0] == "systemd-run" and run.calls[1][0] == "claude" and len(run.calls) == 2


def _user_scopes_work() -> bool:
    if not sys.platform.startswith("linux") or shutil.which("systemd-run") is None:
        return False
    res = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", "true"],
                         capture_output=True, text=True, timeout=30)
    return res.returncode == 0


def test_a_daemon_started_through_the_route_lives_in_its_own_scope(tmp_path):
    """Live, on a machine with a systemd user manager: a fake `claude` starts
    a detached stand-in daemon through `run_scoped`; it lands in a
    `run-*.scope`, not in the caller's cgroup. The stand-in is this test's own
    `sleep`, stopped at the end — no real daemon is touched."""
    if not _user_scopes_work():
        pytest.skip("no systemd user manager here (CI, macOS)")
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(0o755)
    pidfile = tmp_path / "daemon.pid"
    env = {**os.environ, "INVOCATION_ID": "test", "FAKE_DAEMON_PID": str(pidfile)}
    res = orch.run_scoped(subprocess.run, [str(fake), "t1"], "t1", capture_output=True,
                          text=True, timeout=60, env=env)
    assert res.returncode == 0 and "backgrounded · deadbeef" in res.stdout
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.1)
    pid = int(pidfile.read_text())
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text().strip()
        mine = Path("/proc/self/cgroup").read_text().strip()
        assert cgroup.endswith(".scope") and "/run-" in cgroup and cgroup != mine
    finally:
        os.kill(pid, signal.SIGTERM)


# --- 3. plain wording -----------------------------------------------------------------

def test_golden_wording_for_a_merged_a_refused_and_a_running_task():
    pick = {"title": "Fix the thing", "size": "small", "repos": ["example_workspace"]}
    merged = _digest.entry_lines(
        "fix", pick, f"{PR} — merged unattended (close-out, claude-opus-5-5)", True, "glance", PR)
    assert merged == [
        f"- **Merged** — [Fix the thing]({PR})",
        "  <sub>`fix` · glance · small · example_workspace · "
        "merged unattended (close-out, claude-opus-5-5)</sub>"]
    refused = _digest.entry_lines(
        "fix", pick, f"{PR} — awaiting /prm — close-out refused: CI FAILED — never merged "
        "unattended", True, "glance", PR, why="scoped tier glance")
    assert refused == [
        f"- **CI failed — needs you** — [Fix the thing]({PR})",
        "  <sub>`fix` · glance · small · example_workspace · awaiting /prm — close-out "
        "refused: CI FAILED — never merged unattended · why: scoped tier glance</sub>"]
    running = _digest.entry_lines(
        "fix", pick, "running (agent 0123abcd, working, since 2026-11-14T12:26Z)", True,
        "glance", WORK_ISSUE, extra=["re-dispatched 1×"])
    assert running == [
        f"- **Still running** — [Fix the thing]({WORK_ISSUE})",
        "  <sub>`fix` · glance · small · example_workspace · running (agent 0123abcd, "
        "working, since 2026-11-14T12:26Z) · re-dispatched 1×</sub>"]
    assert _digest.plain_outcome("dropped by /drop — not started") == "Dropped"
    assert _digest.plain_outcome(f"{PR} — RUNNING") == "CI running"
    # validate reads the two-line entries and the one-line records before #634.
    two = ("## Digest\n\n### Brief work\n- none\n\n### Backlog picks\n"
           + "\n".join(refused) + "\n\n### Proof packets\n#### fix — x\n\n### Counters\n"
           + "".join(f"- {k}: 0\n" for k in _digest.COUNTERS))
    assert _digest.validate(two) == []
    assert any("backlog pick fix has no `why:`" in e
               for e in _digest.validate(two.replace(" · why: scoped tier glance", "")))


# --- 4. the organ firewall -------------------------------------------------------------

def test_the_worker_template_runs_the_tenant_firewall_before_an_organ_push(tmp_path):
    prompt = orch.worker_prompt("t1", "draft/x/t1.md", tmp_path / "b.md", tmp_path)
    assert ('python3 PyAutoMind/scripts/repos_sync.py --check --only '
            '"tenant firewall (organ code)" --root "$PWD"') in prompt
    assert "Before every push to an organ repo (PyAutoBrain, PyAutoHeart or PyAutoHands" in prompt


# --- 5. the close-out retires the queue entry ------------------------------------------

def test_a_merged_closeout_queues_the_queue_md_retirement(tmp_path):
    mind, brief, home, sp = co._shift(tmp_path)
    co._tick(brief, mind, home, sp, 1)
    co._verdict(home, brief, "named", result="merged", pr=co.PR1, gate="g", model="m")
    co._tick(brief, mind, home, sp, 2)
    ops = [json.loads(f.read_text()) for f in mw.pending_ops(orch.slot_dir(brief, home))]
    retire = [o for o in ops if o["op"] == "queue-retire"]
    assert retire == [{"op": "queue-retire", "path": "queue.md", "prompt": "named.md",
                       "shipped_as": f"{co.PR1} (merged by the unattended close-out, "
                                     "2026-11-04)"}]
    assert "queue-retire queue.md <prompt file name>" in orch.closeout_prompt(
        "named", co.PR1, "draft/x/named.md", brief, tmp_path)


LIFECYCLE = t.LEDGER_MERGE.with_name("lifecycle.py")
QUEUE = """# Queue

## 1. Fix it
- kind: prompt
- ref: draft/feature/x/t1.md

## 2. Other
- kind: prompt
- ref: draft/feature/x/t9.md
"""


@pytest.mark.skipif(not LIFECYCLE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/lifecycle.py beside this Brain")
def test_queue_retire_lands_in_the_ledger_commit_with_minds_own_rule(tmp_path):
    bare, seed = tmp_path / "mind.git", tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    (seed / "scripts").mkdir()
    shutil.copy(t.LEDGER_MERGE, seed / "scripts" / "ledger_merge.py")
    shutil.copy(LIFECYCLE, seed / "scripts" / "lifecycle.py")
    (seed / "queue.md").write_text(QUEUE)
    (seed / "active").mkdir()
    (seed / "active" / "t1.md").write_text("# t1\n")
    _commit(seed, "seed")
    git(seed, "push", "-q", "origin", "HEAD:main")
    canon = tmp_path / "canon"
    git(tmp_path, "clone", "-q", str(bare), str(canon))
    git(canon, "config", "user.name", "T")
    git(canon, "config", "user.email", "t@example.invalid")
    slot = tmp_path / "slot"
    ledger = slot / mw.LEDGER_DIR
    mw.queue_op(ledger, {"op": "move", "path": "active/t1.md",
                         "to": "complete/2026/11/t1.md"})
    mw.queue_op(ledger, {"op": "queue-retire", "path": "queue.md", "prompt": "t1.md",
                         "shipped_as": f"{PR} → complete/2026/11/t1.md (2026-11-14)"})
    # The watcher's safety net, the same retirement again: silent, no note.
    mw.queue_op(ledger, {"op": "queue-retire", "path": "queue.md", "prompt": "t1.md",
                         "shipped_as": f"{PR} (merged by the unattended close-out, 2026-11-14)"})
    res = mw.commit_ledger(slot, canon, "shift: ledger")
    assert res["committed"] and not res.get("set_aside") and not res.get("skipped")
    queue = git(canon, "show", "origin/main:queue.md")
    live, retired = queue.split("## Retired")
    assert "Fix it" not in live and "## 2. Other" in live
    assert f"- shipped-as: {PR} → complete/2026/11/t1.md (2026-11-14)" in retired
    assert mw.QUEUE_RETIRED_BY in retired and "lifecycle.py close" not in retired
    files = git(canon, "show", "--name-status", "--format=", "origin/main")
    assert "queue.md" in files and "complete/2026/11/t1.md" in files   # one commit


# --- N1: a worker still out at review-at --------------------------------------------

def test_a_worker_still_running_at_review_at_is_not_digested_as_not_started(tmp_path):
    slot = tmp_path / "slot"
    (slot / "leases").mkdir(parents=True)
    (slot / "leases" / "t1.json").write_text(json.dumps({"agent_id": "0123abcd",
                                                          "started": "2026-11-14T20:01Z"}))
    counters = {"picks": {"t1": {"title": "One", "tier": "glance", "size": "small",
                                 "prompt": "draft/x/t1.md"},
                          "t2": {"title": "Two", "tier": "glance"}},
                "outcomes": {}}
    brief = {"tasks": {"value": "", "children": [{"text": "draft/x/t1.md"},
                                                 {"text": "draft/x/t2.md"}]},
             "token-budget": {"value": "100"}, "review-minutes": {"value": "15"}}
    d = _digest.build(brief, slot, counters, health=lambda u: "HEALTHY")
    work = d.split("### Brief work")[1].split("### Backlog picks")[0]
    assert ("- **Still running at review time** — One\n  <sub>`t1` · glance · small · "
            "still running at review time — the late sweep will report it</sub>") in work
    assert "- **Not started** — Two" in work            # no lease: truly not started
    assert not any("t1 has no proof packet" in e for e in _digest.validate(d))


def test_queue_retire_contains_a_broken_lifecycle_as_one_op_failure(tmp_path):
    """Mind main's lifecycle.py is not the watcher's code: a syntax error or a
    renamed `queue_retire_text` must surface as this op's MindWriteError (set
    aside like any failing op), never as an exception that crashes the tick."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "queue.md").write_text("# Queue\n\n## Retired\n", encoding="utf-8")
    op = {"op": "queue-retire", "path": "queue.md", "prompt": "t1.md",
          "shipped_as": "https://example.invalid/pr/1"}
    for body in ("def broken(:\n", "def other():\n    pass\n"):
        (tmp_path / "scripts" / "lifecycle.py").write_text(body, encoding="utf-8")
        with pytest.raises(mw.MindWriteError, match="queue-retire"):
            mw.apply_op(tmp_path, op, None)


def test_retired_by_anchors_on_the_heading_not_header_prose():
    text = ("# Queue\nsee the `## Retired` footer\n\n## 1. A\n- note: retired by "
            "`lifecycle.py close` once\n\n## Retired\n\n### B\n- note: retired by "
            "`lifecycle.py close`\n")
    out = mw._retired_by(text, 1)
    assert "- note: retired by `lifecycle.py close` once" in out
    assert out.endswith("- note: " + mw.QUEUE_RETIRED_BY + "\n")

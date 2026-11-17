"""M3.6e (PyAutoBrain#661): every in-shift merge takes a merge slot.

Shift 2026-11-16-pm read "2 merged of merge-cap 1": two workers merged their
`notify` PRs in-turn without asking the watcher, whose `merge-cap:` counted
only its own close-outs. Ruling R3 (AUTONOMY.md, 2026-11-17): a worker takes a
slot with `pyauto-brain merge-slot take <pr>` before its bare `gh pr merge`,
and the watcher's close-outs take from the same count.

These tests drive the real CLI (`bin/pyauto-brain merge-slot`) with a fake
`gh` on PATH that logs its argv, so a merge that should not happen is seen.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_closeout as tc  # noqa: E402 — the 4b close-out fixtures
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
from test_orchestrator_digest import orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

CLI = BRAIN / "bin" / "pyauto-brain"
PR1, PR2 = tc.PR1, tc.PR2


def _fake_gh(tmp_path: Path) -> tuple[Path, Path]:
    """A `gh` that logs one line of argv per call and succeeds."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "gh.log"
    gh = bindir / "gh"
    gh.write_text(f'#!/usr/bin/env bash\necho "$*" >> "{log}"\n')
    gh.chmod(0o755)
    return bindir, log


def _shift_env(slot: Path, bindir: Path | None = None) -> dict:
    """What `worker_env` gives a worker, as far as the merge slot reads it."""
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_REMOTE", None)
    env.update({"PYAUTO_SHIFT_WORKER": "1",
                "PYAUTO_SHIFT_LEDGER_DIR": str(slot / mw.LEDGER_DIR)})
    if bindir is not None:
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    return env


def _slot_cli(slot: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([str(CLI), "merge-slot", *args], env=_shift_env(slot),
                          capture_output=True, text=True, timeout=60)


def _merges(log: Path) -> list[str]:
    if not log.exists():
        return []
    return [ln for ln in log.read_text().splitlines() if ln.startswith("pr merge")]


class InTurnMerger(tc.Spawner):
    """Workers that merge in-turn, as a `notify` worker does: a merge slot
    first, as its own call, then a bare `gh pr merge` only if it was taken;
    a refused worker lists its PR without `merged`."""

    def __init__(self, bindir: Path, prs: dict[str, str]):
        super().__init__()
        self.bindir, self.prs = bindir, prs

    def spawn(self, task, prompt_path, lease_dir):
        lease_dir = Path(lease_dir)
        lease_dir.mkdir(parents=True, exist_ok=True)
        pr = self.prs[task]
        script = (f'if "{CLI}" merge-slot take "{pr}"; then\n'
                  f'  gh pr merge "{pr}" --squash\n'
                  f'  echo "merged {pr}" > "{lease_dir}/{task}.done"\n'
                  f'else\n'
                  f'  echo "{pr}" > "{lease_dir}/{task}.done"\n'
                  f'fi\n')
        subprocess.run(["bash", "-c", script], env=_shift_env(lease_dir.parent, self.bindir),
                       capture_output=True, text=True, timeout=60)
        return {"pid": 0, "session_id": None, "worktree": None}


def test_merge_cap_1_refuses_second_in_turn_notify_merge(tmp_path):
    bindir, log = _fake_gh(tmp_path)
    mind = t._mind(tmp_path / "mind")
    for name in ("named", "picked"):
        f = mind / "draft" / "feature" / "pyautoheart" / f"{name}.md"
        f.write_text(f.read_text().replace("Consequence: glance", "Consequence: notify"))
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet=""))      # merge-cap: 1
    home = tmp_path / "home"
    sp = InTurnMerger(bindir, {"named": PR1, "picked": PR2})
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=tc.Agents(),
                  health=tc._health({}))
    assert sorted(s["task"] for s in r["spawned"]) == ["named", "picked"], r
    tc._tick(brief, mind, home, sp, 1)        # reaps both workers; the watcher looks
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)

    assert len(_merges(log)) == 1, _merges(log)                 # one merge, not two
    merged = [task for task, o in c["outcomes"].items() if o.get("merged")]
    assert len(merged) == 1
    left = PR2 if merged == ["named"] else PR1
    # The left PR is `notify`: the watcher no longer calls it "only glance",
    # it is refused for the cap and left for the human's /prm.
    co = c["closeouts"][left]
    assert co["state"] == "refused", co
    assert "merge-cap 1" in co["why"] and "/prm" in co["why"], co["why"]
    assert sp.closeouts == []                                   # no session started
    st = _slot_cli(slot, "status")
    assert st.returncode == 0 and "1 of merge-cap 1" in st.stdout, st.stdout


def test_take_is_atomic_across_processes(tmp_path):
    slot = tmp_path / "slot"
    (slot / mw.LEDGER_DIR).mkdir(parents=True)
    sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "batch"))
    import _merge_slots
    _merge_slots.publish(slot, 3, False)
    procs = [subprocess.Popen([str(CLI), "merge-slot", "take", f"https://github.com/o/r/pull/{i}"],
                              env=_shift_env(slot), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
             for i in range(10)]
    codes = [p.wait(timeout=60) for p in procs]
    assert sorted(codes) == [0, 0, 0] + [1] * 7, codes
    assert _merge_slots.used(slot) == 3
    data = json.loads((slot / _merge_slots.SLOTS_FILE).read_text())
    assert len(data["slots"]) == 3 and len(data["refusals"]) == 7


def test_watcher_closeout_and_worker_share_slots(tmp_path):
    # A `glance` shift with merge-cap 1: the watcher starts a close-out on PR1,
    # which takes the one slot; a worker's in-turn take of PR2 is refused.
    mind, brief, home, sp = tc._shift(tmp_path, cap=1)
    slot = orch.slot_dir(brief, home)
    r = tc._tick(brief, mind, home, sp, 1)
    assert r["closeouts"]["started"] == [PR1], r["closeouts"]
    assert _slot_cli(slot, "take", PR2).returncode == 1
    # The close-out session's own /prm take for its PR is the watcher's slot.
    assert _slot_cli(slot, "take", PR1).returncode == 0
    # A worker cannot free the watcher's slot.
    _slot_cli(slot, "release", PR1)
    assert _slot_cli(slot, "take", PR2).returncode == 1
    # The close-out refuses: the watcher frees its slot, and the worker gets it.
    tc._verdict(home, brief, "named", result="refused", pr=PR1, why="witness failed")
    tc._tick(brief, mind, home, sp, 2)
    assert orch.read_counters(slot)["closeouts"][PR1]["state"] == "refused"
    assert _slot_cli(slot, "take", PR2).returncode == 0
    st = _slot_cli(slot, "status", PR1)
    assert "witness failed" in st.stdout or "released" in st.stdout, st.stdout


def test_outside_a_shift_the_take_is_a_no_op(tmp_path):
    env = dict(os.environ)
    for k in ("PYAUTO_SHIFT_WORKER", "PYAUTO_SHIFT_LEDGER_DIR", "CLAUDE_CODE_REMOTE"):
        env.pop(k, None)
    r = subprocess.run([str(CLI), "merge-slot", "take", PR1], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "not in a shift" in r.stdout


def test_no_published_cap_or_a_pause_fails_closed(tmp_path):
    slot = tmp_path / "slot"
    (slot / mw.LEDGER_DIR).mkdir(parents=True)
    r = _slot_cli(slot, "take", PR1)
    assert r.returncode == 1 and "no merge-cap" in r.stdout
    sys.path.insert(0, str(BRAIN / "agents" / "conductors" / "batch"))
    import _merge_slots
    _merge_slots.publish(slot, 2, True)
    r = _slot_cli(slot, "take", PR1)
    assert r.returncode == 1 and "paused" in r.stdout
    gone = tmp_path / "nowhere"
    r = _slot_cli(gone, "take", PR1)
    assert r.returncode == 2

"""M3.6e (PyAutoBrain#661), ruling R3 (AUTONOMY.md, 2026-11-17).

A `bug · safe · notify` task with a held `Witness:` merges in-turn under
`--auto`: the `bug` cap lowers its level to `supervised`, and the level
decides the checkpoints, not who merges. Inside a shift that merge takes a
merge slot, so the snapshot counts it against `merge-cap:`. `start_dev` prints
the effective level and merge mode in one line, from `pyauto-brain merge-mode`,
so a worker and a reader see the same answer.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_closeout_merge_slots as ms  # noqa: E402 — fake gh, shift env
import test_orchestrator_closeout as tc  # noqa: E402
import test_orchestrator_digest as t  # noqa: E402
from test_orchestrator_digest import orch  # noqa: E402
import _watch  # noqa: E402

CLI = BRAIN / "bin" / "pyauto-brain"
PR = "https://github.com/o/r/pull/7"

BUG = """\
# Fix the thing

Type: bug
Target: PyAutoHeart
Repos:
- PyAutoHeart
Difficulty: small
Autonomy: {autonomy}
Priority: normal
Status: formalised
Consequence: {tier}
{witness}Review-minutes: 0
Unattended: ready
Lane: any

Body.
"""

BRIEF = """\
# Batch 2026-11-04 am
- dispatched: 2026-11-04T08:30Z
- review-at: 2026-11-04T11:30Z
- issue: {issue}
- brief:
  - goals:
    - 1. one bug
  - tasks:
    - draft/bug/pyautoheart/fix_thing.md
  - backlog: none
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 1
  - token-budget: 100000
  - max-workers: 2
"""


def _prompt(root: Path, autonomy="safe", tier="notify", witness=True) -> Path:
    folder = root / "draft" / "bug" / "pyautoheart"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "fix_thing.md"
    f.write_text(BUG.format(autonomy=autonomy, tier=tier,
                            witness="Witness: `pytest -q tests/test_thing.py` passes\n"
                            if witness else ""))
    return f


def _mode(prompt: Path, *flags) -> subprocess.CompletedProcess:
    return subprocess.run([str(CLI), "merge-mode", str(prompt), *flags],
                          capture_output=True, text=True, timeout=60)


class AutoWorker(tc.Spawner):
    """A shift worker under `--auto`: it asks `merge-mode` (in a shift), and
    when that says auto-merge it takes a slot, then runs a bare merge."""

    def __init__(self, bindir: Path, mind: Path):
        super().__init__()
        self.bindir, self.mind = bindir, mind

    def spawn(self, task, prompt_path, lease_dir):
        lease_dir = Path(lease_dir)
        lease_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = self.mind / prompt_path      # the pick's Mind-relative path
        script = (f'mode=$("{CLI}" merge-mode "{prompt_path}" --auto --in-shift)\n'
                  f'echo "$mode" > "{lease_dir}/{task}.mode"\n'
                  f'case "$mode" in *"merge mode: auto-merge on green"*)\n'
                  f'  if "{CLI}" merge-slot take "{PR}"; then\n'
                  f'    gh pr merge "{PR}" --squash\n'
                  f'    echo "merged {PR}" > "{lease_dir}/{task}.done"; exit 0\n'
                  f'  fi;;\n'
                  f'esac\n'
                  f'echo "{PR}" > "{lease_dir}/{task}.done"\n')
        subprocess.run(["bash", "-c", script], env=ms._shift_env(lease_dir.parent, self.bindir),
                       capture_output=True, text=True, timeout=60)
        return {"pid": 0, "session_id": None, "worktree": None}


def test_auto_safe_notify_bug_with_witness_merges_and_counts(tmp_path):
    bindir, log = ms._fake_gh(tmp_path)
    mind = tmp_path / "mind"
    prompt = _prompt(mind)
    (mind / "queue.md").write_text(t.QUEUE)
    brief = tmp_path / "shift.md"
    brief.write_text(BRIEF.format(issue=t.ISSUE))
    home = tmp_path / "home"
    sp = AutoWorker(bindir, mind)
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=tc.Agents(),
                  health=tc._health({}))
    assert [s["task"] for s in r["spawned"]] == ["fix_thing"], r
    tc._tick(brief, mind, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    # The line the worker read before it merged.
    assert _mode(prompt, "--auto", "--in-shift").stdout == (
        "effective level: supervised; merge mode: auto-merge on green after a merge slot\n")
    assert len(ms._merges(log)) == 1, ms._merges(log)
    c = orch.read_counters(slot)
    assert c["outcomes"]["fix_thing"]["merged"] == [PR]
    assert "1 merged of merge-cap 1" in _watch.attach_summary(brief, slot)
    st = ms._slot_cli(slot, "status")
    assert "1 of merge-cap 1" in st.stdout, st.stdout


def test_merge_mode_prints_effective_level_line(tmp_path):
    prompt = _prompt(tmp_path)
    r = _mode(prompt, "--auto")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "effective level: supervised; merge mode: auto-merge on green\n"
    # R3: a cap-lowered `notify` task with no `Witness:` goes to /prm.
    assert _mode(_prompt(tmp_path, witness=False), "--auto").stdout == (
        "effective level: supervised; merge mode: human /prm\n")
    assert _mode(_prompt(tmp_path, tier="judge"), "--auto").stdout == (
        "effective level: supervised; merge mode: human /prm\n")
    assert _mode(_prompt(tmp_path, tier="glance"), "--auto").stdout == (
        "effective level: supervised; merge mode: auto-merge on green if the Witness passes\n")
    # start_dev step 3 produces its line from this command.
    start_dev = (BRAIN / "skills" / "start_dev" / "start_dev.md").read_text()
    assert "pyauto-brain merge-mode" in start_dev

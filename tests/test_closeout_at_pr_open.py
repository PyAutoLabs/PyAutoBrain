"""M3.7b (PyAutoBrain#688): the close-out starts at PR-open and merges on green CI.

The human's rulings of 2026-11-19 (AUTONOMY.md "Shift speed — 2026-11-19"):

- S5: a close-out may start while CI still runs; it runs the witness and reads
  the diff first, then waits in-turn for CI (`ci-verdict --until`) and merges
  only on GREEN. It takes its merge slot itself, just before the merge
  (decision A).
- S2: the close-out runs no full affected smoke.
- S6: a later library PR is updated from `main` only when its changed files
  overlap a PR of the shift merged ahead of it, or GitHub reports a conflict.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
sys.path.insert(0, str(BRAIN / "bin"))
import test_orchestrator_closeout as tc  # noqa: E402 — the phase-4b and M3.6j fixtures
from test_orchestrator_closeout import (FIT8, GA7, GA8, PR1, PR2, Agents,  # noqa: E402
                                        _verdict)
from test_orchestrator_digest import orch  # noqa: E402
import ci_verdict  # noqa: E402

NOW = tc.t.NOW


class KwSpawner(tc.Spawner):
    """The phase-4b spawner, keeping what each close-out was told."""

    def __init__(self):
        super().__init__()
        self.kws = []

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir, **kw):
        self.kws.append(kw)
        return super().spawn_closeout(task, pr_url, prompt_path, lease_dir)


def _shift(tmp_path, cap=2):
    mind = tc.t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(tc.t.BRIEF.format(issue=tc.t.ISSUE, packet="")
                     .replace("merge-cap: 1", f"merge-cap: {cap}"))
    home = tmp_path / "home"
    sp = KwSpawner()
    orch.tick(brief, mind, home=home, now=NOW, spawner=sp, agents=Agents(),
              health=tc._health({}))
    return mind, brief, home, sp


def _holders(brief, home):
    return orch._merge_slots.holders(orch.slot_dir(brief, home))


# --- S5: started at PR-open, CI still running -----------------------------------------

def test_s5_a_glance_and_a_notify_pr_with_ci_running_start_their_closeouts(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["picks"]["picked"]["tier"] = "notify"
    orch._write_counters(slot, c)
    running = tc._health({PR1: "RUNNING", PR2: "RUNNING"})
    r = tc._tick(brief, mind, home, sp, 1, health=running)
    assert sorted(r["closeouts"]["started"]) == [PR1, PR2]
    assert sorted(sp.closeouts) == [("named", PR1), ("picked", PR2)]
    # The in-turn CI wait's deadline: 30 min from the start (review-at is later).
    until = orch._iso(NOW + _dt.timedelta(minutes=31))
    assert all(kw.get("ci_until") == until for kw in sp.kws), sp.kws
    # Decision A: the watcher takes no merge slot for a merge close-out.
    assert _holders(brief, home) == {}
    tc._tick(brief, mind, home, sp, 2, health=running)
    assert len(sp.closeouts) == 2                              # never twice


def test_s5_the_ci_deadline_leaves_the_merge_margin_before_review_at(tmp_path):
    """Review round 1, finding 1: a close-out started 21 min before review-at
    must not wait until review-at and merge after it (#632 F1): the deadline
    is review-at minus CLOSEOUT_MERGE_MARGIN_S (the /prm run after GREEN)."""
    mind, brief, home, sp = _shift(tmp_path)
    tc._tick(brief, mind, home, sp, 129, health=tc._health({PR1: "RUNNING"}))  # 11:09
    assert orch.CLOSEOUT_MERGE_MARGIN_S == 300
    assert sp.kws and all(kw["ci_until"] == "2026-11-04T11:25:00Z" for kw in sp.kws)


def test_s5_red_or_unknown_ci_still_refuses_with_no_session(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    tc._tick(brief, mind, home, sp, 1, health=tc._health({PR1: "FAILED", PR2: "UNKNOWN"}))
    assert sp.closeouts == []
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["why"] == "CI FAILED — never merged unattended"
    assert c["closeouts"][PR2]["why"] == "CI UNKNOWN — never merged unattended"


def test_s5_no_checks_waits_out_the_grace_then_refuses(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    none = tc._health({PR1: "NO-CHECKS", PR2: "NO-CHECKS"})
    tc._tick(brief, mind, home, sp, 1, health=none)
    tc._tick(brief, mind, home, sp, 9, health=none)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert sp.closeouts == [] and PR1 not in c["closeouts"]   # waiting, not refused
    tc._tick(brief, mind, home, sp, 12, health=none)          # 11 min after first seen
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert sp.closeouts == []
    assert c["closeouts"][PR1]["why"] == "CI NO-CHECKS — never merged unattended"


# --- S2 + S5: the rendered close-out prompt -------------------------------------------

def _prompt(**kw):
    return orch.closeout_prompt("t1", PR1, "draft/x/t1.md", Path("b.md"), Path("leases"),
                                ci_until="2026-11-04T09:31:00Z", **kw)


def test_s2_s5_the_prompt_runs_no_smoke_and_waits_for_ci_after_the_witness(tmp_path):
    text = _prompt()
    assert "--affected-by" not in text and "smoke --affected-by" not in text
    wait = text.index(f"ci-verdict {PR1} --until 2026-11-04T09:31:00Z")
    assert text.index("Witness:") < wait
    assert text.index("Review the diff adversarially") < wait
    assert text.index("headRefOid") < wait                    # recorded at the witness
    assert "2026-11-04T09:31:00Z" in text
    assert "CI not finished by 2026-11-04T09:31:00Z → /prm" in text
    assert "head moved after the witness → /prm" in text
    # Decision A: the session takes its own merge slot, just before the merge.
    take = text.index(f"merge-slot take {PR1} --task t1")
    assert wait < take < text.index("use the prm skill")
    assert "took its slot before starting you" not in text
    assert "/smoke" not in text.split("Last, write", 1)[1]    # the verdict's gate


def test_r1_the_merge_slot_take_must_say_taken():
    """Review round 1, finding 3: `merge-slot take` exits 0 with "not in a
    shift" when the shift env is missing; only a `taken: ` line goes on."""
    text = _prompt()
    step = text.split("\n8. ", 1)[1].split("\n9. ", 1)[0]
    assert "`taken: `" in step and "not in a shift" in step
    assert "merge slot not taken: <first line> → /prm" in step


def test_r1_the_ci_wait_runs_under_a_long_bash_timeout_and_the_merge_is_pinned():
    """Review round 1, findings 4 and 5."""
    text = _prompt()
    wait = text.split("\n5. ", 1)[1].split("\n6. ", 1)[0]
    assert "600000" in wait
    step = text.split("\n8. ", 1)[1].split("\n9. ", 1)[0]
    assert "gh pr merge" in step and "--match-head-commit <the step-1 headRefOid>" in step


def test_s6_disjoint_merged_ahead_prs_are_named_not_compared():
    text = _prompt(after=[GA7], before=[GA7, "https://github.com/example-org/autogalaxy/pull/5"],
                   disjoint=["https://github.com/example-org/autogalaxy/pull/5"])
    step = text.split("4b. Merge order", 1)[1].split("\n5. ", 1)[0]
    assert "merged ahead, disjoint files, not updated (S6)" in step
    compare = step.split("ahead` or `identical`", 1)[1].split("disjoint", 1)[0]
    assert GA7 in compare and "/pull/5" not in compare


# --- S6: branch update only on overlap or conflict ----------------------------------

class FilesOrderSpawner(tc.OrderSpawner):
    """M3.6j's spawner, plus the changed-file read (`gh pr view --json files`)."""

    def __init__(self, files, picked=GA8):
        super().__init__(picked)
        self.files, self.reads = files, []

    def pr_files(self, url):
        self.reads.append(url)
        return self.files.get(url)


def _merged_ahead(tmp_path, files, mergeable=""):
    """#7 refused then merged after #8's worker began; #8 is green."""
    mind, brief, home, _ = tc._order_shift(tmp_path)
    sp = FilesOrderSpawner(files)
    tc._otick(brief, mind, home, sp, 1)
    _verdict(home, brief, "named", result="refused", pr=GA7,
             why="decision-taken label → human /prm")
    tc._otick(brief, mind, home, sp, 2)
    states = {GA7: ("MERGED", "2026-11-04T09:30:00Z")}
    gh = tc._gh_states(states)

    def read(url):
        out = gh(url)
        if out is not None and url == GA8 and mergeable:
            out = {**out, "mergeable": mergeable}
        return out
    r = orch.tick(brief, mind, home=home, now=NOW + _dt.timedelta(minutes=31), spawner=sp,
                  agents=Agents(), health=tc._health({}), pr_state=read)
    return mind, brief, home, sp, r


def test_s6_a_pr_disjoint_from_every_pr_merged_ahead_is_closed_out_without_update(tmp_path):
    files = {GA7: ["autogalaxy/a.py"], GA8: ["autogalaxy/b.py", "test_autogalaxy/test_b.py"]}
    mind, brief, home, sp, r = _merged_ahead(tmp_path, files)
    task, pr, kw = sp.closeouts[-1]
    assert (task, pr) == ("picked", GA8)
    assert "update_after" not in kw and kw["disjoint"] == [GA7] and kw["before"] == [GA7]
    assert "after" not in kw
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][GA8]["state"] == "running" and c["closeouts"][GA8].get("kind") != "update"
    assert c["pr_files"][GA8] == files[GA8]                    # cached for the shift
    assert sorted(set(sp.reads)) == sorted(sp.reads) == sorted([GA7, GA8])   # once each


def test_s6_one_shared_file_still_gets_the_branch_update(tmp_path):
    files = {GA7: ["autogalaxy/a.py", "autogalaxy/shared.py"], GA8: ["autogalaxy/shared.py"]}
    mind, brief, home, sp, r = _merged_ahead(tmp_path, files)
    assert sp.closeouts[-1] == ("picked", GA8, {"update_after": [GA7]})


def test_s6_a_conflicting_pr_gets_the_update_even_with_disjoint_files(tmp_path):
    files = {GA7: ["autogalaxy/a.py"], GA8: ["autogalaxy/b.py"]}
    mind, brief, home, sp, r = _merged_ahead(tmp_path, files, mergeable="CONFLICTING")
    assert sp.closeouts[-1] == ("picked", GA8, {"update_after": [GA7]})


def test_s6_an_unreadable_file_list_fails_toward_the_update(tmp_path):
    mind, brief, home, sp, r = _merged_ahead(tmp_path, {GA7: ["autogalaxy/a.py"]})
    assert sp.closeouts[-1] == ("picked", GA8, {"update_after": [GA7]})
    # Kept as unreadable (None), never read again (review round 1, finding 2).
    assert orch.read_counters(orch.slot_dir(brief, home))["pr_files"][GA8] is None


@pytest.mark.parametrize("bad", ["none", "raise"])
def test_s6_an_unreadable_file_list_is_read_once_a_shift(bad):
    """Review round 1, finding 2: an earlier PR whose files cannot be read is
    cached as unreadable (an overlap) and never read again for a later PR."""
    calls = []

    def reader(url):
        calls.append(url)
        if url == GA7:
            if bad == "raise":
                raise RuntimeError("gh down")
            return None
        return ["autogalaxy/x.py"]
    counters = {}
    ga9 = GA8.replace("/8", "/9")
    for later in (GA8, ga9):
        need, disjoint = orch._overlap(counters, later, [GA7], None, reader, {})
        assert need == [GA7] and disjoint == []
    assert calls.count(GA7) == 1, calls
    assert calls.count(GA8) == 1 and calls.count(ga9) == 1


def test_gh_pr_files_and_mergeable_reads():
    def gh(out, rc=0):
        return lambda argv, **kw: subprocess.CompletedProcess(argv, rc, out, "")
    files = json.dumps({"files": [{"path": "a.py", "additions": 1}, {"path": "b/c.py"}]})
    assert orch.gh_pr_files(GA8, run=gh(files)) == ["a.py", "b/c.py"]
    assert orch.gh_pr_files(GA8, run=gh("", rc=1)) is None
    assert orch.gh_pr_files(GA8, run=gh("not json")) is None
    full = json.dumps({"files": [{"path": f"f{i}.py"} for i in range(100)]})
    assert orch.gh_pr_files(GA8, run=gh(full)) is None         # may be truncated
    seen = []

    def view(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(
            {"state": "OPEN", "headRefOid": "abc", "mergeable": "CONFLICTING"}), "")
    assert orch.gh_pr_state(GA8, run=view)["mergeable"] == "CONFLICTING"
    assert len(seen) == 1 and "mergeable" in seen[0][seen[0].index("--json") + 1]


# --- merge order unchanged ------------------------------------------------------------

def test_merge_order_a_later_pr_waits_while_the_earlier_closeout_waits_on_ci(tmp_path):
    mind, brief, home, sp = tc._order_shift(tmp_path)
    running = tc._health({GA7: "RUNNING", GA8: "RUNNING"})
    tc._otick(brief, mind, home, sp, 1, health=running)
    assert [(task, pr) for task, pr, _ in sp.closeouts] == [("named", GA7)]
    for minute in (2, 3, 4):
        tc._otick(brief, mind, home, sp, minute, health=running)
        c = orch.read_counters(orch.slot_dir(brief, home))
        assert c["closeouts"][GA7]["state"] == "running"
        assert c["merge_waits"][GA8]["behind"] == [GA7] and GA8 not in c["closeouts"]
    assert [pr for _, pr, _ in sp.closeouts] == [GA7]


# --- decision A: the session takes the slot, the reaper frees it ---------------------

def _slot_take(brief, home, pr, task):
    return orch._merge_slots.take(orch.slot_dir(brief, home), pr, "worker", task)


def test_a_a_full_cap_refuses_without_a_session(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=1)
    slot = orch.slot_dir(brief, home)
    orch._merge_slots.publish(slot, 1, False)
    assert _slot_take(brief, home, "https://github.com/o/r/pull/99", "other")[0]
    tc._tick(brief, mind, home, sp, 1)
    assert sp.closeouts == []
    c = orch.read_counters(slot)
    assert c["closeouts"][PR1]["why"] == "merge-cap 1 reached this shift — left for your /prm"


def test_a_a_refused_closeout_frees_the_slot_its_session_took(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    tc._tick(brief, mind, home, sp, 1)
    assert _holders(brief, home) == {}
    assert _slot_take(brief, home, PR1, "named")[0] and _slot_take(brief, home, PR2, "picked")[0]
    _verdict(home, brief, "named", result="refused", pr=PR1, why="CI RED: check-failed")
    _verdict(home, brief, "picked", result="merged", pr=PR2, gate="g", model="m")
    r = tc._tick(brief, mind, home, sp, 2)
    assert r["closeouts"]["refused"] == [PR1] and r["closeouts"]["merged"] == [PR2]
    held = _holders(brief, home)
    assert orch._merge_slots.pr_key(PR1) not in held           # refused: freed
    assert held[orch._merge_slots.pr_key(PR2)]["task"] == "picked"   # merged: kept


def test_a_the_closeout_sessions_own_take_succeeds(tmp_path, monkeypatch, capsys):
    import merge_slot
    slot = tmp_path / "slot"
    (slot / "ledger").mkdir(parents=True)
    (slot / orch.COUNTERS_FILE).write_text(json.dumps({
        "outcomes": {"named": {"prs": [GA7], "merged": [GA7], "issues": []},
                     "picked": {"prs": [GA8], "merged": [], "issues": []}},
        "closeouts": {GA8: {"task": "picked", "state": "running"}}}))
    orch._merge_slots.publish(slot, 1, False)
    env = orch.worker_env(slot / "leases", base={})
    for k in ("PYAUTO_SHIFT_WORKER", "PYAUTO_SHIFT_LEDGER_DIR"):
        monkeypatch.setenv(k, env[k])
    monkeypatch.setattr(orch, "gh_pr_state", lambda u: {"state": "MERGED", "mergedAt": "",
                                                        "mergedBy": ""})
    assert merge_slot.main(["take", GA8, "--task", "picked"]) == 0, capsys.readouterr().out
    assert orch._merge_slots.holders(slot)[orch._merge_slots.pr_key(GA8)]["task"] == "picked"


# --- ci-verdict --until ---------------------------------------------------------------

def _verdicts(monkeypatch, words):
    seq = list(words)
    calls = []

    def fake(ref, run=None, sleep=None):
        calls.append(ref)
        w = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"pr": "o/r#1", "sha": "abc", "verdict": w, "reasons": [], "counts": {},
                "skipped": [], "mergeable_state": "clean", "note": None}
    monkeypatch.setattr(ci_verdict, "verdict_for", fake)
    return calls


class Clock:
    def __init__(self, start):
        self.t, self.slept = start, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += _dt.timedelta(seconds=s)


def test_until_pending_then_green_exits_0(monkeypatch):
    calls = _verdicts(monkeypatch, ["PENDING", "PENDING", "GREEN"])
    clock = Clock(NOW)
    rc = ci_verdict.main([PR1, "--until", "2026-11-04T09:30:00Z"], sleep=clock.sleep,
                         now=clock.now)
    assert rc == 0 and len(calls) == 3 and clock.slept == [30, 30]


def test_until_pending_through_the_deadline_exits_2(monkeypatch):
    calls = _verdicts(monkeypatch, ["PENDING"])
    clock = Clock(NOW)
    rc = ci_verdict.main([PR1, "--until", "2026-11-04T09:01:00Z"], sleep=clock.sleep,
                         now=clock.now)
    # The deadline is re-checked after each sleep (review round 1, finding 4).
    assert rc == 2 and clock.slept == [30, 30] and len(calls) == 2


def test_until_one_call_polls_at_most_540_seconds(monkeypatch):
    _verdicts(monkeypatch, ["PENDING"])
    clock = Clock(NOW)
    rc = ci_verdict.main([PR1, "--until", "2026-11-04T10:00:00Z"], sleep=clock.sleep,
                         now=clock.now)
    assert rc == 2 and sum(clock.slept) <= 540 and sum(clock.slept) >= 510


def test_until_one_call_stays_within_540_seconds_when_reads_take_time(monkeypatch):
    """Review round 1, finding 4: the bound is wall time from the call's
    start, gh reads included, not the sum of the sleeps."""
    clock = Clock(NOW)

    def slow(ref, run=None, sleep=None):
        clock.t += _dt.timedelta(seconds=20)          # each read takes 20 s
        return {"pr": "o/r#1", "sha": "abc", "verdict": "PENDING", "reasons": [],
                "counts": {}, "skipped": [], "mergeable_state": "clean", "note": None}
    monkeypatch.setattr(ci_verdict, "verdict_for", slow)
    start = clock.t
    rc = ci_verdict.main([PR1, "--until", "2026-11-04T10:00:00Z"], sleep=clock.sleep,
                         now=clock.now)
    assert rc == 2 and (clock.t - start).total_seconds() <= 540


def test_until_red_returns_at_once_and_a_bad_timestamp_is_usage(monkeypatch):
    _verdicts(monkeypatch, ["RED"])
    clock = Clock(NOW)
    assert ci_verdict.main([PR1, "--until", "2026-11-04T10:00:00Z"], sleep=clock.sleep,
                           now=clock.now) == 1 and clock.slept == []
    assert ci_verdict.main([PR1, "--until", "half past nine"], sleep=clock.sleep,
                           now=clock.now) == 64


def test_pyauto_brain_passes_until_through():
    text = (BRAIN / "bin" / "pyauto-brain").read_text()
    assert 'exec python3 "$BRAIN_HOME/bin/ci_verdict.py" "$@"' in text
    assert "--until" in text


# --- the doctrine ---------------------------------------------------------------------

def test_autonomy_records_s2_s5_s6_and_their_revert_conditions():
    text = (BRAIN / "AUTONOMY.md").read_text()
    sec = text.split("## Shift speed — 2026-11-19", 1)[1].split("\n## ", 1)[0]
    sec = " ".join(sec.split())
    for ruling in ("**S2,", "**S5,", "**S6,"):
        assert ruling in sec, ruling
    assert "one red sweep traced to an unattended merge" in sec
    assert "one red `main` CI traced to two disjoint shift PRs" in sec
    assert "30 minutes" in sec and "immediately before the merge" in sec
    assert "(S2, S4 to S7)" not in sec
    leg2 = text.split("2. **Smoke**", 1)[1].split("\n3. **Review**", 1)[0]
    assert "S2" in leg2 and "M3.7d" in leg2 and "M3.7e" in leg2
    net = text.split("## The watcher's network surface — 2026-11-03", 1)[1].split("\n## ", 1)[0]
    net = " ".join(net.split())
    assert "M3.7b" in net and "--json files" in net and "mergeable" in net
    glance = text.split("### Unattended `glance` merges — 2026-11-03", 1)[1].split("\n### ", 1)[0]
    assert "S5" in glance and "S6" in glance

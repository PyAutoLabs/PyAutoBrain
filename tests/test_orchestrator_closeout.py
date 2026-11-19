"""Autonomous orchestrators phase 4b (PyAutoBrain#572): the unattended `glance` close-out.

After CI lands green on a declared-`glance` PR a worker opened, the watcher
starts one independent close-out session; its verdict file decides the rest. A
merge lands one row in autonomy_log.md's stage-2 table through the one Mind
writer; every guard that fails starts nothing and is digested; nothing is ever
retried.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
from test_orchestrator_digest import _brief, _digest, orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

PR1 = "https://github.com/o/r/pull/1"
PR2 = "https://github.com/o/r/pull/2"


class Spawner(t.FilesSpawner):
    """Workers that finished at once (PRs open, nothing merged in-turn) and a
    close-out whose verdict the test writes when it chooses."""

    def __init__(self):
        super().__init__(done={"named": PR1 + "\n", "picked": PR2 + "\n"}, proofs={})
        self.closeouts = []

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir):
        self.closeouts.append((task, pr_url))
        return {"pid": 0, "agent_id": f"co{len(self.closeouts):06d}"}


class Agents:
    """`claude agents --json`: every close-out still working unless told."""

    def __init__(self, states=None):
        self.states = states or {}

    def state(self, agent_id):
        return self.states.get(agent_id, "working")

    def session_of(self, agent_id):
        return None


def _health(verdicts):
    return lambda url: verdicts.get(url, "HEALTHY")


def _shift(tmp_path, cap=1, extra=""):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="")
                     .replace("merge-cap: 1", f"merge-cap: {cap}") + extra)
    home = tmp_path / "home"
    sp = Spawner()
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=Agents(),
              health=_health({}))
    return mind, brief, home, sp


def _tick(brief, mind, home, sp, minutes, health=None, agents=None):
    return orch.tick(brief, mind, home=home, now=t.NOW + _dt.timedelta(minutes=minutes),
                     spawner=sp, agents=agents or Agents(), health=health or _health({}))


def _verdict(home, brief, task, **v):
    slot = orch.slot_dir(brief, home)
    (slot / "leases" / f"{task}.closeout").write_text(json.dumps(v))


# --- green + guards → exactly one close-out, merged → one stage-2 row -------------

def test_a_green_glance_pr_gets_exactly_one_closeout(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    r = _tick(brief, mind, home, sp, 1)       # reaps the workers, starts close-outs
    assert sorted(r["closeouts"]["started"]) == [PR1, PR2]
    _tick(brief, mind, home, sp, 2)
    _tick(brief, mind, home, sp, 3)
    assert sorted(sp.closeouts) == [("named", PR1), ("picked", PR2)]   # never twice


def test_a_merged_verdict_counts_and_queues_one_stage2_row(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="tests PASS / witness PASS",
             model="claude-opus-5-5")
    r = _tick(brief, mind, home, sp, 2)
    assert r["closeouts"]["merged"] == [PR1]
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 1
    assert c["outcomes"]["named"]["merged"] == [PR1]
    ops = [json.loads(f.read_text()) for f in mw.pending_ops(slot)]
    rows = [o for o in ops if o["op"] == "table-append"]
    assert len(rows) == 1 and rows[0]["heading"] == orch.STAGE2_HEADING
    assert rows[0]["row"].startswith("| 2026-11-04 | named (" + PR1 + ") | shift |")
    assert "adversary: independent close-out session (claude-opus-5-5)" in rows[0]["row"]
    assert rows[0]["row"].endswith("| merged-unchanged | unattended-watcher |  |")
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert "merged unattended (close-out, claude-opus-5-5)" in d
    assert "- glance-auto-merges: 1" in d and "- merges: 1" in d


# --- each guard failing on its own → nothing started, the reason digested -------

def test_a_notify_pr_left_open_is_closed_out_like_glance(tmp_path):
    """Ruling R3 (AUTONOMY.md, 2026-11-17, #661): the watcher closes out a
    `notify` PR a worker left open on the same terms as a `glance` one — and
    its merge is no stage-2 row and no unattended `glance` merge."""
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["picks"]["named"]["tier"] = "notify"
    orch._write_counters(slot, c)
    _tick(brief, mind, home, sp, 1)
    assert ("named", PR1) in sp.closeouts
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="witness PASS",
             model="claude-opus-5-5")
    r = _tick(brief, mind, home, sp, 2)
    assert r["closeouts"]["merged"] == [PR1]
    c = orch.read_counters(slot)
    assert c["outcomes"]["named"]["merged"] == [PR1]
    assert c["glance_auto_merges"] == 0
    assert _stage2_rows(slot) == []


@pytest.mark.parametrize("tier", ["judge", "?"])
def test_a_judge_or_undeclared_task_is_never_closed_out(tier, tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["picks"]["named"]["tier"] = tier
    orch._write_counters(slot, c)
    _tick(brief, mind, home, sp, 1)
    assert ("named", PR1) not in sp.closeouts
    co = orch.read_counters(slot)["closeouts"][PR1]
    assert co["state"] == "refused"
    assert "never merged unattended → your /prm" in co["why"], co["why"]


def test_witness_343_a_pr_with_zero_completed_checks_is_refused_at_merge(tmp_path):
    """PyAutoHeart#343 Witness: a PR whose head has no completed check (a repo
    with no CI, such as the website, or only skipped checks) is refused at the
    watcher's merge guard and left to the human — through the real
    `gh pr checks --json` reader, not a stubbed verdict."""
    def gh(out, err="", rc=0):
        return lambda argv, **kw: subprocess.CompletedProcess(argv, rc, out, err)
    no_ci = gh("", "no checks reported on the 'feature/x' branch", rc=1)
    skipped_only = gh(json.dumps([{"name": "smoke", "bucket": "skipping", "state": "SKIPPED"}]))
    health = {PR1: lambda u: _digest.pr_health(u, run=no_ci),
              PR2: lambda u: _digest.pr_health(u, run=skipped_only)}
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    _tick(brief, mind, home, sp, 1, health=lambda u: health[u](u))
    assert sp.closeouts == []
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["state"] == "refused"
    assert c["closeouts"][PR1]["why"] == "CI NO-CHECKS — never merged unattended"
    assert c["closeouts"][PR2]["why"] == "CI NO-CHECKS — never merged unattended"


def test_red_ci_is_refused_and_pending_ci_waits(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    h = _health({PR1: "FAILED", PR2: "RUNNING"})
    _tick(brief, mind, home, sp, 1, health=h)
    assert sp.closeouts == []
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["why"] == "CI FAILED — never merged unattended"
    assert PR2 not in c["closeouts"]                          # waiting, not refused
    _tick(brief, mind, home, sp, 2, health=_health({PR1: "HEALTHY"}))
    assert sp.closeouts == [("picked", PR2)]                  # PR1's refusal is final


def test_merge_cap_counts_merges_and_in_flight_closeouts(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=1)
    r = _tick(brief, mind, home, sp, 1)
    assert len(r["closeouts"]["started"]) == 1 and len(r["closeouts"]["refused"]) == 1
    c = orch.read_counters(orch.slot_dir(brief, home))
    refused = [co for co in c["closeouts"].values() if co["state"] == "refused"]
    assert refused[0]["why"] == "merge-cap 1 reached this shift — left for your /prm"


def test_merge_cap_zero_starts_nothing(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=0)
    _tick(brief, mind, home, sp, 1)
    assert sp.closeouts == []


def test_a_shadow_shift_never_closes_out(tmp_path):
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    counters = orch.read_counters(slot)
    events = orch._closeouts(slot, {"shadow": {"value": "yes", "children": []},
                                    "merge-cap": {"value": "2", "children": []}},
                             counters, sp, t.NOW, Agents(), _health({}))
    assert events["started"] == [] and sp.closeouts == []


# --- refusals are final and digested ------------------------------------------

def test_a_refused_closeout_is_digested_and_never_retried(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _verdict(home, brief, "named", result="refused", pr=PR1,
             why="decision-taken label", gate="", model="claude-opus-5-5")
    _tick(brief, mind, home, sp, 2)
    _tick(brief, mind, home, sp, 3)
    assert [c for c in sp.closeouts if c[1] == PR1] == [("named", PR1)]
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 0 and c["outcomes"]["named"]["merged"] == []
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert (f"- **Needs you — not merged unattended** — [named]({PR1})\n"
            "  <sub>`named` · glance · small · pyautoheart · awaiting /prm — close-out refused:"
            " decision-taken label</sub>") in d


def test_a_failed_closeout_is_refused_not_read_as_running(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _tick(brief, mind, home, sp, 2, agents=Agents({"co000001": "failed"}))
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["state"] == "refused"
    assert c["closeouts"][PR1]["why"] == "the close-out session ended without a verdict"


def test_a_closeout_that_ends_without_a_verdict_is_refused_not_retried(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    _tick(brief, mind, home, sp, 2, agents=Agents({"co000001": "done"}))
    _tick(brief, mind, home, sp, 3)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["why"] == "the close-out session ended without a verdict"
    assert len(sp.closeouts) == 1


# --- GitHub is the merge truth (PyAutoBrain#603, ORCH-3) --------------------------

def _gh(states):
    """An offline `gh pr view`: the named state per PR; None = GitHub could not say."""
    def read(url):
        st = states.get(url, "OPEN")
        return None if st is None else {
            "state": st, "mergedAt": "2026-11-04T09:01:30Z" if st == "MERGED" else "",
            "mergedBy": "a-maintainer" if st == "MERGED" else ""}
    return read


def _gh_tick(brief, mind, home, sp, minutes, pr_state, agents=None):
    return orch.tick(brief, mind, home=home, now=t.NOW + _dt.timedelta(minutes=minutes),
                     spawner=sp, agents=agents or Agents(), health=_health({}),
                     pr_state=pr_state)


def test_a_github_merged_pr_with_no_closeout_file_counts_as_one_merge(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    assert sp.closeouts == [("named", PR1)]
    # The close-out merged, then ended before writing `.closeout`.
    r = _gh_tick(brief, mind, home, sp, 2, _gh({PR1: "MERGED"}),
                 agents=Agents({"co000001": "done"}))
    assert r["closeouts"]["merged"] == [PR1] and r["closeouts"]["refused"] == []
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 1 and c["closeouts"][PR1]["state"] == "merged"
    assert c["outcomes"]["named"]["merged"] == [PR1]
    assert c["closeouts"][PR1]["github"]["mergedBy"] == "a-maintainer"
    ops = [json.loads(f.read_text()) for f in mw.pending_ops(slot)]
    rows = [o["row"] for o in ops if o["op"] == "table-append"]
    assert len(rows) == 1 and rows[0].startswith("| 2026-11-04 | named (" + PR1 + ") |")
    assert "merge confirmed on GitHub" in rows[0] and "(no .closeout)" in rows[0]
    # the watcher writes the merge actor, with GitHub's mergedBy as evidence
    assert rows[0].endswith("| unattended-watcher (mergedBy a-maintainer) |  |")
    _gh_tick(brief, mind, home, sp, 3, _gh({PR1: "MERGED"}))
    assert orch.read_counters(slot)["glance_auto_merges"] == 1        # counted once


def test_an_unreadable_github_keeps_the_cap_slot_until_it_can_say(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    ended = Agents({"co000001": "done"})
    _gh_tick(brief, mind, home, sp, 2, _gh({PR1: None}), agents=ended)
    slot = orch.slot_dir(brief, home)
    assert orch.read_counters(slot)["closeouts"][PR1]["state"] == "running"
    _gh_tick(brief, mind, home, sp, 3, _gh({PR1: "OPEN"}), agents=ended)
    co = orch.read_counters(slot)["closeouts"][PR1]
    assert co["state"] == "refused"
    assert co["why"] == "the close-out session ended without a verdict"


def _stage2_rows(slot):
    return [json.loads(f.read_text())["row"] for f in mw.pending_ops(slot)
            if json.loads(f.read_text())["op"] == "table-append"]


def test_a_merged_verdict_on_an_open_pr_holds_the_slot_until_github_merges(tmp_path):
    """`--auto` still pending: the file says merged, GitHub says OPEN."""
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="tests PASS", model="m")
    for minutes, gh in ((2, None), (3, "OPEN")):       # unreadable, then still open
        r = _gh_tick(brief, mind, home, sp, minutes, _gh({PR1: gh}))
        c = orch.read_counters(slot)
        assert r["closeouts"]["merged"] == [] and c["glance_auto_merges"] == 0
        assert c["closeouts"][PR1]["state"] == "running"     # the cap slot stays held
        assert _stage2_rows(slot) == [] and c["outcomes"]["named"]["merged"] == []
    r = _gh_tick(brief, mind, home, sp, 4, _gh({PR1: "MERGED"}))
    assert r["closeouts"]["merged"] == [PR1]
    _gh_tick(brief, mind, home, sp, 5, _gh({PR1: "MERGED"}))
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 1 and c["closeouts"][PR1]["state"] == "merged"
    assert len(_stage2_rows(slot)) == 1                       # counted once


def test_a_merged_verdict_on_a_closed_pr_is_no_merge_and_frees_the_slot(tmp_path):
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="g", model="m")
    r = _gh_tick(brief, mind, home, sp, 2, _gh({PR1: "CLOSED"}))
    c = orch.read_counters(slot)
    assert r["closeouts"]["refused"] == [PR1] and c["glance_auto_merges"] == 0
    assert c["closeouts"][PR1]["state"] == "refused"          # no longer holds the slot
    assert c["closeouts"][PR1]["why"] == "close-out said merged, GitHub closed"
    assert _stage2_rows(slot) == [] and c["outcomes"]["named"]["merged"] == []


def test_a_refused_verdict_on_a_pr_github_shows_merged_is_a_merge_outside(tmp_path):
    """A human merged it: never logged as an unattended merge."""
    mind, brief, home, sp = _shift(tmp_path)
    _tick(brief, mind, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    _verdict(home, brief, "named", result="refused", pr=PR1, why="decision-taken label",
             gate="", model="m")
    r = _gh_tick(brief, mind, home, sp, 2, _gh({PR1: "MERGED"}))
    assert r["closeouts"]["merged"] == [] and r["closeouts"]["merged_outside"] == [PR1]
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 0 and _stage2_rows(slot) == []
    assert c["closeouts"][PR1]["state"] == "refused"          # the slot is freed
    assert c["closeouts"][PR1]["why"] == "merged outside the close-out (mergedBy=a-maintainer)"


def test_gh_pr_state_reads_state_merged_at_and_by():
    from types import SimpleNamespace
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {"state": "MERGED", "mergedAt": "2026-11-04T09:00:00Z",
             "mergedBy": {"login": "someone"}}))
    assert orch.gh_pr_state(PR1, run=run) == {
        "state": "MERGED", "mergedAt": "2026-11-04T09:00:00Z", "mergedBy": "someone"}
    assert seen == [["gh", "pr", "view", PR1, "--json", "state,mergedAt,mergedBy"]]
    assert orch.gh_pr_state(PR1, run=lambda a, **k: SimpleNamespace(
        returncode=1, stdout="")) is None
    assert orch.gh_pr_state(PR1, run=lambda a, **k: SimpleNamespace(
        returncode=0, stdout="nope")) is None


def test_a_started_closeout_is_written_before_the_tick_goes_on(tmp_path, monkeypatch):
    """CODE-1: a tick that fails after starting a close-out never starts a second."""
    import _batch
    mind, brief, home, sp = _shift(tmp_path)

    def boom(mind):
        raise OSError("injected")
    monkeypatch.setattr(_batch, "survey", boom)
    with pytest.raises(OSError):
        _tick(brief, mind, home, sp, 1)
    monkeypatch.undo()
    _tick(brief, mind, home, sp, 2)
    _tick(brief, mind, home, sp, 3)
    assert sp.closeouts == [("named", PR1)]
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][PR1]["state"] == "running" and c["sessions"] == 2


# --- the session and the Mind writer -------------------------------------------

def test_closeout_command_is_named_moded_and_on_the_closeout_model(tmp_path):
    argv = orch.closeout_command("t1", PR1, "draft/x/t1.md", tmp_path / "b.md",
                                 tmp_path / "leases", "auto")
    assert argv[:10] == ["claude", "--bg", "--name", "shift-close:t1", "--model", "opus",
                         "--effort", "medium", "--permission-mode", "auto"]
    prompt = argv[-1]
    assert PR1 in prompt and "run it yourself" in prompt
    assert str(tmp_path / "leases" / "t1.closeout") in prompt
    with pytest.raises(orch.OrchestratorError):
        orch.closeout_command("t1", PR1, "x", tmp_path, tmp_path, "bypassPermissions")


def test_the_worker_template_hands_glance_merges_to_the_closeout():
    tpl = (t.BATCH / "worker_template.md").read_text()
    assert "end at PR-open" in tpl and "independent close-out" in tpl


def test_table_append_keeps_what_follows_the_section():
    text = ("## A\n| x |\n|---|\n| 1 |\n\n" + orch.STAGE2_HEADING + " — opened\n\n"
            "| d |\n|---|\n\n## After\ntail\n")
    out = mw.table_append(text, orch.STAGE2_HEADING, "| 2 |")
    assert out.index("| 2 |") < out.index("## After") and out.count("| 2 |") == 1
    assert out.index("| 2 |") > out.index(orch.STAGE2_HEADING)
    with pytest.raises(mw.MindWriteError):
        mw.table_append("## Other\n", orch.STAGE2_HEADING, "| 2 |")


@pytest.mark.skipif(not t.LEDGER_MERGE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/ledger_merge.py")
def test_a_merged_closeout_lands_one_stage2_row_on_mind_main(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare = tmp_path / "remote.git"
    t.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    canon = tmp_path / "canon"
    t.git(tmp_path, "clone", "-q", str(bare), str(canon))
    t.git(canon, "config", "user.name", "Test")
    t.git(canon, "config", "user.email", "test@example.invalid")
    t._mind(canon)
    (canon / "scripts").mkdir()
    shutil.copy(t.LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    (canon / "autonomy_log.md").write_text(
        "# Log\n\n## Shadow window\n\n| a |\n|---|\n\n" + orch.STAGE2_HEADING
        + " — opened 2026-11-04\n\n| date | task | brief | gate | human action "
        "| merge actor | read by human |\n"
        "|---|---|---|---|---|---|---|\n\n## Later section\nkept\n")
    t.git(canon, "add", "-A")
    t.git(canon, "commit", "-q", "-m", "seed")
    t.git(canon, "push", "-q", "origin", "HEAD:main")

    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet=""))
    home, sp = tmp_path / "home", Spawner()
    orch.tick(brief, canon, home=home, now=t.NOW, spawner=sp, agents=Agents(),
              health=_health({}))
    _tick(brief, canon, home, sp, 1)
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="tests PASS",
             model="claude-opus-5-5")
    r = _tick(brief, canon, home, sp, 2)
    assert r["ledger"]["committed"], r
    log = t.git(bare, "show", "main:autonomy_log.md").stdout
    section = log[log.index(orch.STAGE2_HEADING):log.index("## Later section")]
    rows = [ln for ln in section.splitlines() if ln.startswith("| 2026-11-04 ")]
    assert len(rows) == 1 and "named (" + PR1 + ")" in rows[0]
    assert rows[0].endswith("| merged-unchanged | unattended-watcher |  |")
    assert log.rstrip().endswith("kept")


# --- PyAutoBrain#632: close-outs at review-at (F1) and the budget (F5) ------------

def _merged(at):
    return lambda url: {"state": "MERGED", "mergedAt": at, "mergedBy": "a-human"}


def test_no_closeout_starts_within_20_minutes_of_review_at(tmp_path):
    """F1: a close-out that ran past review-at merged outside the digest."""
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    r = _tick(brief, mind, home, sp, 135)          # 11:15, review-at 11:30
    assert r["closeouts"]["started"] == [] and sp.closeouts == []
    co = orch.read_counters(orch.slot_dir(brief, home))["closeouts"][PR1]
    assert co["state"] == "refused" and "within 20 min of review-at" in co["why"]


def test_a_closeout_out_at_review_at_is_reaped_counted_and_rowed_late(tmp_path):
    """F1: finish_shift reaps a close-out that ended before review-at; one
    still out keeps the late sweep running, and its merge is counted, its
    stage-2 row queued and a late line written — never lost from the ledger."""
    mind, brief, home, sp = _shift(tmp_path, cap=2)
    slot = orch.slot_dir(brief, home)
    _tick(brief, mind, home, sp, 1)                 # both close-outs start
    _verdict(home, brief, "named", result="merged", pr=PR1, gate="g", model="m")
    poster = t.Poster()
    r = orch.tick(brief, mind, home=home, now=t.AFTER, spawner=sp, agents=Agents(),
                  health=_health({}), poster=poster, pr_state=lambda u: (
                      _merged("2026-11-04T11:00:00Z")(u) if u == PR1 else
                      {"state": "OPEN", "mergedAt": "", "mergedBy": ""}))
    assert r["action"] == "digest"
    assert "- glance-auto-merges: 1" in poster.calls[0][1]          # reaped at review-at
    assert orch.closeouts_running(slot)                            # PR2's still out

    _verdict(home, brief, "picked", result="merged", pr=PR2, gate="g2", model="m")
    r = orch.tick(brief, mind, home=home, now=t.AFTER + _dt.timedelta(minutes=4),
                  spawner=sp, agents=Agents(), health=_health({}), poster=poster,
                  pr_state=_merged("2026-11-04T12:02:00Z"))
    assert r["action"] == "late", r
    assert any(f"close-out merged {PR2} unattended" in ln for ln in r["late"])
    c = orch.read_counters(slot)
    assert c["glance_auto_merges"] == 2 and c["closeouts"][PR2]["late"]
    assert c["github"][PR2]["in_window"] is False                  # merged after review-at
    rows = [json.loads(f.read_text()) for f in mw.pending_ops(slot)]
    assert sum(o["op"] == "table-append" and PR2 in o["row"] for o in rows) == 1
    assert not orch.closeouts_running(slot)
    assert not (slot / "leases" / "picked.closeout").exists()


def test_a_closeout_may_pass_the_budget_but_none_starts_at_one_and_a_half_times(tmp_path):
    """F5, the human's ruling 2026-11-14: over budget a close-out still starts
    (it counts against the budget); at 1.5x the budget none does."""
    for spent, started in ((1200, True), (1500, False)):
        mind, brief, home, sp = _shift(tmp_path / str(spent))     # token-budget: 1000
        slot = orch.slot_dir(brief, home)
        c = orch.read_counters(slot)
        c["usage"]["w1"] = {"kind": "worker", "task": "named", "total": spent, "final": True}
        orch._write_counters(slot, c)
        r = _tick(brief, mind, home, sp, 1)
        assert bool(r["closeouts"]["started"]) is started, (spent, r["closeouts"])
        if not started:
            co = orch.read_counters(slot)["closeouts"][PR1]
            assert "reached 1.5× token-budget 1000" in co["why"]


def test_the_closeout_ceiling_counts_reservations_and_holds_on_unread_usage(tmp_path):
    """#632 review (4): the 1.5x ceiling counts spend as the spawn gate does
    (`_committed_tokens`: a live session's reservation included), and an
    unreadable usage holds the start for a tick — it is never read as 0."""
    mind, brief, home, sp = _shift(tmp_path / "reserve")
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["usage"]["w1"] = {"kind": "worker", "task": "named", "total": 100, "reserve": 1600}
    orch._write_counters(slot, c)
    r = _tick(brief, mind, home, sp, 1)
    assert r["closeouts"]["started"] == []
    assert "1600 (committed) reached 1.5×" in orch.read_counters(slot)["closeouts"][PR1]["why"]

    mind, brief, home, sp = _shift(tmp_path / "unread", cap=2)
    r = _tick(brief, mind, home, sp, 1, health=_health({PR2: "RUNNING"}))
    assert r["closeouts"]["started"] == [PR1]
    # PR1's close-out usage cannot be read (no session id): PR2 waits a tick.
    r = _tick(brief, mind, home, sp, 2)
    assert r["closeouts"]["started"] == [] and r["closeouts"]["held"][0]["pr"] == PR2
    assert PR2 not in orch.read_counters(orch.slot_dir(brief, home))["closeouts"]


def test_the_digest_names_closeout_tokens_and_an_overrun():
    c = {"usage": {"w": {"kind": "worker", "total": 1000},
                   "co": {"kind": "closeout", "total": 400}}}
    v = _digest.counter_values({"token-budget": {"value": "1200"}}, c)
    assert v["tokens"] == "1400 of 1200 (close-outs 400; over budget by 200)"


# --- M3.6j (PyAutoBrain#683): a library's shift PRs merge in PR order ---------------------
# Two tasks of one shift on one library: `named` opened #7, `picked` #8. #8's
# close-out waits (no session, no slot, no refusal) while #7 is open; once #7
# merges, #8's branch is updated from main and merges only on CI green there.

GA7 = "https://github.com/example-org/autogalaxy/pull/7"
GA8 = "https://github.com/example-org/autogalaxy/pull/8"
GW9 = "https://github.com/example-org/example-docs/pull/9"
FIT8 = "https://github.com/example-org/autofit/pull/8"
SPAWNED = "2026-11-04T09:00:00Z"          # both workers start at the first tick


class OrderSpawner(t.FilesSpawner):
    """Workers that finished at once with library PRs open; every close-out
    or update session recorded with what it was told, verdicts by the test."""

    def __init__(self, picked=GA8):
        super().__init__(done={"named": GA7 + "\n", "picked": picked + "\n"}, proofs={})
        self.closeouts = []

    def spawn_closeout(self, task, pr_url, prompt_path, lease_dir, **kw):
        self.closeouts.append((task, pr_url, kw))
        return {"pid": 0, "agent_id": f"co{len(self.closeouts):06d}"}


def _gh_states(states):
    """`gh pr view`: OPEN unless named; a name may map to None (unreadable)."""
    def read(url):
        if url in states and states[url] is None:
            return None
        st = states.get(url, "OPEN")
        st, at = st if isinstance(st, tuple) else (st, "")
        return {"state": st, "mergedAt": at, "mergedBy": "a-maintainer" if at else ""}
    return read


def _order_shift(tmp_path, picked=GA8, cap=2):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="")
                     .replace("merge-cap: 1", f"merge-cap: {cap}"))
    home = tmp_path / "home"
    sp = OrderSpawner(picked)
    orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=Agents(),
              health=_health({}))
    return mind, brief, home, sp


def _otick(brief, mind, home, sp, minutes, states=None, health=None, agents=None):
    return orch.tick(brief, mind, home=home, now=t.NOW + _dt.timedelta(minutes=minutes),
                     spawner=sp, agents=agents or Agents(), health=health or _health({}),
                     pr_state=_gh_states(states or {}))


def _slots(brief, home):
    return orch._merge_slots.holders(orch.slot_dir(brief, home))


def _waiting(tmp_path):
    """#7's close-out refused (decision-taken), #7 still OPEN, #8 green."""
    mind, brief, home, sp = _order_shift(tmp_path)
    _otick(brief, mind, home, sp, 1)
    assert [(task, pr) for task, pr, _ in sp.closeouts] == [("named", GA7)]
    _verdict(home, brief, "named", result="refused", pr=GA7,
             why="decision-taken label → human /prm")
    r = _otick(brief, mind, home, sp, 2)
    return mind, brief, home, sp, r


def test_683_a_later_pr_waits_behind_an_earlier_refused_one_no_slot_no_refusal(tmp_path):
    mind, brief, home, sp, r = _waiting(tmp_path)
    assert r["closeouts"]["refused"] == [GA7]
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert GA8 not in c["closeouts"]                       # no close-out, not refused
    assert c["merge_waits"][GA8]["behind"] == [GA7]
    assert c["merge_waits"][GA8]["task"] == "picked"
    assert orch._merge_slots.pr_key(GA8) not in _slots(brief, home)
    assert [pr for _, pr, _ in sp.closeouts] == [GA7]
    r = _otick(brief, mind, home, sp, 3)                   # still waiting, still quiet
    assert r["closeouts"]["started"] == [] and r["closeouts"]["refused"] == []
    assert "waiting" not in r["closeouts"]                 # an event only when it changes


@pytest.mark.parametrize("picked, states, kw", [
    (FIT8, {}, {}),                                                 # another repo
    (GA8, {GA7: "CLOSED"}, {"before": [GA7]}),                      # closed unmerged
    (GA8, {GA7: ("MERGED", "2026-11-04T08:00:00Z")}, {"before": [GA7]}),  # before #8 began
])
def test_683_no_wait_on_another_repo_or_behind_a_merged_or_closed_pr(tmp_path, picked,
                                                                      states, kw):
    mind, brief, home, sp = _order_shift(tmp_path, picked)
    _otick(brief, mind, home, sp, 1, states)
    assert ("picked", picked, kw) in sp.closeouts, sp.closeouts
    assert picked not in orch.read_counters(orch.slot_dir(brief, home))["merge_waits"]


def test_683_an_earlier_pr_github_cannot_read_blocks(tmp_path):
    mind, brief, home, sp = _order_shift(tmp_path)
    _otick(brief, mind, home, sp, 1, {GA7: None})
    assert [pr for _, pr, _ in sp.closeouts] == [GA7]
    assert orch.read_counters(orch.slot_dir(brief, home))["merge_waits"][GA8]["behind"] == [GA7]


def _merged_then_update(tmp_path):
    """#7 merges after #8's worker began: #8 gets one branch-update session."""
    mind, brief, home, sp, _ = _waiting(tmp_path)
    states = {GA7: ("MERGED", "2026-11-04T09:30:00Z")}
    r = _otick(brief, mind, home, sp, 31, states)
    return mind, brief, home, sp, r, states


def test_683_once_the_earlier_pr_merged_after_it_began_the_branch_is_updated(tmp_path):
    mind, brief, home, sp, r, _ = _merged_then_update(tmp_path)
    assert sp.closeouts[-1] == ("picked", GA8, {"update_after": [GA7]})
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][GA8]["kind"] == "update" and c["merge_waits"] == {}
    assert orch._merge_slots.pr_key(GA8) in _slots(brief, home)   # taken before the update
    argv = orch.closeout_command("picked", GA8, "p.md", brief, home, "auto",
                                 update_after=[GA7])
    assert argv[argv.index("--name") + 1] == "shift-update:picked"
    assert f"gh pr update-branch {GA8}" in argv[-1] and GA7 in argv[-1]
    assert "Never `--rebase`, never a force-push" in argv[-1]


def _updated(tmp_path):
    mind, brief, home, sp, r, states = _merged_then_update(tmp_path)
    _verdict(home, brief, "picked", result="updated", pr=GA8, head="abc123")
    r = _otick(brief, mind, home, sp, 32, states, health=_health({GA8: "RUNNING"}))
    return mind, brief, home, sp, r, states


def test_683_an_updated_branch_holds_its_slot_and_waits_for_ci_on_the_new_head(tmp_path):
    mind, brief, home, sp, r, states = _updated(tmp_path)
    c = orch.read_counters(orch.slot_dir(brief, home))
    co = c["closeouts"][GA8]
    assert (co["state"], co["head"], co["updates"], co["after"]) == ("updated", "abc123", 1, [GA7])
    assert r["closeouts"]["merged"] == [] and r["closeouts"]["refused"] == []
    assert orch._merge_slots.pr_key(GA8) in _slots(brief, home)
    n = len(sp.closeouts)
    _otick(brief, mind, home, sp, 33, states, health=_health({GA8: "RUNNING"}))
    _otick(brief, mind, home, sp, 34, states, health=_health({GA8: "NO-CHECKS"}))  # in grace
    assert len(sp.closeouts) == n
    assert orch.read_counters(orch.slot_dir(brief, home))["closeouts"][GA8]["state"] == "updated"
    r = _otick(brief, mind, home, sp, 35, states)                                  # green
    assert r["closeouts"]["started"] == [GA8]
    assert sp.closeouts[-1] == ("picked", GA8, {"after": [GA7], "before": [GA7]})
    prompt = orch.closeout_prompt("picked", GA8, "p.md", brief, home, after=[GA7],
                                  before=[GA7])
    assert "4b. Merge order" in prompt and "branch not updated after <url>" in prompt
    assert f"   - {GA7}\n" in prompt and "still open → merge it first" in prompt
    assert "4b. Merge order" not in orch.closeout_prompt("picked", GA8, "p.md", brief, home)


def test_683_red_ci_on_the_updated_head_is_refused_and_frees_the_slot(tmp_path):
    mind, brief, home, sp, r, states = _updated(tmp_path)
    r = _otick(brief, mind, home, sp, 33, states, health=_health({GA8: "FAILED"}))
    assert r["closeouts"]["refused"] == [GA8]
    co = orch.read_counters(orch.slot_dir(brief, home))["closeouts"][GA8]
    assert co["why"] == "CI FAILED on the updated head → your /prm"
    assert orch._merge_slots.pr_key(GA8) not in _slots(brief, home)


def test_683_a_conflicting_update_is_refused_and_never_retried(tmp_path):
    mind, brief, home, sp, r, states = _merged_then_update(tmp_path)
    _verdict(home, brief, "picked", result="refused", pr=GA8,
             why=f"conflicts with main after {GA7} merged → your /prm")
    r = _otick(brief, mind, home, sp, 32, states)
    assert r["closeouts"]["refused"] == [GA8]
    assert orch._merge_slots.pr_key(GA8) not in _slots(brief, home)
    n = len(sp.closeouts)
    _otick(brief, mind, home, sp, 33, states)
    _otick(brief, mind, home, sp, 34, states)
    assert len(sp.closeouts) == n
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert "conflicts with main after" in d


def test_683_a_third_update_is_refused_main_kept_moving(tmp_path):
    mind, brief, home, sp, r, states = _updated(tmp_path)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    c["closeouts"][GA8].update(updates=orch.UPDATE_LIMIT, after=[])   # two updates used
    orch._write_counters(slot, c)
    n = len(sp.closeouts)
    r = _otick(brief, mind, home, sp, 33, states)
    assert r["closeouts"]["refused"] == [GA8] and len(sp.closeouts) == n
    co = orch.read_counters(slot)["closeouts"][GA8]
    assert co["why"].startswith("main kept moving") and co["why"].endswith("→ your /prm")
    assert orch._merge_slots.pr_key(GA8) not in _slots(brief, home)


def test_683_a_workspace_pr_waits_behind_its_own_tasks_waiting_library_pr(tmp_path):
    mind, brief, home, sp = _order_shift(tmp_path, picked=GA8 + "\n" + GW9)
    _otick(brief, mind, home, sp, 1)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["merge_waits"][GA8]["behind"] == [GA7]
    assert c["merge_waits"][GW9]["behind"] == [GA8]
    assert GW9 not in c["closeouts"] and [pr for _, pr, _ in sp.closeouts] == [GA7]


def test_683_a_wait_at_review_at_is_not_refused_and_the_digest_says_so(tmp_path):
    mind, brief, home, sp = _order_shift(tmp_path)
    r = _otick(brief, mind, home, sp, 140)                  # 11:20, review-at 11:30
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert GA8 not in c["closeouts"] and GA8 in c["merge_waits"]
    assert GA8 not in r["closeouts"]["refused"]
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert f"{GA8} — waits behind autogalaxy#7" in d or "waits behind autogalaxy#7" in d
    assert "merge autogalaxy#7 first" in d


def test_683_carry_in_carries_an_updated_or_waiting_pr_with_what_it_waited_behind(tmp_path):
    home = tmp_path / "home"
    prev = home / "2026-11-03-pm"
    prev.mkdir(parents=True)
    pick = {"prompt": "draft/feature/x/{}.md", "why": "named task", "tier": "glance"}
    (prev / orch.COUNTERS_FILE).write_text(json.dumps({
        "picks": {k: dict(pick, prompt=pick["prompt"].format(k)) for k in "abc"},
        "outcomes": {"a": {"prs": [GA7], "merged": [], "issues": []},
                     "b": {"prs": [GA8], "merged": [], "issues": []},
                     "c": {"prs": [FIT8], "merged": [], "issues": []}},
        "closeouts": {GA7: {"task": "a", "state": "refused",
                            "why": "decision-taken label → human /prm"},
                      FIT8: {"task": "c", "state": "updated", "after": [], "updates": 1}},
        "merge_waits": {GA8: {"task": "b", "behind": [GA7], "since": SPAWNED}},
        "parked": [], "done": ["a", "b", "c"]}))
    slot = home / "2026-11-04-am"
    slot.mkdir()
    c = {"outcomes": {}, "picks": {}, "done": []}
    rec = orch.carry_in(slot, c, t.NOW)
    assert sorted(rec["prs"]) == sorted([GA8, FIT8])        # never the refused #7
    assert c["outcomes"]["b"]["behind"] == [GA7]
    assert "behind" not in c["outcomes"]["c"]
    # In the new shift the carried #8 still waits behind the uncarried #7.
    c.update(closeouts={}, dropped={}, merge_waits={})
    assert orch._merge_blockers(c, GA8, _gh_states({}), {}) == [GA7]

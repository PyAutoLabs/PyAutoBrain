"""PyAutoBrain#610 (M1.5) Witness (3) and (4): the digest's counters come from
per-worker exits and GitHub, and every shift keeps one machine-readable row.

(3) a worker read as `killed` at its first tick is `spawned/crashed` and
counts in workers-crashed; a PR a human merged before `review-at:` counts in
merges; a `.done` written after the last live tick reaches the digest.
(4) `batches/pilot/pilot.jsonl` holds exactly one line per slot, written
through the one Mind writer; a late arrival amends that line (`amended`)
and never adds a second.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_dispatch as d  # noqa: E402 — the 3b fixtures
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
from test_orchestrator_dispatch import _brief, _digest, orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

NOW = d.NOW
AFTER = NOW + _dt.timedelta(hours=3)          # past review-at 11:30Z
PR = "https://github.com/o/r/pull/41"
ISSUE = t.ISSUE


def _later(minutes):
    return NOW + _dt.timedelta(minutes=minutes)


def _digest_of(brief, home):
    slot = orch.slot_dir(brief, home)
    return _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                         orch.read_counters(slot), health=t._health)


def _finish(brief, mind, home, now, agents=None, pr_state=None, poster=None):
    return orch.tick(brief, mind, home=home, now=now, grace_s=0, health=t._health,
                     agents=agents or orch.AgentsView([]), tokens=lambda s: 0,
                     poster=poster or t.Poster(), pr_state=pr_state or (lambda u: None))


# --- (3) exits and GitHub -------------------------------------------------------

def test_a_worker_killed_at_its_first_tick_is_spawned_crashed(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude, grace_s=3600)
    d._tick(brief, mind, home, _later(3), claude, agents=d._agents({"t1": "killed"}, slot),
            grace_s=3600)
    text = _digest_of(brief, home)
    assert "- workers-crashed: 1" in text
    workers = text.split(_digest.WORKERS_HEADING)[1]
    assert "(00000001): spawned/crashed" in workers
    assert "(00000002): spawned" in workers               # its one re-dispatch


def test_a_failed_launch_counts_once_however_often_it_is_retried(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    claude = d.FakeClaude(rc=1)
    for m in (0, 1, 2):
        d._tick(brief, mind, home, _later(m), claude)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert [w["exits"] for w in c["workers"]] == [["launch-failed"]]
    assert c["workers"][0]["attempts"] == 3
    assert _digest.counter_values({}, c)["workers-crashed"] == 1


def _one_pr_shift(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    (slot / "leases" / "t1.done").write_text(PR + "\n")
    d._tick(brief, mind, home, _later(5), claude, agents=d._agents({"t1": "done"}, slot))
    return mind, brief, home, slot


def test_a_pr_a_human_merged_before_review_at_counts_in_merges(tmp_path):
    mind, brief, home, slot = _one_pr_shift(tmp_path)
    asked = []

    def github(url):
        asked.append(url)
        return {"state": "MERGED", "mergedAt": "2026-11-04T10:00:00Z", "mergedBy": "a-human"}
    _finish(brief, mind, home, AFTER, pr_state=github)
    assert asked == [PR]
    text = (slot / orch.DIGEST_FILE).read_text()
    assert "- merges: 1" in text
    rec = _digest.pilot_record(slot.name, _brief.parse(brief.read_text())["brief"],
                               orch.read_counters(slot))
    assert rec["merged"] == [{"url": PR, "task": "t1", "mergedBy": "a-human", "actor": "unknown"}]


def test_a_pr_merged_after_review_at_is_not_this_shifts_merge(tmp_path):
    mind, brief, home, slot = _one_pr_shift(tmp_path)
    _finish(brief, mind, home, AFTER, pr_state=lambda u: {
        "state": "MERGED", "mergedAt": "2026-11-04T12:00:00Z", "mergedBy": "a-human"})
    assert "- merges: 0" in (slot / orch.DIGEST_FILE).read_text()


def test_a_done_written_after_the_last_tick_appears_in_the_digest(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    d._tick(brief, mind, home, _later(5), claude, agents=d._agents({"t1": "working"}, slot))
    (slot / "leases" / "t1.done").write_text(PR + "\n")       # after the last live tick
    r = _finish(brief, mind, home, AFTER, agents=d._agents({"t1": "done"}, slot))
    assert r["action"] == "digest"
    text = (slot / orch.DIGEST_FILE).read_text()
    assert f"{PR} — HEALTHY" in text and "the worker wrote no proof packet" in text
    assert "(00000001): spawned/finished" in text
    assert orch.leases(slot) == {}


# --- (4) one machine-readable row per shift ----------------------------------------

def test_jsonl_and_table_upserts_keep_one_row_per_key():
    text = mw.jsonl_upsert("", "slot", {"slot": "a", "amended": False, "n": 1})
    text = mw.jsonl_upsert(text, "slot", {"slot": "b", "amended": False})
    text = mw.jsonl_upsert(text, "slot", {"slot": "a", "amended": True})
    rows = [json.loads(x) for x in text.splitlines()]
    assert rows == [{"slot": "a", "amended": True, "n": 1}, {"slot": "b", "amended": False}]
    table = mw.table_upsert("", "a", "| a | 1 | ? |", "| slot | x | human |\n|---|---|---|\n")
    table = table.replace("| a | 1 | ? |", "| a | 1 | 7 |")            # the human fills in
    table = mw.table_upsert(table, "a", "| a | 2 | ? |")
    assert table.count("| a |") == 1 and "| a | 2 | 7 |" in table


@pytest.mark.skipif(not t.LEDGER_MERGE.is_file() or shutil.which("git") is None,
                    reason="needs git and PyAutoMind's scripts/ledger_merge.py")
def test_one_pilot_jsonl_line_per_shift_and_a_late_arrival_amends_it(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    bare = tmp_path / "remote.git"
    t.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    canon = tmp_path / "canon"
    t.git(tmp_path, "clone", "-q", str(bare), str(canon))
    t.git(canon, "config", "user.name", "Test")
    t.git(canon, "config", "user.email", "test@example.invalid")
    (canon / "scripts").mkdir()
    shutil.copy(t.LEDGER_MERGE, canon / "scripts" / "ledger_merge.py")
    folder = canon / "draft" / "feature" / "pyautobrain"
    folder.mkdir(parents=True)
    for n in ("t1", "t2"):
        (folder / f"{n}.md").write_text(d.PROMPT.format(name=n))
    (canon / "batches").mkdir()
    brief = canon / "batches" / "2026-11-04-am.md"
    tasks = "\n".join(f"    - draft/feature/pyautobrain/{n}.md" for n in ("t1", "t2"))
    brief.write_text(d.BRIEF.format(tasks=tasks, budget=100000, extra="")
                     .replace("- review-at: 2026-11-04T11:30Z\n",
                              f"- review-at: 2026-11-04T11:30Z\n- issue: {ISSUE}\n"))
    t.git(canon, "add", "-A")
    t.git(canon, "commit", "-q", "-m", "seed")
    t.git(canon, "push", "-q", "origin", "HEAD:main")

    home = tmp_path / "home"
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    usage = lambda s: {"total": 1000, "input": 900, "output": 100}  # noqa: E731
    d._tick(brief, canon, home, NOW, claude, tokens=usage)
    (slot / "leases" / "t1.done").write_text(PR + "\n")
    d._tick(brief, canon, home, _later(5), claude, tokens=usage,
            agents=d._agents({"t1": "done", "t2": "working"}, slot))
    poster = t.Poster()
    r = orch.tick(brief, canon, home=home, now=AFTER, grace_s=3600, poster=poster,
                  health=t._health, tokens=usage, pr_state=lambda u: None,
                  agents=d._agents({"t2": "working"}, slot))
    assert r["action"] == "digest" and r["ledger"]["committed"], r

    def pilot():
        lines = t.git(bare, "show", "main:batches/pilot/pilot.jsonl").stdout.splitlines()
        return [json.loads(x) for x in lines]
    rows = pilot()
    assert [x["slot"] for x in rows] == ["2026-11-04-am"] and rows[0]["amended"] is False
    assert rows[0]["mode"] == "live" and rows[0]["tokens"]["total"] == 2000   # never null
    assert rows[0]["tokens"]["input"] == 1800 and rows[0]["tokens"]["workers"] == 2000
    assert {w["exits"] for w in rows[0]["workers"]} == {"spawned/finished", "spawned"}

    # t2 finishes after review-at: the late sweep amends the one line.
    (slot / "leases" / "t2.done").write_text("https://github.com/o/r/pull/42\n")
    r = orch.tick(brief, canon, home=home, now=AFTER + _dt.timedelta(minutes=10), grace_s=0,
                  poster=poster, tokens=lambda s: {"total": 1500},
                  agents=d._agents({"t2": "done"}, slot))
    assert r["action"] == "late" and r["ledger"]["committed"], r
    rows = pilot()
    assert len(rows) == 1 and rows[0]["amended"] is True
    assert rows[0]["tokens"]["total"] == 2500
    assert "spawned/late/finished" in {w["exits"] for w in rows[0]["workers"]}
    md = t.git(bare, "show", "main:batches/pilot/pilot.md").stdout
    assert md.count("| 2026-11-04-am |") == 1 and md.count("| slot |") == 1
    # One digest comment, one correction comment — never a third.
    assert [body.split("\n")[0][:13] for _, body in poster.calls] == ["## Digest", "Late arrivals"]
    orch.tick(brief, canon, home=home, now=AFTER + _dt.timedelta(minutes=20), poster=poster)
    assert len(poster.calls) == 2


def test_the_digest_prints_each_spawn_refusal_with_its_reason(tmp_path):
    """#610 review item 2: a refusal is a digest fact, not only a tick-log line."""
    mind, brief, home = d._shift(tmp_path, names=("t1", "t2"), extra="  - max-workers: 1\n")
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    d._tick(brief, mind, home, _later(1), claude,
            agents=d._agents({"t1": "working"}, orch.slot_dir(brief, home)))
    text = _digest_of(brief, home)
    refusals = text.split(_digest.REFUSALS_HEADING)[1]
    assert ("- max-workers 1 reached — 1 task(s) waited: t2 — 2× from "
            "2026-11-04T09:00:00Z to 2026-11-04T09:01:00Z") in refusals


def test_refusals_are_one_entry_per_task_and_reason_class(tmp_path):
    """PyAutoBrain#632 (F3): a refusal repeated every tick is one entry with a
    count and first/last time; a token reason is keyed by its class, not the
    running figure; every max-workers refusal is one digest line."""
    c = {"refusals": []}
    for i, spent in enumerate((410000, 420000, 432999)):
        at = f"2026-11-16T13:0{i}:00Z"
        _digest.note_refusals(c, [
            {"task": "a", "why": f"token-budget 400000 spent ({spent})"},
            {"task": "b", "why": "max-workers 2 reached"},
            {"task": "x", "why": "max-workers 2 reached"}], at)
    assert len(c["refusals"]) == 3
    a = next(r for r in c["refusals"] if r["task"] == "a")
    assert (a["count"], a["at"], a["last"]) == (3, "2026-11-16T13:00:00Z",
                                                "2026-11-16T13:02:00Z")
    lines = _digest.refusal_lines(c)
    assert lines == [
        "- a — token-budget 400000 spent — 3× from 2026-11-16T13:00:00Z to "
        "2026-11-16T13:02:00Z (last: token-budget 400000 spent (432999))",
        "- max-workers 2 reached — 2 task(s) waited: b, x — 6× from "
        "2026-11-16T13:00:00Z to 2026-11-16T13:02:00Z"]
    # A slot recorded one entry per tick (before #632) folds into the same lines.
    old = {"refusals": [{"task": "a", "why": f"token-budget 400000 spent ({n})",
                         "at": f"2026-11-16T13:0{i}:00Z"} for i, n in enumerate((1, 2))]}
    assert len(_digest.refusal_lines(old)) == 1
    _digest.note_refusals(old, [{"task": "a", "why": "token-budget 400000 spent (3)"}],
                          "2026-11-16T13:05:00Z")
    assert len(old["refusals"]) == 2 and "3× from" in _digest.refusal_lines(old)[0]

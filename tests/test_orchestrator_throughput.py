"""M3.6c (PyAutoBrain#669): shift throughput.

Shift 2026-11-16-pm produced no stage-2 rows and idled twice: a late `glance`
PR no later shift picks up, an answered question that released its task only
to the next shift, and `max-sessions 8` stopping new starts with 2.3M tokens
unspent. Human decisions 2026-11-17 (PyAutoMind
`active/shift_throughput_carryover_and_order.md`): a bounded in-shift fetch; carry
over only `glance`/`notify` PRs never closed out or refused by the cutoff, from
the newest earlier slot; `first: glance` reorders; a 150k-token session floor.

One test group per Witness clause (1-4), on a fake clock; each fails on main
2ca1bd3. Fictional fixtures only.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_closeout as co  # noqa: E402 — the 4b close-out fixtures
import test_orchestrator_digest as t  # noqa: E402 — the 3d fixtures
import test_orchestrator_dispatch as d  # noqa: E402 — the real-spawner fixtures
from test_orchestrator_digest import _brief, orch  # noqa: E402
import _batch  # noqa: E402
import _questions  # noqa: E402
import _watch  # noqa: E402

NOW = d.NOW                       # 09:00Z; the d-fixture briefs end at 11:30Z
LATE = "https://github.com/o/r/pull/720"
CUT = "https://github.com/o/r/pull/721"
RED = "https://github.com/o/r/pull/722"
JUDGE = "https://github.com/o/r/pull/723"
Q1 = "https://github.com/example-org/widgets/issues/70"


# --- 1. carry-over at the first tick ---------------------------------------------------

def _previous_slot(home: Path, name="2026-11-03-pm") -> Path:
    """The last shift: a late glance PR, one refused by the cutoff, one refused
    for CI and a judge PR — only the first two carry over."""
    slot = home / name
    slot.mkdir(parents=True)
    pick = {"prompt": "draft/feature/pyautoheart/{}.md", "why": "named task", "tier": "glance",
            "title": "", "size": "small", "repos": ["pyautoheart"]}
    picks = {k: dict(pick, prompt=pick["prompt"].format(k)) for k in ("late", "cut", "red")}
    picks["big"] = dict(pick, prompt=pick["prompt"].format("big"), tier="judge")
    (slot / orch.COUNTERS_FILE).write_text(json.dumps({
        "picks": picks,
        "outcomes": {k: {"prs": [u], "merged": [], "issues": []}
                     for k, u in (("late", LATE), ("cut", CUT), ("red", RED), ("big", JUDGE))},
        "closeouts": {CUT: {"task": "cut", "state": "refused",
                            "why": f"green within {orch.CLOSEOUT_CUTOFF_S // 60} min of "
                                   "review-at — no close-out starts this late"},
                      RED: {"task": "red", "state": "refused",
                            "why": "CI FAILING — never merged unattended"},
                      JUDGE: {"task": "big", "state": "refused",
                              "why": "tier judge — never merged unattended → your /prm"}},
        "parked": [], "done": ["late", "cut", "red", "big"]}))
    return slot


class _OpenSpawner(co.Spawner):
    """GitHub reads every PR OPEN, except those named MERGED."""

    def __init__(self, merged=()):
        super().__init__()
        self.merged = set(merged)

    def pr_state(self, url):
        return {"state": "MERGED" if url in self.merged else "OPEN", "mergedAt": "",
                "mergedBy": ""}


def test_1_the_first_tick_closes_out_the_last_shifts_late_glance_prs(tmp_path):
    home = tmp_path / "home"
    _previous_slot(home)
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "2026-11-04-am.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="").replace("merge-cap: 1",
                                                                      "merge-cap: 4"))
    sp = _OpenSpawner()
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=co.Agents(),
                  health=co._health({}))
    assert {LATE, CUT} <= set(r["closeouts"]["started"]), r["closeouts"]
    assert RED not in r["closeouts"]["started"] and JUDGE not in r["closeouts"]["started"]
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["carried_in"]["from"] == "2026-11-03-pm"
    assert sorted(c["carried_in"]["prs"]) == [LATE, CUT]
    assert c["picks"]["late"]["why"].startswith("carried over from 2026-11-03-pm")
    # Once per shift: a later tick neither re-imports nor starts a second close-out.
    co._tick(brief, mind, home, sp, 1)
    co._tick(brief, mind, home, sp, 2)
    assert [p for _, p in sp.closeouts].count(LATE) == 1
    # The digest says what was carried, and from where.
    lines = t._digest.backlog_gate_lines(orch.read_counters(orch.slot_dir(brief, home)))
    assert any(ln.startswith("Carried over from 2026-11-03-pm: 2 late PR(s)") for ln in lines)


def test_1_a_released_task_is_admitted_whatever_the_brief_scope():
    """The first tick restarts a task whose question was answered: the answer
    is the human's word, as naming it would be, so `backlog: none` (or a scope
    that does not cover it) does not keep it out."""
    rec = {"path": "active/alpha.md", "lane": "any", "epic": "", "themes": [],
           "resume": {"ids": ["Q1"], "shift": "2026-11-03-pm"}}
    brief = {"backlog": {"value": "none"}, "lanes": {"value": "any", "children": []}}
    kept, rejected, _ = _brief.scope([rec], brief)
    assert kept == [rec] and rejected == []


# --- 2. in-shift restart: more than 30 minutes left -----------------------------------

def _parked_shift(tmp_path, monkeypatch, answered: bool = True):
    mind, brief, home = d._shift(tmp_path, names=("t1",))
    slot = orch.slot_dir(brief, home)
    claude = d.FakeClaude()
    d._tick(brief, mind, home, NOW, claude)
    (slot / "leases" / "t1.done").write_text(f"question: {Q1}\n")
    d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=5), claude,
            d._agents({"t1": "done"}, slot))
    assert "t1" in orch.read_counters(slot)["done"]
    inbox = {"t1": [{"id": "Q7", "shift": slot.name, "issue": Q1,
                     "state": "answered" if answered else "open",
                     "answered": "2026-11-04T09:20Z" if answered else "",
                     "answer": "(a) brass" if answered else "",
                     "comment": f"{Q1}#issuecomment-1" if answered else ""}]}
    monkeypatch.setattr(_questions, "read_origin", lambda *a, **k: inbox)
    return mind, brief, home, slot, claude


@pytest.mark.parametrize("left,restarts", [(31, True), (29, False)])
@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_2_an_answer_with_more_than_30_minutes_left_restarts_the_task(tmp_path, monkeypatch,
                                                                     left, restarts):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    r = d._tick(brief, mind, home, review_at - _dt.timedelta(minutes=left), claude)
    spawned = [s["task"] for s in r["spawned"]]
    assert spawned == (["t1"] if restarts else []), r
    if restarts:
        prompt = claude.calls[-1][0][-1]
        assert "parked on a question" in prompt and "Q7" in prompt
        c = orch.read_counters(slot)
        assert c["picks"]["t1"]["why"].startswith("resumed after Q7 was answered")
        # Used up: the next tick does not restart it again.
        r = d._tick(brief, mind, home, review_at - _dt.timedelta(minutes=left - 1), claude)
        assert r["spawned"] == []


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_2_an_open_question_restarts_nothing(tmp_path, monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch, answered=False)
    r = d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=30), claude)
    assert r["spawned"] == []


def test_2_the_fetch_repeats_only_for_an_open_park_and_at_most_every_10_minutes(tmp_path,
                                                                              monkeypatch):
    calls = []
    monkeypatch.setattr(orch._mind_writer, "fetch", lambda mind: calls.append(mind))
    counters = {"outcomes": {}, "done": [], "inshift_released": {}}
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    mind = Path("/nonexistent")
    orch._fetch_for_answers(mind, counters, NOW, review_at)            # the shift's one fetch
    orch._fetch_for_answers(mind, counters, NOW + _dt.timedelta(minutes=20), review_at)
    assert len(calls) == 1                                           # no open park: no more
    counters["outcomes"]["t1"] = {"questions": [Q1], "prs": [], "merged": []}
    orch._fetch_for_answers(mind, counters, NOW + _dt.timedelta(minutes=21), review_at)
    orch._fetch_for_answers(mind, counters, NOW + _dt.timedelta(minutes=25), review_at)
    assert len(calls) == 2                                           # then not within 10 min
    orch._fetch_for_answers(mind, counters, NOW + _dt.timedelta(minutes=32), review_at)
    assert len(calls) == 3
    late = review_at - _dt.timedelta(minutes=29)
    orch._fetch_for_answers(mind, counters, late, review_at)
    assert len(calls) == 3                                           # 30 min or less: never


# --- 3. `first: glance` ----------------------------------------------------------------

JUDGE_PROMPT = d.PROMPT.replace("Consequence: glance", "Consequence: judge")


def _ordered_shift(tmp_path, first: bool):
    mind, brief, home = d._shift(tmp_path, names=("j1", "j2", "g1"),
                                 extra="  - max-workers: 1\n"
                                       + ("  - first: glance\n" if first else ""))
    folder = mind / "draft" / "feature" / "pyautobrain"
    for n in ("j1", "j2"):
        (folder / f"{n}.md").write_text(JUDGE_PROMPT.format(name=n))
    return mind, brief, home


@pytest.mark.parametrize("first,expect", [(True, "g1"), (False, "j1")])
def test_3_first_glance_starts_ready_glance_work_before_named_judge_tasks(tmp_path, first,
                                                                         expect):
    mind, brief, home = _ordered_shift(tmp_path, first)
    r = d._tick(brief, mind, home, NOW, d.FakeClaude())
    assert [s["task"] for s in r["spawned"]] == [expect], r


def test_3_brief_check_takes_first_glance_and_refuses_anything_else(tmp_path):
    mind, brief, _ = _ordered_shift(tmp_path, True)
    assert _brief.check(brief, mind)["ok"]
    brief.write_text(brief.read_text().replace("first: glance", "first: notify"))
    res = _brief.check(brief, mind)
    assert not res["ok"] and any(e.startswith("brief.first:") for e in res["errors"])


# --- 4. a session cap from the token budget --------------------------------------------

def _caps(**kv) -> dict:
    return {k: {"value": str(v), "children": []} for k, v in kv.items()}


def test_4_no_max_sessions_derives_the_cap_from_budget_and_workers():
    assert _brief.cap_of(_caps(**{"token-budget": 5_000_000, "max-workers": 4}),
                         "max-sessions") == 34                   # ceil(5M / 150k)
    assert _brief.cap_of(_caps(**{"token-budget": 300_000, "max-workers": 4}),
                         "max-sessions") == 8                    # floor: 2 x max-workers
    assert _brief.cap_of(_caps(**{"token-budget": 5_000_000, "max-sessions": 8}),
                         "max-sessions") == 8                    # an explicit value wins
    assert _brief.cap_of({}, "max-sessions") == 8                # no budget: as before
    assert _brief.cap_source(_caps(**{"token-budget": 5_000_000}), "max-sessions") \
        == "from token-budget"


def test_4_the_snapshot_shows_the_derived_cap(tmp_path):
    mind, brief, home = d._shift(tmp_path, budget=5_000_000)
    d._tick(brief, mind, home, NOW, d.FakeClaude())
    snap = _watch.snapshot(brief, orch.slot_dir(brief, home), NOW)
    assert snap["budgets"]["sessions"] == "1 of 34 (from token-budget)", snap["budgets"]


def test_4_the_2026_11_16_pm_brief_never_refuses_on_sessions_under_half_its_budget(tmp_path):
    """Replayed: max-workers 4, token-budget 5M, no max-sessions; each worker
    spends what that shift's eight did on average (2.63M / 8)."""
    names = tuple(f"w{i:02d}" for i in range(16))
    mind, brief, home = d._shift(tmp_path, names=names, budget=5_000_000,
                                 extra="  - max-workers: 4\n")
    slot = orch.slot_dir(brief, home)
    claude, spend = d.FakeClaude(), 2_630_539 // 8
    tokens = lambda sid: spend                                  # noqa: E731
    now = NOW
    for _ in range(12):
        r = d._tick(brief, mind, home, now, claude, tokens=tokens,
                    agents=d._agents({n: "done" for n in names}, slot))
        c = orch.read_counters(slot)
        if c["tokens"] < 5_000_000 // 2:
            assert not any(x["why"].startswith("max-sessions") for x in r["refused"]), r
        for task in orch.leases(slot):
            (slot / "leases" / f"{task}.done").write_text("https://github.com/o/r/pull/1\n")
        now += _dt.timedelta(minutes=5)
    assert orch.read_counters(slot)["sessions"] > 8      # past the old cap


# --- review fixes (Fable 5.2) ----------------------------------------------------------

def _carry_shift(tmp_path, prev_extra: dict, merged=()):
    home = tmp_path / "home"
    prev = _previous_slot(home)
    c = json.loads((prev / orch.COUNTERS_FILE).read_text())
    for k, v in prev_extra.items():
        c.setdefault(k, {}).update(v)
    (prev / orch.COUNTERS_FILE).write_text(json.dumps(c))
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "2026-11-04-am.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="").replace("merge-cap: 1",
                                                                      "merge-cap: 4"))
    sp = _OpenSpawner(merged)
    r = orch.tick(brief, mind, home=home, now=t.NOW, spawner=sp, agents=co.Agents(),
                  health=co._health({}))
    return r, orch.read_counters(orch.slot_dir(brief, home))


def test_review_a_carried_pr_the_human_merged_since_is_not_closed_out(tmp_path):
    r, c = _carry_shift(tmp_path, {}, merged=(LATE,))
    assert LATE not in r["closeouts"]["started"] and CUT in r["closeouts"]["started"]
    assert c["closeouts"][LATE]["why"].endswith("GitHub reads it MERGED — not closed out")
    assert c.get("glance_auto_merges", 0) == 0


def test_review_a_question_parked_tasks_pr_is_not_carried(tmp_path):
    r, c = _carry_shift(tmp_path, {"outcomes": {"late": {"prs": [LATE], "merged": [],
                                                         "questions": [Q1]}}})
    assert LATE not in c["carried_in"]["prs"] and "late" not in c["outcomes"]


def test_review_an_undated_or_empty_newest_slot_does_not_hide_the_last_real_one(tmp_path):
    home = tmp_path / "home"
    _previous_slot(home)
    for name in ("2026-11-04-aa", "2026-11-03-zz"):          # a shadow/empty slot
        (home / name).mkdir()
        (home / name / orch.COUNTERS_FILE).write_text(json.dumps({"picks": {"x": {}}}))
    slot = home / "2026-11-04-am"
    slot.mkdir()
    c = {"outcomes": {}, "picks": {}, "done": []}
    assert orch.carry_in(slot, c, NOW)["from"] == "2026-11-03-pm"
    undated = home / "shift"
    undated.mkdir()
    assert orch.carry_in(undated, {"outcomes": {}, "picks": {}, "done": []}, NOW)["prs"] == []


def test_review_the_first_tick_restarts_a_task_answered_since_the_last_shift(tmp_path,
                                                                           monkeypatch):
    """Witness clause 1, second half, by a tick: `backlog: none`, the task not
    named, and still restarted with the human's answer."""
    mind, brief, home = d._shift(tmp_path, names=("t0",))
    (mind / "draft" / "feature" / "pyautobrain" / "t1.md").write_text(d.PROMPT.format(name="t1"))
    prev = home / "2026-11-03-pm"
    prev.mkdir(parents=True)
    (prev / orch.COUNTERS_FILE).write_text(json.dumps({
        "outcomes": {"t1": {"questions": [Q1], "prs": [], "merged": []}}, "parked": [],
        "picks": {"t1": {"prompt": "draft/feature/pyautobrain/t1.md"}}}))
    monkeypatch.setattr(_questions, "read_origin", lambda *a, **k: {"t1": [
        {"id": "Q3", "shift": "2026-11-03-pm", "issue": Q1, "state": "answered",
         "answered": "2026-11-03T22:00Z", "answer": "yes", "comment": ""}]})
    claude = d.FakeClaude()
    r = d._tick(brief, mind, home, NOW, claude)
    assert sorted(s["task"] for s in r["spawned"]) == ["t0", "t1"], r
    prompt = next(c[0][-1] for c in claude.calls if "shift:t1" in c[0])
    assert "parked on a question" in prompt and "Q3" in prompt


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_review_a_release_refused_one_tick_still_resumes_the_next(tmp_path, monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    (mind / "draft" / "feature" / "pyautobrain" / "t2.md").write_text(d.PROMPT.format(name="t2"))
    brief.write_text(brief.read_text().replace(
        "    - draft/feature/pyautobrain/t1.md",
        "    - draft/feature/pyautobrain/t2.md\n    - draft/feature/pyautobrain/t1.md")
        + "  - max-workers: 1\n  - max-sessions: 8\n")
    r = d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=30), claude)
    assert [s["task"] for s in r["spawned"]] == ["t2"]            # t1 held by max-workers
    c = orch.read_counters(slot)
    assert "t1" in c["outcomes"] and "t1" in c["inshift_pending"]  # the park is kept
    (slot / "leases" / "t2.done").write_text("https://github.com/o/r/pull/9\n")
    r = d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=40), claude,
                d._agents({"t2": "done"}, slot))
    assert [s["task"] for s in r["spawned"]] == ["t1"], r
    prompt = claude.calls[-1][0][-1]
    assert "parked on a question" in prompt and "Q7" in prompt


def test_review_a_release_that_never_spawns_leaves_the_park_for_the_next_shift(tmp_path,
                                                                              monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    monkeypatch.setattr(orch, "INSHIFT_RESTART_S", 10**6)        # never in time
    d._tick(brief, mind, home, review_at - _dt.timedelta(minutes=40), claude)
    c = orch.read_counters(slot)
    assert "t1" in c["outcomes"] and c["outcomes"]["t1"]["questions"]
    resumes = {}
    nxt = home / "2026-11-05-am"
    nxt.mkdir()
    orch.parked_elsewhere(nxt, {"t1": [{"id": "Q7", "shift": slot.name, "state": "answered",
                                        "answered": "x", "answer": "y", "comment": ""}]},
                          resumes)
    assert "t1" in resumes


def test_review_first_glance_reorders_but_selects_the_same_tasks():
    def r(path, tier, minutes):
        return {"path": path, "repos": [], "work_type": "feature", "difficulty": "small",
                "score": 1, "consequence": tier, "witness": "w", "review_minutes": minutes,
                "unattended": "ready", "why": "", "ready_why": [], "epic": "", "lane": "any",
                "priority": "normal", "blocked": False, "autonomy": "safe",
                "autonomy_cap": "safe", "declared_autonomy": "safe", "done": False,
                "phase": float("inf")}
    recs = [r("j1.md", "judge", 40)] + [r(f"g{i}.md", "glance", 5) for i in (1, 2, 3)]
    base = {"backlog": {"value": "fill-idle", "children": []},
            "lanes": {"value": "any", "children": []},
            "tasks": {"value": "", "children": [{"text": "j1.md"}]},
            "review-minutes": {"value": "45", "children": []}}
    a = _batch.plan(recs, brief=base, queue=["x"])
    b = _batch.plan(recs, brief=dict(base, first={"value": "glance", "children": []}),
                    queue=["x"])
    assert [m["path"] for m in a["members"]] == [m["path"] for m in b["members"]]


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_review_once_per_answer_a_new_answered_question_restarts_again(tmp_path, monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    r = d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=20), claude)
    assert [s["task"] for s in r["spawned"]] == ["t1"]
    (slot / "leases" / "t1.done").write_text(f"question: {Q1}\n")      # parks again
    d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=25), claude,
            d._agents({"t1": "done"}, slot))
    entry = {"shift": slot.name, "issue": Q1, "state": "answered", "answered": "x",
             "answer": "y", "comment": ""}
    monkeypatch.setattr(_questions, "read_origin", lambda *a, **k: {"t1": [
        dict(entry, id="Q7"), dict(entry, id="Q8")]})
    r = d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=40), claude)
    assert [s["task"] for s in r["spawned"]] == ["t1"], r
    assert "Q8" in claude.calls[-1][0][-1]
    assert [x["ids"] for x in orch.read_counters(slot)["inshift_released"]["t1"]] == \
        [["Q7"], ["Q8"]]


def test_review2_a_dropped_tasks_late_pr_is_not_carried(tmp_path):
    r, c = _carry_shift(tmp_path, {"dropped": {"late": {"at": "2026-11-03T18:00Z"}}})
    assert LATE not in c["carried_in"]["prs"] and LATE not in r["closeouts"]["started"]


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_review2_a_pending_release_clears_at_30_minutes_and_the_park_stays(tmp_path,
                                                                         monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    (mind / "draft" / "feature" / "pyautobrain" / "t2.md").write_text(d.PROMPT.format(name="t2"))
    brief.write_text(brief.read_text().replace(
        "    - draft/feature/pyautobrain/t1.md",
        "    - draft/feature/pyautobrain/t2.md\n    - draft/feature/pyautobrain/t1.md")
        + "  - max-workers: 1\n  - max-sessions: 8\n")
    review_at = _dt.datetime(2026, 11, 4, 11, 30, tzinfo=_dt.timezone.utc)
    d._tick(brief, mind, home, review_at - _dt.timedelta(minutes=40), claude)
    assert "t1" in orch.read_counters(slot)["inshift_pending"]
    r = d._tick(brief, mind, home, review_at - _dt.timedelta(minutes=29), claude)
    c = orch.read_counters(slot)
    assert r["spawned"] == [] and c["inshift_pending"] == {}
    assert c["outcomes"]["t1"]["questions"] and "t1" in c["done"]


@pytest.mark.usefixtures("shift_held_open")   # M3.7c: no early close
def test_review2_the_digest_names_an_in_shift_restart(tmp_path, monkeypatch):
    mind, brief, home, slot, claude = _parked_shift(tmp_path, monkeypatch)
    d._tick(brief, mind, home, NOW + _dt.timedelta(minutes=20), claude)
    lines = t._digest.backlog_gate_lines(orch.read_counters(slot))
    assert "Restarted in-shift after an answer: 1 task(s) — `t1` (Q7)" in lines

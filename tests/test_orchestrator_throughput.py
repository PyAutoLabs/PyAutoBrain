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


def test_1_the_first_tick_closes_out_the_last_shifts_late_glance_prs(tmp_path):
    home = tmp_path / "home"
    _previous_slot(home)
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "2026-11-04-am.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="").replace("merge-cap: 1",
                                                                      "merge-cap: 4"))
    sp = co.Spawner()
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

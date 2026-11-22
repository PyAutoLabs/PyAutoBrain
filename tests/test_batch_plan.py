"""tests/test_batch_plan.py — the Batch Agent's composition rules.

The planner's whole job is refusing things for stated reasons, so every test
here is a refusal (or the one case that must never be refused: zero-cost fill
under full backpressure).
"""

from __future__ import annotations


from _shift_fixtures import _batch  # noqa: E402


def rec(path, *, minutes=20, tier="judge", ready="ready", repos=(), epic="",
        lane="any", blocked=False, priority="normal", autonomy="safe",
        done=False, phase=float("inf")):
    return {"path": path, "repos": list(repos), "work_type": "feature",
            "difficulty": "medium", "score": 4, "consequence": tier,
            "witness": None, "review_minutes": minutes, "unattended": ready,
            "why": "", "ready_why": [], "epic": epic, "lane": lane,
            "priority": priority, "blocked": blocked, "autonomy": autonomy,
            "autonomy_cap": "safe", "declared_autonomy": autonomy,
            "done": done, "phase": phase}


def paths(d):
    return [m["path"] for m in d["members"]]


def why(d, path):
    return next(w for p, w in d["rejected"] if p == path)


def test_the_budget_is_review_minutes_not_a_task_count():
    """Three 20-minute tasks do not fit a 45-minute slot, however small they
    look by any other measure."""
    d = _batch.plan([rec(f"{i}.md") for i in "abc"], budget=45)
    assert len(d["members"]) == 2
    assert d["review_minutes_planned"] == 40
    assert "exceed the budget" in why(d, "c.md")


def test_notify_tier_work_costs_the_human_nothing():
    """The fill. It is capped by the token allowance, not by the human's hour,
    which is what lets the allowance be spent without growing the queue."""
    d = _batch.plan([rec(f"{i}.md", tier="notify", minutes=0) for i in range(9)],
                    budget=45)
    assert len(d["members"]) == 9
    assert d["review_minutes_planned"] == 0


def test_one_member_per_library_repo_per_shift():
    """They do not collide at dispatch — separate worktrees — they collide at
    merge, when the first /prm moves main and invalidates the rest. A library
    is held only while its worker runs (M3.6j, #683); merges wait in order."""
    d = _batch.plan([rec("a.md", repos=["autoarray"]),
                     rec("b.md", repos=["autoarray"])], budget=100)
    assert paths(d) == ["a.md"]
    assert "autoarray held by a while its worker runs" in why(d, "b.md")


def test_a_released_member_holds_no_library():
    """PyAutoBrain#679: a pick whose PR merged collides with nothing at merge,
    so the next task on its library is admitted; it stays a member."""
    two = [rec("a.md", repos=["autoarray"]), rec("b.md", repos=["autoarray"])]
    d = _batch.plan(two, budget=100, released={"a"})
    assert paths(d) == ["a.md", "b.md"]
    assert paths(_batch.plan(two, budget=100, released={"b"})) == ["a.md"]


def test_non_library_repos_do_not_claim_a_shift():
    """Two docs changes to the same organ repo cost nothing to merge together."""
    d = _batch.plan([rec("a.md", repos=["pyautomind"]),
                     rec("b.md", repos=["pyautomind"])], budget=100)
    assert paths(d) == ["a.md", "b.md"]


def test_one_slice_per_epic():
    """One `Phase:` task per epic (ruling R5, 2026-11-17); a side task with no
    `Phase:` is not counted (tests/test_batch_named_tasks.py)."""
    d = _batch.plan([rec("a.md", epic="euclid", phase=2), rec("b.md", epic="euclid", phase=2)],
                    budget=100)
    assert paths(d) == ["a.md"]
    assert "epic euclid already" in why(d, "b.md")


def test_a_session_never_plans_the_other_lane_but_reports_it():
    """Silently dropping it would leave the human unable to tell 'nothing ready'
    from 'nothing I can run from here'."""
    d = _batch.plan([rec("a.md", lane="local-dev")], session_lane="web-github")
    assert d["members"] == []
    assert d["other_lane_ready"] == 1
    d2 = _batch.plan([rec("a.md", lane="local-dev")], session_lane="local-dev")
    assert paths(d2) == ["a.md"]


def test_only_unattended_ready_work_is_selected():
    d = _batch.plan([rec("a.md", ready="needs-slicing"),
                     rec("b.md", ready="never"),
                     rec("c.md", blocked=True)], budget=100)
    assert d["members"] == []
    assert "needs-slicing" in why(d, "a.md")
    assert "Blocked-by" in why(d, "c.md")


def test_backpressure_ramps_rather_than_cliffs():
    pool = [rec(f"{i}.md") for i in range(6)]
    assert _batch.plan(pool, budget=60, awaiting_review=0)["effective_budget"] == 60
    assert _batch.plan(pool, budget=60, awaiting_review=6)["effective_budget"] == 30
    assert _batch.plan(pool, budget=60, awaiting_review=8)["effective_budget"] == 0


def test_at_the_cap_the_batch_is_fill_only_and_still_composes():
    """Backpressure measures review-queue depth, not the human's timing. At the
    cap the review-bearing half is zero — but zero-cost work still composes, and
    the human still dispatches it."""
    d = _batch.plan([rec("a.md"), rec("b.md", tier="notify", minutes=0)],
                    budget=60, awaiting_review=99)
    assert paths(d) == ["b.md"]


def test_priority_sorts_before_review_minutes():
    """M2.3 (2026-11-12): below the queue a declared `Priority:` outranks cost.
    Cheapest-first let the cheapest review win and broke ties by filename."""
    d = _batch.plan([rec("slow.md", minutes=20, priority="high"),
                     rec("fast.md", minutes=2, priority="low")], budget=45)
    assert paths(d) == ["slow.md", "fast.md"]


def test_cheapest_first_still_decides_within_a_priority():
    d = _batch.plan([rec("a_slow.md", minutes=20), rec("b_fast.md", minutes=2)],
                    budget=45)
    assert paths(d) == ["b_fast.md", "a_slow.md"]


def test_every_rejection_states_a_reason():
    d = _batch.plan([rec("a.md"), rec("b.md"), rec("c.md")], budget=20)
    assert d["rejected"]
    assert all(isinstance(w, str) and w for _, w in d["rejected"])


def test_lane_detection_reads_the_environment_not_a_flag():
    """A session that could be told where it is could plan local-dev work it
    cannot run. Probed from `gh`, the same signal the organism already uses."""
    assert _batch.detect_lane() in ("local-dev", "web-github")


def test_human_required_work_is_never_dispatched():
    """Readiness says the work FITS one run; autonomy says the run may FINISH
    it. Under `--auto` a `supervised` run's ship checkpoint resolves to
    decide-and-flag rather than parking (AUTONOMY.md, "Decide-and-flag",
    extended 2026-09-07), so it finishes at an open PR and belongs in the pool.
    Only `human-required` would still stop at the ship checkpoint and come back
    as a question — which is the failure the epic exists to remove."""
    d = _batch.plan([rec("a.md", autonomy="safe"),
                     rec("b.md", autonomy="supervised"),
                     rec("c.md", autonomy="human-required")], budget=100)
    assert sorted(paths(d)) == ["a.md", "b.md"]
    assert "would park at ship" in why(d, "c.md")
    assert "human-required" in why(d, "c.md")


def test_a_prompt_that_says_it_is_done_is_never_dispatched():
    """A session that ships the work and writes the outcome into `Status:` but
    leaves the file in draft/ is a recorded failure mode; the file keeps
    rendering as pickable backlog. Dispatching one wastes a whole shift
    re-doing finished work."""
    d = _batch.plan([rec("a.md", done=True), rec("b.md")], budget=100)
    assert paths(d) == ["b.md"]
    assert "already done" in why(d, "a.md")


def test_an_epic_offers_only_its_next_phase():
    """Members are worked in order. One-slice-per-epic caps how many run; this
    decides WHICH — without it the planner can propose phase 6 while phase 3 is
    still open."""
    d = _batch.plan([rec("late.md", epic="euclid", phase=6),
                     rec("next.md", epic="euclid", phase=3)], budget=100)
    assert paths(d) == ["next.md"]
    assert "is not next" in why(d, "late.md")


def test_a_shipped_phase_does_not_block_the_one_after_it():
    d = _batch.plan([rec("done.md", epic="e", phase=1, done=True),
                     rec("next.md", epic="e", phase=2)], budget=100)
    assert paths(d) == ["next.md"]


def test_dispatch_payloads_carry_no_decisions():
    """The launch is the human's act, so what they perform should carry nothing
    still to be decided — everything was decided when they approved the batch."""
    d = _batch.plan([rec("draft/x/y/z.md")], budget=100)
    assert d["dispatch"] == ["Use the start-dev skill. draft/x/y/z.md --auto"]


# ------------------------------------------------- the derived review queue --
ACTIVE_MD = """# Active Tasks

## shipped-with-a-pr-key
- prompt: active/one.md
- status: library-shipped, awaiting-merge
- library-pr: https://github.com/ExampleOrg/ExampleFit/pull/1554

## shipped-before-the-pr-keys-existed
- prompt: active/two.md
- status: workspace-shipped, PR open (waiting on the library)

## two-prs-is-still-one-task
- prompt: active/three.md
- status: library-shipped, awaiting-merge
- library-pr: https://github.com/ExampleOrg/ExampleFit/pull/1555
- workspace-pr: https://github.com/ExampleOrg/ExampleWorkspace/pull/22

## still-being-written
- prompt: active/four.md
- status: library-dev
"""


def test_the_review_queue_depth_is_derived_from_active_md(tmp_path):
    """The backpressure input used to default to 0 and was never derived, so
    every plan composed a shift as though nothing were waiting. A row counts
    once, whether it names one PR or two, and whether it says so with the PR
    keys or in words."""
    (tmp_path / "active.md").write_text(ACTIVE_MD, encoding="utf-8")
    assert _batch.derive_awaiting_review(tmp_path) == 3


def test_a_row_with_no_pr_and_no_shipped_status_is_not_awaiting_review(tmp_path):
    (tmp_path / "active.md").write_text(
        "# Active Tasks\n\n## writing\n- status: library-dev\n", encoding="utf-8")
    assert _batch.derive_awaiting_review(tmp_path) == 0


def test_a_mind_with_no_active_md_derives_zero(tmp_path):
    """A missing registry is an empty queue, not a crash: `plan` must still
    compose in a checkout that has not got one."""
    assert _batch.derive_awaiting_review(tmp_path) == 0


# ----------------------------------------------------------- queue.md order --
QUEUE_MD = """# Queue

```markdown
## <n>. <label>
- kind: prompt | epic-slice | theme-sweep
- ref: draft/<work-type>/<target>/<name>.md    # kind: prompt
```

## 1. The thing I want first
- kind: prompt
- ref: draft/feature/example/slow.md
- note: the human's own words

## 2. Already shipped
- kind: retired
- ref: draft/feature/example/gone.md

## 3. Any ready chip on this theme
- kind: theme-sweep
- ref: numba-cpu

## 4. The thing I want second
- kind: prompt
- ref: draft/feature/example/fast.md
"""


def test_read_queue_keeps_prompt_entries_in_file_order(tmp_path):
    """And skips the schema example inside the fenced block, the retired
    entries and the kinds that name an epic or a theme rather than a file."""
    (tmp_path / "queue.md").write_text(QUEUE_MD, encoding="utf-8")
    assert _batch.read_queue(tmp_path) == ["draft/feature/example/slow.md",
                                           "draft/feature/example/fast.md"]


def test_a_missing_queue_is_no_queue_not_a_crash(tmp_path):
    assert _batch.read_queue(tmp_path) == []


def test_the_queue_outranks_cheapest_first():
    """`queue.md` is the human's statement of importance and the only one the
    planner has. Order is priority: the expensive queued task goes first, and
    the cheap unqueued one waits."""
    d = _batch.plan([rec("draft/feature/example/slow.md", minutes=20),
                     rec("draft/feature/example/fast.md", minutes=2)],
                    budget=45, queue=["draft/feature/example/slow.md"])
    assert paths(d) == ["draft/feature/example/slow.md",
                        "draft/feature/example/fast.md"]


def test_among_queued_prompts_the_file_order_wins():
    d = _batch.plan([rec("a.md", minutes=2), rec("b.md", minutes=20)],
                    budget=45, queue=["b.md", "a.md"])
    assert paths(d) == ["b.md", "a.md"]


def test_a_queue_entry_still_matches_its_prompt_after_it_is_issued():
    """The entry is written against `draft/…` and the prompt moves to
    `active/` the moment it is issued. An entry that stopped matching would
    silently lose its priority rather than report anything."""
    d = _batch.plan([rec("active/slow.md", minutes=20),
                     rec("draft/x/fast.md", minutes=2)],
                    budget=45, queue=["draft/x/slow.md"])
    assert paths(d)[0] == "active/slow.md"


def test_the_decision_says_where_the_review_queue_number_came_from():
    d = _batch.plan([rec("a.md")], budget=45, awaiting_review=2,
                    awaiting_source="--awaiting-review")
    assert d["backpressure"]["source"] == "--awaiting-review"
    assert d["backpressure"]["awaiting_review"] == 2


def test_carried_members_are_reported_to_the_next_plan():
    """A carried member is already costing the human review-minutes in the
    slot being planned; a batch composed as though it were not is over-sold by
    exactly that much."""
    d = _batch.plan([rec("a.md")], budget=45, carried=["subhalo-wave"],
                    carried_from="2026-09-03-pm")
    assert d["carried"] == ["subhalo-wave"]
    assert d["carried_from"] == "2026-09-03-pm"


# ------------------------------------- a queued epic queues its phases (#696) --
EPIC_BRIEF = """# Batch 2026-11-20 am
- dispatched: 2026-11-20T08:00Z
- review-at: 2026-11-20T12:00Z
- brief:
  - goals:
    - 1. drive the queued epics
  - backlog: scoped
  - scoped:
    - epics: lib
    - tiers: notify, glance
  - review-minutes: 200
  - lanes: any local-dev ral
  - merge-cap: 0
  - token-budget: 5000000
"""
LEDGER = "draft/feature/lib/lib_epic.md"


def _brief_of(text=EPIC_BRIEF):
    return _batch._brief.parse(text)["brief"]


def ledger(path=LEDGER, epic="lib"):
    r = rec(path, epic=epic, autonomy="human-required")
    r.update(ledger=bool(epic), phase_declared=False, witness="the map")
    return r


def member(path, phase, *, epic="lib", repos=("autofit", "autolens"), **kw):
    r = rec(path, epic=epic, phase=phase, repos=repos, **kw)
    r.update(phase_declared=True, witness="a fixture passes")
    return r


def test_a_queued_epic_ledger_queues_its_medium_multi_repo_phase():
    """Ruling 2026-11-16 narrowed (#696): the human queuing an epic ledger is
    the human queuing its phases. The medium 2-repo next phase is taken at the
    ledger's rank, with no scoped-reach rejection."""
    other = rec("draft/x/queued_first.md", repos=["autoarray"])
    other["witness"] = "w"
    d = _batch.plan([ledger(), member("draft/feature/lib/p5c.md", 5), other],
                    budget=200, session_lane="local-dev", brief=_brief_of(),
                    queue=["draft/x/queued_first.md", LEDGER])
    assert "draft/feature/lib/p5c.md" in paths(d)
    m = next(m for m in d["members"] if m["path"] == "draft/feature/lib/p5c.md")
    assert m["queue_rank"] == 1 and m["queued"] and m["queued_via"] == "lib"
    assert d["scoped_reach"] == []
    assert "via epic lib" in _batch._brief.rank_note(m)
    assert [e["line"] for e in d["queued_epics"]] == ["lib (q2): takes p5c"]


def test_an_unqueued_epic_member_is_still_held_to_the_reach_ruling():
    d = _batch.plan([ledger(), member("draft/feature/lib/p5c.md", 5)],
                    budget=200, session_lane="local-dev", brief=_brief_of(), queue=["x.md"])
    assert "the human queues bigger work" in why(d, "draft/feature/lib/p5c.md")


def test_a_queued_epic_still_offers_only_its_next_phase():
    d = _batch.plan([ledger(), member("draft/feature/lib/p5.md", 5),
                     member("draft/feature/lib/p6.md", 6)],
                    budget=200, session_lane="local-dev", brief=_brief_of(), queue=[LEDGER])
    assert paths(d) == ["draft/feature/lib/p5.md"]
    assert why(d, "draft/feature/lib/p6.md") == "epic lib phase 6 is not next"
    # The ledger itself is never a member: it is human-required.
    assert "human-required" in why(d, LEDGER)


def test_epics_md_maps_a_ledger_whose_epic_header_was_not_read(tmp_path):
    (tmp_path / "epics.md").write_text(
        "# Epics\n\n## lib\n- title: L\n- ledger: draft/feature/lib/lib_epic.md\n"
        "## web\n- ledger: https://example.invalid/x.md\n", encoding="utf-8")
    ledgers = _batch.read_epic_ledgers(tmp_path)
    assert ledgers == {LEDGER: "lib"}
    plain = ledger(epic="")
    assert _batch.queued_epics([LEDGER], [plain], ledgers) == {"lib": 0}
    assert _batch.queued_epics([LEDGER], [plain]) == {}
    # A queued phase prompt queues only itself, not its epic.
    assert _batch.queued_epics(["draft/feature/lib/p5.md"],
                               [member("draft/feature/lib/p5.md", 5)]) == {}


def test_a_queued_epic_with_no_draft_phase_says_to_file_one():
    d = _batch.plan([ledger()], budget=200, session_lane="local-dev",
                    brief=_brief_of(), queue=[LEDGER])
    (line,) = _batch.queued_epic_lines(d)
    assert line.startswith("lib (q1): nothing — no draft prompt for its next phase")
    assert "Continue prompt in an attended chat" in line


def test_a_queued_epic_whose_next_phase_is_human_required_names_the_gate():
    d = _batch.plan([ledger(),
                     member("draft/feature/lib/p2a.md", 2, autonomy="human-required"),
                     member("draft/feature/lib/p2b.md", 2, autonomy="human-required"),
                     member("draft/feature/lib/p3.md", 3)],
                    budget=200, session_lane="local-dev", brief=_brief_of(), queue=[LEDGER])
    assert paths(d) == []
    (e,) = d["queued_epics"]
    assert e["next_phase"] == "2" and not e["taken"]
    assert e["line"] == ("lib (q1): nothing — next phase 2: "
                         "p2a (autonomy human-required); p2b (autonomy human-required)")
    assert e["members"][0]["why"] == "autonomy human-required — would park at ship"


def test_a_held_lower_phase_still_blocks_the_next_one():
    """A phase the caller kept out before planning (claimed on Mind
    origin/main, parked) is still open: the phase after it is not next."""
    p4 = member("draft/feature/lib/p4.md", 4)
    d = _batch.plan([ledger(), member("draft/feature/lib/p5.md", 5)], budget=200,
                    session_lane="local-dev", brief=_brief_of(), queue=[LEDGER],
                    withheld=[(p4, "repo autofit claimed by `x` in active.md")])
    assert paths(d) == []
    assert why(d, "draft/feature/lib/p5.md") == "epic lib phase 5 is not next"
    (line,) = _batch.queued_epic_lines(d)
    assert line == "lib (q1): nothing — next phase 4: p4 (repo autofit claimed by `x` in active.md)"


def test_the_plan_text_and_json_carry_the_queued_epics(capsys):
    d = _batch.plan([ledger()], budget=200, session_lane="local-dev",
                    brief=_brief_of(), queue=[LEDGER])
    _batch.emit(d)
    out = capsys.readouterr().out
    assert "Queued epics:\n  lib (q1): nothing" in out
    assert out.index("Queued epics:") < out.index("Not selected:")
    import json
    assert json.loads(json.dumps(d))["queued_epics"][0]["epic"] == "lib"

#!/usr/bin/env python3
"""agents/conductors/batch/_batch.py — the batch conductor.

Composes what goes into one unattended shift, and reports what came back. Thin
by construction: every judgement it uses — consequence tier, review-minutes,
readiness, difficulty — belongs to the sizing faculty, because `ORGANISM.md`
makes faculties the opinion sinks and forbids a conductor consulting a
conductor. This module decides *membership*, which is an act, not an opinion.

The composition rule, and the reason the epic exists:

    sum(Review-minutes) over `glance` and `judge` members <= the slot budget

not a task count. Read against the ledger, an honest review hour holds about
three library-touching tasks; a design that plans by count over-promises
capacity roughly threefold and lands the overflow on the human at 6am.

Everything above that budget is the FILL: work costing zero review-minutes
(`notify`-tier work, slicing, witness authoring, re-grading, deeper verification
of work that already passed). It is sized by the remaining token allowance
rather than by the human's hour, which is what lets the organism spend its whole
weekly budget without growing the review queue. Research is never fill — it
produces verdicts, and a verdict is the most expensive review there is.

Stdlib-only and offline, like every Brain entrypoint.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    BODY_MAP_PATH, LIBRARY_REPOS, effective_autonomy, effective_consequence,
    effective_difficulty, effective_review_minutes, effective_unattended,
    parse_prompt, priority_rank,
)

# One slot's worth of the human's attention. Not a task count — see the module
# docstring. 45 rather than 60 because a slot also has to queue the next batch.
DEFAULT_REVIEW_BUDGET = 45
# Above half the cap the review-bearing half is halved; at the cap the batch is
# fill only. Counted in TASKS AWAITING REVIEW, never in PRs: 94 of 332 records in
# 2026-08 named two or more PRs, so a PR-count cap trips on one healthy batch.
DEFAULT_BACKPRESSURE_CAP = 8
CHEAP_TIERS = ("notify",)


def detect_lane() -> str:
    """`local-dev` or `web-github` — where this session is running.

    Probed from the environment rather than declared, and deliberately from the
    same signal the rest of the organism already uses: a remote session has no
    `gh` (measured, documented in `skills/GITHUB_ACCESS.md` — installing one is
    a trap that authenticates and then 403s every repo-scoped call). No env var
    and no flag decides this; a session that could lie about where it is could
    plan `local-dev` work it cannot run.
    """
    return "local-dev" if shutil.which("gh") else "web-github"


def _lane_ok(record_lane: str, session_lane: str) -> bool:
    """A `local-dev` task runs only in a `local-dev` session; `any` runs anywhere."""
    return record_lane != "local-dev" or session_lane == "local-dev"


def grade(path: Path, mind: Path) -> dict:
    """Everything the planner needs about one prompt, from the faculty."""
    p = parse_prompt(path, mind)
    level, score, factors, derived = effective_difficulty(p)
    tier, why, _ = effective_consequence(p, factors)
    ready, ready_why, _ = effective_unattended(p, level, factors, derived)
    minutes, _ = effective_review_minutes(p, tier, level)
    autonomy, cap, declared_autonomy = effective_autonomy(p, level)
    return {
        "autonomy": autonomy, "autonomy_cap": cap,
        "declared_autonomy": declared_autonomy,
        "path": p["path"], "repos": p["repos"], "work_type": p["work_type"],
        "difficulty": level, "score": score, "consequence": tier,
        "witness": p.get("witness"), "review_minutes": minutes,
        "unattended": ready, "why": (why or [""])[0],
        "ready_why": ready_why, "epic": None, "lane": p.get("lane") or "any",
        "priority": p.get("priority") or "normal",
        "blocked": bool(p.get("blocked_by")),
    }


# A prompt whose own header says the work is finished. Mirrors intake's
# DONE_STATUSES: a session that ships the work and writes the outcome into
# `Status:` but leaves the file in `draft/` is a known, recorded failure mode,
# and the file keeps rendering as pickable backlog until someone retires it.
# Dispatching one wastes a whole shift re-doing finished work.
DONE_STATUSES = ("shipped", "superseded", "absorbed", "complete", "completed",
                 "done", "retired")


def _header_of(text: str, key: str) -> str:
    for line in text.splitlines()[:30]:
        if line.lower().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _epic_of(text: str) -> str:
    return _header_of(text, "epic")


def _is_done(text: str) -> bool:
    status = _header_of(text, "status").lower()
    return any(status.startswith(d) for d in DONE_STATUSES)


def _phase_of(text: str) -> float:
    """`Phase: <n>` as a sortable number; phase-less members sort last."""
    raw = _header_of(text, "phase")
    try:
        return float(raw.rstrip("abcdefgh") or "inf")
    except ValueError:
        return float("inf")


def survey(mind: Path) -> list[dict]:
    """Grade every backlog prompt. Epic membership rides along for the
    one-slice-per-epic rule."""
    out = []
    for f in sorted(mind.glob("draft/**/*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        g = grade(f, mind)
        g["epic"] = _epic_of(text)
        g["phase"] = _phase_of(text)
        g["done"] = _is_done(text)
        out.append(g)
    return out


def plan(records: list[dict], *, budget: int = DEFAULT_REVIEW_BUDGET,
         session_lane: str = "web-github", awaiting_review: int = 0,
         cap: int = DEFAULT_BACKPRESSURE_CAP) -> dict:
    """Compose the next batch — a BatchDecision.

    Every constraint states itself in `rejected`, because a planner that
    silently drops work teaches the human to distrust the number it reports.
    """
    rejected: list[tuple[str, str]] = []

    # Backpressure RAMPS; it never deadlocks. A missed slot is the common case
    # for an academic, and a conference week must not stop the thing whose whole
    # purpose is working while nobody watches.
    if awaiting_review >= cap:
        effective_budget, pressure = 0, "at cap — fill only"
    elif awaiting_review > cap / 2:
        effective_budget, pressure = budget // 2, "above half cap — halved"
    else:
        effective_budget, pressure = budget, "clear"

    # An epic's members are worked IN ORDER, so only its lowest un-shipped
    # phase is startable. Without this the planner can propose phase 6 while
    # phase 3 is still open — the one-slice-per-epic rule below caps how many
    # run, not which.
    next_phase: dict[str, float] = {}
    for r in records:
        if r.get("epic") and not r.get("done"):
            e = r["epic"]
            next_phase[e] = min(next_phase.get(e, float("inf")),
                                r.get("phase", float("inf")))

    pool = []
    for r in records:
        # Readiness says the work FITS one run; autonomy says the run may
        # FINISH it. A batch that ignores the second fills a shift with tasks
        # that all stop at the ship checkpoint and come back as questions —
        # which is the failure the whole epic exists to remove.
        if r.get("done"):
            rejected.append((r["path"], "Status: says the work is already done"))
        elif r.get("epic") and r.get("phase", float("inf")) > next_phase.get(
                r["epic"], float("inf")):
            rejected.append((r["path"],
                             f"epic {r['epic']} phase {r.get('phase')} is not next"))
        elif r["autonomy"] != "safe":
            rejected.append((r["path"],
                             f"autonomy {r['autonomy']} — would park at ship"))
        elif r["unattended"] != "ready":
            rejected.append((r["path"], f"unattended: {r['unattended']}"))
        elif r["blocked"]:
            rejected.append((r["path"], "declares Blocked-by:"))
        elif not _lane_ok(r["lane"], session_lane):
            rejected.append((r["path"], f"lane {r['lane']}, session {session_lane}"))
        else:
            pool.append(r)

    # Cheapest first: this list is read when the human has a slot to fill and
    # wants to know what fits in it. Importance is answered by the queue's order.
    pool.sort(key=lambda r: (r["review_minutes"], priority_rank(r), r["path"]))

    members, spent, seen_epics, libs = [], 0, set(), set()
    for r in pool:
        if r["epic"] and r["epic"] in seen_epics:
            rejected.append((r["path"], f"epic {r['epic']} already in this batch"))
            continue
        # Concurrent members do not collide at dispatch (separate worktrees) —
        # they collide at MERGE, because the first /prm moves main and
        # invalidates the others' test and smoke evidence. Only LIBRARY repos
        # claim a shift: they are what the library-first gate serialises and
        # what downstream suites are re-run against. Workspace, docs and organ
        # repos are exempt — two docs changes in one shift cost nothing.
        clash = next((x for x in r["repos"] if x in LIBRARY_REPOS and x in libs), None)
        if clash:
            rejected.append((r["path"], f"{clash} already claimed this shift"))
            continue
        cost = 0 if r["consequence"] in CHEAP_TIERS else r["review_minutes"]
        if spent + cost > effective_budget:
            rejected.append((r["path"], f"{cost} min would exceed the budget"))
            continue
        members.append(r)
        spent += cost
        if r["epic"]:
            seen_epics.add(r["epic"])
        libs.update(x for x in r["repos"] if x in LIBRARY_REPOS)

    return {
        "dispatch": [_dispatch_payload(r) for r in members],
        "session_lane": session_lane,
        "review_budget": budget,
        "effective_budget": effective_budget,
        "backpressure": {"awaiting_review": awaiting_review, "cap": cap,
                         "state": pressure},
        "review_minutes_planned": spent,
        "members": members,
        "rejected": rejected,
        "other_lane_ready": sum(
            1 for r in records
            if r["unattended"] == "ready" and not _lane_ok(r["lane"], session_lane)),
    }


def _dispatch_payload(r: dict) -> str:
    """The exact text a human pastes into one unattended session.

    Written out rather than left to be composed at dispatch time: the launch is
    the human's act (AUTONOMY.md, "What a batch launch is"), so the thing they
    perform should carry no decisions — everything decided was decided when they
    approved the batch.
    """
    return f"/start_dev {r['path']} --auto"


def emit(d: dict) -> None:
    lane = d["session_lane"]
    print("== BatchDecision ==")
    print(f"Session lane:      {lane}")
    print(f"Review budget:     {d['effective_budget']} of {d['review_budget']} min "
          f"({d['backpressure']['state']}; "
          f"{d['backpressure']['awaiting_review']} awaiting review, "
          f"cap {d['backpressure']['cap']})")
    print(f"Planned:           {d['review_minutes_planned']} review-minutes over "
          f"{len(d['members'])} member(s)")
    print()
    if d["members"]:
        for r in d["members"]:
            cost = 0 if r["consequence"] in CHEAP_TIERS else r["review_minutes"]
            print(f"  {cost:>3} min  {r['consequence']:<7} {r['path']}")
            if not r["witness"]:
                print("           (no witness — reviewed as `judge`)")
    elif d["effective_budget"] == 0:
        # At the cap the batch is the FLOOR: fill only, dispatched whether or
        # not the human turned up. An empty floor is a finding, not a deadlock —
        # it means nothing in the backlog costs zero review-minutes, which is
        # what the `notify` tier and the witness field exist to change.
        print("  (no members — at the backpressure cap, so this batch is the")
        print("   FLOOR: fill only. Nothing in the backlog currently qualifies")
        print("   as fill, which is itself the finding — clear the review queue,")
        print("   or write witnesses so work can grade `notify`.)")
    else:
        print("  (no members — see the rejections below)")
    print()
    if d["other_lane_ready"]:
        # Reported, never silently dropped: a task the session cannot run is
        # still a task the human can, from the other machine.
        print(f"{d['other_lane_ready']} local-dev task(s) are ready — run "
              "`batch plan` from the laptop to see them.")
        print()
    print(f"Not selected: {len(d['rejected'])}")
    counts: dict[str, int] = {}
    for _, why in d["rejected"]:
        counts[why.split(":")[0].split(" already")[0]] = counts.get(
            why.split(":")[0].split(" already")[0], 0) + 1
    for why, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {n:>4}  {why}")
    print()
    if d["members"]:
        print("To dispatch: paste ONE of these into its own session —")
        for line in d["dispatch"]:
            print(f"  {line}")
        print()
    print("This is a PROPOSAL. Approving it in the slot is what launches the")
    print("batch — membership is fixed at approval and the grant expires with")
    print("the shift (AUTONOMY.md, \"What a batch launch is\").")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="batch")
    ap.add_argument("verb", choices=["plan"], nargs="?", default="plan")
    ap.add_argument("--mind", type=Path, default=BODY_MAP_PATH.parent)
    ap.add_argument("--budget", type=int, default=DEFAULT_REVIEW_BUDGET,
                    help="review-minutes available in the slot")
    ap.add_argument("--awaiting-review", type=int, default=0,
                    help="tasks already awaiting review (backpressure input)")
    ap.add_argument("--cap", type=int, default=DEFAULT_BACKPRESSURE_CAP)
    ap.add_argument("--lane", default="", help="override the detected session lane")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)

    mind = a.mind.resolve()
    if not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return 4
    d = plan(survey(mind), budget=a.budget, session_lane=a.lane or detect_lane(),
             awaiting_review=a.awaiting_review, cap=a.cap)
    print(json.dumps(d, indent=2)) if a.as_json else emit(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

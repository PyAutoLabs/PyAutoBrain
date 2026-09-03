#!/usr/bin/env python3
"""agents/conductors/batch/_batch.py — the batch conductor.

Composes what goes into one unattended shift, and reports what came back. Thin
by construction: every judgement it uses — consequence tier, review-minutes,
readiness, difficulty — belongs to the sizing faculty, because `ORGANISM.md`
makes faculties the opinion sinks and forbids a conductor consulting a
conductor. This module decides *membership*, which is an act, not an opinion.

The composition rule, and the reason the epic exists:

    sum(Review-minutes) over `glance` and `judge` members <= the slot budget

not a task count. The budget is the human's to set per slot (default 45) — a
slot is whenever they come in, not a scheduled hour. Read against the ledger, an
honest review hour holds about three library-touching tasks; a design that plans
by count over-promises capacity roughly threefold and lands the overflow on the
human at 6am.

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
import datetime as _dt
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    BODY_MAP_PATH, LIBRARY_REPOS, effective_autonomy, effective_consequence,
    effective_difficulty, effective_review_minutes, effective_unattended,
    parse_prompt, priority_rank,
)
# `_status` (same directory) is the one definition of this vocabulary — the
# batch status box on both dashboards reads a record the same way this
# conductor writes one. Re-exported below (`RULING_WORDS`, `PENDING_RE`,
# `CORTEX_BOARD_STATES`) so existing importers of `_batch` keep working.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _status import (  # noqa: E402
    PENDING_RE, RULING_WORDS, CORTEX_BOARD_STATES, _carried_slugs, freeze_line,
)

# One slot's worth of the human's attention, and only the DEFAULT: the human
# sets it per slot with --budget, because they know whether the next one is a
# quick morning check or a long afternoon. Not a task count — see the module
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

    # Backpressure RAMPS; it never deadlocks. It measures review-queue DEPTH,
    # never timing: timing is the human's, declared as `review-at:` at dispatch.
    # An academic comes back late and vanishes for conference weeks, and a deep
    # queue must shrink the next batch rather than refuse to compose one.
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
        # At the cap the batch is fill only — and the human still dispatches it.
        # (The FLOOR, a fill-only batch dispatched whether or not they turned
        # up, was closed 2026-08-31 and never built.) An empty fill-only batch
        # is a finding, not a deadlock: nothing in the backlog costs zero
        # review-minutes, which is what the `notify` tier and the witness field
        # exist to change.
        print("  (no members — at the backpressure cap, so this batch is FILL")
        print("   ONLY. Nothing in the backlog currently qualifies as fill,")
        print("   which is itself the finding — clear the review queue, or")
        print("   write witnesses so work can grade `notify`.)")
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
    print("State review-at (when you expect to be back) when you say go: the")
    print("shift is dispatch -> review-at, and it is where the grant expires.")


# ================================================================ collect ===
# What came back from one shift, scored — and the page the human reads it on.
#
# One fact shapes every rule below. **A green session is not a delivered
# task.** A cloud session's green status means it started and exited without an
# infrastructure error; `batches/AGENTS.md` says a member counts as delivered
# only with "a PR that has a non-empty diff and checks that actually ran", and
# that a member ending green with no PR is reported not delivered, loudly, at
# the top of the packet. So this verb never reads a session's own report of
# itself. It reads PR evidence, and where it has none it says UNOBSERVABLE
# rather than inventing either verdict — the third answer the Cortex's own
# collect had to grow for exactly the same reason.
#
# It is offline by default and writes nothing without `--apply`. `--fetch` is
# the one leg that shells out, and only to `gh`, and only where `gh` exists.

# The batch record's own grammar. `RECORD_KEY` is the Cortex conductor's, kept
# byte-identical so both organs read one record the same way; `MEMBER_RE` is
# NOT — see `parse_member`.
RECORD_KEY = re.compile(r"^- ([a-z][a-z0-9-]*):(?:\s+(.*?))?\s*$")
MEMBER_RE = re.compile(r"^  - (?P<slug>[^:]+): (?P<rest>.+)$")

# `RULING_WORDS` and `PENDING_RE` are `_status`'s (imported above): a record
# line opening with a ruling word is a VERDICT, and `--apply` leaves it alone;
# `PENDING_RE` is the ledger's own "not finished yet" vocabulary. Kept as one
# definition so the batch status box and this conductor never drift.

PR_URL_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
ISSUE_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")


class BatchUsageError(Exception):
    """Bad input from the human — reported on stderr, exit 2, nothing written."""


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


#: How long a pushed `integration/<slot>` ref lives after the review it exists
#: for. A week is generous for a branch whose whole reason to exist is one
#: reading; longer, and the namespace becomes a graveyard nobody dares sweep.
SWEEP_DAYS = 7


def sweep_after_default(review_at: str, notes: list) -> str:
    """`review-at` plus a week — the default expiry of a pushed review ref.

    The review is the branch's reason to exist, so the review date is what the
    expiry hangs off. An unparsable `review-at:` falls back to today plus the
    same week and SAYS SO: a silently guessed deletion date is the one kind of
    guess a branch sweep must never act on unexplained.
    """
    try:
        day = _dt.date.fromisoformat((review_at or "").strip()[:10])
    except ValueError:
        notes.append(f"sweep-after: review-at {review_at or '(none)'!r} does "
                     f"not read as a date — defaulted to today + {SWEEP_DAYS} "
                     f"days; edit the record to change it")
        day = _dt.datetime.now(_dt.timezone.utc).date()
    return (day + _dt.timedelta(days=SWEEP_DAYS)).isoformat()


def _dash(line: str) -> str:
    """` -- ` typed for an em dash. Records are hand-written as often as not."""
    return line.replace(" -- ", " — ")


#: The spellings a hand-written record's boolean key is allowed to use.
YES_WORDS = ("yes", "true", "on", "1")


def _yes(values) -> bool:
    """Is this record key asking for something? `read_record` keeps every value
    of every key in file order, so a key is a LIST; the FIRST value is the
    answer and a later `- integration: no` does not un-ask it — the same rule
    `collected:` follows (the first collect owns it)."""
    if isinstance(values, str):
        values = [values]
    for v in values or []:
        return str(v).strip().casefold() in YES_WORDS
    return False


def parse_member(raw: str) -> dict | None:
    """`  - <slug>: <path> — <tier> — <minutes> — <outcome…>`, or None.

    Deliberately not the Cortex conductor's `MEMBER_RE`: its `(?P<state>\\S+)$`
    fails on every real dev line (all nine outcomes in the 2026-08-31-pm record
    contain spaces) and its `(?P<path>\\S+)` fails on the two science lines,
    whose "path" is a sentence. Splitting on the separator with `maxsplit=3`
    keeps the outcome whole however long it runs — and a line whose path holds
    a space is simply not this grammar, which is a NOTE, not a crash.
    """
    m = MEMBER_RE.match(_dash(raw))
    if not m:
        return None
    fields = [f.strip() for f in m.group("rest").split(" — ", 3)]
    if len(fields) != 4:
        return None
    path, tier, minutes, outcome = fields
    if not path or " " in path:
        return None
    return {"slug": m.group("slug").strip(), "path": path, "tier": tier,
            "minutes": minutes, "outcome": outcome}


def read_record(text: str) -> dict:
    """One batch record, lossless and line-indexed.

    `{"keys": {k: [v…]}, "key_lines": {k: [lineno…]}, "members": [row…],
      "unparsable": [(lineno, raw)…], "members_end": lineno}`.

    Every value of every key is kept, in file order (`- refreshed:` repeats once
    per pull and each one is history). The body of `- notes: |` is invisible to
    `keys` — which is why every write in this module edits `lines[]` in place
    and nothing is ever re-serialised from this dict.
    """
    keys: dict[str, list[str]] = {}
    key_lines: dict[str, list[int]] = {}
    members: list[dict] = []
    unparsable: list[tuple[int, str]] = []
    in_members = False
    members_end = 0
    for lineno, raw in enumerate(text.split("\n"), 1):
        m = RECORD_KEY.match(raw)
        if m:
            in_members = m.group(1) == "members"
            keys.setdefault(m.group(1), []).append((m.group(2) or "").strip())
            key_lines.setdefault(m.group(1), []).append(lineno)
            continue
        if in_members and raw.startswith("  - "):
            members_end = lineno
            row = parse_member(raw)
            if row is None:
                unparsable.append((lineno, raw))
            else:
                row.update({"lineno": lineno, "raw": raw})
                members.append(row)
        elif raw.strip() and not raw.startswith("    ") and in_members:
            # The continuation rule: a member list ends at the first line that
            # is neither a member nor an indented wrap of one.
            in_members = False
    return {"keys": keys, "key_lines": key_lines, "members": members,
            "unparsable": unparsable, "members_end": members_end}


def batch_records(mind: Path) -> list[Path]:
    return sorted(p for p in (mind / "batches").glob("*.md")
                  if p.name != "AGENTS.md")


def newest_slot(mind: Path) -> str:
    """The last record by NAME, which is lexical: `-night` sorts before `-pm`
    on the same date, so a night slot collected after a pm one is not the
    newest by this reckoning. `--slot` is the escape, and the reason it exists.
    """
    records = batch_records(mind)
    return records[-1].stem if records else ""


# ------------------------------------------------------- the other inputs ---
def find_prompt(mind: Path, path: str) -> Path | None:
    """A member's prompt, wherever the lifecycle has moved it to.

    A prompt is written under `draft/`, issued into `active/` and retired into
    `complete/<YYYY>/<MM>/`; the record names where it was AT DISPATCH. All
    three are tried, by basename, because a member collected after its own
    close-out would otherwise lose its question and its witness.
    """
    if not path:
        return None
    direct = mind / path
    if direct.is_file():
        return direct
    name = Path(path).name
    issued = mind / "active" / name
    if issued.is_file():
        return issued
    return next(iter(sorted(mind.glob(f"complete/**/{name}"))), None)


_HEADER_LINE_RE = re.compile(r"^[A-Z][A-Za-z_ -]{0,24}:(?:\s|$)")


def _title_of(text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _question_of(text: str) -> str:
    """The first prose paragraph — what the member was dispatched to answer.

    Header keys, headings, fences and bullets are skipped rather than joined:
    the packet block wants the sentence a human wrote, not the front matter.
    """
    para: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not s:
            if para:
                break
            continue
        if (s.startswith("#") or s.startswith(("- ", "* ", "|", ">"))
                or _HEADER_LINE_RE.match(s)):
            if para:
                break
            continue
        para.append(s)
    return " ".join(para)[:600]


def prompt_facts(mind: Path, path: str) -> dict:
    """What the prompt says about itself. The record's own tier and minutes
    win — `grade()` is never called here, because re-sizing a task at collect
    would report a member against a number nobody dispatched it under."""
    out = {"witness": None, "consequence": None, "review_minutes": None,
           "repos": [], "path": path, "found": "", "title": "", "question": ""}
    p = find_prompt(mind, path)
    if p is None:
        return out
    try:
        parsed = parse_prompt(p, mind)
    except (OSError, ValueError, KeyError):
        # A prompt that will not parse is a note on one member, never the end
        # of the collect.
        return out
    text = parsed.get("text", "")
    out.update(witness=parsed.get("witness"),
               consequence=parsed.get("declared_consequence"),
               review_minutes=parsed.get("declared_review_minutes"),
               repos=parsed.get("repos") or [],
               found=parsed.get("path") or str(p),
               title=_title_of(text), question=_question_of(text))
    return out


ACTIVE_KEY_RE = re.compile(r"^- ([a-z][a-z0-9_-]*):(?:\s+(.*?))?\s*$")


def _active_entry(slug: str, body: str) -> dict:
    keys: dict[str, list[str]] = {}
    current = None
    for line in body.split("\n"):
        m = ACTIVE_KEY_RE.match(line)
        if m:
            current = m.group(1)
            keys.setdefault(current, [])
            value = (m.group(2) or "").strip()
            if value and value != "|":
                keys[current].append(value)
            continue
        if current and (line.startswith("  - ") or line.startswith("    ")):
            keys[current].append(line.strip().lstrip("- ").strip())
        elif line.strip():
            current = None
    prompt = keys.get("prompt") or [""]
    issue = ISSUE_URL_RE.search(body)
    return {"slug": slug, "keys": keys, "text": body,
            "prompt": Path(prompt[0]).name if prompt[0] else "",
            "prs": sorted({m.group(0) for m in PR_URL_RE.finditer(body)}),
            "issue": issue.group(0) if issue else "",
            "status": (keys.get("status") or [""])[0]}


def read_active(mind: Path) -> dict:
    """`active.md` as `{slug: entry}`. PR urls are harvested from the whole
    entry text — they are spelled `library-pr:`, `workspace-pr:` and `prs:` in
    different entries, and a reader keyed to one of those spellings sees a
    third of them."""
    try:
        text = (mind / "active.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, dict] = {}
    slug, buf = None, []
    for line in text.split("\n"):
        if line.startswith("## "):
            if slug:
                out[slug] = _active_entry(slug, "\n".join(buf))
            slug, buf = line[3:].strip(), []
        elif slug is not None:
            buf.append(line)
    if slug:
        out[slug] = _active_entry(slug, "\n".join(buf))
    return out


def active_for(member: dict, active: dict) -> tuple:
    """`(entry, how)` — the `active.md` entry for a member, and which pass
    found it.

    Three passes because the record's member slug is a dispatch label and the
    registry's slug is the task's name, and they routinely differ:
    `autofit-resampling-info` is registered as `resampling-info-summary-section`,
    `autonerves-colab-silence` as `silence-colab-cli-message`. An unmatched
    member is reported, never crashed on.
    """
    slug = member.get("slug", "")
    if slug in active:
        return active[slug], "slug"
    name = Path(member.get("path") or "").name
    if name:
        for entry in active.values():
            if entry["prompt"] and entry["prompt"] == name:
                return entry, "prompt basename"
    for entry in active.values():
        if f"member {slug}" in entry["text"]:
            return entry, "named in the entry"
    return None, ""


# -------------------------------------------------------------- evidence ---
#: The evidence file's shape, `{"schema": 1, "members": {slug: {…}}}`. Every
#: key is optional and a bare `{slug: …}` map reads too — a human assembling
#: one by hand from the GitHub MCP tools in a web session should not have to
#: get a wrapper right.
EVIDENCE_KEYS = ("prs", "witness", "adversary", "flagged", "pending", "summary")

#: The `gh pr view --json` field list. The four `head*` fields are the
#: authoritative member -> (repo, branch) map: the record stores no branch per
#: member, so a PR's own head is the only reliable source. The head *repo* is
#: recorded too because a fork's head is not on `origin` and cannot be merged
#: from a local checkout at all.
#: `mergedAt`, NOT `merged`: `gh pr view --json` has no `merged` field (gh
#: 2.98 rejects the whole request with "Unknown JSON field", so ONE bad name
#: made every `--fetch` PR UNOBSERVABLE rather than dropping one column). The
#: timestamp is the same fact, and `merged` is derived from it below.
GH_FIELDS = ("number,url,state,additions,deletions,changedFiles,mergeable,"
             "mergedAt,statusCheckRollup,headRefName,headRefOid,"
             "headRepository,headRepositoryOwner")


def load_evidence(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise BatchUsageError(f"batch: cannot read --evidence {path}: {e}")
    except json.JSONDecodeError as e:
        raise BatchUsageError(f"batch: --evidence {path} is not valid JSON: {e}")
    if not isinstance(data, dict):
        raise BatchUsageError(f"batch: --evidence {path} must be a JSON object")
    members = data.get("members") if isinstance(data.get("members"), dict) else data
    return {k: v for k, v in members.items() if isinstance(v, dict)}


def load_evidence_doc(path) -> dict:
    """The whole evidence document. `load_evidence` deliberately returns only
    its members; this returns the wrapper too, because `integration` is
    slot-level rather than per member — and a laptop's integration block pasted
    into a cloud session is how a non-laptop surface renders one at all."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


#: The integration leg lives in its own module: it is a git engine, it imports
#: nothing from here, and a session that never types `--integration` never pays
#: for it. Loaded by file location and cached, exactly like the Cortex
#: conductor below — and for the same reason.
INTEGRATION_MOD = (BRAIN / "agents" / "conductors" / "batch" /
                   "_integration.py")
_INTEG = None


def load_integration():
    global _INTEG
    if _INTEG is None:
        spec = importlib.util.spec_from_file_location(
            "_batch_integration_leg", INTEGRATION_MOD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _INTEG = mod
    return _INTEG


def _checks_from_rollup(rollup) -> list:
    """`statusCheckRollup` — two shapes in one list. A check run reports
    `status`/`conclusion`; a commit status context reports `state` only, and a
    reader that knows one shape scores half of a PR's checks UNOBSERVABLE."""
    out = []
    for row in rollup or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("context") or "check"
        if row.get("state"):
            state = str(row["state"]).lower()
            out.append({"name": name, "status": "completed",
                        "conclusion": "success" if state == "success" else state})
        else:
            out.append({"name": name,
                        "status": str(row.get("status") or "").lower(),
                        "conclusion": str(row.get("conclusion") or "").lower()})
    return out


def _head_of(data: dict, repo: str) -> dict:
    """The PR's head branch and where it lives. `headRepository` /
    `headRepositoryOwner` are objects (`{"name": ...}` / `{"login": ...}`) and
    either may be null on a deleted fork — a missing head is reported empty,
    never guessed as `origin`, so a caller can tell "same repo" from "unknown".
    """
    data = data if isinstance(data, dict) else {}
    name = data.get("headRepository")
    owner = data.get("headRepositoryOwner")
    name = name.get("name") if isinstance(name, dict) else None
    owner = owner.get("login") if isinstance(owner, dict) else None
    return {
        "head_ref": str(data.get("headRefName") or ""),
        "head_sha": str(data.get("headRefOid") or ""),
        "head_repo": f"{owner}/{name}" if owner and name else "",
    }


def fetch_evidence(members: list, active: dict) -> tuple:
    """PR evidence from `gh`, when there is a `gh`. Never writes.

    `gh` is the lane probe (`detect_lane`), so its absence is answered with one
    pointer line rather than a caught 403: in a web session `gh` installs fine,
    authenticates fine and then 403s every repo-scoped call
    (`skills/GITHUB_ACCESS.md`), which is worse than not having it.
    """
    notes: list[str] = []
    if detect_lane() != "local-dev":
        notes.append(
            "batch collect: no gh here — gather PR evidence with the GitHub "
            "MCP tools (skills/GITHUB_ACCESS.md) and pass it as "
            "--evidence <json>.")
        return {}, notes
    out: dict[str, dict] = {}
    for m in members:
        entry, _how = active_for(m, active)
        prs = []
        for url in (entry or {}).get("prs", []):
            got = PR_URL_RE.match(url)
            if not got:
                continue
            repo, number = got.group(1), got.group(2)
            try:
                r = subprocess.run(
                    ["gh", "pr", "view", number, "--repo", repo, "--json",
                     GH_FIELDS], capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.SubprocessError) as e:
                notes.append(f"{m['slug']}: gh pr view {repo}#{number} could "
                             f"not run ({e}) — scored UNOBSERVABLE")
                continue
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()
                notes.append(f"{m['slug']}: gh pr view {repo}#{number} exited "
                             f"{r.returncode}" + (f": {tail[-1][:120]}" if tail
                                                  else "") + " — UNOBSERVABLE")
                continue
            try:
                data = json.loads(r.stdout)
            except json.JSONDecodeError:
                notes.append(f"{m['slug']}: gh returned no JSON for "
                             f"{repo}#{number} — UNOBSERVABLE")
                continue
            prs.append({
                "repo": repo, "number": data.get("number") or int(number),
                "url": data.get("url") or url, "state": data.get("state"),
                "additions": data.get("additions"),
                "deletions": data.get("deletions"),
                "changed_files": data.get("changedFiles"),
                "mergeable": data.get("mergeable"),
                "merged": bool(data.get("mergedAt")),
                "checks": _checks_from_rollup(data.get("statusCheckRollup")),
                **_head_of(data, repo),
            })
        if prs:
            out[m["slug"]] = {"prs": prs}
    return out, notes


# ------------------------------------------------------------- the legs ----
PASS, FAIL, UNOBSERVABLE = "PASS", "FAIL", "UNOBSERVABLE"

#: The six legs, in packet order — the three `delivered:` legs of
#: `batches/AGENTS.md` (a PR, a non-empty diff, checks that ran), the green
#: reading of those checks, and the two legs `AUTONOMY.md` adds to a batch
#: launch: the pre-registered witness and the independent adversary.
LEGS = ("pr", "diff", "checks", "green", "witness", "adversary")
LEG_TITLES = {
    "pr": "a PR exists",
    "diff": "the diff is non-empty",
    "checks": "every check completed",
    "green": "every check green",
    "witness": "the witness is declared, and holds",
    "adversary": "an independent adversary read it",
}
GREEN_CONCLUSIONS = ("success", "neutral", "skipped")

NO_EVIDENCE = "no evidence supplied — pass --evidence or run --fetch"


def _prs(ev) -> list:
    return [p for p in (ev or {}).get("prs", []) if isinstance(p, dict)]


def _pr_label(p: dict) -> str:
    return f"{p.get('repo') or '?'}#{p.get('number') or '?'}"


def _all_checks(prs: list) -> list:
    out = []
    for p in prs:
        for c in p.get("checks") or []:
            if isinstance(c, dict):
                out.append((p, c))
    return out


def leg_pr(ev) -> tuple:
    if ev is None:
        return UNOBSERVABLE, NO_EVIDENCE
    prs = _prs(ev)
    if not prs:
        # The loud one. `batches/AGENTS.md`: a member that ends green with no
        # PR is reported as not delivered, at the top of the packet.
        return FAIL, "no PR — a session that ended green with no PR is not delivered"
    return PASS, ", ".join(_pr_label(p) for p in prs)


def leg_diff(ev) -> tuple:
    if ev is None:
        return UNOBSERVABLE, NO_EVIDENCE
    prs = _prs(ev)
    if not prs:
        return UNOBSERVABLE, "no PR to measure"
    counted = [p for p in prs if any(p.get(k) is not None
                                     for k in ("additions", "deletions",
                                               "changed_files"))]
    if not counted:
        return UNOBSERVABLE, "the evidence carries no diff counts"
    adds = sum(int(p.get("additions") or 0) for p in counted)
    dels = sum(int(p.get("deletions") or 0) for p in counted)
    files = sum(int(p.get("changed_files") or 0) for p in counted)
    if adds + dels == 0 or files == 0:
        return FAIL, (f"+{adds}/−{dels} over {files} file(s) — an empty diff "
                      "is not a delivery")
    return PASS, f"+{adds}/−{dels} over {files} file(s)"


def leg_checks(ev, *, pending: bool) -> tuple:
    if ev is None:
        return UNOBSERVABLE, NO_EVIDENCE
    prs = _prs(ev)
    if not prs:
        return UNOBSERVABLE, "no PR to check"
    if not any("checks" in p for p in prs):
        return UNOBSERVABLE, "the evidence records no checks"
    checks = _all_checks(prs)
    if not checks:
        # Distinct from red, and the record's own words for it: green with
        # checks that never ran is NOT DELIVERED, not FAILED.
        return FAIL, "checks never ran"
    unfinished = [(p, c) for p, c in checks if c.get("status") != "completed"]
    if unfinished:
        p, c = unfinished[0]
        why = (f"{len(unfinished)} of {len(checks)} still "
               f"{c.get('status') or 'queued'} ({_pr_label(p)} {c.get('name')})")
        return (UNOBSERVABLE, why + " — still in flight") if pending \
            else (FAIL, why)
    return PASS, f"{len(checks)} check(s) completed"


def leg_green(ev) -> tuple:
    if ev is None:
        return UNOBSERVABLE, NO_EVIDENCE
    checks = _all_checks(_prs(ev))
    if not checks:
        return UNOBSERVABLE, "no checks to read"
    red = [(p, c) for p, c in checks
           if (c.get("conclusion") or "") not in GREEN_CONCLUSIONS]
    if red:
        p, c = red[0]
        return FAIL, (f"{_pr_label(p)} {c.get('name')}: "
                      f"{c.get('conclusion') or 'no conclusion'}"
                      + (f" (+{len(red) - 1} more)" if len(red) > 1 else ""))
    return PASS, f"{len(checks)}/{len(checks)} green"


def leg_witness(declared, ev) -> tuple:
    if not (declared or "").strip():
        return UNOBSERVABLE, "no witness declared — reviewed as `judge`"
    row = (ev or {}).get("witness")
    holds = row.get("holds") if isinstance(row, dict) else None
    detail = (row.get("evidence") if isinstance(row, dict) else "") or ""
    if holds is False:
        return FAIL, f"the declared witness does not hold: {detail or declared}"
    if holds is True:
        return PASS, detail or declared
    return UNOBSERVABLE, (f"declared (`{declared[:80]}`) but not verified here "
                          "— read it on the PR")


def leg_adversary(ev) -> tuple:
    row = (ev or {}).get("adversary")
    if not isinstance(row, dict) or not row.get("ran"):
        return UNOBSERVABLE, "no adversary leg recorded"
    model, author = (row.get("model") or ""), (row.get("author_model") or "")
    if not model or not author or model == author:
        # AUTONOMY.md leg 5, verbatim in intent: the leg is a reading by a
        # DIFFERENT model from the one that wrote the diff.
        return FAIL, ("a self-run adversary leg is an absent leg, not a weak "
                      "one (AUTONOMY.md leg 5)"
                      + (f" — model {model}" if model else " — no model named"))
    return PASS, f"{model} vs author {author}: {row.get('verdict') or 'read'}"


#: Health, in the order the packet shows members in: what failed, what did not
#: arrive, what cannot be trusted, what is fine, what has not finished, what
#: already landed. `RUNNING` is the Cortex kind's word for a member whose run
#: line is still live — it is not `PENDING` (a dev member whose checks have not
#: come back), and it holds no review control at all.
HEALTHS = ("FAILED", "NOT-DELIVERED", "SUSPECT", "HEALTHY", "RUNNING",
           "PENDING", "MERGED")
HEALTH_SEV = {"FAILED": "failed", "NOT-DELIVERED": "failed",
              "SUSPECT": "suspect", "HEALTHY": "healthy",
              "RUNNING": "running", "PENDING": "running", "MERGED": "merged"}


def health_of(legs: dict, *, pending: bool = False, merged: bool = False,
              flagged=()) -> str:
    """One member's health from its six legs.

    The three `delivered:` legs are tested BEFORE the red-check leg, which
    inverts the order the legs are listed in: "checks never ran" is a FAIL on
    the checks leg but `batches/AGENTS.md` calls it not-delivered, not failed,
    and the distinction is the whole point of that page's first rule.
    """
    verdicts = {k: legs[k][0] for k in LEGS}
    if merged:
        return "MERGED"
    if pending:
        return "PENDING"
    never_ran = (verdicts["checks"] == FAIL
                 and "never ran" in legs["checks"][1])
    if never_ran or FAIL in (verdicts["pr"], verdicts["diff"]):
        return "NOT-DELIVERED"
    if FAIL in (verdicts["checks"], verdicts["green"], verdicts["witness"]):
        return "FAILED"
    if flagged or UNOBSERVABLE in verdicts.values():
        return "SUSPECT"
    return "HEALTHY"


# ------------------------------------------------- the scored dev member ---
def _int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _md_link(text: str, url: str) -> str:
    return f"[{text}]({url})" if url else text


def score_dev(member: dict, ctx: dict) -> dict:
    """One dev member, scored. The ONLY shape the report and the renderer read.

    A `kind` is exactly this: a scorer that returns this dict and a block
    builder that fills its `blocks`. Registering one is how the Cortex's
    science members join a Mind packet without either side learning the
    other's vocabulary.
    """
    slug = member["slug"]
    ev = (ctx.get("evidence") or {}).get(slug)
    entry, how = active_for(member, ctx.get("active") or {})
    facts = prompt_facts(ctx["mind"], member.get("path") or "")
    notes: list[str] = []
    if entry is None:
        notes.append("no active.md entry matched — PR links come from the "
                     "evidence only")
    elif how != "slug":
        notes.append(f"matched active.md entry `{entry['slug']}` by {how}")
    if facts["found"]:
        if facts["found"] != member.get("path"):
            notes.append(f"prompt found at `{facts['found']}` (the record "
                         f"names `{member.get('path')}`)")
    elif member.get("path"):
        notes.append(f"prompt `{member.get('path')}` is not in this Mind — "
                     "question and witness unavailable")

    prs = _prs(ev)
    flagged = [str(f) for f in (ev or {}).get("flagged") or []]
    merged = any(p.get("merged") for p in prs)
    pending = bool((ev or {}).get("pending")) or bool(
        PENDING_RE.search(member.get("outcome") or ""))
    legs = {
        "pr": leg_pr(ev),
        "diff": leg_diff(ev),
        "checks": leg_checks(ev, pending=pending),
        "green": leg_green(ev),
        "witness": leg_witness(facts["witness"], ev),
        "adversary": leg_adversary(ev),
    }
    health = health_of(legs, pending=pending, merged=merged, flagged=flagged)
    est = _int(member.get("minutes"))
    links = [(_pr_label(p), p.get("url") or "") for p in prs]
    if entry and entry["issue"]:
        links.append(("issue", entry["issue"]))
    for url in (entry or {}).get("prs", []):
        got = PR_URL_RE.match(url)
        label = f"{got.group(1)}#{got.group(2)}" if got else url
        if label not in [t for t, _u in links]:
            links.append((label, url))

    s = {
        "slug": slug, "kind": "dev", "id": f"m-{slug}",
        "title": facts["title"] or slug.replace("-", " "),
        "health": health,
        "eyebrow": " · ".join(x for x in (
            ", ".join(facts["repos"]) or (entry or {}).get("slug", ""),
            member.get("tier") or "", (entry or {}).get("status", "")) if x),
        "jobs": " · ".join(t for t, _u in links) or "(no PR recorded)",
        "chip": _chip_text(health, legs, prs),
        "est_minutes": est, "tier": member.get("tier") or "",
        "pending": pending, "merged": merged, "flagged": flagged,
        "legs": legs, "links": links, "notes": notes,
        "path": member.get("path") or "", "outcome": member.get("outcome") or "",
        "prs": prs, "facts": facts,
        "ruling_line": "_(one line — yours to write)_",
        "review_chips": review_chips(health, pending),
        "summary": (ev or {}).get("summary") or "",
    }
    s["blocks"] = dev_blocks(s)
    return s


def _chip_text(health: str, legs: dict, prs: list) -> str:
    if health == "MERGED":
        return "merged"
    if health == "PENDING":
        return "PENDING — refreshed during your read"
    if legs["green"][0] == PASS:
        return f"PR green · {legs['green'][1]}"
    if health == "NOT-DELIVERED":
        return "not delivered"
    return health.lower()


def review_chips(health: str, pending: bool) -> list:
    """`Accept / Tweak / Reject / Defer`, with the first chip renamed to fit
    the member — TEMPLATE.md's rule, and the values the submit schema names."""
    first = ("leave-to-finish", "Leave to finish") if pending else \
        ("structure-ok", "Structure OK") if health == "MERGED" else \
        ("merge", "Merge")
    return [first, ("tweak", "Tweak"), ("reject", "Reject"), ("defer", "Defer")]


def dev_blocks(s: dict) -> list:
    """One member's blocks, in `batches/packets/TEMPLATE.md`'s order."""
    facts = s["facts"]
    blocks = [("Question this member was dispatched to answer",
               facts["question"] or "_(no prompt found — see the record line)_")]
    witness = facts["witness"]
    blocks.append(("Witness",
                   (f"Declared: {witness}\n\n{s['legs']['witness'][0]} — "
                    f"{s['legs']['witness'][1]}") if witness else
                   "None declared — the review is the diff itself "
                   "(reviewed as `judge`)."))
    if s["pending"]:
        # A pending member shows what it was asked and nothing it has not
        # earned: its health legs are a reading of a run still going.
        blocks.append(("Status", f"PENDING — {s['outcome'] or 'in flight'}"))
        return blocks
    blocks.append(("Health evidence", "\n".join(
        f"- {LEG_TITLES[k]} — {s['legs'][k][0]} — {s['legs'][k][1]}"
        for k in LEGS)))
    blocks.append(("Readout", _pr_table(s)))
    blocks.append(("Ruling", s["ruling_line"]))
    blocks.append(("Follow-ups", "\n".join(f"- {f}" for f in s["flagged"])
                   or "_(none flagged by the run)_"))
    where = [f"- {_md_link(t, u)}" for t, u in s["links"]]
    if s["path"]:
        where.append(f"- prompt: `{facts['found'] or s['path']}`")
    # Deliberately NOT the record's outcome column: `--apply` rewrites that
    # column, so a packet quoting it would differ from itself on the next
    # refresh for no reason a reader could see.
    blocks.append(("Where to look yourself", "\n".join(where)
                   or "_(nothing recorded)_"))
    return blocks


def _pr_table(s: dict) -> str:
    if not s["prs"]:
        return "_(no PR evidence — nothing to read out)_"
    rows = ["| PR | State | Diff | Mergeable | Checks |", "|---|---|---|---|---|"]
    for p in s["prs"]:
        checks = p.get("checks")
        if checks is None:
            cell = "not recorded"
        elif not checks:
            cell = "never ran"
        else:
            green = sum(1 for c in checks
                        if (c.get("conclusion") or "") in GREEN_CONCLUSIONS)
            cell = f"{green}/{len(checks)} green"
        diff = ("not recorded" if p.get("additions") is None
                and p.get("deletions") is None else
                f"+{_int(p.get('additions'))}/−{_int(p.get('deletions'))} over "
                f"{_int(p.get('changed_files'))} file(s)")
        rows.append(f"| {_md_link(_pr_label(p), p.get('url') or '')} "
                    f"| {p.get('state') or '?'} | {diff} "
                    f"| {p.get('mergeable') or '?'} | {cell} |")
    return "\n".join(rows)


def kind_of(member: dict, ctx: dict) -> str:
    """`dev` unless a registered kind claims the member. The Cortex's phase-5
    `cortex` kind claims a member whose path is a `phases/…` file; nothing else
    may claim one, so the default is never a guess."""
    for name, (_score, _blocks, claims) in ctx.get("kinds", KINDS).items():
        if claims is not None and claims(member, ctx):
            return name
    return "dev"


#: The extension point. `{name: (score, blocks, claims)}` — `score(member, ctx)`
#: returns the scored dict, `blocks(scored)` fills its `blocks`, and
#: `claims(member, ctx)` says whether this kind owns a member (None = the
#: fallback kind, which claims whatever is left). A scored dict must carry
#: `slug id kind title health eyebrow jobs chip est_minutes tier pending legs
#: blocks review_chips notes path outcome` — the report, the record and the
#: renderer read those and nothing else, which is what lets the Cortex register
#: a `cortex` kind without either organ learning the other's vocabulary.
#:
#: Six keys are OPTIONAL, each with the dev reading as its default: `leg_order`
#: and `leg_titles` (a kind whose legs are not the dev six), `reviewable`
#: (False takes the member's review controls away and drops it from the
#: progress denominator), `state`, and `pending_line`/`clean_line` (the one
#: line the rulings list shows when nothing failed).
KINDS = {"dev": (score_dev, dev_blocks, None)}


# --------------------------------------------------------- collect() -------
def collect(mind: Path, slot: str, *, evidence: dict | None = None,
            kinds: dict | None = None, kind: str = "dev",
            cortex: dict | None = None) -> dict:
    """Score one slot. Reads three inputs, writes nothing.

    The record is the spine (it is the ledger of what was dispatched); the
    prompt supplies the question and the pre-registered witness; `active.md`
    supplies where the work landed. Evidence — PR state, checks, the witness
    verdict, the adversary leg — comes from outside, because nothing this
    conductor can reach offline knows whether a PR is green.

    `kind` names the ORGAN this slot belongs to, not the member kinds in it:
    `dev` reads a `PyAutoMind/batches/` record, `cortex` a
    `PyAutoCortex/batches/` one (its root arrives as `cortex["root"]`, and
    `mind` is that root too). The member kinds are still claimed per member —
    a Cortex record's members are `phases/…` paths and the `cortex` kind
    claims them.
    """
    kinds = kinds or KINDS
    root = cortex["root"] if (kind == "cortex" and cortex) else mind
    organ = organ_for(kind, root, slot)
    record_path = root / "batches" / f"{slot}.md"
    text = record_path.read_text(encoding="utf-8", errors="replace")
    rec = read_record(text)
    notes: list[str] = []
    for lineno, raw in rec["unparsable"]:
        notes.append(f"line {lineno} does not read as a member line — reported, "
                     f"not scored: {raw.strip()[:140]}")
    ctx = {"mind": mind, "root": root, "organ": organ, "slot": slot,
           "active": read_active(mind) if kind == "dev" else {},
           "evidence": evidence or {}, "notes": notes, "kinds": kinds,
           "cortex": cortex}

    if kind == "cortex":
        # A rolling slot may have more than one sitting — see `_merge_reviews`.
        review = _merge_reviews(_review_paths(root, slot))
    else:
        review_path = root / "batches" / "reviews" / f"{slot}.md"
        review = (read_review(review_path.read_text(encoding="utf-8",
                                                    errors="replace"))
                  if review_path.is_file() else None)
    ruled = {slug for slug, row in (review or {}).get("members", {}).items()
             if row.get("ruled") == "yes"}

    scored = []
    for member in rec["members"]:
        name = kind_of(member, ctx)
        score, blocks, _claims = kinds.get(name) or kinds["dev"]
        s = score(member, ctx)
        s.setdefault("kind", name)
        s.setdefault("id", f"m-{s['slug']}")
        if not s.get("blocks"):
            s["blocks"] = blocks(s)
        if name == "cortex" and not _on_the_board(s, ruled, notes):
            continue
        scored.append(s)
        notes += [f"{s['slug']}: {n}" for n in s.get("notes", [])]
    # Failures first, then what cannot be trusted, then the clean ones, then
    # what has not finished — the order TEMPLATE.md gives the packet. Within a
    # band, the most expensive review first: it is what the slot is spent on.
    scored.sort(key=lambda s: (HEALTHS.index(s["health"]), -s["est_minutes"],
                               s["slug"]))

    counts: dict[str, int] = {}
    for s in scored:
        counts[s["health"]] = counts.get(s["health"], 0) + 1
    ended = [s for s in scored if not s["pending"]]
    delivered = (sum(1 for s in ended if s["health"] in ("HEALTHY", "MERGED")),
                 len(ended))
    return {
        "slot": slot, "mind": mind, "root": root, "kind": kind,
        "organ": organ, "cortex": cortex,
        "carry": carried_members(cortex, record_path) if cortex else [],
        "record": str(record_path),
        "members": scored, "notes": notes, "counts": counts,
        "delivered": delivered,
        "est_minutes": sum(s["est_minutes"] for s in scored),
        "review": review,
        "not_delivered": [s["slug"] for s in scored
                          if s["health"] == "NOT-DELIVERED"],
        # Heart's release freeze, read at collect time: the packet is where a
        # human decides what to merge, so the window has to be on the page.
        # Empty whenever nothing is frozen (or Heart's state is absent — this
        # runs on a laptop, in CI and in a web container).
        "freeze": freeze_line(heart_freeze()),
        "rulings": [(s["slug"], _ruling_line(s)) for s in scored],
        "unparsable": rec["unparsable"],
        # `members` above is sorted by HEALTH, so it cannot drive a merge
        # order. Dispatch order is a property of the record — the order the
        # human listed the members in — and it is the order `--integration`
        # merges heads in, so the preview matches the shift.
        "dispatch_order": [m["slug"] for m in rec["members"]],
        "integration_requested": _yes(rec["keys"].get("integration")),
        # Read for `--push` only: `review-at` is what the default expiry of a
        # published ref hangs off, and a `sweep-after:` the human wrote is
        # theirs and wins over that default.
        "review_at": (rec["keys"].get("review-at") or [""])[0].strip(),
        "sweep_after": (rec["keys"].get("sweep-after") or [""])[0].strip(),
        "stamp": "",
    }


def _ruling_line(s: dict) -> str:
    """The one-line "why this needs you" for the rulings list.

    The legs are read through `leg_order`/`leg_titles` rather than the dev
    constants: a `cortex` member's six legs are the Cortex's own (`err`,
    `wall`, `version`, `checkpoint`, `resume`, `witness`), and a reader keyed
    to `pr`/`green` raises `KeyError` on every one of them.
    """
    order = s.get("leg_order", LEGS)
    titles = s.get("leg_titles", LEG_TITLES)
    for k in order:
        if s["legs"][k][0] == FAIL:
            return f"{s['health']} — {titles[k]}: {s['legs'][k][1]}"
    if s["pending"]:
        return s.get("pending_line") or (
            "PENDING — not finished at collect; refreshed during your read")
    for k in order:
        if s["legs"][k][0] == UNOBSERVABLE:
            return f"{s['health']} — {titles[k]}: {s['legs'][k][1]}"
    clean = s.get("clean_line") or (
        f"{s['legs']['green'][1]}; merge / tweak / reject")
    return f"{s['health']} — {clean}"


# ------------------------------------------------------- report and JSON ---
def _integ_detail(r: dict) -> str:
    """One repo's outcome, minus its name and its status word — what the packet
    puts after the chip and the report puts after both. Written once so the
    terminal and the page cannot report the same merge differently."""
    if r.get("status") == "skipped":
        return r.get("note") or "nothing to cut from"
    merged = ", ".join(r.get("merged") or [])
    detail = (f"{r.get('branch')} — {len(r.get('merged') or [])} member(s) "
              "merged" + (f": {merged}" if merged else ""))
    for c in r.get("conflicts") or []:
        paths = ", ".join(c.get("paths") or []) or "(no paths reported)"
        detail += (f"; {c['member']} ({c['branch']}) collides on {paths} — "
                   "left out")
    if r.get("pushed") and r.get("remote_branch"):
        detail += f"; pushed to origin/{r['remote_branch']}"
        if r.get("push_note"):
            detail += f" ({r['push_note']})"
    elif r.get("push_note"):
        detail += f"; NOT pushed — {r['push_note']}"
    return detail


def _integ_line(r: dict) -> str:
    return f"{r.get('repo', '')} — {r.get('status', '')} — {_integ_detail(r)}"


def _integration_report(d: dict) -> list:
    """The copy-paste line first, at the top of the report: the whole point of
    the leg is that the human can RUN the batch, and a `source …` line five
    screens down is a line nobody sources."""
    block = d.get("integration")
    if not block:
        return []
    L = ["## Integration branches", "",
         f"Run the whole batch: `source {block.get('activate', '')}`", ""]
    if block.get("pushed"):
        L += [f"Pushed for review; the branch sweep may delete these after "
              f"**{block.get('sweep_after') or '(no sweep-after)'}**. Never a "
              f"PR, never a base.", ""]
    L += [f"- {_integ_line(r)}" for r in block.get("repos") or []]
    return L + [""]


#: PyAutoHeart's freeze flag, read straight off its sidecar. Brain never
#: writes it — Heart owns the file (`PyAutoHeart/heart/freeze.py`), and this is
#: a read of state that lives on the same box, in the same spirit as the
#: profiling conductor's read of `~/.pyauto-heart`. A shell-out to
#: `pyauto-heart freeze --show --json` would say the same thing; the file read
#: keeps `collect` runnable where Heart is not on PATH.
HEART_STATE_DIR = Path(os.environ.get("HEART_STATE_DIR")
                       or Path.home() / ".pyauto-heart")


def heart_freeze(now: _dt.datetime | None = None,
                 state_dir: Path | None = None) -> dict:
    """`{"state": clear|active|expired, ...}` — Heart's reading, re-derived.

    Expiry is applied here rather than trusted from the file, so a flag whose
    window has passed reads as thawed even if nobody cleared it. Anything
    unreadable reads as clear: a freeze nobody can parse must not be able to
    stop a batch from being collected.
    """
    path = (state_dir or HEART_STATE_DIR) / "freeze.json"
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "clear"}
    if not isinstance(rec, dict):
        return {"state": "clear"}
    try:
        until = _dt.datetime.fromisoformat(str(rec.get("until", "")).replace("Z", "+00:00"))
    except ValueError:
        return {"state": "clear"}
    if until.tzinfo is None:
        until = until.replace(tzinfo=_dt.timezone.utc)
    ref = now or _dt.datetime.now(_dt.timezone.utc)
    return {**rec, "state": "active" if ref < until else "expired"}


def collect_report(d: dict) -> str:
    L = [f"# Batch collect {d['slot']}", ""]
    if d["not_delivered"]:
        # First and loud, per `batches/AGENTS.md` — this is the one finding a
        # human must not have to scroll for.
        n, total = len(d["not_delivered"]), d["delivered"][1]
        by_slug = {s["slug"]: s for s in d["members"]}
        why = ", ".join(
            f"{slug} ({_short(by_slug[slug]['legs']['pr'][1] if by_slug[slug]['legs']['pr'][0] == FAIL else _evidence_line(by_slug[slug]))})"
            for slug in d["not_delivered"])
        L += [f"**NOT DELIVERED — {n} of {total}**: {why}", ""]
    if d.get("freeze"):
        # One line, above the members: whoever reads this packet is deciding
        # what to merge, and a library merge landing inside a validation window
        # restales the whole rehearsal. `/prm` is what actually stops.
        L += [f"**{d['freeze']}** — library `main`s are frozen; `/prm` will "
              "refuse a library PR until it clears (`--thaw` overrides, "
              "logged).", ""]
    L += _integration_report(d)
    for s in d["members"]:
        L += _member_report(s)
    if d["review"] is not None:
        L += ["## Review submitted", "",
              f"`batches/reviews/{d['slot']}.md` exists — the packet is not "
              "rewritten after a review. Decisions are reported, never enacted:",
              ""]
        for slug, row in d["review"]["members"].items():
            L.append(f"- {slug}: {row['decision'] or '(none)'} "
                     f"(ruled {row['ruled'] or 'no'})")
        L.append("")
    if d["notes"]:
        L += ["## Notes", ""] + [f"- {n}" for n in d["notes"]] + [""]
    return "\n".join(L) + "\n"


def _member_report(s: dict) -> list:
    L = [f"## {s['slug']} — {s['health']}", ""]
    facets = [x for x in (f"`{s['path']}`" if s["path"] else "", s["eyebrow"],
                          f"{s['est_minutes']} est. review-minutes") if x]
    L += [" — ".join(facets), ""]
    for label, body in s["blocks"]:
        L += [f"**{label}**", "", body, ""]
    return L


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def emit_collect(d: dict, out: str = "") -> None:
    n, total = d["delivered"]
    print(f"collect {d['slot']}: {len(d['members'])} members, "
          f"delivered {n}/{total}")
    if d.get("freeze"):
        print(d["freeze"])
    body = collect_report(d)
    if out:
        Path(out).write_text(body, encoding="utf-8")
        print(f"Wrote: {out}")
    else:
        print(body, end="")


# ------------------------------------------------------------ the packet ---
def _asset(name: str) -> str:
    """The CSS and JS live beside this file. They are full of `{`, `}` and `%`
    — every one of which a `.format`/`%`/`Template` pass would eat — so they
    are read verbatim and only `%%TOKEN%%` placeholders are substituted."""
    return (Path(__file__).resolve().parent / name).read_text(encoding="utf-8")


def _e(value) -> str:
    return html.escape(str(value), quote=True)


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_EM_RE = re.compile(r"(?<![\w*])_([^_]+)_(?![\w*])")


def _inline(text: str) -> str:
    """Inline markdown → HTML, escaped FIRST so nothing in a record, a prompt
    or a check name can inject markup. (Escaping first also means a `&` inside
    a link target arrives as `&amp;`; no url this page emits carries one.)"""
    out = _e(text)
    out = _MD_LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
                          out)
    out = _MD_CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _MD_BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = _MD_EM_RE.sub(lambda m: f"<em>{m.group(1)}</em>", out)
    return out


def _md_table(rows: list) -> str:
    cells = [[c.strip() for c in row.strip().strip("|").split("|")]
             for row in rows]
    head, body = cells[0], cells[2:] if len(cells) > 1 else []
    out = ['<div class="scroll"><table>', "<thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in head]
    out += ["</tr></thead>", "<tbody>"]
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row)
                   + "</tr>")
    out += ["</tbody>", "</table></div>"]
    return "".join(out)


def _md_to_html(body: str) -> str:
    """The small subset the blocks are written in: paragraphs, `- ` lists and
    pipe tables. One block shape feeds the markdown report and this page, so
    neither surface can drift from the other."""
    lines = body.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_md_table(block))
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(_inline(lines[i][2:]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items)
                       + "</ul>")
            continue
        if not line.strip():
            i += 1
            continue
        para = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith(("- ", "|"))):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out)


def render_member_section(s: dict) -> str:
    """One `<section class="member …" id="m-<slug>">`, self-contained.

    Self-contained is load-bearing: the refresh replaces exactly this span and
    nothing else, so everything a member needs — including its review controls,
    whose state the human may already have typed — has to live inside it.

    A member that is not `reviewable` (a RUNNING science phase) renders with no
    Ruled box and no decision chips: `PyAutoCortex/batches/AGENTS.md` says
    nothing in `submitted`/`running` holds review control, and carry-forward —
    not an unclickable chip — is what moves it to the next board. The note
    textarea stays, because a human starts noting on a running member long
    before it finishes.
    """
    sev = HEALTH_SEV.get(s["health"], "suspect")
    reviewable = s.get("reviewable", True)
    if not reviewable:
        classes, chip_cls = "member running", "chip-running"
    elif s["pending"]:
        classes, chip_cls = "member pending", "chip-pending"
    else:
        classes, chip_cls = "member", f"chip-{sev}"
    mid = _e(s["id"])
    L = [f'<section class="{classes} sev-{sev}" id="{mid}">',
         '  <div class="m-head">',
         '    <div class="m-head-main">',
         f'      <p class="eyebrow">{_e(s["eyebrow"] or s["kind"])}</p>',
         f'      <h2>{_e(s["title"])}</h2>',
         f'      <p class="jobs">{_e(s["jobs"])}</p>',
         '    </div>',
         '    <div class="m-head-side">',
         f'      <span class="chip {chip_cls}">{_e(s["chip"])}</span>']
    if reviewable:
        L.append(f'      <label class="ruled"><input type="checkbox" '
                 f'data-ruled="{mid}"> Ruled</label>')
    L += ['    </div>',
          '  </div>',
          '  <div class="blocks">']
    for label, body in s["blocks"]:
        if label == "Ruling":
            L += ['    <div class="block ruling">',
                  '      <p class="label">Ruling</p>',
                  f'      <p class="decision">{_inline(body)}</p>',
                  '    </div>']
            continue
        L += ['    <div class="block">',
              f'      <p class="label">{_e(label)}</p>',
              _indent(_md_to_html(body), 6),
              '    </div>']
    # Present on PENDING members too, deliberately: the reference packet found
    # that a human starts noting on a running member long before it finishes,
    # and a refresh that withheld the controls would drop those notes.
    L += ['    <div class="block yourreview">',
          '      <p class="label">Your review</p>']
    if reviewable:
        L.append('      <div class="rchips" role="radiogroup" '
                 'aria-label="Decision">')
        for value, label in s["review_chips"]:
            L.append(f'        <label class="rchip"><input type="radio" '
                     f'name="rv-{mid}" value="{_e(value)}" '
                     f'data-decision="{mid}">'
                     f'<span>{_e(label)}</span></label>')
        L.append('      </div>')
    else:
        L.append('      <p class="runnote">Still running — no review control '
                 'until its results are pulled. A note here is kept.</p>')
    L += [f'      <textarea class="notetext" data-note="{mid}" rows="2" '
          'placeholder="One line is enough — a tweak note becomes a queued '
          'follow-up prompt."></textarea>',
          '    </div>',
          f'    <p class="chip chip-min">Est. {_e(s["est_minutes"])} '
          f'review-minutes · {_e(s["tier"] or s["kind"])}</p>',
          '  </div>',
          '</section>']
    return "\n".join(L)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.split("\n"))


def section_span(html_text: str, member_id: str) -> tuple | None:
    """`(start, end)` of the member section carrying this id, `</section>`
    included — depth-aware, because a member block may nest a section."""
    needle = f'id="{member_id}"'
    pos = 0
    while True:
        start = html_text.find("<section", pos)
        if start < 0:
            return None
        gt = html_text.find(">", start)
        if gt < 0:
            return None
        tag = html_text[start:gt]
        if 'class="member' in tag and needle in tag:
            depth, i = 0, start
            while i < len(html_text):
                nxt_open = html_text.find("<section", i)
                nxt_close = html_text.find("</section>", i)
                if nxt_close < 0:
                    return None
                if 0 <= nxt_open < nxt_close:
                    depth += 1
                    i = nxt_open + len("<section")
                else:
                    depth -= 1
                    i = nxt_close + len("</section>")
                    if depth == 0:
                        return start, i
            return None
        pos = gt + 1


def _member_spans(html_text: str) -> list:
    """Every member section in the page, in page order."""
    spans, pos = [], 0
    while True:
        start = html_text.find("<section", pos)
        if start < 0:
            return spans
        gt = html_text.find(">", start)
        if gt < 0:
            return spans
        tag = html_text[start:gt]
        got = re.search(r'id="([^"]+)"', tag)
        if 'class="member' in tag and got:
            span = section_span(html_text, got.group(1))
            if span:
                spans.append((span[0], span[1], got.group(1)))
                pos = span[1]
                continue
        pos = gt + 1


def splice(html_text: str, start: int, end: int, new: str) -> str:
    return html_text[:start] + new + html_text[end:]


def replace_region(html_text: str, name: str, new: str) -> tuple:
    """Rewrite one sentinelled region. `(html, replaced)` — a page with no
    sentinels for it is left ALONE, never guessed at."""
    begin, end = f"<!-- pyauto:{name}:begin -->", f"<!-- pyauto:{name}:end -->"
    i, j = html_text.find(begin), html_text.find(end)
    if i < 0 or j < 0 or j < i:
        return html_text, False
    return (html_text[:i + len(begin)] + "\n" + new.strip("\n") + "\n"
            + html_text[j:]), True


_GENERATED_RE = re.compile(r"Generated ([^·<]+)")


def _mind_home(mind: Path) -> str:
    """`https://github.com/<owner>/PyAutoMind`, read from the checkout rather
    than named here — a fork's packets must point at the fork, and organ code
    names no GitHub owner (the Mind's tenant firewall). The `origin` remote is
    tried first, then a page that travels with the repo; with neither there is
    no home, and the packet's Commit-on-GitHub button says so instead of
    guessing one."""
    try:
        r = subprocess.run(["git", "-C", str(mind), "config", "--get",
                            "remote.origin.url"], capture_output=True,
                           text=True, timeout=10)
        m = re.search(r"github\.com[:/]([\w.-]+)/PyAutoMind", r.stdout)
        if r.returncode == 0 and m:
            return f"https://github.com/{m.group(1)}/PyAutoMind"
    except (OSError, subprocess.SubprocessError):
        pass
    for name in ("README.md", "AGENTS.md"):
        f = mind / name
        if f.is_file():
            m = re.search(r"https://github\.com/([\w.-]+)/PyAutoMind",
                          f.read_text(encoding="utf-8", errors="replace"))
            if m:
                return f"https://github.com/{m.group(1)}/PyAutoMind"
    return ""


def _tiles(d: dict) -> str:
    L = ['<section class="tiles" aria-label="Summary">',
         f'  <div class="tile"><span class="num">{len(d["members"])}</span>'
         '<span class="cap">Members</span></div>']
    for health in HEALTHS:
        n = d["counts"].get(health, 0)
        if not n:
            continue
        L.append(f'  <div class="tile t-{HEALTH_SEV[health]}">'
                 f'<span class="num">{n}</span>'
                 f'<span class="cap">{_e(health.title())}</span></div>')
    total = d["est_minutes"]
    addition = " + ".join(str(s["est_minutes"]) for s in d["members"]) or "0"
    L += ['  <div class="tile t-minutes">',
          f'    <span class="num">{total}</span>',
          '    <span class="cap">Est. review-minutes</span>',
          f'    <span class="sum">{_e(addition)}</span>',
          f'    <span class="foot">delivered {d["delivered"][0]} of '
          f'{d["delivered"][1]} ended member(s)</span>',
          '  </div>', '</section>']
    return "\n".join(L)


def _rulings(d: dict) -> str:
    L = ['<section class="panel" id="rulings">', '  <h2>Rulings needed</h2>',
         '  <ol class="rulings">']
    for slug, line in d["rulings"]:
        L.append(f'    <li><span class="who"><a href="#m-{_e(slug)}">'
                 f'{_e(slug)}</a></span> — {_e(line)}</li>')
    if not d["rulings"]:
        L.append("    <li>No members in this record.</li>")
    L += ['  </ol>', '</section>']
    return "\n".join(L)


CHIP_FOR_STATUS = {"clean": "chip-healthy", "conflicted": "chip-failed",
                   "skipped": "chip-pending"}


def _integration_panel(d: dict) -> str:
    """The integration block, rendered. Every value goes through `_e` and the
    panel carries no `data-*` hook: `packet.js` queries `[data-ruled]`,
    `[data-decision]`, `[data-note]` and `[data-meta]` only, and there is
    nothing for the human to *rule* about a merge preview — it is a finding they
    read, not a control they operate."""
    block = d.get("integration")
    if not block:
        return ""
    root = block.get("root", "")
    # The lede tells the truth about THIS block: "nothing is pushed" is a
    # promise the panel may no longer be able to make.
    pushed = bool(block.get("pushed"))
    lede = ('One throwaway worktree root merges every member&#x27;s head '
            'branch per repo, off <code>origin/main</code>. '
            + ('Nothing is resolved: a member whose merge conflicts is left '
               'out and named.' if pushed else
               'Nothing is pushed and nothing is resolved: a member whose '
               'merge conflicts is left out and named.'))
    L = ['<section class="panel" id="integration">',
         '  <h2>Integration branches</h2>',
         f'  <p>{lede}</p>',
         f'  <p><code>source {_e(block.get("activate", ""))}</code></p>']
    if pushed:
        L.append(
            '  <p class="smallprint">Pushed for review; the branch sweep may '
            'delete these after <strong>'
            f'{_e(block.get("sweep_after") or "(no sweep-after)")}</strong>. '
            'Never a PR, never a base. A pushed branch carries only the '
            'members that merged — each one named <code>left out</code> below '
            'is not in it.</p>')
    L += ['  <p class="smallprint">Once that is sourced, a <strong>library</strong> '
         'change is live anywhere — it is on the <code>PYTHONPATH</code>. A '
         '<strong>workspace</strong> member is a real worktree but is not on the '
         'PYTHONPATH, so run its script from inside '
         f'<code>{_e(root)}/&lt;workspace&gt;</code>.</p>',
         '  <ul class="integ">']
    for r in block.get("repos") or []:
        status = str(r.get("status") or "")
        chip = CHIP_FOR_STATUS.get(status, "chip-pending")
        L.append(f'    <li><span class="who">{_e(r.get("repo", ""))}</span> '
                 f'<span class="chip {chip}">{_e(status)}</span> — '
                 f'{_e(_integ_detail(r))}</li>')
    if not (block.get("repos") or []):
        L.append("    <li>No repo had a mergeable member head.</li>")
    L += ['  </ul>', '</section>']
    return "\n".join(L)


def _sidenav(d: dict) -> str:
    L = ['<nav class="sidenav" aria-label="Members">',
         '  <p class="navhead">Members</p>', '  <ul>']
    for s in d["members"]:
        sev = HEALTH_SEV.get(s["health"], "suspect")
        L.append(f'    <li><a href="#{_e(s["id"])}" data-nav="{_e(s["id"])}">'
                 f'{_e(s["slug"])}<span class="mini m-{sev}">'
                 f'{_e(s["health"])} · {s["est_minutes"]} min</span></a></li>')
    L += ['  </ul>', '</nav>']
    return "\n".join(L)


def _organ(d: dict) -> dict:
    """The organ this packet belongs to. A `d` assembled by hand (a test, an
    older caller) still renders: the Mind is the default, as it always was."""
    return d.get("organ") or organ_for("dev", d.get("mind") or Path("."),
                                       d["slot"])


def _members_js(d: dict) -> str:
    members = [{"id": s["id"], "slug": s["slug"], "health": s["health"],
                "reviewable": s.get("reviewable", True)}
               for s in d["members"]]
    # `<` escaped to its JSON `\u003c` escape — still valid JSON, and the one
    # thing that keeps a slug reading `</script>` from ending the script tag
    # early. Every other interpolation goes through `_e`; this one cannot,
    # because it must stay parseable JSON.
    payload = json.dumps(members, indent=2, ensure_ascii=False).replace(
        "<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    js = _asset("packet.js")
    organ = _organ(d)
    home = organ["home"]
    for token, value in (
            ("%%MEMBERS_JSON%%", payload),
            ("%%SLOT%%", d["slot"]),
            ("%%PACKET_PATH%%", organ["packet_path"]),
            ("%%REVIEW_PATH%%", organ["review_path"]),
            ("%%FOLLOWUPS_HEADING%%", organ["followups_heading"]),
            ("%%DEFAULT_DECISION%%", organ["default_decision"]),
            ("%%GITHUB_NEW%%", (f"{home}/new/main" if home else ""))):
        js = js.replace(token, value)
    return "<script>\n" + js + "</script>"


def _callout(d: dict) -> str:
    if _organ(d)["key"] == "cortex":
        return _cortex_callout(d)
    if d["not_delivered"]:
        by_slug = {s["slug"]: s for s in d["members"]}
        items = "".join(
            f"<li><a href=\"#m-{_e(slug)}\">{_e(slug)}</a> — "
            f"{_e(_short(_evidence_line(by_slug[slug]), 140))}</li>"
            for slug in d["not_delivered"])
        return (f'<section class="callout" aria-label="Most important finding">'
                f'\n  <p class="eyebrow">Most important finding</p>\n'
                f'  <p>{len(d["not_delivered"])} member(s) did not deliver. A '
                f'session that ends green is not a delivered task — these have '
                f'no PR, an empty diff, or checks that never ran.</p>\n'
                f'  <ul>{items}</ul>\n</section>')
    return ('<section class="callout ok" aria-label="Most important finding">\n'
            '  <p class="eyebrow">Most important finding</p>\n'
            f'  <p>Every ended member of this slot produced a PR with a '
            f'non-empty diff and checks that ran. '
            f'{_e(d["counts"].get("SUSPECT", 0))} still need your eyes for a '
            f'leg the collect could not observe.</p>\n</section>')


def _stamp_block(d: dict, generated: str, stamp: str) -> str:
    return "\n".join([
        f'<p class="stampline">Generated {_e(generated)} · refreshed '
        f'{_e(stamp)}</p>',
        f'<p class="stampline">Permanent home: '
        f'<code>batches/packets/{_e(d["slot"])}.html</code></p>'])


PACKET_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Slot Review %%SLOT%%</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
%%CSS%%
</style>
</head>
<body>
"""


def _fresh_packet(d: dict, stamp: str) -> str:
    slot = d["slot"]
    head = PACKET_HEAD.replace("%%CSS%%", _asset("packet.css")).replace(
        "%%SLOT%%", _e(slot))
    organ = _organ(d)
    n, total = d["delivered"]
    # The progress line counts what can actually be ruled: a RUNNING science
    # member holds no review control, so a denominator that included it would
    # never reach "all decided" however complete the review was.
    votes = sum(1 for s in d["members"] if s.get("reviewable", True))
    L = [head, '<div class="page">', '', '<header class="pagehead">',
         f'  <p class="eyebrow">{_e(slot)} · batch collect · '
         f'{len(d["members"])} member(s)</p>',
         f'  <h1>Slot Review — {_e(slot)}</h1>',
         '  <p class="lede">'
         + organ["lede"].format(n=n, total=total)
         + ' Choose a decision and leave a note on each member, then '
         '<strong>Submit review</strong> at the bottom; the review lands in '
         f'<code>{_e(organ["review_path"])}</code> for the orchestrator to '
         'enact.</p>',
         '<!-- pyauto:stamp:begin -->',
         _stamp_block(d, stamp, stamp),
         '<!-- pyauto:stamp:end -->',
         '</header>', '',
         '<!-- pyauto:tiles:begin -->', _tiles(d), '<!-- pyauto:tiles:end -->',
         '',
         '<section class="inputsbar" aria-label="Review metadata">',
         '  <div class="field">',
         '    <label for="in-reviewed-at">Reviewed at</label>',
         '    <input type="text" id="in-reviewed-at" data-meta="reviewedAt" '
         'placeholder="auto-filled">',
         '  </div>',
         '  <div class="field">',
         '    <label for="in-minutes">Review-minutes-actual</label>',
         '    <input type="number" id="in-minutes" data-meta="minutes" min="0" '
         'step="1" placeholder="e.g. 60">',
         '  </div>',
         '  <p class="inputshint">The minutes figure is the only calibration '
         'the review-cost estimate ever gets.</p>',
         '</section>', '',
         _callout(d), '',
         '<!-- pyauto:rulings:begin -->', _rulings(d),
         '<!-- pyauto:rulings:end -->', '',
         # The sentinels ship even when the body is empty, so a LATER
         # `--integration` refresh of this same page has somewhere to splice
         # into. A region that only appears once it has content can never be
         # filled in place.
         '<!-- pyauto:integration:begin -->', _integration_panel(d),
         '<!-- pyauto:integration:end -->', '',
         '<div class="shell">', '',
         '<!-- pyauto:sidenav:begin -->', _sidenav(d),
         '<!-- pyauto:sidenav:end -->', '',
         '<div class="content">', '',
         '<!-- pyauto:members:begin -->']
    for s in d["members"]:
        L += [render_member_section(s), '']
    L += ['<!-- pyauto:members:end -->', '',
          '</div>', '</div>', '',
          '<div class="submitspacer"></div>',
          '</div>', '',
          '<div class="submitbar">',
          f'  <p class="progresscount" id="progress-count">Ruled 0 of '
          f'{votes} · decisions 0 of {votes}</p>',
          '  <button type="button" class="btn btn-primary" id="btn-submit">'
          'Submit review</button>',
          '</div>', '',
          '<div class="modal" id="submit-modal" hidden>',
          '  <div class="modal-panel" role="dialog" aria-modal="true" '
          'aria-labelledby="modal-title">',
          '    <div class="modal-head">',
          '      <h2 id="modal-title">Submit review</h2>',
          '      <button type="button" class="btn" id="btn-close">Close'
          '</button>',
          '    </div>',
          '    <p class="modal-hint"><strong>Copy</strong> always works — '
          'paste it into the orchestrator chat, or commit it yourself.</p>',
          '    <div class="modal-actions">',
          '      <button type="button" class="btn btn-primary" id="btn-copy">'
          'Copy to clipboard</button>',
          '      <button type="button" class="btn" id="btn-download">'
          'Download .md</button>',
          '      <a class="btn" id="btn-github" target="_blank" '
          'rel="noopener">Commit on GitHub</a>',
          '    </div>',
          f'    <p class="smallprint" id="gh-hint">Commit opens a prefilled '
          f'new-file editor at <code>{_e(organ["review_path"])}</code> (you '
          'press the green commit button there).</p>',
          '    <p class="smallprint">Downloads are inert when this page is '
          'viewed inside an artifact sandbox — use Copy there; Download works '
          'from the archived copy.</p>',
          '    <pre class="mdpreview" id="md-preview"></pre>',
          '    <p class="modal-final">Last step: tell the orchestrator chat '
          '“review submitted”.</p>',
          '  </div>',
          '</div>', '',
          '<!-- pyauto:members-js:begin -->', _members_js(d),
          '<!-- pyauto:members-js:end -->', '',
          '</body>', '</html>', '']
    return "\n".join(L)


def packet_html(d: dict, existing: str | None = None) -> tuple:
    """`(html, notes)` — the packet page, fresh or refreshed IN PLACE.

    A refresh never rewrites the page: it replaces each member's own section
    and the regenerable regions between their sentinels, and leaves every other
    byte alone. That is what lets the human keep reading a packet while the
    overnight members fill in under them, and it is why an archived
    hand-authored page (no sentinels) degrades to member splices plus a note
    rather than being regenerated wholesale.
    """
    stamp = d.get("stamp") or _utc_now()
    if existing is None:
        return _fresh_packet(d, stamp), []
    notes: list[str] = []
    out = existing
    generated = (_GENERATED_RE.search(existing).group(1).strip()
                 if _GENERATED_RE.search(existing) else stamp)
    missing = []
    for s in d["members"]:
        span = section_span(out, s["id"])
        if span:
            out = splice(out, span[0], span[1], render_member_section(s))
        else:
            missing.append(s)
    if missing:
        block = "\n".join(render_member_section(s) for s in missing) + "\n"
        at = out.find("<!-- pyauto:members:end -->")
        if at >= 0:
            out = out[:at] + block + out[at:]
        else:
            spans = _member_spans(out)
            at = spans[-1][1] if spans else out.find("</body>")
            if at < 0:
                at = len(out)
            out = out[:at] + "\n" + block + out[at:]
            notes.append(
                f"packet has no pyauto:members sentinels — {len(missing)} new "
                "member section(s) appended after the last existing one; this "
                "page was not written by this renderer")
    regions = [
        ("stamp", _stamp_block(d, generated, stamp), "header stamp"),
        ("tiles", _tiles(d), "stat tiles"),
        ("rulings", _rulings(d), "rulings list"),
        ("sidenav", _sidenav(d), "sidenav"),
        ("members-js", _members_js(d), "MEMBERS array"),
    ]
    # Only when this collect HAS an integration block. A plain refresh must not
    # blank the region the last `--integration` filled: the merge preview is
    # still true, and the human is reading it.
    if d.get("integration"):
        regions.append(("integration", _integration_panel(d),
                        "integration branches"))
    for name, new, what in regions:
        out, ok = replace_region(out, name, new)
        if not ok:
            notes.append(f"packet has no pyauto:{name} sentinels — member "
                         f"sections refreshed, {what} left alone")
    return out, notes


# ------------------------------------------------------------- the record ---
def _evidence_line(s: dict) -> str:
    """The one line the record's outcome column carries — the first leg that
    explains the health, never a summary of all six."""
    order = s.get("leg_order", LEGS)
    titles = s.get("leg_titles", LEG_TITLES)
    for k in order:
        if s["legs"][k][0] == FAIL:
            return _short(f"{titles[k]}: {s['legs'][k][1]}", 160)
    if s["pending"]:
        return _short(s["outcome"] or "still in flight", 160)
    for k in order:
        if s["legs"][k][0] == UNOBSERVABLE:
            return _short(f"{titles[k]}: {s['legs'][k][1]}", 160)
    if s.get("clean_line"):
        return _short(s["clean_line"], 160)
    return _short(f"{s['legs']['pr'][1]}; {s['legs']['green'][1]}", 160)


def _set_key(lines: list, rec: dict, key: str, value: str,
             inserts: list) -> None:
    """Replace the first line for this key in place, or queue an insert. Key
    ORDER varies between records (the am record writes `packet:` before
    `collected:`), so nothing here may assume a position."""
    line = f"- {key}: {value}"
    if rec["key_lines"].get(key):
        lines[rec["key_lines"][key][0] - 1] = line
    else:
        inserts.append(line)


def _insert_anchor(rec: dict) -> int:
    """Where a new key goes: immediately before `- notes:` when there is one.
    Never inside or after that block — its body is prose, and a `- key:` line
    indented into it is not a key at all."""
    notes = rec["key_lines"].get("notes")
    if notes:
        return notes[0] - 1
    last = rec["members_end"]
    for linenos in rec["key_lines"].values():
        last = max(last, max(linenos))
    return last


def _fill_key(lines: list, rec: dict, key: str, value: str,
              inserts: list) -> None:
    """Like `_set_key`, but only where the record has no value yet (or the
    placeholder `(not given)`). The close leg fills what the human left blank;
    a `reviewed-at:` someone already wrote — the pm record's carries a whole
    clause about where the review sat — is theirs, and stays."""
    have = [v for v in rec["keys"].get(key, []) if v and v != "(not given)"]
    if not have:
        _set_key(lines, rec, key, value, inserts)


def record_update(text: str, d: dict, stamp: str) -> str:
    """The batch record, updated in place — line by line, never re-serialised.

    A member whose outcome already opens with a ruling word is left exactly as
    it is: the am record's `REJECTED`/`ACCEPTED` lines are a review that
    happened, and this verb's own earlier verdicts are the same. Rewriting one
    would erase a human's sentence with a machine's. And once the slot's
    review has landed, NO member line changes: the record is the history of a
    batch that closed, and the pm record's `PR OPENED AT REVIEW (…)` sentences
    are exactly the kind of outcome no word list would have protected.
    """
    lines = text.split("\n")
    rec = read_record(text)
    by_slug = {m["slug"]: m for m in rec["members"]}
    closed = d.get("review") is not None
    for s in d["members"]:
        m = by_slug.get(s["slug"])
        if m is None or closed:
            continue
        words = (m["outcome"] or "").split()
        first = words[0].strip("(,.").upper() if words else ""
        if first in RULING_WORDS:
            continue
        lines[m["lineno"] - 1] = (
            f"  - {s['slug']}: {m['path']} — {m['tier']} — {m['minutes']} — "
            f"{s['health']} ({_evidence_line(s)})")

    inserts: list[str] = []
    if not rec["key_lines"].get("collected"):
        inserts.append(f"- collected: {stamp}")
    n, total = d["delivered"]
    # An open batch's `delivered:`/`packet:` are collect's own and move with
    # every apply; a closed batch's are history (the pm record's `delivered:`
    # is a sentence about what the shift produced) and are filled, not set.
    put = _fill_key if closed else _set_key
    put(lines, rec, "delivered", f"{n}/{total}", inserts)
    put(lines, rec, "packet", f"batches/packets/{d['slot']}.html", inserts)
    block = d.get("integration")
    if block and not closed:
        # A SEPARATE key from the dispatch-time `- integration: yes`. That line
        # is the human's REQUEST; overwriting it with a path would erase what
        # they asked for and leave only what happened.
        clean = sum(1 for r in block.get("repos") or []
                    if r.get("status") == "clean")
        bad = sum(1 for r in block.get("repos") or []
                  if r.get("status") == "conflicted")
        _set_key(lines, rec, "integration-root",
                 f"{block.get('root', '')} — {block.get('branch', '')}; "
                 f"{clean} clean, {bad} conflicted", inserts)
        # What was PUBLISHED, per repo, under the name `branch_sweep.sh --name`
        # matches on. Rewritten on every push, because the current publication
        # is the truth; `sweep-after:` is filled once and never overwritten,
        # because the date a human typed is a decision about their own review.
        remotes = [f"{r['dir']}:{r['remote_branch']}"
                   for r in block.get("repos") or [] if r.get("remote_branch")]
        if remotes:
            _set_key(lines, rec, "integration-remote", ", ".join(remotes),
                     inserts)
            if block.get("sweep_after"):
                _fill_key(lines, rec, "sweep-after", block["sweep_after"],
                          inserts)
    review = d.get("review")
    if review is not None:
        _fill_key(lines, rec, "review",
                  f"batches/reviews/{d['slot']}.md", inserts)
        reviewed_at = review["keys"].get("reviewed-at", "")
        if reviewed_at:
            _fill_key(lines, rec, "reviewed-at", reviewed_at, inserts)
        minutes = review["keys"].get("review-minutes-actual", "")
        if minutes and minutes != "(not given)":
            _fill_key(lines, rec, "review-minutes-actual", minutes, inserts)
    inserts.append(f"- refreshed: {stamp} — collect "
                   f"({len(d['members'])} member(s))")
    at = _insert_anchor(rec)
    lines[at:at] = inserts
    return "\n".join(lines)


def apply_collect(mind: Path, d: dict, stamp: str) -> list:
    """Write the record and the packet. Returns the notes; writes nothing when
    the rehearsal finds the rewritten record has lost anything."""
    notes: list[str] = []
    record = mind / "batches" / f"{d['slot']}.md"
    before = record.read_text(encoding="utf-8", errors="replace")
    after = record_update(before, d, stamp)
    problems = _rehearse_record(mind, before, after)
    if problems:
        return [f"record NOT written — the rewrite loses something: {p}"
                for p in problems]
    record.write_text(after, encoding="utf-8")
    notes.append(f"record updated: batches/{d['slot']}.md")
    return notes + _apply_packet(mind, d)


def _apply_packet(root: Path, d: dict) -> list:
    """The packet leg of an apply — the same one for both organs, because the
    page is the same page. Written under the organ's own `batches/packets/`."""
    notes: list[str] = []
    packet = root / "batches" / "packets" / f"{d['slot']}.html"
    if d.get("kind") != "cortex" and d.get("review") is not None:
        # `batches/packets/AGENTS.md`: the archived page and the review file are
        # the audit pair — what was shown, what was ruled. A correction gets a
        # new dated page, not an edit. A dev batch is reviewed once — this is
        # the WHOLE close. A Cortex slot is a rolling board (`batches/AGENTS.md`,
        # "The first review does not close the slot"): a review lands, more
        # members may still join the board, and the packet keeps refreshing
        # under `d["members"]` (which `_on_the_board` already keeps the ruled
        # ones out of) until nothing is left on it.
        notes.append("review submitted — the packet is never rewritten after a "
                     f"review; batches/reviews/{d['slot']}.md is the record now")
        return notes
    existing = (packet.read_text(encoding="utf-8", errors="replace")
                if packet.is_file() else None)
    page, pnotes = packet_html(d, existing)
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(page, encoding="utf-8")
    notes += pnotes
    notes.append(("packet refreshed" if existing is not None
                  else "packet written") + f": batches/packets/{d['slot']}.html")
    return notes


def _rehearse_record(mind: Path, before: str, after: str) -> list:
    """Re-read the rewritten record from a throwaway copy of `batches/` before
    it is written for real. The Cortex's collect does the same, for the same
    reason: a partial write of a ledger has no way back."""
    tmp = Path(tempfile.mkdtemp(prefix="batch-collect-"))
    try:
        copy = tmp / "batches"
        shutil.copytree(mind / "batches", copy, symlinks=True)
        rehearsal = copy / "rehearsal.md"
        rehearsal.write_text(after, encoding="utf-8")
        again = read_record(rehearsal.read_text(encoding="utf-8"))
    except OSError as e:
        return [f"the rehearsal copy could not be made ({e})"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    was = read_record(before)
    problems = []
    got = {m["slug"] for m in again["members"]}
    for m in was["members"]:
        if m["slug"] not in got:
            problems.append(f"member `{m['slug']}` no longer parses")
    for key in was["keys"]:
        if key not in again["keys"]:
            problems.append(f"key `{key}` disappeared")
    if len(again["unparsable"]) > len(was["unparsable"]):
        problems.append("a member line stopped parsing")
    return problems


# --------------------------------------------------------- the close leg ---
REVIEW_HEAD_RE = re.compile(r"^## (?P<slug>.+?)(?:\s+—\s+(?P<health>[A-Z-]+))?$")
REVIEW_KEY_RE = re.compile(r"^- (decision|ruled|note): (.*)$")


def read_review(text: str) -> dict:
    """`batches/reviews/<slot>.md` — what the human ruled, verbatim.

    Read, reported, and never enacted: `batches/reviews/AGENTS.md` gives the
    close-out to the orchestrator, and a review never executes its own
    follow-ups.
    """
    keys: dict[str, str] = {}
    members: dict[str, dict] = {}
    slug = None
    for raw in text.split("\n"):
        line = _dash(raw)
        head = REVIEW_HEAD_RE.match(line)
        if head:
            name = head.group("slug").strip()
            if name.lower().startswith("follow-up"):
                slug = None
                continue
            slug = name
            members[slug] = {"health": head.group("health") or "",
                             "decision": "", "ruled": "", "note": []}
            continue
        if slug is None:
            m = RECORD_KEY.match(line)
            if m:
                keys[m.group(1)] = (m.group(2) or "").strip()
            continue
        m = REVIEW_KEY_RE.match(line)
        if m:
            if m.group(1) == "note":
                members[slug]["note"].append(m.group(2).strip())
            else:
                members[slug][m.group(1)] = m.group(2).strip()
        elif line.strip() and not line.startswith("<!--"):
            members[slug]["note"].append(line.strip())
    for row in members.values():
        row["note"] = " ".join(x for x in row["note"] if x)
    return {"keys": keys, "members": members}


# ================================================================= cortex ===
# The second member kind: a phase of a science project, on a rolling board.
#
# The dependency runs ONE WAY. This module imports the cortex conductor; the
# cortex conductor imports nothing of this one and nothing of the Mind's,
# because it renders the Cortex's own board inside that repo's
# `dashboard_refresh.yml`, where no PyAutoMind checkout exists. So everything
# the science side knows — the admission rule, the six legs, the packet block,
# the state table — is ASKED of `_cortex` here and never re-implemented, which
# is what keeps the two surfaces from drifting.

CORTEX_CONDUCTOR = BRAIN / "agents" / "conductors" / "cortex" / "_cortex.py"
_CX = None

# `CORTEX_BOARD_STATES` is `_status`'s (imported above) — the four states a
# science member is on the board in. `ready` and `planned` are scope;
# `accepted`, `rerun` and `dropped` are history the rulings ledger carries. A
# record naming one of those is reported, never scored.

#: The Cortex's review vocabulary (`scripts/cortex.py::RULING_VERBS`), not the
#: Mind's merge/tweak/reject/defer. A RUNNING member gets none of them.
CORTEX_CHIPS = (("accept", "Accept"), ("rerun", "Rerun"), ("drop", "Drop"),
                ("leave-to-finish", "Leave to finish"))

DEV_LEDE = ("{n} of {total} ended member(s) delivered on the evidence — a PR "
            "with a non-empty diff and checks that ran.")
CORTEX_LEDE = ("{n} of {total} scored member(s) delivered on the evidence — a "
               "witness that landed inside its budget, on a clean run that is "
               "not a resume. Members still running hold no review control; "
               "carry-forward moves them to the next board.")

#: The `-r<N>` suffix of a slot's later, partial reviews (`<slot>-r2.md`,
#: N >= 2) — `scripts/cortex.py`'s own pattern, kept byte-identical so a
#: review file this conductor offers is one `cortex.py check` also resolves.
REVIEW_PART_RE = re.compile(r"-r(\d+)$")


def _review_paths(root: Path, slot: str) -> list:
    """Every partial review file a rolling slot has, in sitting order:
    `reviews/<slot>.md` (the first sitting, if it exists) then `-r2.md`,
    `-r3.md`, … by N — `scripts/cortex.py::batch_problems`'s own resolution.
    `-r1` is not a name; the first review is `<slot>.md`."""
    reviews = root / "batches" / "reviews"
    out = []
    first = reviews / f"{slot}.md"
    if first.is_file():
        out.append(first)
    numbered = []
    for p in reviews.glob(f"{slot}-r*.md"):
        m = REVIEW_PART_RE.search(p.stem)
        if m:
            numbered.append((int(m.group(1)), p))
    numbered.sort(key=lambda t: t[0])
    return out + [p for _, p in numbered]


def _next_review_path(root: Path, slot: str) -> str:
    """The next free `reviews/<slot>[-r<N>].md` — `<slot>.md` if the first
    sitting has not happened yet, else the smallest free `-r<N>`, N >= 2."""
    reviews = root / "batches" / "reviews"
    if not (reviews / f"{slot}.md").is_file():
        return f"batches/reviews/{slot}.md"
    n = 2
    while (reviews / f"{slot}-r{n}.md").is_file():
        n += 1
    return f"batches/reviews/{slot}-r{n}.md"


def _merge_reviews(paths: list) -> dict | None:
    """Every partial review file for a slot, read and merged — `keys` from
    the latest file that set them, `members` per slug from the latest file
    that named it. `ruled` is STICKY: a member already ruled `yes` at an
    earlier sitting stays ruled even if a later, narrower sitting (one that
    lists only what it itself rules on) does not mention it again — that is
    what lets `_on_the_board` keep skipping it forever, not just this pass.
    """
    if not paths:
        return None
    keys: dict = {}
    members: dict = {}
    for p in paths:
        r = read_review(p.read_text(encoding="utf-8", errors="replace"))
        keys.update(r["keys"])
        for slug, row in r["members"].items():
            if members.get(slug, {}).get("ruled") == "yes":
                continue
            members[slug] = row
    return {"keys": keys, "members": members}


def _review_rel_paths(d: dict) -> list:
    """`batches/reviews/<slot>[-r<N>].md`, one per file this slot has ever
    had, in sitting order. Recomputed from the tree rather than threaded
    through `d`: the review files on disk do not move between a collect and
    its own apply."""
    root = d.get("root")
    if root is None or not d.get("slot"):
        return []
    return [f"batches/reviews/{p.name}" for p in _review_paths(root, d["slot"])]


class CortexMissing(BatchUsageError):
    """No usable Cortex tree. Its own words, and its own exit code — a session
    with no science checkout is not a session that typed something wrong."""


def load_cortex_conductor():
    """`agents/conductors/cortex/_cortex.py`, imported by file location and
    cached. Never at module import: `batch plan` and `batch collect` must run
    in a session with no Cortex checkout at all, which is most of them."""
    global _CX
    if _CX is None:
        spec = importlib.util.spec_from_file_location(
            "_batch_cortex_conductor", CORTEX_CONDUCTOR)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CX = mod
    return _CX


def cortex_context(cortex_arg: str = "") -> dict:
    """Everything the cortex kind reads: the conductor, the tree's own schema
    module, its root, its projects and its phases by path."""
    cx = load_cortex_conductor()
    try:
        root = cx.resolve_root(cortex_arg or None)
        mod = cx.load_cortex(root)
    except cx.CortexUnavailable as e:
        raise CortexMissing(f"batch: {e}")
    return {"cx": cx, "mod": mod, "root": root,
            "projects": mod.load_projects(root)[0],
            "by_rel": {ph.rel: ph for ph in mod.load_phases(root)[0]}}


def default_kinds(lane: str) -> str:
    """What a session offers when the human names no kind. Every Cortex phase
    is `local-dev` (the review happens at the laptop), so a cloud session is
    offered the dev kind and TOLD the science count rather than shown a board
    it cannot run."""
    return "both" if lane == "local-dev" else "dev"


# ----------------------------------------------------------- the organ ------
def organ_for(kind: str, root: Path, slot: str) -> dict:
    """Which organ's packet this is. Everything the renderer would otherwise
    have hardcoded to the Mind: the repo, its GitHub home, where the packet and
    the review live, and the two review-file spellings the two organs' checks
    disagree on."""
    if kind == "cortex":
        cx = load_cortex_conductor()
        return {
            "key": "cortex", "repo": cx.CORTEX_REPO, "home": cx._home(root),
            "packet_path": f"{cx.CORTEX_REPO}/batches/packets/{slot}.html",
            # The rolling board's first review is `<slot>.md`; every later
            # sitting is the next free `-r<N>.md` (`batches/reviews/AGENTS.md`).
            "review_path": _next_review_path(root, slot),
            # `cortex.py check` requires every `##` heading in a review to name
            # a member of the record, so the follow-ups block is one level down.
            "followups_heading": "### Follow-ups accepted",
            # `UNREVIEWED` is not a ruling verb; `(none)` is the Cortex's own
            # word for "no verdict yet" and its check accepts it.
            "default_decision": "(none)",
            "lede": CORTEX_LEDE,
        }
    return {
        "key": "dev", "repo": "PyAutoMind", "home": _mind_home(root),
        "packet_path": f"PyAutoMind/batches/packets/{slot}.html",
        "review_path": f"batches/reviews/{slot}.md",
        "followups_heading": "## Follow-ups accepted",
        "default_decision": "UNREVIEWED",
        "lede": DEV_LEDE,
    }


# ------------------------------------------------------- the scored member --
_BLOCK_LABEL_RE = re.compile(r"^\*\*(.+?)\*\*$")
_EST_LINE_RE = re.compile(r"^\*\*Est\. review-minutes\*\*")


def _pairs(lines: list, drop=("Your review",)) -> list:
    """`**Label**` full-line headings → the `(label, body)` pairs the packet
    and the report both read.

    Everything before the first label — the `## <slug> — HEALTH` head and the
    facets line — is dropped, because both surfaces render those themselves;
    `**Est. review-minutes** — n` is not a full-line label and is dropped too
    (the est chip carries it). Parsing rather than re-authoring: the Cortex's
    `member_block` stays the ONE source of the Question · Witness · Health
    evidence · Readout · Ruling · Follow-ups · Where-to-look text.
    """
    out, label, body = [], None, []
    for raw in lines:
        line = raw.rstrip()
        m = _BLOCK_LABEL_RE.match(line.strip())
        if m:
            if label is not None:
                out.append((label, "\n".join(body).strip()))
            label, body = m.group(1).strip(), []
            continue
        if label is None or _EST_LINE_RE.match(line.strip()):
            continue
        body.append(line)
    if label is not None:
        out.append((label, "\n".join(body).strip()))
    return [(k, v) for k, v in out if k not in drop]


def cortex_claims(member: dict, ctx: dict) -> bool:
    """A `phases/…` member, and only where a cortex context is loaded. With no
    Cortex in play the kind is not registered against anything and the member
    stays `dev` — a dev record that happens to name a phase path is a note,
    not a science member."""
    return bool(ctx.get("cortex")) and (
        member.get("path") or "").startswith("phases/")


def score_cortex(member: dict, ctx: dict) -> dict:
    """One science member, scored — the same flat dict the dev kind returns.

    Every judgement here is the Cortex conductor's: `score_phase` for the six
    legs and the health word, `LIVE_STATES` for what is still running. This
    function's own work is the translation: which chips the member gets, what
    the chip says, and whether it is reviewable at all.
    """
    cxc = ctx["cortex"]
    cx, mod = cxc["cx"], cxc["mod"]
    slug, rel = member["slug"], member.get("path") or ""
    est = _int(member.get("minutes"))
    base = {
        "slug": slug, "kind": "cortex", "id": f"m-{slug}",
        "est_minutes": est,
        # Positionally the record's RUNS column, not a tier: a Cortex member
        # line is `<slug>: <path> — <runs> — <minutes> — <state>`. Never print
        # it as one.
        "tier": "", "merged": False, "flagged": [], "links": [], "prs": [],
        "summary": "", "path": rel, "outcome": member.get("outcome") or "",
        "ruling_line": "_(one line — yours to write)_",
        "rel": rel, "cx": cx, "mod": mod,
    }
    ph = cxc["by_rel"].get(rel)
    if ph is None:
        # A record naming a phase this Cortex does not have is a NOTE on one
        # member, never the end of the collect.
        note = f"`{rel or slug}` is not in this Cortex — not scored"
        base.update({
            "title": slug, "health": "SUSPECT", "eyebrow": "cortex",
            "jobs": "(no phase)", "chip": "not scored", "pending": False,
            "legs": {}, "leg_order": (), "leg_titles": {}, "state": "",
            "notes": [note],
            # No chips and no Ruled box: there is nothing here to rule ON. It
            # is not RUNNING either — the callout below reads the health word,
            # not this flag, so a ghost is never reported as a live run.
            "review_chips": [], "reviewable": False,
            "cortex": None, "clean_line": note,
            "blocks": [("Status", f"_{note}_")],
        })
        return base

    sc = cx.score_phase(mod, ph, cxc["projects"])
    running = ph.state in cx.LIVE_STATES or sc["live_run"]
    health = "RUNNING" if running else sc["health"]
    wall = sc["legs"]["wall"][1]
    if running:
        chip = f"RUNNING — {wall}"
    elif health == "HEALTHY" and sc["legs"]["witness"][0] == PASS:
        chip = "witness landed"
    else:
        chip = health.lower()
    base.update({
        "title": ph.title or slug,
        "health": health,
        "eyebrow": " · ".join(x for x in (
            sc["project"],
            f"phase {ph.get('Phase')}" if ph.get("Phase") else "",
            ph.state) if x),
        "jobs": ", ".join(r.ident for r in ph.runs) or "(no runs)",
        "chip": chip,
        # `pending` is what keeps a running member out of the delivered
        # denominator; `reviewable` is what takes its review controls away.
        "pending": running,
        "reviewable": not running,
        "legs": sc["legs"], "leg_order": cx.LEGS, "leg_titles": cx.LEG_TITLES,
        "state": ph.state, "notes": [], "cortex": sc,
        "review_chips": [] if running else list(CORTEX_CHIPS),
        "pending_line": f"RUNNING — {wall}; no review control "
                        "until it is pulled",
        "clean_line": f"{sc['legs']['witness'][1]}; accept / rerun / drop",
    })
    base["blocks"] = cortex_blocks(base)
    return base


def cortex_blocks(s: dict) -> list:
    """The Cortex's own packet block, split into this renderer's pairs."""
    if not s.get("cortex"):
        return list(s.get("blocks") or [("Status", "_(not scored)_")])
    return _pairs(s["cx"].member_block(s["mod"], s["cortex"]))


def _on_the_board(s: dict, ruled: set, notes: list) -> bool:
    """Whether a scored science member belongs on this packet.

    Two exclusions, both from `batches/AGENTS.md`'s rolling board: a member the
    human has already ruled on in this slot's review is not re-rendered (its
    packet span is what they were shown), and a phase that has left the board
    — `accepted`, `rerun`, `dropped`, back to `ready` — is history, not work.
    """
    if s["slug"] in ruled:
        notes.append(f"{s['slug']}: already ruled in this slot's review — its "
                     "packet section is left exactly as it was")
        return False
    state = s.get("state") or ""
    if state and state not in CORTEX_BOARD_STATES:
        notes.append(f"{s['slug']}: state `{state}` is off the board "
                     f"({' | '.join(CORTEX_BOARD_STATES)}) — not scored")
        return False
    return True


def _cortex_callout(d: dict) -> str:
    """The Cortex packet's "most important finding". The dev callout's subject
    — a session that ended green with no PR — has no science equivalent; the
    live strip is what a science reviewer needs at the top instead."""
    live = [s for s in d["members"] if s["health"] == "RUNNING"]
    failed = d["counts"].get("FAILED", 0)
    if live:
        items = "".join(
            f'<li><a href="#{_e(s["id"])}">{_e(s["slug"])}</a> — '
            f'{_e(_short(s["chip"], 140))}</li>' for s in live)
        return (f'<section class="callout" aria-label="Most important finding">'
                f'\n  <p class="eyebrow">Most important finding</p>\n'
                f'  <p>{len(live)} member(s) are still running — they hold no '
                f'review control, and carry-forward moves them to the next '
                f'board. Rule on what is pulled; nothing here waits on them.'
                f'</p>\n  <ul>{items}</ul>\n</section>')
    return ('<section class="callout ok" aria-label="Most important finding">\n'
            '  <p class="eyebrow">Most important finding</p>\n'
            f'  <p>Nothing is still running: every member of this slot has its '
            f'results in. {_e(failed)} failed a leg outright and '
            f'{_e(d["counts"].get("SUSPECT", 0))} need your eyes for a leg the '
            f'collect could not observe.</p>\n</section>')


KINDS["cortex"] = (score_cortex, cortex_blocks, cortex_claims)


# ------------------------------------------------------------- plan ---------
def plan_cortex(ctx: dict, *, budget: int, lane: str) -> dict:
    """Which ready phases fit the slot — the phase-2 admission rule, whole.

    `ready` + a registered `Witness:` + a `Budget:` + the session's lane, and
    nothing else. The autonomy cap is NEVER consulted: a science member is
    supervised by definition and the ruling is the human's, so there is no
    "would park at ship" to reject it for. `LIBRARY_REPOS` clash detection
    applies in neither direction either — a science run claims no library
    worktree, so it can never collide at merge with a dev member.
    """
    cx = ctx["cx"]
    c = cx.census(ctx["root"])
    d = cx.plan(c, budget, lane)
    d["census"] = c
    return d


def _cortex_member_row(ph) -> dict:
    """One record member line's fields, read off the phase itself.

    The runs column is the run STEMS (`342091`), not the idents (`342091_0`):
    `cortex.py`'s batch check compares the column against `{r.stem for r in
    ph.runs}` and an ident fails it.
    """
    return {"slug": ph.slug, "rel": ph.rel,
            "runs": ", ".join(sorted({r.stem for r in ph.runs})) or "none",
            "minutes": _int(ph.get("Review-minutes")), "state": ph.state}


def cortex_record_text(members: list, *, slot: str, dispatched: str,
                       review_at: str, shift: str, planned: int,
                       carried: list, carried_from: str) -> str:
    """The Cortex batch record, in `PyAutoCortex/batches/AGENTS.md`'s schema.

    `heart-ack:` and `expected-effects:` are deliberately NOT written: that
    page drops them on purpose (the Heart gates releases, not runs, and a
    science batch has no autonomy leg to license), so a record carrying them
    would be a field nothing ever reads.
    """
    rows = list(members) + [m for m in carried
                            if m["slug"] not in {x["slug"] for x in members}]
    L = [f"# Batch {slot[:10]} {slot[11:]}",
         f"- dispatched: {dispatched}",
         f"- review-at: {review_at}",
         f"- shift: {shift}",
         "- lane: local-dev",
         f"- review-minutes-planned: {planned}"]
    if carried and carried_from:
        L.append(f"- carried-from: {carried_from}")
    L.append("- members:")
    for m in rows:
        L.append(f"  - {m['slug']}: {m['rel']} — {m['runs']} — "
                 f"{m['minutes']} — {m['state']}")
    L += ["- notes: |",
          "    Opened by `pyauto-brain batch plan --kind cortex --apply`. The",
          "    review-minutes figure is a seed; `review-minutes-actual:` at",
          "    close is the only calibration this surface gets."]
    if carried and carried_from:
        L += ["",
              f"    {len(carried)} member(s) carried from {carried_from},",
              f"    still live at its review: "
              f"{', '.join(m['slug'] for m in carried)}. Their minutes are",
              "    counted in the planned figure above."]
    return "\n".join(L) + "\n"


def write_cortex_record(root: Path, text: str, slot: str) -> str:
    """Write the record, refusing to overwrite one. A slot's record is the
    ledger of what was on that board; a second `plan --apply` on the same slot
    is a typo, not an intent."""
    path = root / "batches" / f"{slot}.md"
    if path.exists():
        raise BatchUsageError(
            f"batch: batches/{slot}.md already exists — pick another --slot "
            "(a record is the ledger of one board and is never reopened)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return f"batches/{slot}.md"


def _rehearse_cortex(root: Path, mod, rel: str, text: str) -> list:
    """Write `text` at `rel` on a throwaway copy of the whole tree and run the
    Cortex's own `check` over it. Same reason as the dev rehearsal, plus one:
    the member lines this module writes are checked against the phase files by
    a schema that is not this module's, and being wrong about it is drift in
    someone else's repo."""
    tmp = Path(tempfile.mkdtemp(prefix="batch-cortex-"))
    try:
        copy = tmp / root.name
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns(".git"),
                        symlinks=True)
        target = copy / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return mod.check_problems(copy)
    except OSError as e:
        return [f"the rehearsal copy could not be made ({e})"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9_-]+$")


def cortex_plan_record(ctx: dict, d: dict, *, slot: str, review_at: str,
                       shift: str, dispatched: str) -> tuple:
    """`(rel, notes)` — compose and write one Cortex batch record.

    Carried members ride along without being named by the human: whatever was
    still `submitted`/`running` at the last closed record's review is on this
    board too, at its CURRENT state, with the record it came from recorded.
    """
    if not SLOT_RE.match(slot):
        raise BatchUsageError(
            f"batch: `{slot}` is not a slot name (<YYYY-MM-DD>-<label>)")
    if not review_at.strip():
        raise BatchUsageError(
            "batch: plan --kind cortex --apply needs --review-at — the shift "
            "is dispatch → review-at, and it is the human's to declare")
    root, mod = ctx["root"], ctx["mod"]
    by_rel = ctx["by_rel"]
    rows = [_cortex_member_row(by_rel[r["rel"]]) for r in d["members"]
            if r["rel"] in by_rel]
    previous = newest_closed_record(root, mod)
    carried = carried_members(ctx, previous) if previous is not None else []
    carried = [m for m in carried if m["slug"] not in {r["slug"] for r in rows}]
    carried_from = (f"batches/{previous.stem}.md" if previous is not None
                    else "")
    planned = d["review_minutes_planned"] + sum(m["minutes"] for m in carried)
    text = cortex_record_text(
        rows, slot=slot, dispatched=dispatched, review_at=review_at,
        shift=shift, planned=planned, carried=carried,
        carried_from=carried_from)
    rel = f"batches/{slot}.md"
    problems = _rehearse_cortex(root, mod, rel, text)
    if problems:
        return "", ["record NOT written — the Cortex does not check with it:"
                    ] + [f"  {p}" for p in problems[:10]]
    write_cortex_record(root, text, slot)
    notes = [f"record written: {rel}"]
    if carried:
        notes.append(f"{len(carried)} member(s) carried from {carried_from}: "
                     + ", ".join(m["slug"] for m in carried))
    return rel, notes


# --------------------------------------------------------- carry-forward ----
def newest_closed_record(root: Path, mod):
    """The last record whose review has landed — the one carry-forward reads.
    An OPEN record's live members have not reached a review yet, so nothing
    about them is carried anywhere."""
    for path in reversed(mod.batch_records(root)):
        rec = read_record(path.read_text(encoding="utf-8", errors="replace"))
        if any(v for v in rec["keys"].get("review", [])):
            return path
    return None


def carried_members(ctx: dict | None, record) -> list:
    """A record's members whose phase is STILL `submitted`/`running` NOW.

    The new record writes the phase's current state; the old record's line
    stays as the ledger of what it was at its own review. A science member
    never blocks a science review — that is the whole rule this implements.
    """
    if not ctx or record is None:
        return []
    try:
        text = Path(record).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    live = ctx["cx"].LIVE_STATES
    out = []
    for m in read_record(text)["members"]:
        ph = ctx["by_rel"].get(m.get("path") or "")
        if ph is not None and ph.state in live:
            out.append(_cortex_member_row(ph))
    return out


def carried_lines(d: dict, rec: dict) -> list:
    """`- carried: <slug> — still <state> at review`, once per slug.

    Written at CLOSE only: it is a statement about where a member stood when
    the human ruled, and idempotent, because a collect may be re-run over a
    closed record any number of times.
    """
    have = {v.split(" — ")[0].strip() for v in rec["keys"].get("carried", [])}
    return [f"- carried: {m['slug']} — still {m['state']} at review"
            for m in d.get("carry", []) if m["slug"] not in have]


# -------------------------------------------------------------- collect -----
def _cortex_movers(d: dict) -> list:
    """The raw scored phases an apply may MOVE — `pulled`, and `running` with
    no live run line. An `awaiting-ruling` member is already on the board, and
    `apply_ops` writes one `refreshed:` line per phase it is handed, so
    handing it those would stamp the record on every refresh forever."""
    out = []
    for s in d["members"]:
        sc = s.get("cortex")
        if not sc:
            continue
        if s.get("state") == "pulled" or (
                s.get("state") == "running" and not sc["live_run"]):
            out.append(sc)
    return out


def _recorded_carried_slugs(rec: dict) -> set:
    """Slugs an EARLIER sitting already carried forward — `_status`'s own
    reading of the `- carried:` line, replayed against this record's
    already-read `rec` so the box and the close leg can never disagree."""
    return _carried_slugs(rec["keys"], rec["members"])


def _cortex_slot_open(d: dict, rec: dict) -> bool:
    """Whether the science board still holds something worth waiting for —
    `_status.cortex_status`'s reading: nothing left in a board state, members
    an EARLIER sitting already carried forward excluded. `d["members"]` is
    already the board (`_on_the_board` has dropped the ruled and the
    off-board); a member leaves it for `carried` only once a `- carried:` line
    naming it is already IN THE RECORD — one merely running right now, before
    any sitting has said so, still holds this slot open (`batches/AGENTS.md`:
    "the slot stays open while any non-carried member is still `submitted`,
    `running`, `pulled` or `awaiting-ruling`")."""
    carried = _recorded_carried_slugs(rec)
    return any(s["slug"] not in carried for s in d.get("members") or [])


def record_update_cortex(text: str, d: dict, stamp: str,
                         review_at: str = "") -> str:
    """The Cortex record's collect keys, updated in place. The MEMBER LINES ARE
    NOT TOUCHED: their last column is a phase state, `apply_ops` owns it, and
    the dev rewrite (`HEALTHY (…)`) would fail `cortex.py check` outright."""
    lines = text.split("\n")
    rec = read_record(text)
    # A slot closes when nothing is left on the board (`batches/AGENTS.md`,
    # "The first review does not close the slot") — NOT the moment a review
    # file exists: a rolling slot may be reviewed more than once while it is
    # still open.
    closed = not _cortex_slot_open(d, rec)
    inserts: list[str] = []
    if not rec["key_lines"].get("collected"):
        inserts.append(f"- collected: {stamp}")
    n, total = d["delivered"]
    # An open board's `delivered:`/`packet:` move with every refresh; a closed
    # one's are history and are filled, never set.
    put = _fill_key if closed else _set_key
    put(lines, rec, "delivered", f"{n}/{total}", inserts)
    put(lines, rec, "packet", f"batches/packets/{d['slot']}.html", inserts)
    if review_at.strip():
        # "re-declared at each refresh" — the human's own number, always.
        _set_key(lines, rec, "review-at", review_at.strip(), inserts)
    review = d.get("review")
    if review is not None:
        # `review:` REPEATS — one line per sitting (`batches/reviews/AGENTS.md`)
        # — so this is never a fill-once key; only lines the record does not
        # already carry are appended, in sitting order.
        have = set(rec["keys"].get("review") or [])
        inserts += [f"- review: {p}" for p in _review_rel_paths(d)
                   if p not in have]
        reviewed_at = review["keys"].get("reviewed-at", "")
        if reviewed_at:
            _fill_key(lines, rec, "reviewed-at", reviewed_at, inserts)
        minutes = review["keys"].get("review-minutes-actual", "")
        if minutes and minutes != "(not given)":
            _fill_key(lines, rec, "review-minutes-actual", minutes, inserts)
        inserts += carried_lines(d, rec)
    at = _insert_anchor(rec)
    lines[at:at] = inserts
    return "\n".join(lines)


def apply_collect_cortex(ctx: dict, d: dict, stamp: str,
                         review_at: str = "") -> list:
    """Move the phases, update the record's collect keys, refresh the packet.

    In that order, and each leg rehearsed before it is made: the phase moves
    are the Cortex's own `_apply_checked` (the whole tree copied, moved,
    `check`ed and only then replayed for real), the record keys are re-read and
    re-checked, and the packet is spliced in place exactly as a dev packet is.

    `d` is REFRESHED IN PLACE when the moves land: the caller's report, the
    record's `delivered:` and the packet then describe the board as it stands
    after this collect, not as it stood before it. Assign the returned notes
    (`d["notes"] = d["notes"] + apply_collect_cortex(…)`); `+=` would store a
    stale list back.
    """
    notes: list[str] = []
    cx, mod, root = ctx["cx"], ctx["mod"], ctx["root"]
    record = root / "batches" / f"{d['slot']}.md"
    rel = f"batches/{d['slot']}.md"

    movers = _cortex_movers(d)
    if movers:
        problems, applied, wrote = cx._apply_checked(root, mod, movers, stamp,
                                                     record)
        notes += applied
        if problems:
            notes.append(
                "the Cortex does not check after the moves — "
                + ("they were written; run `python3 scripts/cortex.py check`"
                   if wrote else "nothing was moved") + ": "
                + "; ".join(problems[:3]))
        elif wrote:
            notes.append("phases moved and one `refreshed:` line written per "
                         "pull: " + ", ".join(s["slug"] for s in movers))
            # Re-score against the tree as it NOW stands. A member the moves
            # just walked `running → pulled → awaiting-ruling` has its results
            # in, and a packet that still drew it as RUNNING would withhold the
            # review controls of the very member this refresh delivered — the
            # human would have to collect twice to rule once.
            _reload_phases(ctx)
            fresh = collect(root, d["slot"], kind="cortex", cortex=ctx)
            keep = list(d["notes"])
            d.update({k: v for k, v in fresh.items() if k != "notes"})
            d["stamp"] = stamp
            d["notes"] = keep + [n for n in fresh["notes"] if n not in keep]

    before = record.read_text(encoding="utf-8", errors="replace")
    after = record_update_cortex(before, d, stamp, review_at)
    if after != before:
        problems = (_rehearse_record(root, before, after)
                    + _rehearse_cortex(root, mod, rel, after))
        if problems:
            notes += [f"record keys NOT written — {p}" for p in problems[:5]]
        else:
            record.write_text(after, encoding="utf-8")
            notes.append(f"record updated: {rel}")

    notes += _apply_packet(root, d)
    return notes


def _reload_phases(ctx: dict) -> None:
    """Re-read the phase files. The context caches `Phase` objects, and a move
    has just changed the one thing they are read for."""
    ctx["by_rel"] = {ph.rel: ph
                     for ph in ctx["mod"].load_phases(ctx["root"])[0]}


def cortex_ready_note(cortex_arg: str = "") -> str:
    """"N Cortex phase(s) are ready — run from the laptop", for a session that
    is not at the laptop. Reported, never silently dropped: a board this
    session cannot run is still a board the human can, from the other machine.

    Any failure at all is silence: a dev plan must not depend on a science
    checkout being present, readable, or in schema.
    """
    try:
        ctx = cortex_context(cortex_arg)
        ready = len(ctx["cx"].census(ctx["root"])["ready"])
    except Exception:  # noqa: BLE001 - a dev plan never fails on the Cortex
        return ""
    if not ready:
        return ""
    return (f"{ready} Cortex phase(s) are ready — every Cortex phase is "
            f"local-dev, so run\n`batch plan --kind cortex` from the laptop "
            f"to plan them.")


# -------------------------------------------------------------------- cli ---
#: Flags that belong to `collect` only. Passing one to `plan` is a usage error
#: rather than a silent no-op: a human who types `batch plan --apply` means
#: something, and it is not "plan".
COLLECT_ONLY = ("slot", "evidence", "fetch", "integration", "push", "apply",
                "out", "stamp")

#: …except on `plan --kind cortex`, which OPENS a board: the slot is its name,
#: `--apply` writes it, and the stamp is its `dispatched:`. Only with the kind
#: named explicitly, so `batch plan --apply` on a laptop stays the usage error
#: it has always been.
CORTEX_PLAN_FLAGS = ("slot", "apply", "stamp")

RC_OK, RC_FINDINGS, RC_USAGE, RC_NO_MIND, RC_NO_CORTEX = 0, 1, 2, 4, 5


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="batch")
    ap.add_argument("verb", choices=["plan", "collect"], nargs="?",
                    default="plan")
    ap.add_argument("--mind", type=Path, default=BODY_MAP_PATH.parent)
    ap.add_argument("--budget", type=int, default=DEFAULT_REVIEW_BUDGET,
                    help="review-minutes available in the slot")
    ap.add_argument("--awaiting-review", type=int, default=0,
                    help="tasks already awaiting review (backpressure input)")
    ap.add_argument("--cap", type=int, default=DEFAULT_BACKPRESSURE_CAP)
    ap.add_argument("--lane", default="", help="override the detected session lane")
    ap.add_argument("--json", action="store_true", dest="as_json")
    # collect only
    ap.add_argument("--slot", default="",
                    help="the batch record to collect (default: the newest)")
    ap.add_argument("--evidence", default="",
                    help="JSON file of PR/witness/adversary evidence per member")
    ap.add_argument("--fetch", action="store_true",
                    help="gather PR evidence with gh, where there is a gh")
    ap.add_argument("--integration", action="store_true",
                    help="laptop: build one throwaway worktree root merging "
                         "every member's head branch per repo, and report the "
                         "conflicts (writes no remote, pushes nothing)")
    ap.add_argument("--push", action="store_true",
                    help="laptop: push each integration/<slot> to origin as a "
                         "throwaway review ref (needs --integration; never a "
                         "PR, never forced, expires at the record's "
                         "sweep-after:)")
    ap.add_argument("--apply", action="store_true",
                    help="write the packet and update the record")
    ap.add_argument("--out", default="", help="write the report here")
    ap.add_argument("--stamp", default="",
                    help="the refresh stamp to record (default: now, UTC)")
    # the second kind
    ap.add_argument("--kind", choices=["dev", "cortex", "both"], default="",
                    help="which organ's board (default: from the session lane)")
    ap.add_argument("--cortex", default="",
                    help="the PyAutoCortex checkout (default: $PYAUTO_CORTEX, "
                         "or beside this Brain)")
    ap.add_argument("--cortex-budget", type=int, default=0,
                    help="review-minutes for the science board (default: "
                         "--budget)")
    ap.add_argument("--review-at", default="",
                    help="when you expect to be back — the shift is dispatch "
                         "-> review-at, and it is yours to declare")
    ap.add_argument("--shift", default="",
                    help="the shift label a new Cortex record carries")
    ap.add_argument("--pull", action="store_true",
                    help="run each project's own `pull` first (laptop only)")
    a = ap.parse_args(argv)

    lane = a.lane or detect_lane()
    kind = a.kind or default_kinds(lane)
    mind = a.mind.resolve()
    try:
        if a.verb == "collect":
            if a.kind == "both":
                print("batch: collect takes one board at a time — --kind dev "
                      "or --kind cortex", file=sys.stderr)
                return RC_USAGE
            if kind == "cortex":
                return _main_collect_cortex(a)
            return _main_collect(mind, a)
        return _main_plan(mind, a, lane, kind)
    except CortexMissing as e:
        print(e, file=sys.stderr)
        return RC_NO_CORTEX
    except BatchUsageError as e:
        print(e, file=sys.stderr)
        return RC_USAGE


def _main_plan(mind: Path, a, lane: str, kind: str) -> int:
    allowed = CORTEX_PLAN_FLAGS if a.kind == "cortex" else ()
    used = [f"--{f}" for f in COLLECT_ONLY
            if getattr(a, f) and f not in allowed]
    if used:
        print(f"batch: {', '.join(used)} belong(s) to `batch collect`, not "
              "`batch plan`", file=sys.stderr)
        return RC_USAGE
    if kind == "cortex":
        return _main_plan_cortex(a, lane)
    if not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return RC_NO_MIND
    d = plan(survey(mind), budget=a.budget, session_lane=lane,
             awaiting_review=a.awaiting_review, cap=a.cap)
    if a.as_json:
        print(json.dumps(d, indent=2))
        return RC_OK
    emit(d)
    if kind == "both":
        # Both boards, one after the other, and the reason they are two.
        print()
        try:
            _main_plan_cortex(a, lane)
        except CortexMissing as e:
            # A laptop with no science checkout still gets its dev board: the
            # second kind was OFFERED by the lane, not asked for.
            if a.kind:
                raise
            print(f"(no science board: {e})")
            return RC_OK
        print()
        print("Two records, one per organ — PyAutoMind/batches/ for the dev "
              "board and")
        print("PyAutoCortex/batches/ for the science one, each with its own "
              "review-at:.")
        print("Neither ever lists the other's members.")
    else:
        note = cortex_ready_note(a.cortex)
        if note:
            print()
            print(note)
    return RC_OK


def _main_plan_cortex(a, lane: str) -> int:
    """The science board. Offline, and it dispatches nothing: `emit_plan`
    prints the project's own submit line for the human to run."""
    ctx = cortex_context(a.cortex)
    d = plan_cortex(ctx, budget=a.cortex_budget or a.budget, lane=lane)
    if a.as_json:
        print(json.dumps({k: v for k, v in d.items() if k != "census"},
                         indent=2, default=str))
    else:
        ctx["cx"].emit_plan(d)
    if not a.apply:
        return RC_OK
    if lane != ctx["cx"].LOCAL_LANE:
        raise BatchUsageError(
            "batch: plan --kind cortex --apply opens a board that is reviewed "
            "at the laptop — run it there (or pass --lane local-dev if you "
            "are there and this session cannot tell)")
    stamp = a.stamp.strip() or _utc_now()
    shift = a.shift.strip() or (a.slot[11:] if a.slot else _shift_label())
    today = f"{_dt.datetime.now(_dt.timezone.utc):%Y-%m-%d}"
    slot = a.slot.strip() or f"{today}-{shift}"
    rel, notes = cortex_plan_record(ctx, d, slot=slot, review_at=a.review_at,
                                   shift=shift, dispatched=stamp)
    print()
    for note in notes:
        print(f"  {note}")
    return RC_OK if rel else RC_FINDINGS


def _shift_label() -> str:
    """`am` or `pm` — a default label, never a schedule. A slot is whenever the
    human comes in; this only names the file when they did not."""
    return "am" if _dt.datetime.now(_dt.timezone.utc).hour < 12 else "pm"


def _main_collect(mind: Path, a) -> int:
    if not (mind / "batches").is_dir():
        print(f"batch: no batch records at {mind}", file=sys.stderr)
        return RC_NO_MIND
    if a.push and not a.integration:
        raise BatchUsageError(
            "batch: --push publishes what --integration built — pass both. A "
            "record's `- integration: yes` asks for the LOCAL preview; putting "
            "a ref on GitHub is a separate act, typed at collect.")
    slot = a.slot or newest_slot(mind)
    if not slot or not (mind / "batches" / f"{slot}.md").is_file():
        print(f"batch: no batch record batches/{slot or '<none>'}.md at {mind}",
              file=sys.stderr)
        return RC_USAGE
    try:
        evidence = load_evidence(a.evidence) if a.evidence else {}
    except BatchUsageError as e:
        print(e, file=sys.stderr)
        return RC_USAGE
    doc = load_evidence_doc(a.evidence) if a.evidence else {}

    d = collect(mind, slot, evidence=evidence)
    if a.fetch:
        # Fetched evidence never overrides a file the human passed: they wrote
        # it, and this leg is a convenience.
        fetched, notes = fetch_evidence(
            [{"slug": s["slug"], "path": s["path"]} for s in d["members"]],
            read_active(mind))
        merged = dict(fetched)
        merged.update(evidence)
        d = collect(mind, slot, evidence=merged)
        d["notes"] += notes

    # `--integration` on the command line, or `- integration: yes` written into
    # the record at dispatch — the flag turns it on for one run without editing
    # the record, and the record asks for it without anyone remembering a flag.
    if a.integration or d.get("integration_requested"):
        integ = load_integration()
        block, inotes = integ.run(d["members"], d["dispatch_order"], slot,
                                  lane=(a.lane or detect_lane()),
                                  push=a.push)
        if block and a.push:
            # The expiry is a fact about the RECORD, so it is filled here and
            # not in the merge engine: the human's own `sweep-after:` wins, and
            # the default hangs off the review the branch exists for.
            block["sweep_after"] = (d.get("sweep_after")
                                    or sweep_after_default(
                                        d.get("review_at", ""), inotes))
        d["integration"] = block
        d["notes"] += inotes
    elif isinstance(doc.get("integration"), dict):
        # Computed on the laptop, rendered anywhere: collect never rewrites the
        # human's --evidence file, so a block that reaches a cloud session got
        # there through `--json > ev.json` and a paste.
        d["integration"] = doc["integration"]
    d["stamp"] = a.stamp.strip() or _utc_now()

    if a.apply:
        d["notes"] += apply_collect(mind, d, d["stamp"])

    if a.as_json:
        print(json.dumps(d, indent=2, default=str))
    else:
        emit_collect(d, a.out)
    return _collect_rc(d)


def _collect_rc(d: dict) -> int:
    ended = [s for s in d["members"] if not s["pending"]]
    clean = all(s["health"] in ("HEALTHY", "MERGED") for s in ended)
    return RC_OK if clean and len(ended) == len(d["members"]) else RC_FINDINGS


def _main_collect_cortex(a) -> int:
    """The science board, refreshed. It may run any number of times per batch:
    a member joins the packet on the pull that fills its results in, and every
    other section is re-rendered identically, so the human can keep reading the
    page while the overnight members land under them."""
    if a.fetch or a.evidence:
        raise BatchUsageError(
            "batch: --fetch and --evidence read PR evidence — they belong to "
            "the dev board. A science member's evidence is what the project's "
            "own pull mirrored to the laptop; see --pull")
    ctx = cortex_context(a.cortex)
    cx, root = ctx["cx"], ctx["root"]
    if not (root / "batches").is_dir():
        raise CortexMissing(f"batch: no batch records at {root}")
    slot = a.slot or newest_slot(root)
    record = root / "batches" / f"{slot}.md" if slot else None
    if not slot or not record.is_file():
        print(f"batch: no batch record batches/{slot or '<none>'}.md at "
              f"{root}", file=sys.stderr)
        return RC_USAGE

    notes: list[str] = []
    if a.pull:
        # The one leg that touches the cluster, through the human's own CLI,
        # and only from the machine that can reach it.
        if (a.lane or detect_lane()) != cx.LOCAL_LANE:
            notes.append("batch collect --kind cortex --pull: no laptop here "
                         "— run collect from the laptop; what is already "
                         "mirrored is scored anyway")
        else:
            notes += cx.run_pull(ctx["projects"], _record_projects(ctx, record))

    d = collect(root, slot, kind="cortex", cortex=ctx)
    d["notes"] += notes
    d["stamp"] = a.stamp.strip() or _utc_now()
    if a.apply:
        # Assigned, not `+=`: the apply refreshes `d` in place (the phase moves
        # change what the members are), and `d["notes"] += …` would load the
        # pre-refresh list before the call and store that one back.
        applied = apply_collect_cortex(ctx, d, d["stamp"], a.review_at)
        d["notes"] = d["notes"] + applied
    elif a.review_at.strip():
        d["notes"].append("--review-at is recorded by --apply; nothing was "
                          "written")

    if a.as_json:
        print(json.dumps(d, indent=2, default=str))
    else:
        emit_collect(d, a.out)
    return _collect_rc(d)


def _record_projects(ctx: dict, record: Path) -> list:
    """The projects a record's members belong to — what `--pull` pulls."""
    keys = set()
    text = record.read_text(encoding="utf-8", errors="replace")
    for m in read_record(text)["members"]:
        ph = ctx["by_rel"].get(m.get("path") or "")
        if ph is not None:
            keys.add(ph.get("Project") or ph.project_dir)
    return sorted(keys)


if __name__ == "__main__":
    sys.exit(main())

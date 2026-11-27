#!/usr/bin/env python3
"""agents/conductors/batch/_batch.py — the batch conductor.

Composes what goes into one unattended shift. Thin by construction: every
judgement it uses — consequence tier, review-minutes, readiness, difficulty —
belongs to the sizing faculty, because `ORGANISM.md` makes faculties the
opinion sinks and forbids a conductor consulting a conductor. This module
decides *membership*, which is an act, not an opinion.

The composition rule:

    sum(Review-minutes) over `glance` and `judge` members <= the slot budget

not a task count: a plan by count over-promises the human's review capacity.
The budget is the human's to set per slot (default 45) — a slot is whenever
they come in, not a scheduled hour.

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
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    BODY_MAP_PATH, LIBRARY_REPOS, effective_autonomy, effective_consequence,
    effective_difficulty, pyauto_root, effective_review_minutes, effective_unattended,
    lane_is_local, normalise_repo, parse_prompt, priority_rank,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _brief  # noqa: E402
import _green  # noqa: E402 — the keep-Heart-green lane
import _login  # noqa: E402 — the CLI login probe
import _ral  # noqa: E402 — the unattended-ssh probe for a granted `ral` lane
# The human's goals (goals.md): `brief --new` copies them.
from _steer import read_goals  # noqa: E402,F401 — re-exported beside read_queue
# The close-out guard's reader (intake `looks-shipped`): the live flags minus
# human dismissals. Loaded by path, so the batch planner shadows nothing else
# of that name.
_shipped_spec = importlib.util.spec_from_file_location(
    "_shipped_for_batch", BRAIN / "agents" / "conductors" / "intake" / "_shipped.py")
_shipped = importlib.util.module_from_spec(_shipped_spec)
_shipped_spec.loader.exec_module(_shipped)

# One slot's worth of the human's attention, and only the DEFAULT: the human
# sets it per slot with --budget, because they know whether the next one is a
# quick morning check or a long afternoon. Not a task count — see the module
# docstring. 45 rather than 60 because a slot also has to queue the next batch.
DEFAULT_REVIEW_BUDGET = 45
# Above half the cap the review-bearing half is halved; at the cap the batch is
# fill only. Counted in TASKS AWAITING REVIEW, never in PRs: one task often
# names two or more PRs, so a PR-count cap would trip on one healthy batch.
DEFAULT_BACKPRESSURE_CAP = 8
CHEAP_TIERS = ("notify",)


def detect_lane() -> str:
    """`local-dev` or `web-github` — where this session is running.

    Probed from the environment rather than declared, from the same signal the
    rest of the organism uses: a remote session has no `gh`
    (`skills/GITHUB_ACCESS.md`). No env var and no flag decides this; a
    session that could lie about where it is could plan `local-dev` work it
    cannot run.
    """
    return "local-dev" if shutil.which("gh") else "web-github"


def _lane_ok(record_lane: str, session_lane: str) -> bool:
    """A laptop-lane task (`local-dev`, `ral`, `gpu`, `wsl-data`) runs only in
    a `local-dev` session; `any` runs anywhere. An ABSENT lane passes here: it
    is the unattended gate in `plan` (`lane_absent_why`) that excludes it."""
    return not lane_is_local(record_lane) or session_lane == "local-dev"


def lane_absent_why(r: dict) -> str:
    """Why an unattended pick refuses this record for want of a lane, or "".

    Fail closed: a draft with no valid `Lane:` is excluded from every
    unattended or cloud pick, because a lane-less draft that needs the laptop,
    RAL or private data would otherwise reach a cloud worker and burn its run.
    An attended session still reads it as `any`.
    Worded without a colon: `emit` groups rejections on the text before one."""
    if r.get("lane"):
        return ""
    if r.get("lane_invalid"):
        return (f"lane invalid ({r['lane_invalid']!r}) — unattended picks fail "
                "closed; declare a valid Lane")
    return "lane absent — unattended picks fail closed; declare a Lane"


def declared_repos(p: dict) -> list[str]:
    """The repos a parsed prompt will touch, normalised: its `Repos:` header
    when that names any known repo; otherwise its `Target:` when that is a
    known repo; otherwise its survey `repos`.

    `Target:` is not unioned into a declared `Repos:` block: it is often only
    an epic label (a prompt with `Target: autofit` whose `Repos:` lists only
    PyAutoCortex), and adding it would make the claim gate report a false
    conflict on a repo the prompt never touches."""
    from _sizing import KNOWN_REPOS  # noqa: E402
    out = set()
    block = re.search(r"^Repos:\n((?:- .+\n)+)", p.get("text") or "", re.M)
    for ln in block.group(1).splitlines() if block else ():
        r = normalise_repo(ln[1:].strip())
        if r in KNOWN_REPOS:
            out.add(r)
    if out:
        return sorted(out)
    t = normalise_repo(p.get("target") or "")
    if t in KNOWN_REPOS:
        return [t]
    return list(p.get("repos") or [])


def grade(path: Path, mind: Path, text: str | None = None) -> dict:
    """Everything the planner needs about one prompt, from the faculty.
    `text`, when given, is the prompt's content (`grade_text`): nothing else
    is read by path."""
    p = parse_prompt(path, mind, text=text)
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
        "ready_why": ready_why, "epic": None,
        # The DECLARED lane, or None when the header has no valid `Lane:`.
        # Absence is not read as `any` here (AUTONOMY.md "M2 rulings"):
        # `plan` excludes a lane-less draft from an unattended pick and
        # reads it as `any` only when `attended=True`.
        "lane": p.get("lane"), "lane_invalid": p.get("lane_invalid"),
        "target": p.get("target") or "",
        # What the prompt declares it will touch — its `Repos:` header and
        # its target — not every repo its body mentions: the repo-claim gate
        # reads these, so a passing `@repo` never skips a task.
        "declared_repos": declared_repos(p),
        "priority": p.get("priority") or "normal",
        "blocked": bool(p.get("blocked_by")),
        # What it waits for, so a rejection names it (a side task orders
        # itself after its epic's phase by `Blocked-by:`).
        "blocked_by": list(p.get("blocked_by") or []),
    }


# A prompt whose own header says the work is finished. Mirrors intake's
# DONE_STATUSES: a session can ship the work and write the outcome into
# `Status:` but leave the file in `draft/`, where it keeps rendering as
# pickable backlog. Dispatching one wastes a whole shift re-doing finished work.
DONE_STATUSES = ("shipped", "superseded", "absorbed", "complete", "completed",
                 "done", "retired")


def _header_of(text: str, key: str) -> str:
    for line in text.splitlines()[:30]:
        if line.lower().startswith(f"{key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _themes_of(text: str) -> list[str]:
    """The header's `Themes:` bullets — what a brief's `scoped: tags` match."""
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^Themes:\s*$", line):
            inside = True
        elif inside and line.startswith("- "):
            out.append(line[2:].strip())
        elif inside:
            break
    return out


def _epic_of(text: str) -> str:
    return _header_of(text, "epic")


def _is_done(text: str) -> bool:
    status = _header_of(text, "status").lower()
    return any(status.startswith(d) for d in DONE_STATUSES)


def _phase_of(text: str) -> float:
    """`Phase: <n>` as a sortable number; phase-less members sort last."""
    raw = _header_of(text, "phase")
    # The leading number: `5a`/`5A` → 5, `6b2` → 6. A label with no leading
    # number (`C2`) sorts last but is still a declared phase
    # (`_phase_declared`), so the per-epic limit counts it.
    m = re.match(r"\s*(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else float("inf")


def _phase_declared(text: str) -> bool:
    return bool(_header_of(text, "phase"))


def survey(mind: Path) -> list[dict]:
    """Grade every backlog prompt. Epic membership rides along for the
    one-slice-per-epic rule."""
    out = []
    # Backpressure from the close-out guard: a draft with strong evidence that
    # its work already shipped waits for a human to close or dismiss it.
    flagged = _shipped.flagged_paths(mind)
    for f in sorted(mind.glob("draft/**/*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        g = grade(f, mind)
        g["looks_shipped"] = f.relative_to(mind).as_posix() in flagged
        g["epic"] = _epic_of(text)
        g["phase"] = _phase_of(text)
        g["phase_declared"] = _phase_declared(text)
        g["done"] = _is_done(text)
        g["ledger"] = is_ledger_text(text)
        g["themes"] = _themes_of(text)
        g["title"] = _title_of(text)
        out.append(g)
    return out


def grade_text(text: str, rel: str, mind: Path) -> dict:
    """One `survey` record from a prompt's text as Mind origin/main holds it
    (`/add`): the canonical working tree nobody pulls mid-shift may not have
    it yet. `rel` is its Mind-relative path."""
    g = grade(Path(mind) / rel, Path(mind), text=text)
    g["path"] = rel
    g["looks_shipped"] = rel in _shipped.flagged_paths(mind)
    g["epic"] = _epic_of(text)
    g["phase"] = _phase_of(text)
    g["phase_declared"] = _phase_declared(text)
    g["done"] = _is_done(text)
    g["ledger"] = is_ledger_text(text)
    g["themes"] = _themes_of(text)
    g["title"] = _title_of(text)
    return g


def _title_of(text: str) -> str:
    """The prompt's first `# ` heading — what a human reads the pick by."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# `read_queue` (and its grammar) lives in `_steer.py`, so the Mind dashboard
# ranks its read-only stars with this same reader.
from _steer import read_queue  # noqa: E402


def queue_rank(r: dict, queue: list[str]) -> int:
    """Where this prompt sits in the human's queue; unqueued sorts last.

    Matched on the path, then the basename, because a queue entry is written
    against `draft/…` and the prompt it names moves to `active/` the moment it
    is issued — a path-only match would silently lose its priority."""
    path = r.get("path") or ""
    if path in queue:
        return queue.index(path)
    name = Path(path).name
    if name:
        for i, q in enumerate(queue):
            if Path(q).name == name:
                return i
    return len(queue)


def is_ledger_text(text: str) -> bool:
    """An epic ledger: `Status: campaign map` with `Epic:` and no `Phase:`
    (as intake's `_shipped` reads a map). A side task of an epic (`Epic:`, no
    `Phase:`, any other status) is an ordinary prompt."""
    return bool(_epic_of(text)) and not _phase_declared(text) \
        and _header_of(text, "status").lower().startswith("campaign map")


def read_epic_ledgers(mind: Path) -> dict[str, str]:
    """{ledger path: epic slug} from Mind `epics.md` (`## <slug>` sections,
    each with a `- ledger:` line). The fallback that maps a queued ledger to
    its epic when the ledger's own `Epic:` header is missing or sits below
    the lines `_header_of` reads."""
    try:
        text = (Path(mind) / "epics.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    slug = ""
    for line in text.splitlines():
        h = re.match(r"^##\s+(\S+)", line)
        if h:
            slug = h.group(1)
        elif slug and line.startswith("- ledger:"):
            ledger = line.split(":", 1)[1].strip().strip("`")
            if ledger and not ledger.startswith("http"):
                out.setdefault(ledger, slug)
            slug = ""
    return out


def queued_epics(queue: list[str], records: list[dict],
                 epic_ledgers: dict[str, str] | None = None) -> dict[str, int]:
    """{epic slug: queue index} for every queue entry that names an epic
    ledger. An entry is an epic when the prompt it names is a ledger (`ledger`
    in its survey record: `Epic:`, no `Phase:`, `Status: campaign map`), or
    when `epics.md` lists it as an epic's `- ledger:`. A queued phase or side
    task queues only itself. The first entry wins."""
    by_path = {r.get("path") or "": r for r in records}
    by_name: dict[str, dict] = {}
    for r in records:
        by_name.setdefault(Path(r.get("path") or "").name, r)
    ledgers = epic_ledgers or {}
    ledger_names = {Path(p).name: s for p, s in ledgers.items()}
    out: dict[str, int] = {}
    for i, q in enumerate(queue):
        r = by_path.get(q) or by_name.get(Path(q).name)
        slug = r["epic"] if r and r.get("ledger") and r.get("epic") else ""
        slug = slug or ledgers.get(q) or ledger_names.get(Path(q).name, "")
        if slug:
            out.setdefault(slug, i)
    return out


def queue_standing(r: dict, queue: list[str],
                   epic_ranks: dict[str, int] | None = None) -> tuple[int, str]:
    """(rank, epic it is queued through or "") — the ONE answer to "is this
    record queued?". Queued directly (`queue_rank`), or as a member of a
    queued epic ledger, at the ledger's rank, whichever is higher in the file.
    `rank == len(queue)` is unqueued. Only the queue standing changes: every
    gate of `pool_gate` (phase order, autonomy, Unattended, Blocked-by) still
    applies to the member."""
    direct = queue_rank(r, queue)
    epic = r.get("epic") or ""
    via = (epic_ranks or {}).get(epic) if epic and not r.get("ledger") else None
    if via is not None and via < direct:
        return via, epic
    return direct, ""


def next_phases(records: list[dict]) -> dict[str, float]:
    """Each epic's lowest un-shipped phase — the only one that is startable."""
    next_phase: dict[str, float] = {}
    for r in records:
        if r.get("epic") and not r.get("done"):
            e = r["epic"]
            next_phase[e] = min(next_phase.get(e, float("inf")),
                                r.get("phase", float("inf")))
    return next_phase


def pool_gate(r: dict, next_phase: dict[str, float]) -> str:
    """Why a surveyed record is NOT in the planner pool, or "" if it is.

    Every gate but the lane, which depends on the session. Readiness says the
    work FITS one run; autonomy says the run may FINISH it. Under `--auto` a
    `supervised` run's ship checkpoint resolves to decide-and-flag
    (AUTONOMY.md, "Decide-and-flag"): it ships to an open PR rather than
    parking, so it FINISHES and belongs in the pool. Only `human-required`
    would still stop at the ship checkpoint and come back as a question."""
    if r.get("done"):
        return "Status: says the work is already done"
    if r.get("looks_shipped"):
        return ("looks shipped — confirm (close) or "
                f"dismiss it ({_shipped.DISMISS_FILE}) first")
    # Phase order binds only a task with a `Phase:` number: a side task of
    # the epic (no `Phase:`) is not a later phase, and orders itself by
    # `Blocked-by:` below.
    if r.get("epic") and has_phase(r) and r["phase"] == float("inf") \
            and next_phase.get(r["epic"], float("inf")) < float("inf"):
        return f"epic {r['epic']} phase (unnumbered) is not next"
    if r.get("epic") and has_phase(r) and r["phase"] > next_phase.get(
            r["epic"], float("inf")):
        return f"epic {r['epic']} phase {r['phase']:g} is not next"
    if r["autonomy"] == "human-required":
        return f"autonomy {r['autonomy']} — would park at ship"
    if r["unattended"] != "ready":
        return f"unattended: {r['unattended']}"
    if r["blocked"]:
        waits = "; ".join(r.get("blocked_by") or [])
        return f"waits for {waits} (its Blocked-by)" if waits else "declares Blocked-by:"
    return ""


def has_phase(r: dict) -> bool:
    """Whether a record declares a `Phase:` (`phase_declared`, from the
    survey); else whether its phase is a number (`_phase_of` reads a missing
    one as infinity, so phase-less side tasks sort last)."""
    if "phase_declared" in r:
        return bool(r["phase_declared"])
    phase = r.get("phase", float("inf"))
    return isinstance(phase, (int, float)) and phase != float("inf")


def self_organ_why(r: dict) -> str:
    """Why a shift never dips this draft, or "": it targets an organ the shift
    runs on — its watcher, writer or release path (`_brief.SELF_ORGANS`). By
    rule, not by a brief's `exclude:` list, so a draft filed after the brief
    is written is kept out too. Read from the target and every repo the draft
    names: a draft that names one is out."""
    organs = {normalise_repo(o): o for o in _brief.SELF_ORGANS}
    hit = sorted({organs[n] for x in {r.get("target") or "", *(r.get("repos") or [])}
                  if x and (n := normalise_repo(x)) in organs})
    if not hit:
        return ""
    return (f"targets {', '.join(hit)} — a shift never changes its own watcher, "
            "writer or release path")


def scoped_reach_why(r: dict) -> str:
    """Why `backlog: scoped` may not dip this unqueued draft, or "".

    AUTONOMY.md "Shift briefs and unattended `glance`": queue.md first, then
    only small single-repo backlog tasks. Anything bigger is queued by the
    human."""
    repos = r.get("repos") or []
    small = r.get("difficulty") == _brief.SCOPED_REACH_DIFFICULTY
    if small and len(repos) == 1:
        return ""
    size = r.get("difficulty") or "unsized"
    return (f"not in queue.md and {size}, {len(repos)} repo(s) — beyond queue.md a "
            "scoped dip takes only small single-repo tasks; the human queues "
            "bigger work")


#: The idle line for a queued epic with no draft prompt at its next phase.
NO_NEXT_PHASE_DRAFT = ("no draft prompt for {phase} — run the epic's Continue prompt "
                       "in an attended chat to file it")
#: How many next-phase members an idle line names before `+n more`.
EPIC_LINE_MEMBERS = 4


def queued_epic_summary(records: list[dict], epic_ranks: dict[str, int],
                        members: list[dict], rejected: list[tuple[str, str]],
                        queue: list[str]) -> list[dict]:
    """One entry per queued epic, in queue order: what it contributes to this
    plan, or why nothing — its next phase, and each next-phase member with
    the planner's reason for leaving it out; or no draft prompt at all for
    its next phase. Each entry carries its `line`."""
    why_of: dict[str, str] = {}
    for p, w in rejected:
        why_of.setdefault(p, w)
    out = []
    for slug, rank in sorted(epic_ranks.items(), key=lambda kv: kv[1]):
        tag = f"{slug} (q{rank + 1})"
        taken = [m["path"] for m in members if m.get("epic") == slug]
        open_ = [r for r in records if r.get("epic") == slug and not r.get("ledger")
                 and not r.get("done")]
        phased = [r for r in open_ if has_phase(r)]
        nxt = min((r["phase"] for r in phased), default=None)
        e = {"epic": slug, "rank": rank + 1, "ledger": queue[rank] if rank < len(queue) else "",
             "taken": taken, "next_phase": None, "members": []}
        if nxt is not None:
            e["next_phase"] = f"{nxt:g}" if nxt != float("inf") else "(unnumbered)"
            e["members"] = [{"path": r["path"],
                             "why": why_of.get(r["path"], "not planned this tick")}
                            for r in sorted(phased, key=lambda r: r["path"])
                            if r["phase"] == nxt]
        if taken:
            e["line"] = f"{tag}: takes " + ", ".join(Path(p).stem for p in taken)
        elif nxt is None:
            e["line"] = f"{tag}: nothing — " + NO_NEXT_PHASE_DRAFT.format(
                phase="its next phase")
        else:
            shown = e["members"][:EPIC_LINE_MEMBERS]
            more = len(e["members"]) - len(shown)
            e["line"] = (f"{tag}: nothing — next phase {e['next_phase']}: "
                         + "; ".join(f"{Path(m['path']).stem} ({_gate_word(m['why'])})"
                                     for m in shown)
                         + (f"; +{more} more" if more > 0 else ""))
        out.append(e)
    return out


def _gate_word(why: str) -> str:
    """A rejection reason cut to its gate words for a one-line epic summary:
    the clause before ` — `, prompt paths as their stems, asides dropped. The
    full reason stays in the entry's `members`."""
    w = why.split(" — ")[0]
    w = re.sub(r"(?:draft|active)/\S*?([\w-]+)\.md", r"\1", w)
    return re.sub(r"\s*\([^()]*\)", "", w).strip()


def queued_epic_lines(d: dict) -> list[str]:
    """The one-line-per-queued-epic text of a plan (`plan()["queued_epics"]`)."""
    return [e["line"] for e in d.get("queued_epics") or []]


def planner_pool(records: list[dict]) -> list[dict]:
    """The records every session's planner would consider, before its lane
    filters them — what a Lane backfill must cover."""
    next_phase = next_phases(records)
    return [r for r in records if not pool_gate(r, next_phase)]


def plan(records: list[dict], *, budget: int = DEFAULT_REVIEW_BUDGET,
         session_lane: str = "web-github", awaiting_review: int = 0,
         cap: int = DEFAULT_BACKPRESSURE_CAP, queue: list[str] | None = None,
         awaiting_source: str = "given", brief: dict | None = None,
         attended: bool = False, released: set[str] | None = None,
         epic_ledgers: dict[str, str] | None = None,
         withheld: list[tuple[dict, str]] | None = None,
         held_why: dict[str, str] | None = None) -> dict:
    """Compose the next batch — a BatchDecision.

    Every constraint states itself in `rejected`, because a planner that
    silently drops work teaches the human to distrust the number it reports.

    `queue` is `queue.md` in file order (`read_queue`) — the human's statement
    of importance, and the only input here that is a preference rather than a
    property of the work. `awaiting_review` is the review-queue depth, derived
    from `active.md` by the caller (`derive_awaiting_review`) unless the human
    passed the flag; `awaiting_source` says which.

    `attended` is False for every shift this planner composes (the batch it
    proposes runs unattended, and the watcher picks unattended). Two rules
    (AUTONOMY.md "M2 rulings") apply only then:

    - a backlog draft with no valid `Lane:` is excluded (`lane_absent_why`);
    - an EMPTY queue stops the backlog dip: the brief's named tasks still run,
      nothing else is picked. `queue=[]` is "queue.md was read and is empty or
      absent" (`read_queue` returns that); `queue=None` means the caller read
      no queue at all and is left ungated — every Mind-reading caller passes a
      list.

    With `attended=True` (`batch plan --attended`, a human at the keyboard
    picking for this session) an absent Lane reads as `any` and an empty queue
    falls back to the backlog order.

    A queue entry naming an epic ledger queues the epic's members at the
    ledger's rank (`queue_standing`); `epic_ledgers` is
    `read_epic_ledgers(mind)`, the `epics.md` fallback for a ledger whose
    `Epic:` header the survey did not read. `queued_epics` in the result says,
    per queued epic, what it contributes or why nothing; `withheld` is the
    (record, why) pairs the caller kept out before planning (claimed on Mind
    origin/main, parked), read only for that summary.
    """
    rejected: list[tuple[str, str]] = []
    queue_given = queue is not None
    queue = queue or []
    # Read BEFORE a brief folds its named tasks into the order: an empty
    # queue.md is the human saying nothing is wanted beyond the brief.
    queue_stop = not attended and queue_given and not queue
    all_records = records
    named_names: set[str] = set()
    # Under a shift brief the brief IS the human's composition (AUTONOMY.md,
    # "Shift briefs and unattended `glance`"): its named tasks outrank the
    # queue, then only the backlog its dip policy covers. The brief's
    # `review-minutes:` is the budget.
    if brief is not None:
        records, out_of_scope, named = _brief.scope(records, brief)
        rejected += out_of_scope
        named_names = {Path(t).name for t in named}
        queue = named + [q for q in queue if q not in named]
        minutes = _brief._nonneg_int(brief.get("review-minutes", {}).get("value", ""))
        if minutes is not None:
            budget = minutes

    # Backpressure RAMPS; it never deadlocks. It measures review-queue DEPTH,
    # never timing: timing is the human's, declared as `review-at:` at dispatch.
    # A deep queue must shrink the next batch rather than refuse to compose one.
    if awaiting_review >= cap:
        effective_budget, pressure = 0, "at cap — fill only"
    elif awaiting_review > cap / 2:
        effective_budget, pressure = budget // 2, "above half cap — halved"
    else:
        effective_budget, pressure = budget, "clear"

    # A queued epic ledger queues its members at its rank. Read from every
    # record, before the brief's scope drops any, so a ledger outside the
    # brief's scope still lends its rank.
    epic_ranks = queued_epics(queue, all_records, epic_ledgers)

    # An epic's members are worked IN ORDER, so only its lowest un-shipped
    # phase is startable — the one-slice-per-epic rule below caps how many
    # run, not which. Read over every record, the ones the brief's scope or
    # the caller kept out included: a phase held by a claim, parked, or
    # outside the brief is still open, so the phase after it is not next.
    held_out = [w for w, _ in withheld or []]
    next_phase = next_phases(all_records + held_out)

    shift_dip = brief is not None and not attended
    scoped_dip = shift_dip and brief.get("backlog", {}).get("value") == "scoped"
    pool, lane_absent, reach, witness_absent = [], [], [], []
    for r in records:
        # A brief's named task is the human's own pick, not a backlog dip:
        # neither dip gate below applies to it (the brief's `lanes:` still does).
        # A task an answer released is the human's word too: no dip gate.
        backlog = Path(r["path"]).name not in named_names and not r.get("resume")
        why = pool_gate(r, next_phase)
        if why:
            rejected.append((r["path"], why))
        elif not _lane_ok(r["lane"], session_lane):
            rejected.append((r["path"], f"lane {r['lane']}, session {session_lane}"))
        elif not attended and backlog and lane_absent_why(r):
            rejected.append((r["path"], lane_absent_why(r)))
            lane_absent.append(r["path"])
        elif queue_stop and backlog:
            rejected.append((r["path"], "queue.md empty — no backlog dip "
                                        "(named tasks only)"))
        elif shift_dip and backlog and self_organ_why(r):
            rejected.append((r["path"], self_organ_why(r)))
        elif shift_dip and backlog and not r.get("witness") and not r.get("resume"):
            # A shift dips only witnessed drafts: one without a `Witness:`
            # is reviewed as `judge`, so it is never cheap fill. Counted
            # for the digest; a named task is the human's pick.
            rejected.append((r["path"], "no Witness — a shift dips only witnessed "
                                        "drafts (declare one to make it pickable)"))
            witness_absent.append(r["path"])
        elif scoped_dip and backlog \
                and queue_standing(r, queue, epic_ranks)[0] >= len(queue) \
                and scoped_reach_why(r):
            rejected.append((r["path"], scoped_reach_why(r)))
            reach.append(r["path"])
        else:
            pool.append(r)

    # The queue first; below it priority, THEN review-minutes. `queue.md` is
    # the human's order and outranks everything: a queued prompt beats an
    # unqueued one, and among queued ones the file's order wins, because moving
    # an entry up IS the act of prioritising it. Below the queue a declared
    # `Priority:` outranks cost: cheapest-first alone would pick work the
    # human did not ask for. Cheapest first still decides within a priority.
    for r in pool:
        r["queue_rank"], via = queue_standing(r, queue, epic_ranks)
        r["queued"] = r["queue_rank"] < len(queue)
        if via:
            r["queued_via"] = via
    pool.sort(key=lambda r: (r["queue_rank"], priority_rank(r),
                             r["review_minutes"], r["path"]))

    # `released`: the watcher's own picks whose worker has ended (PR open or
    # not) and that wait on no question, re-dispatch or restart. They stay
    # members (known, counted, never re-dispatched) but hold no library:
    # merges collide, starts do not, and the close-out merges a library's
    # shift PRs in PR order (the merge-order wait), so the next task on that
    # library may start.
    released = released or set()
    members, spent, seen_epics, libs = [], 0, set(), {}
    for r in pool:
        # One slice per epic counts only `Phase:` tasks: a side task of the
        # epic shares the shift with its phase.
        if r["epic"] and has_phase(r) and r["epic"] in seen_epics:
            rejected.append((r["path"], f"epic {r['epic']} already has a phase task in "
                                        "this batch (one Phase: task per epic)"))
            continue
        # Concurrent members do not collide at dispatch (separate worktrees) —
        # they collide at MERGE, because the first /prm moves main and
        # invalidates the others' test and smoke evidence. Only LIBRARY repos
        # claim a shift: they are what the library-first gate serialises and
        # what downstream suites are re-run against. Workspace, docs and organ
        # repos are exempt — two docs changes in one shift cost nothing. A
        # library is held while its worker runs, so two workers never share
        # one; its PRs then merge in PR order at the close-out.
        clash = next((x for x in r["repos"] if x in LIBRARY_REPOS and x in libs), None)
        if clash:
            holder = libs[clash]
            if holder in (held_why or {}):
                # A park's hold (ruling d, amended 2026-11-24 and 11-27), in
                # the spawn loop's words (`_orchestrator.park_hold_suffix`):
                # until when inside its grace, else why it still holds.
                rejected.append((r["path"], f"{clash} held by {holder}{held_why[holder]}"))
                continue
            rejected.append((r["path"], f"{clash} held by {holder} — will start once "
                                        f"{holder}'s worker ends"
                             if Path(r["path"]).name in named_names
                             else f"{clash} held by {holder} while its worker runs"))
            continue
        cost = 0 if r["consequence"] in CHEAP_TIERS else r["review_minutes"]
        if spent + cost > effective_budget:
            rejected.append((r["path"], f"{cost} min would exceed the budget"))
            continue
        members.append(r)
        spent += cost
        if r["epic"] and has_phase(r):
            seen_epics.add(r["epic"])
        if Path(r["path"]).stem not in released:
            libs.update((x, Path(r["path"]).stem) for x in r["repos"]
                        if x in LIBRARY_REPOS and x not in libs)

    other_lane = _lane_counts(
        r for r in records
        if r["unattended"] == "ready" and not _lane_ok(r["lane"], session_lane))
    return {
        "dispatch": [_dispatch_payload(r) for r in members],
        "session_lane": session_lane,
        "review_budget": budget,
        "effective_budget": effective_budget,
        "backpressure": {"awaiting_review": awaiting_review, "cap": cap,
                         "state": pressure, "source": awaiting_source},
        "queue": queue,
        "review_minutes_planned": spent,
        "members": members,
        "rejected": rejected,
        "other_lane_ready": sum(other_lane.values()),
        # Per resource, so the line names what the other machine has to offer
        # (`3 ral, 1 gpu`) rather than a bare count.
        "other_lane_by_lane": other_lane,
        # Where the ready backlog can run, before the session's lane filters it.
        "lane_counts": _lane_counts(r for r in all_records
                                    if r["unattended"] == "ready" and not r.get("done")),
        "brief": brief is not None,
        "attended": attended,
        # The two unattended gates, stated rather than buried in `rejected`.
        "lane_absent": lane_absent,
        "queue_stop": queue_stop,
        # The `backlog: scoped` reach rule, stated likewise.
        "scoped_reach": reach,
        # Backlog drafts with no `Witness:`, kept out of a shift's dip.
        "witness_absent": witness_absent,
        # Per queued epic ledger, what it gives this plan or why nothing.
        "queued_epics": queued_epic_summary(
            all_records + [w for w in held_out
                           if w.get("path") not in {r.get("path") for r in all_records}],
            epic_ranks, members, rejected + [(w.get("path"), why) for w, why in withheld or []],
            queue),
    }


def _lane_counts(records) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in records:
        lane = r.get("lane") or "absent"
        counts[lane] = counts.get(lane, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _dispatch_payload(r: dict) -> str:
    """The exact text a human pastes into one unattended session.

    Written out rather than composed at dispatch time: the launch is the
    human's act (AUTONOMY.md, "What a batch launch is"), so the thing they
    perform carries no decisions.
    """
    return f"Use the start-dev skill. {r['path']} --auto"


def emit(d: dict) -> None:
    lane = d["session_lane"]
    print("== BatchDecision ==")
    print(f"Session lane:      {lane}")
    if d.get("lane_counts"):
        print("Ready by lane:     " + " · ".join(
            f"{k} {n}" for k, n in d["lane_counts"].items()))
    if d.get("brief"):
        print("Brief:             named tasks first, then the brief's backlog "
              "policy; budget is its review-minutes")
    print(f"Review budget:     {d['effective_budget']} of {d['review_budget']} min "
          f"({d['backpressure']['state']}; "
          f"{d['backpressure']['awaiting_review']} awaiting review "
          f"[{d['backpressure'].get('source', 'given')}], "
          f"cap {d['backpressure']['cap']})")
    print(f"Queue:             {len(d.get('queue') or [])} prompt entr"
          f"{'y' if len(d.get('queue') or []) == 1 else 'ies'} from queue.md "
          f"(queued members marked q<n>)")
    print(f"Planned:           {d['review_minutes_planned']} review-minutes over "
          f"{len(d['members'])} member(s)")
    if d.get("attended"):
        print("Mode:              attended (--attended) — an absent Lane reads as "
              "any, an empty queue.md falls back to the backlog order")
    if d.get("queue_stop"):
        # An empty queue is the human saying nothing beyond the brief.
        print("Backlog dip:       STOPPED — queue.md is empty, so this unattended "
              "shift takes the brief's named tasks only")
    if d.get("lane_absent"):
        n = len(d["lane_absent"])
        print(f"Lane absent:       {n} draft(s) excluded — no valid `Lane:`, and an "
              "unattended pick fails closed (declare one; bin/lane_backfill.py)")
    lines = queued_epic_lines(d)
    if lines:
        # One line per queued epic ledger: what it gives this batch, or why
        # nothing — read before the long tally of rejections below.
        print("Queued epics:")
        for line in lines:
            print(f"  {line}")
    print()
    if d["members"]:
        queued = len(d.get("queue") or [])
        for r in d["members"]:
            cost = 0 if r["consequence"] in CHEAP_TIERS else r["review_minutes"]
            rank = r.get("queue_rank", queued)
            mark = f"q{rank + 1}" if rank < queued else "  "
            # A `supervised` member ships under decide-and-flag rather than
            # parking (AUTONOMY.md); say so on the line, so the human
            # approving the batch sees which members carry a flagged
            # decision at review.
            note = ("  (supervised — decide-and-flag at ship)"
                    if r.get("autonomy") == "supervised" else "")
            print(f"  {mark:<3}{cost:>3} min  {r['consequence']:<7} "
                  f"{r['path']}{note}")
            if not r["witness"]:
                print("           (no witness — reviewed as `judge`)")
    elif d["effective_budget"] == 0:
        # At the cap the batch is fill only — and the human still dispatches it.
        # An empty fill-only batch is a finding, not a deadlock: nothing in the
        # backlog costs zero review-minutes, which is what the `notify` tier and
        # the witness field exist to change.
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
        by = ", ".join(f"{n} {k}" for k, n in
                       (d.get("other_lane_by_lane") or {}).items())
        print(f"{d['other_lane_ready']} laptop-lane task(s) are ready ({by}) — "
              "run `batch plan` from the laptop to see them.")
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


# ---------------------------------------------------------- Mind records ---
PR_URL_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
ISSUE_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+")


class BatchUsageError(Exception):
    """Bad input from the human — reported on stderr, exit 2, nothing written."""


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


#: An `active.md` status that says this task's PRs are open and unmerged. The
#: `library-pr:`/`workspace-pr:` keys are the PRIMARY signal — they are the PR
#: ledger (PyAutoMind REFERENCE.md, "The PR keys") — and these words are the
#: fallback for rows without them.
AWAITING_STATUS_WORDS = ("awaiting-merge", "pr open", "pr-open")


def derive_awaiting_review(mind: Path) -> int:
    """How deep the human's review queue already is, read from `active.md`.

    The backpressure input — the one that SHRINKS a batch — must not depend on
    a human supplying it by hand. A task counts when its row names an open PR
    (`library-pr:` / `workspace-pr:`) or its `status:` says so in words.

    Deliberately NOT a `gh` call. `active.md` is the ledger; GitHub is the
    truth about mergeability and nobody should have to be online to plan a
    shift.
    """
    n = 0
    for entry in read_active(mind).values():
        keyed = any(PR_URL_RE.search(v)
                    for key in ("library-pr", "workspace-pr")
                    for v in entry["keys"].get(key, []))
        spoken = any(w in entry["status"].lower() for w in AWAITING_STATUS_WORDS)
        if keyed or spoken:
            n += 1
    return n


# -------------------------------------------------------------------- cli ---
#: Flags other verbs own. Passing one to `plan` or `slice` is a usage error
#: rather than a silent no-op.
NOT_PLAN = ("fetch", "apply", "out")

RC_OK, RC_FINDINGS, RC_USAGE, RC_NO_MIND = 0, 1, 2, 4


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="batch")
    ap.add_argument("verb", choices=["plan", "brief", "digest", "watch",
                                     "slice", "premise", "green", "ready"],
                    nargs="?",
                    default="plan")
    ap.add_argument("prompt", nargs="?", default="",
                    help="slice: the needs-slicing prompt to decompose; "
                         "premise: the draft whose premise to check")
    ap.add_argument("--mind", type=Path, default=None,
                    help="the PyAutoMind checkout (default: the canonical one)")
    ap.add_argument("--budget", type=int, default=DEFAULT_REVIEW_BUDGET,
                    help="review-minutes available in the slot")
    ap.add_argument("--awaiting-review", type=int, default=None,
                    help="tasks already awaiting review (backpressure input); "
                         "default: derived from active.md")
    ap.add_argument("--cap", type=int, default=DEFAULT_BACKPRESSURE_CAP)
    ap.add_argument("--lane", default="", help="override the detected session lane")
    ap.add_argument("--attended", action="store_true",
                    help="plan: a human at the keyboard picks for THIS session — "
                         "an absent Lane reads as any and an empty queue.md "
                         "does not stop the backlog dip (default: unattended, "
                         "both fail closed; see AUTONOMY.md)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    # brief / plan
    ap.add_argument("--check", default="", metavar="FILE", nargs="?", const=True,
                    help="brief: validate this shift brief against "
                         "PyAutoMind/batches/AGENTS.md; watch --stream: only say "
                         "whether the stream is attachable now (no FILE)")
    ap.add_argument("--new", default="", metavar="SLOT",
                    help="brief: print a skeleton shift brief for SLOT (e.g. "
                         "<YYYY-MM-DD>-am) whose goals: come from goals.md; "
                         "needs --review-at; --out FILE writes it instead")
    # the keep-Heart-green lane: `brief --new` and `green`
    ap.add_argument("--green", default="", choices=("",) + _green.MODES,
                    help="brief --new / green: the keep-Heart-green lane — off | "
                         "report | file (bug drafts) | pick (file, then name them "
                         f"as tasks; opt-in). Default: ${_green.MODE_ENV}, else "
                         f"{_green.DEFAULT_MODE} for brief --new, report for green. "
                         "It writes only with --out and an explicit, non-canonical "
                         "--mind")
    ap.add_argument("--green-cap", type=int, default=_green.DEFAULT_CAP,
                    help="brief --new / green: at most this many new drafts")
    ap.add_argument("--issue", default="", metavar="URL",
                    help="brief --new: the shift issue to write as `issue:` instead "
                         "of creating one (with --out, `brief --new` makes one "
                         "`gh issue create` on PyAutoMind unless this is given or "
                         "$PYAUTO_BRIEF_ISSUE=off)")
    ap.add_argument("--heart-json", default="", metavar="FILE",
                    help="brief --new / --check / green: read this saved `readiness --json` "
                         "or state.json instead of Heart (a replay; --at sets now)")
    ap.add_argument("--brief", default="", metavar="FILE",
                    help="plan: compose inside this shift brief (named tasks "
                         "first, then its backlog policy)")
    # slice
    ap.add_argument("--slices", default="", metavar="FILE",
                    help="slice: an agent-authored slice plan (numbered items "
                         "with *Witness:* fields) instead of the parent's own "
                         "`## Slices`/`## Phases` section")
    # digest
    ap.add_argument("--record", default="", metavar="FILE",
                    help="digest / watch: the shift brief record (read-only — "
                         "the watcher alone writes and posts the digest)")
    ap.add_argument("--home", type=Path, default=None,
                    help="digest / watch: the watcher's state directory "
                         "(default: $PYAUTO_ORCHESTRATOR_HOME, else .orchestrator)")
    # ready
    ap.add_argument("--queue", type=Path, default=None, metavar="SLOT_DIR", dest="queue_slot",
                    help="ready: queue each new ruling as a question-add op in this "
                         "shift slot's Mind-writer ledger (default: a dry run that "
                         "writes nothing); --apply instead writes them into --mind's "
                         "questions.md on a session branch (never main, no commit)")
    # watch
    ap.add_argument("--once", action="store_true",
                    help="watch: print one snapshot and exit")
    ap.add_argument("--interval", type=float, default=30.0,
                    help="watch: seconds between refreshes (at least 30)")
    ap.add_argument("--stream", action="store_true",
                    help="watch: print the shift's events, one plain line each, "
                         "until the shift ends (the cockpit's watch; local reads only)")
    ap.add_argument("--from", type=int, default=None, dest="from_seq", metavar="SEQ",
                    help="watch --stream: print every event after this seq first")
    ap.add_argument("--for", type=float, default=None, dest="for_min", metavar="MIN",
                    help="watch --stream: end this segment after MIN minutes "
                         "(prints `segment-end next=--from N`, exit 3)")
    # premise (and the premise leg of `brief --check`)
    ap.add_argument("--root", type=Path, default=None,
                    help="premise: the workspace root holding the repo checkouts "
                         "(default: $PYAUTO_ROOT, else derived)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="premise: read the cached origin/main, do not fetch")
    ap.add_argument("--at", default="",
                    help="premise: judge main as it stood at this ISO time (a replay)")
    ap.add_argument("--offline", action="store_true",
                    help="premise: do not read issue/PR state with gh")
    ap.add_argument("--write-verified", action="store_true",
                    help="premise: on `ok`, stamp `Verified: <date> <sha>` into the "
                         "draft — as a ledger op inside a shift, else in place")
    ap.add_argument("--no-premise", action="store_true",
                    help="brief: skip the premise check of the named tasks")
    # shared by several verbs
    ap.add_argument("--fetch", action="store_true",
                    help="ready: fetch origin before reading main")
    ap.add_argument("--apply", action="store_true",
                    help="slice: write the children; ready: write the rulings "
                         "into --mind's questions.md")
    ap.add_argument("--out", default="",
                    help="brief --new: write the brief to this file")
    ap.add_argument("--review-at", default="",
                    help="when you expect to be back — the shift is dispatch "
                         "-> review-at, and it is yours to declare")
    a = ap.parse_args(argv)

    lane = a.lane or detect_lane()
    a.mind_explicit = a.mind is not None
    mind = (a.mind or BODY_MAP_PATH.parent).resolve()
    if a.prompt and a.verb not in ("slice", "premise"):
        print(f"batch {a.verb}: unexpected argument {a.prompt!r}", file=sys.stderr)
        return RC_USAGE
    if a.slices and a.verb != "slice":
        print("batch: --slices belongs to `batch slice`", file=sys.stderr)
        return RC_USAGE
    try:
        if a.verb == "slice":
            return _main_slice(mind, a)
        if a.verb == "premise":
            return _main_premise(mind, a)
        if a.verb == "brief":
            return _main_brief(mind, a)
        if a.verb == "digest":
            return _main_digest(mind, a)
        if a.verb == "watch":
            return _main_watch(a)
        if a.verb == "green":
            return _main_green(mind, a)
        if a.verb == "ready":
            return _main_ready(mind, a)
        return _main_plan(mind, a, lane)
    except BatchUsageError as e:
        print(e, file=sys.stderr)
        return RC_USAGE


def _main_ready(mind: Path, a) -> int:
    """`batch ready [--queue SLOT_DIR | --apply] [--fetch] [--root DIR]` — the
    readiness pass (`_ready`): every queue.md entry's next unit(s), their
    gates, and the rulings it would file. A dry run by default; the premise
    check is offline unless `--fetch`."""
    import _ready
    if a.queue_slot is not None and a.apply:
        raise BatchUsageError("batch ready: --queue and --apply are exclusive")
    if not (mind / "queue.md").is_file() and not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return RC_NO_MIND
    slot = a.queue_slot.resolve() if a.queue_slot is not None else None
    if slot is not None and _ready.slot_refusal(slot):
        print(_ready.slot_refusal(slot), file=sys.stderr)
        return RC_USAGE
    res = _ready.run(mind, root=a.root, fetch=a.fetch,
                     shift=slot.name if slot is not None else "")
    if a.apply:
        try:
            written = _ready.apply(res, mind)
        except _ready.ApplyRefused as e:
            print(e, file=sys.stderr)
            return RC_USAGE
        print(_ready.report(res, written=written))
        return RC_OK
    if slot is not None:
        try:
            queued = _ready.queue(res, slot)
        except _ready.QueueRefused as e:
            print(e, file=sys.stderr)
            return RC_USAGE
        print(_ready.report(res, queued=queued, slot=slot))
        return RC_OK
    if a.as_json:
        print(json.dumps({k: v for k, v in res.items()}, indent=2, default=str))
    else:
        print(_ready.report(res))
    return RC_OK


def _main_slice(mind: Path, a) -> int:
    """`batch slice <prompt> [--slices FILE] [--apply] [--json]` — propose the
    children of a needs-slicing prompt; only `--apply` writes (`_slice`)."""
    import _slice
    if not a.prompt:
        print("batch slice: name the needs-slicing prompt to slice",
              file=sys.stderr)
        return RC_USAGE
    used = [f"--{f}" for f in NOT_PLAN if f != "apply" and getattr(a, f)]
    if used:
        print(f"batch slice: {', '.join(used)} do(es) not belong to `batch slice`",
              file=sys.stderr)
        return RC_USAGE
    if not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return RC_NO_MIND
    try:
        d = _slice.propose(mind, a.prompt, slices_file=a.slices)
        written = _slice.apply(mind, d) if a.apply and d["ok"] else []
    except _slice.SliceError as e:
        print(e, file=sys.stderr)
        return RC_USAGE
    if a.as_json:
        print(json.dumps({**d, "written": written}, indent=2))
    else:
        print(_slice.report(d, applied=written))
        if a.apply and not d["ok"]:
            print("(--apply refused: the proposal has refusals)")
    return RC_OK if d["ok"] else RC_FINDINGS


def _premise_root(a) -> Path:
    if a.root is not None:
        return a.root.resolve()
    return Path(os.environ.get("PYAUTO_ROOT") or pyauto_root()).resolve()


def _main_premise(mind: Path, a) -> int:
    """`batch premise <draft> [--write-verified] [--at ISO] [--no-fetch] [--json]` —
    does the draft's premise still hold on a fresh main? (`_premise`)

    Exit 0 on `ok` or `unknown`, 1 on `obsolete`: a dispatched worker stops on
    1 and reports the evidence instead of implementing."""
    import _premise
    if not a.prompt:
        print("batch premise: name the draft to check", file=sys.stderr)
        return RC_USAGE
    draft = Path(a.prompt)
    if not draft.is_file():
        draft = find_prompt(mind, a.prompt) or draft
    if not draft.is_file():
        print(f"batch premise: no such draft {a.prompt}", file=sys.stderr)
        return RC_USAGE
    try:
        root = _premise_root(a)
    except Exception as e:  # noqa: BLE001 — degrade to unknown, never exit 1
        root = Path(".")
        print(f"batch premise: no workspace root ({e})", file=sys.stderr)
    res = _premise.safe_check(draft.resolve(), root, fetch=not a.no_fetch,
                              at=a.at or None, offline=a.offline)
    if a.write_verified:
        import _mind_writer
        try:
            res["recorded"] = record_verified(mind, draft.resolve(), res)
        except _mind_writer.ShiftEnvMismatch as e:
            print(f"batch premise: {e}", file=sys.stderr)
            return RC_USAGE
    if a.as_json:
        print(json.dumps(res, indent=2))
    else:
        print(_premise.report(res))
        if a.write_verified:
            print(f"  Verified: {res['recorded']}")
    return RC_FINDINGS if res["status"] == "obsolete" else RC_OK


def record_verified(mind: Path, draft: Path, res: dict) -> str:
    """Stamp `Verified: <date> <sha>` on an `ok` draft.

    Inside a shift (`$PYAUTO_SHIFT_LEDGER_DIR` set) this is a `set-header`
    ledger op the orchestrator commits — a worker never writes PyAutoMind
    (AUTONOMY.md, "One Mind writer per shift"). Outside one it edits the file
    in place and commits nothing. Only `ok` is stamped: a header saying
    "verified" on an obsolete or unchecked premise would be a lie."""
    import _mind_writer
    if res["status"] != "ok":
        return f"not stamped ({res['status']})"
    import _premise
    value = _premise.verified_value(res)
    try:
        rel = draft.relative_to(mind.resolve()).as_posix()
    except ValueError:
        return "not stamped (the draft is not inside the Mind)"
    ledger = _mind_writer.shift_ledger_dir()   # raises on another shift's ledger
    if ledger:
        op = {"op": "set-header", "path": rel, "key": _premise.VERIFIED_KEY,
              "value": value}
        queued = _mind_writer.queue_op(ledger, op)
        return f"queued set-header {rel} → {queued.name}"
    draft.write_text(_mind_writer.set_header(draft.read_text(encoding="utf-8"),
                                             _premise.VERIFIED_KEY, value),
                     encoding="utf-8")
    return f"wrote {_premise.VERIFIED_KEY}: {value} into {rel} (not committed)"


def brief_premises(brief_path: Path, mind: Path, root: Path, *, fetch: bool = True,
                   offline: bool = False) -> list[dict]:
    """The premise verdict of every named task in a brief that resolves.

    Run by `batch brief --check` so a stale pick is flagged before the shift
    starts rather than discovered by the worker it would have cost."""
    import _premise
    try:
        rec = _brief.parse(brief_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, _brief.BriefError):
        return []
    if rec["brief"] is None:
        return []
    views: dict = {}
    out = []
    for task in _brief.tasks_of(rec["brief"]):
        f = _brief._resolve(mind, task)
        if f is not None:
            out.append({**_premise.safe_check(f, root, fetch=fetch, offline=offline,
                                              views=views), "task": task})
    return out


def _main_digest(mind: Path, a) -> int:
    """`batch digest --record <file>` — print the shift's digest; writes nothing.

    The record append and the one issue comment are the watcher's, at
    `review-at:` (`_orchestrator.finish_shift`); this verb is how a person or a
    session reads the digest before then."""
    if not a.record:
        print("batch digest: --record <file> is required", file=sys.stderr)
        return RC_USAGE
    import _digest
    import _orchestrator
    record = Path(a.record)
    rec = _brief.parse(record.read_text(encoding="utf-8"))
    brief = rec["brief"]
    if brief is None:
        print(f"batch digest: {record} has no brief: block", file=sys.stderr)
        return RC_USAGE
    slot = _orchestrator.slot_dir(record, a.home)
    issue = (rec["top"].get("issue") or {}).get("value", "")
    print(_digest.build(brief, slot, _orchestrator.read_counters(slot), issue=issue), end="")
    return RC_OK


def _main_watch(a) -> int:
    """`batch watch --record <file> [--once] [--interval N]` — a live view of a
    running shift; writes nothing anywhere (`_watch`). With `--stream`, the
    shift's event stream (`_watch.stream`)."""
    import _watch
    if isinstance(a.check, str) and a.check:
        print("batch watch: --check takes no file (the record is --record)", file=sys.stderr)
        return RC_USAGE
    if a.stream or a.check is True:
        env = _watch.env_file()
        record = Path(a.record or env.get("PYAUTO_SHIFT_BRIEF") or "")
        if not str(record) or not record.is_file():
            print(f"batch watch --stream: no brief record ({record or 'none'}; pass --record "
                  "or set PYAUTO_SHIFT_BRIEF in the orchestrator env file)", file=sys.stderr)
            return RC_USAGE
        home = a.home or (Path(env["PYAUTO_ORCHESTRATOR_HOME"])
                          if env.get("PYAUTO_ORCHESTRATOR_HOME") else None)
        import _orchestrator
        return _watch.stream(record, _orchestrator.slot_dir(record, home),
                             from_seq=a.from_seq, for_min=a.for_min, as_json=a.as_json,
                             check=a.check is True)
    if not a.record:
        print("batch watch: --record <file> is required", file=sys.stderr)
        return RC_USAGE
    import _orchestrator
    record = Path(a.record)
    if not record.is_file():
        print(f"batch watch: no such brief record {record}", file=sys.stderr)
        return RC_USAGE
    return _watch.watch(record, _orchestrator.slot_dir(record, a.home),
                        interval=a.interval, once=a.once)


#: A brief's slot names its record, `batches/<slot>.md`.
SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(am|pm)$")
#: Defaults `brief --new` writes for the keys the human usually leaves alone.
#: `merge-cap: 0` is the safe one: nothing merges unattended until raised.
#: RAL is in `lanes:` by default: a shift that leaves it out rejects every
#: `Lane: ral` phase the human has queued.
NEW_BRIEF_DEFAULTS = {"review-minutes": str(DEFAULT_REVIEW_BUDGET),
                      "lanes": "any local-dev ral", "merge-cap": "0",
                      "token-budget": "5000000"}
#: The `ral-allowance:` `brief --new` writes beside `ral` in `lanes:` — the
#: block `brief --check` requires then. Edit it per shift.
NEW_BRIEF_RAL_ALLOWANCE = {"packets": "2", "partition": "ral", "cpu-hours": "64"}


def _last_brief_goals(mind: Path) -> tuple[str, list[str]] | None:
    """(record name, goal texts) of the newest batch record with a brief."""
    records = sorted(f for f in (mind / "batches").glob("*.md") if f.name != "AGENTS.md")
    for f in reversed(records):
        try:
            brief = _brief.parse(f.read_text(encoding="utf-8", errors="replace"))["brief"]
        except (OSError, _brief.BriefError):
            continue
        if brief and brief.get("goals"):
            goals = [re.sub(r"^\d+\.\s*", "", c["text"])
                     for c in brief["goals"]["children"]]
            return f.name, [g for g in goals if not g.startswith(_green.GOAL_PREFIX)]
    return None


def goals_report(mind: Path) -> list[str]:
    """What `brief --new` tells the human on stderr: how the goals changed
    since the newest brief."""
    goals = [g["text"] for g in read_goals(mind)]
    L = []
    last = _last_brief_goals(mind)
    if last is None:
        L.append("goals: no earlier brief to compare with")
        return L
    name, before = last
    added = [g for g in goals if g not in before]
    dropped = [g for g in before if g not in goals]
    moved = [(g, before.index(g) + 1, goals.index(g) + 1) for g in goals
             if g in before and before.index(g) != goals.index(g)]
    if not (added or dropped or moved):
        L.append(f"goals: unchanged since {name}")
        return L
    L.append(f"goals since {name}:")
    L += [f"  + {g}" for g in added] + [f"  - {g}" for g in dropped]
    L += [f"  ~ {g} ({a} → {b})" for g, a, b in moved]
    return L


#: `brief --new`'s scope when no goal names an epic or tag: the tiers a shift
#: may merge, under the `backlog: scoped` reach rule.
NEW_BRIEF_SCOPED_TIERS = ("notify", "glance")


def new_brief(mind: Path, slot: str, review_at: str, now=None,
              heart: dict | None = None, issue: str = "") -> str:
    """A skeleton shift brief whose `goals:` are `goals.md`'s, in order.

    `goals.md` has one kind of writer, the human (by hand or in chat), so
    every goal is copied as their word. `backlog: scoped` covers the union of
    the goals' `epics:`/`tags:`; with none named, `scoped` by the tiers a shift
    may merge (`NEW_BRIEF_SCOPED_TIERS`). Every other required key
    gets a default the human edits. Writing the record (with its `review-at:`)
    is the dispatch, so this only composes the text (batches/AGENTS.md
    "Shift brief").

    `heart` is the keep-Heart-green lane's result (`_green.run`): its picks
    become a last `heart-green` goal plus named `tasks:`, and its report the
    record's `## Heart` section.

    `issue` is the shift issue (`create_shift_issue`), written as `issue:`:
    `brief --check` refuses a live brief without it."""
    goals = read_goals(mind)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    epics: list[str] = []
    tags: list[str] = []
    for g in goals:
        epics += [e for e in g["epics"] if e not in epics]
        tags += [t for t in g["tags"] if t not in tags]
    # A queued epic ledger queues its phases, so its epic is in scope:
    # without it a `scoped` brief would keep out the work the queue asks for.
    goal_scoped = bool(epics or tags)
    queued = [e for e in queued_epics(read_queue(mind), survey(mind),
                                      read_epic_ledgers(mind)) if e not in epics]
    shift = {"am": "morning", "pm": "afternoon"}.get(slot.rsplit("-", 1)[-1], slot)
    L = [f"# Batch {slot.rsplit('-', 1)[0]} {slot.rsplit('-', 1)[-1]}",
         f"- dispatched: {now.strftime('%Y-%m-%dT%H:%MZ')}",
         f"- review-at: {review_at}",
         f"- shift: {shift}"]
    if issue:
        L.append(f"- issue: {issue}")
    L += ["- brief:",
          "  - goals:                          # from goals.md, in order"]
    # A goal is one line of plain text (goals.md's own check); ` # ` would
    # read as a trailing comment here, so it is spelled out.
    L += [f"    - {g['n']}. " + re.sub(r"\s#\s", " no. ", g["text"]) for g in goals]
    picks = (heart or {}).get("picks") or []
    if picks:
        L.append(f"    - {len(goals) + 1}. {_green.GOAL_PREFIX}: clear the "
                 "fixable Heart reasons the lane picked (see ## Heart)")
        L.append("  - tasks:                          # the heart-green lane's picks")
        L += [f"    - {t}" for t in picks]
    every = epics + queued
    epics_line = (f"    - epics: {', '.join(every)}"
                  + ("                 # queue.md's queued epics" if queued and not epics
                     else "   # goals' epics, then queue.md's" if queued else ""))
    if goal_scoped:
        L += ["  - backlog: scoped                 # the goals' epics and tags",
              "  - scoped:"]
        if every:
            L.append(epics_line)
        if tags:
            L.append(f"    - tags: {', '.join(tags)}")
    else:
        # No goal names an epic or tag: `scoped`, not `fill-idle`, is the
        # default — the planner dips queue.md first, then only small
        # single-repo tasks, and these tiers are the ones a shift may merge.
        L += ["  - backlog: scoped                 # tiers a shift may merge; beyond "
              "queue.md small single-repo only (ruling 2026-11-16)",
              "  - scoped:",
              f"    - tiers: {', '.join(NEW_BRIEF_SCOPED_TIERS)}"]
        if queued:
            L.append(epics_line)
    L += [f"  - review-minutes: {NEW_BRIEF_DEFAULTS['review-minutes']}",
          f"  - lanes: {NEW_BRIEF_DEFAULTS['lanes']}",
          f"  - merge-cap: {NEW_BRIEF_DEFAULTS['merge-cap']}"
          "                     # unattended glance merges: raise deliberately",
          f"  - token-budget: {NEW_BRIEF_DEFAULTS['token-budget']}"]
    if "ral" in NEW_BRIEF_DEFAULTS["lanes"].split():
        L += ["  - ral-allowance:                   # what the shift may spend on RAL; edit per shift"]
        L += [f"    - {k}: {v}" for k, v in NEW_BRIEF_RAL_ALLOWANCE.items()]
    text = "\n".join(L) + "\n"
    return text + "\n" + _green.section(heart) if heart else text


#: `brief --check`'s word for a named task whose prompt is in `active/`.
NAMED_IN_ACTIVE = ("its prompt is in active/ — already issued: a shift starts it only "
                   "as a resume after an answered question (or it has started)")


def check_plan(brief: dict, mind: Path) -> tuple[dict, dict[str, str], str]:
    """(plan, {path: why held}, note) — the watcher's plan under `brief`, as
    `brief --check` runs it: the claim gate against Mind's local
    `origin/main` (never a fetch), then `plan` unattended on the watcher's
    lane. `note` says when the claims could not be read."""
    import _orchestrator as orch  # noqa: E402 — deferred: it imports this module
    recs = survey(mind)
    note = ""
    claims = orch.origin_claims(mind)
    held: dict[str, str] = {}
    withheld: list[tuple[dict, str]] = []
    if claims is not None and "error" in claims:
        note = (f"brief.tasks: claims on Mind origin/main not read ({claims['error']}) — "
                "the watcher fails closed on that; repo claims not checked here")
    elif claims is not None:
        kept, held = orch.on_origin(recs, mind, own=set())
        withheld = [(r, held[r["path"]]) for r in recs if r["path"] in held]
        recs = kept
    d = plan(recs, session_lane="local-dev", brief=brief, queue=read_queue(mind),
             epic_ledgers=read_epic_ledgers(mind), withheld=withheld)
    return d, held, note


def named_skips(brief: dict, mind: Path,
                planned: tuple[dict, dict[str, str], str] | None = None
                ) -> tuple[dict[str, str], str]:
    """({named task: why it will not start}, a note when the claims on Mind
    origin/main could not be read) — the watcher's own gates, run at
    `brief --check`: the claim gate against Mind's local `origin/main` (never
    a fetch), then `plan` under this brief, unattended, on the watcher's
    lane. A task the planner keeps is not listed; one that resolves to no
    prompt is `_brief.check`'s warning already."""
    named = _brief.tasks_of(brief)
    if not named:
        return {}, ""
    d, held, note = planned or check_plan(brief, mind)
    rejected = {Path(p).name: w for p, w in d["rejected"]}
    rejected.update({Path(p).name: w for p, w in held.items()})
    members = {Path(m["path"]).name for m in d["members"]}
    out = {}
    for t in named:
        name = Path(t).name
        if name in rejected:
            out[t] = rejected[name]
        elif name not in members and _brief._resolve(mind, t) is not None:
            # In active/ (already issued): `_brief.check` resolves it, so no
            # warning came from there, and no survey of draft/ holds it. A
            # shift resumes it only once its question is answered, and on a
            # record re-checked after launch it is a task that started.
            out[t] = NAMED_IN_ACTIVE
    return out, note


#: `PYAUTO_BRIEF_ISSUE=off`: `brief --new --out` makes no shift issue.
BRIEF_ISSUE_ENV = "PYAUTO_BRIEF_ISSUE"
_GITHUB_REMOTE_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def mind_repo(mind: Path) -> str:
    """`owner/repo` of the Mind checkout's `origin` on GitHub, or ""."""
    try:
        res = subprocess.run(["git", "-C", str(mind), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = _GITHUB_REMOTE_RE.search(res.stdout.strip()) if res.returncode == 0 else None
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def create_shift_issue(mind: Path, slot: str, review_at: str, run=None) -> tuple[str, str]:
    """(issue URL, "") or ("", why not): the one `gh issue create` on the Mind
    repo that `brief --new --out` makes (AUTONOMY.md "The Brain reads no
    network" names the exception). It runs in the launch chat, never in the
    watcher."""
    repo = mind_repo(mind)
    if not repo:
        return "", f"no GitHub `origin` remote in {mind} to make the shift issue on"
    body = (f"The shift issue for `batches/{slot}.md` (review at {review_at}).\n\n"
            "The watcher keeps one live status comment here, reads the steering "
            "commands (`/pause`, `/resume`, `/drop`, `/stop`, `/add`, `/cap`, `/kill`) "
            "from comments here, and posts the digest here at `review-at:`.\n")
    run = run or subprocess.run
    try:
        res = run(["gh", "issue", "create", "--repo", repo,
                   "--title", f"Shift {slot} (review at {review_at})", "--body", body],
                  capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"gh issue create failed ({e})"
    m = _brief.ISSUE_RE.search(res.stdout or "") if res.returncode == 0 else None
    if not m:
        return "", (f"gh issue create on {repo} failed (exit {res.returncode}): "
                    + ((res.stderr or res.stdout or "").strip()[:200] or "no issue URL"))
    return m.group(0), ""


def _issue_in(path: Path) -> str:
    """The `issue:` an existing brief file already names, or ""."""
    try:
        top = _brief.parse(path.read_text(encoding="utf-8", errors="replace"))["top"]
    except (OSError, _brief.BriefError):
        return ""
    return (top.get("issue") or {}).get("value", "").strip()


def login_findings(top: dict, brief: dict | None) -> tuple[dict, list[str], list[str]]:
    """(probe result, errors, warnings) of the CLI login for a launch: an
    expired login, or one that lapses before `review-at:`, refuses it. A
    shadow brief starts no worker and is not probed."""
    if brief is None or _brief.is_shadow(brief):
        return {"state": "skipped", "detail": "shadow shift", "expires_at": ""}, [], []
    if _brief.backend_of(brief) == "codex":
        import _codex
        login = _codex.probe()
        # Even merge-cap: 0 requires the independent Opus pre-ship review.
        if login["state"] == "ok":
            review_login = _login.probe()
            if review_login["state"] not in {"ok", "skipped"}:
                return login, ["review login: independent Opus pre-ship review requires a verified Claude login"], []
    else:
        login = _login.probe()
    errors, warnings = [], []
    if login["state"] == "expired":
        errors.append(f"login: {login['detail']}" if _brief.backend_of(brief) == "codex"
                      else f"login: {_login.EXPIRED_LINE} ({login['detail']})")
    elif login["state"] == "unknown":
        warnings.append(f"login: could not tell whether the CLI login holds "
                        f"({login['detail']})")
    elif login["state"] == "ok":
        review_at = _brief._iso((top.get("review-at") or {}).get("value", ""))
        lapses = _login.expires(login)
        if review_at is not None and lapses is not None and lapses < review_at:
            errors.append(f"login: the CLI login expires at {login['expires_at']}, before "
                          f"review-at {top['review-at']['value']} — run `claude /login` "
                          "before the launch")
    return login, errors, warnings


#: `brief --check`'s Heart read: `off` skips it (a test-only switch); a saved
#: document is `--heart-json`. Anything else reads Heart as `brief --new` does.
HEART_PROBE_ENV = "PYAUTO_HEART_PROBE"
#: The launch read R1 writes into the record, between these marks.
R1_START, R1_END = "<!-- heart-launch-read:start -->", "<!-- heart-launch-read:end -->"
#: The severities a launch judges. A STALE reason is an evidence gap: it is
#: recorded in the launch read, marked "not judged", and never judged here.
LAUNCH_SEVERITIES = ("red", "yellow")
#: A touched set that could not be resolved: every repo counts as touched.
ALL_REPOS = "*"


def _known_repos() -> set[str]:
    """Every spelling of every repo the body map knows (`_sizing`)."""
    from _sizing import KNOWN_REPOS  # noqa: E402
    return set(KNOWN_REPOS)


def _workspace_repos() -> set[str]:
    """Every workspace repo the body map knows: `Target: workspaces`."""
    from _sizing import WORKSPACE_REPOS  # noqa: E402
    return set(WORKSPACE_REPOS)


def _repo_key(entry: str) -> str:
    """A `Repos:` line or `Target:` value as one normalised repo key: the last
    path segment, with any `(…)`, ` — …` or ` - …` tail and backticks or `@`
    stripped. "" when nothing is left."""
    s = re.split(r"\s+[—–-]\s+|\s*\(", entry.strip(), 1)[0]
    s = s.strip().strip("`").lstrip("@").rstrip("/")
    return normalise_repo(s.rsplit("/", 1)[-1]) if s else ""


def _prompt_repos(path: Path, mind: Path) -> tuple[set[str], str]:
    """(the repos one prompt touches, why it cannot be resolved or "")."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return set(), f"{path.name} unreadable ({e})"
    known, out, bad = _known_repos(), set(), []
    entries = []
    block = re.search(r"^Repos:\n((?:- .+\n?)+)", text, re.M)
    if block:
        entries += [ln[1:] for ln in block.group(1).splitlines() if ln.startswith("- ")]
    m = re.search(r"^Target:\s*(.+?)\s*$", text, re.M)
    if m:
        entries.append(m.group(1))
    for entry in entries:
        key = _repo_key(entry)
        if key == "workspaces":
            out |= {normalise_repo(w) for w in _workspace_repos()}
        elif key and key in known:
            out.add(key)
        else:
            bad.append(entry.strip())
    out |= {normalise_repo(r) for r in parse_prompt(path, mind, text)["repos"]
            if normalise_repo(r) in known}
    if bad:
        return out, f"{path.name}: {', '.join(bad)} is not a known repo"
    if not out:
        return out, f"{path.name} names no repo"
    return out, ""


def touched_repos(brief: dict, mind: Path, planned: dict | None = None
                  ) -> tuple[set[str], str]:
    """(every repo the brief may touch, normalised; why it is every repo or "").

    A launch-time prediction: the named tasks, every member the watcher's plan
    takes, and for a `backlog: fill-idle | scoped` brief every backlog prompt
    its scope admits. Anything that cannot be resolved fails closed: the set
    is `{ALL_REPOS}` and R1 cannot pass."""
    paths, why = [], []
    for t in _brief.tasks_of(brief):
        p = _brief._resolve(mind, t)
        if p is None:
            why.append(f"{t} resolves to no prompt")
        else:
            paths.append(p)
    paths += [mind / m["path"] for m in (planned or {}).get("members") or []
              if m.get("path")]
    if brief.get("backlog", {}).get("value", "none") != "none":
        try:
            kept, _rejected, _named = _brief.scope(survey(mind), brief)
        except Exception as e:  # noqa: BLE001 — any failure fails closed
            return {ALL_REPOS}, f"the backlog scope could not be read ({e})"
        paths += [mind / r["path"] for r in kept]
    out: set[str] = set()
    for p in dict.fromkeys(paths):
        repos, bad = _prompt_repos(p, mind)
        out |= repos
        if bad:
            why.append(bad)
    if why:
        return {ALL_REPOS}, "; ".join(why[:3]) + (f"; +{len(why) - 3} more"
                                                   if len(why) > 3 else "")
    return {r for r in out if r}, ""


def _names_repo(finding: dict, touched: set[str]) -> str:
    """The touched repo a Heart reason names (its own `repo`, or any word of
    its text), or "". Every reason names one when the set is `{ALL_REPOS}`."""
    if ALL_REPOS in touched:
        return "every repo (touched set unresolved)"
    names = {normalise_repo(finding.get("repo") or "")}
    names |= {normalise_repo(w) for w in re.findall(r"[\w.-]+", finding.get("text", ""))}
    hit = sorted(names & touched)
    return hit[0] if hit else ""


def _launch_findings(heart: dict, severities) -> list[dict]:
    return [f for r in heart.get("reasons") or [] if r.get("severity") in severities
            for f in _green.classify(r)]


def heart_launch(top: dict, brief: dict | None, mind: Path, a,
                 planned: dict | None = None) -> tuple[dict, list[str], list[str]]:
    """(result, errors, warnings) of Heart at a shift launch (AUTONOMY.md,
    "Leg 4 under a batch launch": ruling R1 2026-11-17 and the rulings of
    2026-11-27). The human's `heart-ack:` passes any read. Without it, a RED
    or YELLOW, or a read that is grey, unreadable, missing or over 6 h old,
    is refused — except a fresh RED or YELLOW whose every red and yellow
    reason is local-checkout `report only` and names no repo the brief
    touches: then `r1` is set and the reason set goes into the record
    (`write_launch_read`). A shadow brief starts no worker and is not read."""
    res = {"state": "skipped", "r1": False, "findings": [], "stale": []}
    if brief is None or _brief.is_shadow(brief):
        return res, [], []
    ack = top.get("heart-ack")
    if ack and (ack["value"] or ack["children"]):
        return dict(res, state="acknowledged"), [], []
    if not a.heart_json and os.environ.get(HEART_PROBE_ENV, "").lower() == "off":
        return dict(res, state="not read"), [], []
    now = _brief._iso(a.at) if a.at else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    heart = _green.read_heart(a.heart_json, now=now)
    status, age = str(heart.get("status") or "grey").lower(), heart.get("age_hours")
    res.update(state=status, heart=heart)
    if status == "green":
        return res, [], []
    need = "heart-ack: missing — "
    tail = " (AUTONOMY.md, leg 4 under a batch launch, rulings of 2026-11-27)"
    if status not in ("red", "yellow"):
        return res, [need + f"Heart read {status.upper()} "
                     f"({heart.get('why') or 'no verdict'}): a launch needs a fresh "
                     "read or your acknowledgement" + tail], []
    if age is None or age > _green.MAX_AGE_HOURS:
        return res, [need + f"Heart {status.upper()} evidence "
                     + ("of unknown age" if age is None else f"{age:.1f} h old")
                     + f", over the {_green.MAX_AGE_HOURS:g} h rule: a launch needs a "
                     "fresh read or your acknowledgement" + tail], []
    touched, unresolved = touched_repos(brief, mind, planned)
    findings = _launch_findings(heart, LAUNCH_SEVERITIES)
    res.update(findings=findings, stale=_launch_findings(heart, ("stale",)),
               touched=sorted(touched), unresolved=unresolved)
    why = []
    for f in findings:
        repo = _names_repo(f, touched)
        if f["cls"] != "local-checkout" or not f["action"].startswith("report only"):
            why.append(f"[{f['severity']}] {f['text']} ({f['cls']})")
        elif repo:
            why.append(f"[{f['severity']}] {f['text']} (names {repo}, which this brief "
                       "touches)")
    if why:
        if unresolved:
            why.append(f"touched repos unresolved: {unresolved}")
        return res, [need + f"Heart is {status.upper()} and needs your acknowledgement: "
                     + "; ".join(why[:5]) + (f"; +{len(why) - 5} more" if len(why) > 5
                                              else "") + tail], []
    res["r1"] = True
    return res, [], []


def launch_read(res: dict) -> str:
    """The reason set R1 writes into the record under `## Heart`."""
    h = res["heart"]
    touched = ", ".join(res.get("touched") or []) or "none named"
    L = [R1_START, "### Launch read — no `heart-ack:` needed (R1, 2026-11-17)", "",
         f"Heart **{res['state'].upper()}**, read {h.get('updated') or 'never'} from "
         f"{h.get('source', 'none')}. Every red and yellow reason is local-checkout "
         f"`report only` and none names a repo this brief touches ({touched}), so the "
         "shift launches without your `heart-ack:` (AUTONOMY.md, leg 4 under a batch "
         "launch). The reason set:", ""]
    L += [f"- [{f['severity']}] {f['text']} — rule `{f['rule']}`" for f in res["findings"]]
    L += [f"- [stale] {f['text']} — rule `{f['rule']}` — not judged (an evidence gap)"
          for f in res.get("stale") or []]
    return "\n".join(L + [R1_END]) + "\n"


def _with_launch_read(text: str, block: str) -> str:
    """`text` with the launch read set to `block` ("" removes it)."""
    if R1_START in text and R1_END in text:
        head, rest = text.split(R1_START, 1)
        rest = rest.split(R1_END, 1)[1]
        if block:
            return head + block.rstrip("\n") + rest
        return head.rstrip("\n") + "\n" + rest.lstrip("\n") if rest.strip() else \
            head.rstrip("\n") + "\n"
    if not block:
        return text
    if "\n## Heart\n" in text:
        head, rest = text.split("\n## Heart\n", 1)
        nxt = re.search(r"^## ", rest, re.M)
        cut = nxt.start() if nxt else len(rest)
        body = rest[:cut].rstrip("\n") + "\n\n" + block + ("\n" if nxt else "")
        return head + "\n## Heart\n" + body + rest[cut:]
    return text.rstrip("\n") + "\n\n## Heart\n\n" + block


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def record_write_hold(path: Path) -> str:
    """Why `--check` may not write into the record at `path`, or "": never into
    the shared canonical Mind checkout (`$PYAUTO_MIND`, else the resolved
    one), nor into a record already on its checkout's `origin/main`. A record
    outside git (`--out`) or in a temp worktree is fine."""
    path = Path(path).resolve()
    top = _git(path.parent, "rev-parse", "--show-toplevel")
    if top is None or top.returncode != 0 or not top.stdout.strip():
        return ""
    root = Path(top.stdout.strip()).resolve()
    canonical = Path(os.environ.get("PYAUTO_MIND") or BODY_MAP_PATH.parent).resolve()
    if root == canonical:
        return (f"{path} is in the shared canonical Mind checkout ({root}) — write the "
                "brief in a temp worktree on origin/main and check it there")
    rel = path.relative_to(root).as_posix()
    on_main = _git(root, "cat-file", "-e", f"origin/main:{rel}")
    if on_main is not None and on_main.returncode == 0:
        return (f"{rel} is already on origin/main — the launch read goes in before the "
                "push")
    return ""


def write_launch_read(path: Path, res: dict) -> tuple[bool, str]:
    """Set the record's launch read: R1's reason set when `res["r1"]`, else
    remove a launch read left by an earlier check. (changed?, why it could not
    be written or ""). Nothing is written when the text would not change."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"{path} unreadable ({e})"
    new = _with_launch_read(text, launch_read(res) if res["r1"] else "")
    if new == text:
        return False, ""
    hold = record_write_hold(path)
    if hold:
        return False, hold
    path.write_text(new, encoding="utf-8")
    return True, ""


def goal_one_warning(path: Path, mind: Path) -> str:
    """A warning when `goals.md`'s goal 1 is missing from the brief at `path`."""
    goals = read_goals(mind)
    if not goals:
        return ""
    try:
        brief = _brief.parse(path.read_text(encoding="utf-8", errors="replace"))["brief"]
    except (OSError, _brief.BriefError):
        return ""
    node = (brief or {}).get("goals")
    have = " ".join(c["text"] for c in node["children"]) if node else ""
    if goals[0]["text"].lower() in have.lower():
        return ""
    return (f"brief.goals: goal 1 of goals.md (\"{goals[0]['text']}\") is not "
            "in this brief — `batch brief --new` copies the current list")


def _main_brief(mind: Path, a) -> int:
    """`batch brief --check <file>` — exit 0 valid, 1 refused; read-only but
    for one write: a Heart RED or YELLOW that ruling R1 lets launch without a
    `heart-ack:` has its reason set written into the record (`heart_launch`).
    `batch brief --new <slot> --review-at <ISO>` — print (or `--out`) a
    skeleton brief whose goals come from goals.md."""
    if a.check is True:
        print("batch brief --check: name the brief FILE to check", file=sys.stderr)
        return RC_USAGE
    if a.new:
        if a.check:
            print("batch brief: --new and --check are separate runs", file=sys.stderr)
            return RC_USAGE
        if not SLOT_RE.match(a.new):
            print(f"batch brief --new: slot {a.new!r} is not YYYY-MM-DD-am|pm",
                  file=sys.stderr)
            return RC_USAGE
        if not a.review_at or _brief._iso(a.review_at) is None:
            print("batch brief --new: --review-at <ISO time> is required — the "
                  "grant expires there, and it is yours to declare", file=sys.stderr)
            return RC_USAGE
        if a.issue and not _brief.ISSUE_RE.fullmatch(a.issue.strip()):
            print(f"batch brief --new: --issue {a.issue!r} is not a GitHub issue URL",
                  file=sys.stderr)
            return RC_USAGE
        heart = green_lane(mind, a, os.environ.get(_green.MODE_ENV) or _green.DEFAULT_MODE,
                           preview=not a.out)
        if heart["filed"]:
            print(f"batch brief --new: heart-green filed {len(heart['filed'])} "
                  f"draft(s) in {mind} (uncommitted — commit them with the "
                  "record): " + ", ".join(heart["filed"]), file=sys.stderr)
        for line in goals_report(mind):
            print(line, file=sys.stderr)
        # The shift issue is made last, just before the write, so nothing that
        # can still fail stands between the two. A file that already names one
        # keeps it: a re-run never makes a second.
        issue = a.issue.strip() or (_issue_in(Path(a.out)) if a.out else "")
        made = False
        if a.out and not issue and \
                os.environ.get(BRIEF_ISSUE_ENV, "").strip().lower() != "off":
            issue, why = create_shift_issue(mind, a.new, a.review_at)
            if not issue:
                print(f"batch brief --new: no shift issue, so no brief written — {why}. "
                      "Pass --issue <url> to name one by hand.", file=sys.stderr)
                return RC_FINDINGS
            made = True
            print(f"batch brief --new: made the shift issue {issue}", file=sys.stderr)
        text = new_brief(mind, a.new, a.review_at, heart=heart, issue=issue)
        if a.out:
            try:
                Path(a.out).write_text(text, encoding="utf-8")
            except OSError as e:
                hint = (f" The shift issue {issue} exists: re-run with `--issue {issue}` "
                        "so no second one is made." if made else "")
                print(f"batch brief --new: could not write {a.out} ({e}).{hint}",
                      file=sys.stderr)
                return RC_FINDINGS
            print(f"batch brief --new: wrote {a.out} "
                  f"({len(read_goals(mind))} goal(s) from goals.md)")
        else:
            sys.stdout.write(text)
        if not read_goals(mind):
            print("batch brief --new: goals.md has no goals — `brief --check` "
                  "refuses a brief without one", file=sys.stderr)
        return RC_OK
    if not a.check:
        print("batch brief: --check <file> or --new <slot> "
              "(the digest is `batch digest --record <file>`)", file=sys.stderr)
        return RC_USAGE
    res = _brief.check(Path(a.check), mind)
    # What only a launch needs: the shift issue, and a CLI login that holds
    # until review-at. `_brief.check` stays the watcher's.
    try:
        rec = _brief.parse(Path(a.check).read_text(encoding="utf-8", errors="replace"))
    except (OSError, _brief.BriefError):
        rec = None
    if rec is not None:
        res["errors"] += _brief.launch_errors(rec["top"], rec["brief"])
        login, errs, warns = login_findings(rec["top"], rec["brief"])
        res["login"] = login
        res["errors"] += errs
        res["warnings"] += warns
        # A granted `ral` lane a worker cannot reach: one BatchMode ssh, a
        # warning only. A shadow brief starts no worker.
        if rec["brief"] is not None and not _brief.is_shadow(rec["brief"]):
            res["ral"], warns = _ral.findings(_brief.lanes_of(rec["brief"]), mind)
            res["warnings"] += warns
        res["ok"] = not res["errors"]
    warn = goal_one_warning(Path(a.check), mind)
    if warn:
        res["warnings"].append(warn)
    # Every named task that will not start, with the planner's own reason,
    # and the organ rule for each one, before the shift opens.
    res["notes"] = []
    if rec is not None and rec["brief"] is not None:
        planned = check_plan(rec["brief"], mind)
        why_not, claim_note = named_skips(rec["brief"], mind, planned)
        res["warnings"] += [f"brief.tasks: {Path(t).stem} will not start — {w}"
                            for t, w in why_not.items()]
        if claim_note:
            res["warnings"].append(claim_note)
        # Each queued epic ledger, and why it gives this shift nothing.
        res["queued_epics"] = planned[0]["queued_epics"]
        res["warnings"] += [f"queued epic {e['line']}" for e in res["queued_epics"]
                            if not e["taken"]]
        res["notes"] += [f"queued epic {e['line']}" for e in res["queued_epics"]
                         if e["taken"]]
        for t in _brief.tasks_of(rec["brief"]):
            f = _brief._resolve(mind, t)
            if f is not None:
                errs, warns, notes = _brief.organ_findings(Path(t).stem, f, mind)
                res["errors"] += errs
                res["warnings"] += warns
                res["notes"] += notes
        # Heart at the launch (R1): a report-only RED or YELLOW on repos the
        # brief does not touch needs no `heart-ack:`; its reason set is
        # written into the record instead. The one write `--check` makes.
        heart, errs, warns = heart_launch(rec["top"], rec["brief"], mind, a, planned[0])
        res["heart"] = {k: v for k, v in heart.items()
                        if k in ("state", "r1", "touched", "unresolved")}
        res["heart"]["reasons"] = [f"[{f['severity']}] {f['text']}"
                                   for f in heart["findings"] + heart["stale"]]
        res["errors"] += errs
        res["warnings"] += warns
        if heart["state"] != "not read" and not _brief.is_shadow(rec["brief"]):
            changed, hold = write_launch_read(Path(a.check), heart)
            res["heart"]["written"] = changed
            if hold and heart["r1"]:
                res["errors"].append(f"heart: R1 holds, but its reason set cannot be "
                                     f"written into the record: {hold}")
            elif hold:
                res["warnings"].append(f"heart: an earlier launch read is left in the "
                                       f"record: {hold}")
            elif changed and not heart["r1"]:
                res["notes"].append("heart: removed the earlier R1 launch read — this "
                                    "read does not qualify")
        if heart["r1"]:
            res["notes"].append(f"heart: {heart['state'].upper()}, every reason report "
                                "only and none on a touched repo — no heart-ack needed "
                                "(R1); the reason set is under ## Heart")
        res["ok"] = not res["errors"]
    # The premise leg: a named task whose premise is gone on main is flagged
    # here, before the shift pays a worker to discover it. A warning, not a
    # refusal — the check is mechanical, and the human reads the evidence.
    res["premise"] = [] if a.no_premise else brief_premises(
        Path(a.check), mind, _premise_root(a), fetch=not a.no_fetch,
        offline=a.offline)
    for p in res["premise"]:
        if p["status"] == "obsolete":
            res["warnings"].append(f"brief.tasks: {p['task']} premise OBSOLETE on main — "
                                   + "; ".join(p["reasons"] + p["evidence"][:2]))
    if a.as_json:
        print(json.dumps(res, indent=2))
    else:
        print(f"== Shift brief: {a.check} — {'OK' if res['ok'] else 'REFUSED'} ==")
        for e in res["errors"]:
            print(f"  ✗ {e}")
        for w in res["warnings"]:
            print(f"  ! {w}")
        for n in res.get("notes") or []:
            print(f"  · {n}")
        for p in res["premise"]:
            print(f"  premise {p['status']}: {p['task']}")
    return RC_OK if res["ok"] else RC_FINDINGS


#: Where the lane may not write: the shared, canonical Mind checkout other
#: sessions work in (shared-Mind writes go through a temp worktree).
SHARED_MIND_HOLD = ("--mind is not a linked worktree ({}) — a main checkout is the "
                    "shared canonical Mind; the lane writes drafts only into a "
                    "Mind the caller names that is a temp "
                    "worktree on origin/main (`git -C <mind> worktree add <dir> "
                    "origin/main`), passed as --mind, committed and pushed from there")


def is_linked_worktree(path: Path) -> bool:
    """True only for a LINKED git worktree (`--git-dir` differs from
    `--git-common-dir`). The main checkout of any clone, wherever it lives,
    is False — so is anything git cannot read."""
    dirs = []
    for flag in ("--git-dir", "--git-common-dir"):
        try:
            out = subprocess.run(["git", "-C", str(path), "rev-parse", flag],
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if out.returncode != 0 or not out.stdout.strip():
            return False
        dirs.append((path / out.stdout.strip()).resolve())
    return dirs[0] != dirs[1]


def write_hold(mind: Path, a, preview: bool) -> str:
    """Why the lane may not write here, or "": never in a preview, never into
    an implicit Mind, and only into a linked worktree — the main checkout of
    any Mind clone is the shared one."""
    if preview:
        return "a preview (no --out) writes nothing"
    if not getattr(a, "mind_explicit", False) or not is_linked_worktree(mind):
        return SHARED_MIND_HOLD.format(mind)
    return ""


def green_lane(mind: Path, a, default_mode: str, preview: bool = False) -> dict:
    """Run the keep-Heart-green lane for `brief --new` / `green` (`_green`).
    It reads Heart and may write NEW drafts and its state file — only when
    `write_hold` allows; nothing else."""
    mode = a.green or default_mode
    if mode not in _green.MODES:
        raise BatchUsageError(f"batch: --green {mode!r} — one of "
                              + " | ".join(_green.MODES))
    now = _brief._iso(a.at) if a.at else None
    if now is not None and now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    if mode == "off":
        heart = {"status": "grey", "source": "not read", "reasons": []}
    else:
        heart = _green.read_heart(a.heart_json, now=now)
    import _orchestrator  # noqa: E402 — deferred: only the state path
    home = a.home or _orchestrator.orchestrator_home()
    lanes = NEW_BRIEF_DEFAULTS["lanes"].split()
    return _green.run(mind, heart, mode=mode, cap=max(a.green_cap, 0), lanes=lanes,
                      state_path=Path(home) / _green.STATE_NAME, now=now,
                      hold=write_hold(mind, a, preview))


def _main_green(mind: Path, a) -> int:
    """`batch green [--green report|file|pick] [--heart-json F] [--json]` —
    the lane on its own: classify Heart's reasons and (from `file`) file the
    fixable ones. Defaults to `report`, which writes nothing."""
    if not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return RC_NO_MIND
    res = green_lane(mind, a, os.environ.get(_green.MODE_ENV) or "report")
    if a.as_json:
        print(json.dumps(res, indent=2, default=str))
    else:
        sys.stdout.write(_green.section(res))
    return RC_OK


def _main_plan(mind: Path, a, lane: str) -> int:
    used = [f"--{f}" for f in NOT_PLAN if getattr(a, f)]
    if used:
        print(f"batch: {', '.join(used)} do(es) not belong to `batch plan`",
              file=sys.stderr)
        return RC_USAGE
    if not (mind / "draft").is_dir():
        print(f"batch: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return RC_NO_MIND
    # Derived unless the human said otherwise. `is None`, not falsiness:
    # `--awaiting-review 0` is a human asserting the queue is empty, and it
    # must beat the derivation rather than fall through to it.
    if a.awaiting_review is None:
        awaiting, source = derive_awaiting_review(mind), "derived from active.md"
    else:
        awaiting, source = a.awaiting_review, "--awaiting-review"
    brief = None
    if a.brief:
        res = _brief.check(Path(a.brief), mind)
        if not res["ok"]:
            print(f"batch plan: the brief {a.brief} is refused — run "
                  "`batch brief --check` for the reasons", file=sys.stderr)
            return RC_FINDINGS
        brief = _brief.parse(Path(a.brief).read_text(encoding="utf-8"))["brief"]
    d = plan(survey(mind), budget=a.budget, session_lane=lane,
             awaiting_review=awaiting, cap=a.cap, queue=read_queue(mind),
             awaiting_source=source, brief=brief, attended=a.attended, epic_ledgers=read_epic_ledgers(mind))
    if a.as_json:
        print(json.dumps(d, indent=2))
        return RC_OK
    emit(d)
    return RC_OK


if __name__ == "__main__":
    sys.exit(main())

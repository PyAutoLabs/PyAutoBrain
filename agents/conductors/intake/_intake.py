#!/usr/bin/env python3
"""agents/conductors/intake/_intake.py — analysis core for the Intake Agent.

The Intake Agent (organism-facing: the **Conception Agent**) is where a task is
*conceived*: it turns raw input — a text-vomit idea, a bug report, an ideas.md
bullet — into a **formal, grouped, headed PyAutoMind prompt** that the Feature /
Bug / … agents can then reason over. It sits strictly *before* create_issue /
start_dev: it FILES a prompt, it does not start development.

    raw input  ->  Intake Agent  ->  PyAutoMind draft/<work-type>/<target>/<name>.md
                                      (with a light Type/Target/Difficulty/…
                                       header — no YAML)

Boundary (see AGENTS.md): `/route` infers a work-type and *dispatches* (starts
dev now); intake infers a work-type and *files a prompt* (defers). Low-confidence
classification lands in `triage/` — the existing unclassified bucket, reused not
reinvented. Difficulty is OWNED here (scope is decided during the intake
back-and-forth) and persisted into the header via the shared sizing faculty, so
the Feature Agent later trusts the same number.

Stdlib only. Writes ONLY under --apply; every other path is read-only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import re
import sys
from pathlib import Path

# The shared sizing faculty: prompt parsing, the PyAutoMind taxonomy/vocabulary,
# repo resolution (incl. the organism repos), and the difficulty heuristic. Both
# the Feature Agent and this agent consult it — one source of truth for sizing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    WORK_TYPES, LIBRARY_REPOS, WORKSPACE_REPOS, ORGANISM_REPOS, KNOWN_REPOS,
    RISK_KEYWORDS, AMBIGUITY_KEYWORDS, normalise_repo, estimate_difficulty, _hits,
    policy as _sizing_policy, BODY_MAP_PATH,
)

# --- work-type classification -------------------------------------------------
# Keyword signals per work-type. The classifier scores each type by keyword hits
# (word-boundary prefix match via _sizing._hits) and picks the strongest; ties /
# zero-signal fall to `triage`. `feature` verbs are the natural default for "I
# want X", so they are broad — but bug/test/docs/etc. win when their signals fire.
WORK_TYPE_SIGNALS = {
    "bug": ["bug", "crash", "regression", "fails", "failing", "broken", "error",
            "traceback", "incorrect", "wrong", "nan", "exception", "does not work",
            "doesn't work", "raises", "stack trace", "segfault"],
    "test": ["test", "smoke test", "coverage", "parity", "unit test",
             "regression test", "pytest", "assert"],
    "docs": ["document", "docs", "tutorial", "notebook", "example script",
             "guide", "readme", "docstring", "walkthrough", "how-to", "howto"],
    "refactor": ["refactor", "restructure", "reorganise", "reorganize", "rename",
                 "tidy", "decouple", "clean up", "cleanup the", "extract into",
                 "split out", "no behaviour change", "no behavior change"],
    "release": ["release", "pypi", "changelog", "version bump", "tag a",
                "packaging", "deploy", "wheel"],
    "maintenance": ["dependency", "dependencies", "bump", "upgrade", "pin ",
                    "version cap", "tech debt", "hygiene", "housekeeping"],
    "research": ["research", "investigate", "explore", "study", "figure out",
                 "open question", "not sure", "design note", "scoping",
                 "literature", "compare approaches"],
    "experiment": ["experiment", "spike", "proof of concept", "proof-of-concept",
                   "poc", "prototype", "try out", "sandbox"],
    # `_hits` is word-boundary *prefix* matching, so keep bare stems that would
    # over-fire out: "add " (with the space) matches "add X" but not "address"/
    # "additional"; "new " not "renew".
    "feature": ["add ", "implement", "support", "introduce", "enable", "new ",
                "extend", "build a", "create a", "capability", "feature"],
}
# Order used to break exact-score ties (more specific intent wins over feature).
TYPE_PRECEDENCE = ["bug", "test", "docs", "refactor", "release", "maintenance",
                   "research", "experiment", "feature"]

# --- target inference ---------------------------------------------------------
# When no @RepoName resolves a target, guess the domain from keywords. Maps a
# domain keyword -> the target folder (second-folder slug) it belongs under.
TARGET_SIGNALS = _sizing_policy()["target_signals"]

# Human-readable display name for the header's `Target:` line.
REPO_DISPLAY = {
    "autonerves": "PyAutoNerves", "autoconf": "PyAutoNerves",  # autoconf = legacy alias
    "autofit": "PyAutoFit", "autoarray": "PyAutoArray",
    "autogalaxy": "PyAutoGalaxy", "autolens": "PyAutoLens",
    "pyautomind": "PyAutoMind", "pyautobrain": "PyAutoBrain",
    "pyautoheart": "PyAutoHeart", "pyautobuild": "PyAutoHands",
    "pyautomemory": "PyAutoMemory", "autohands": "PyAutoHands",
    "autobuild": "PyAutoHands",  # back-compat: the package was renamed autobuild -> autohands
    "workspaces": "workspaces",
}
PRIORITY_HIGH = ["urgent", "asap", "blocker", "blocking", "critical", "important",
                 "high priority", "must fix", "regression"]
PRIORITY_LOW = ["someday", "nice to have", "eventually", "low priority", "minor",
                "when there is time", "backlog"]


def _slug(text: str, maxwords: int = 7) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "_".join(words[:maxwords])
    return slug[:48].strip("_") or "untitled"


def _title(text: str) -> str:
    """First markdown heading, else first non-empty line, trimmed to a title."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = s.lstrip("#").strip().rstrip(":").rstrip(".")
        # Keep it title-length: first sentence / ~10 words.
        s = re.split(r"(?<=[a-z])[.?!]\s", s)[0]
        return " ".join(s.split()[:10]) or "Untitled"
    return "Untitled"


def _repos_in(text: str) -> list:
    # Resolve both @RepoName mentions and bare repo names — a raw text dump often
    # writes "autolens" / "pyautobrain", not "@PyAutoLens". The known-repo names
    # all carry an auto/pyauto/howto stem, so a word-boundary match is safe (it
    # will not fire on generic words, and \b keeps "autolens" out of
    # "autolens_workspace").
    found = {normalise_repo(m) for m in re.findall(r"@[A-Za-z0-9._/-]+", text)}
    low = text.lower()
    for token in KNOWN_REPOS:
        if re.search(r"\b" + re.escape(token) + r"\b", low):
            found.add(normalise_repo(token))
    return sorted(m for m in found if m in KNOWN_REPOS)


def classify_work_type(text: str):
    """Return (work_type, confidence, per_type_hits)."""
    scores = {}
    for wt, sigs in WORK_TYPE_SIGNALS.items():
        # Word-boundary prefix match (shared _hits) — not plain substring, so
        # "add" does not fire on "address" and "test" not on "latest".
        hits = _hits(text, sigs)
        if hits:
            scores[wt] = hits
    if not scores:
        return "triage", "low", {}
    best = max(scores, key=lambda k: (len(scores[k]), -TYPE_PRECEDENCE.index(k)))
    top = len(scores[best])
    contenders = [k for k in scores if len(scores[k]) == top]
    # A confident call needs a clear winner; a tie across dissimilar types (e.g.
    # bug vs feature both at 1) is genuinely ambiguous -> triage.
    if len(contenders) > 1 and best != "feature" and "feature" not in contenders:
        # Distinct non-feature types tied: unclear which kind of work this is.
        if len({c for c in contenders}) > 1:
            return "triage", "low", scores
    conf = "high" if top >= 2 else "medium"
    return best, conf, scores


def infer_target(text: str, repos: list):
    """Return (target_folder, primary_repo_display, resolved_repos)."""
    lib = [r for r in repos if r in LIBRARY_REPOS]
    wsp = [r for r in repos if r in WORKSPACE_REPOS]
    org = [r for r in repos if r in ORGANISM_REPOS]
    # Primary target folder preference: library repo, then organism, then
    # workspace bucket. (A library+workspace task still targets its library.)
    if lib:
        return lib[0], REPO_DISPLAY.get(lib[0], lib[0]), repos
    if org:
        return org[0], REPO_DISPLAY.get(org[0], org[0]), repos
    if wsp:
        return "workspaces", "workspaces", repos
    # No @mention resolved — guess the domain from keywords.
    low = text.lower()
    for tgt, sigs in TARGET_SIGNALS.items():
        if any(re.search(r"\b" + re.escape(s), low) for s in sigs):
            return tgt, REPO_DISPLAY.get(tgt, tgt), repos
    return "?", "?", repos


def infer_workflow(target: str, repos: list):
    lib = [r for r in repos if r in LIBRARY_REPOS]
    wsp = [r for r in repos if r in WORKSPACE_REPOS]
    org = [r for r in repos if r in ORGANISM_REPOS]
    if lib and wsp:
        return "combined"
    if lib or target in LIBRARY_REPOS:
        return "library"
    if org or target in ORGANISM_REPOS:
        return "infrastructure"
    if wsp or target == "workspaces":
        return "workspace"
    return "unknown"


def infer_priority(text: str) -> str:
    low = text.lower()
    if any(k in low for k in PRIORITY_HIGH):
        return "high"
    if any(k in low for k in PRIORITY_LOW):
        return "low"
    return "normal"


def infer_autonomy(level: str, factors: dict) -> str:
    """safe | supervised | human-required."""
    repo_count = factors["repos_affected"]
    if factors["human_judgement"] and repo_count == 0:
        return "human-required"          # unscoped / needs a design decision
    if (factors["architectural_risk"] or level in ("large", "too-large")
            or repo_count > 1):
        return "supervised"
    return "safe"


def analyse(text: str, source: str):
    """Classify raw text into a full IntakeDecision (never writes)."""
    repos = _repos_in(text)
    work_type, confidence, type_hits = classify_work_type(text)
    target, target_display, repos = infer_target(text, repos)

    # Build a prompt-shaped dict the shared sizing faculty understands.
    p = {"text": text, "repos": repos, "words": len(text.split()),
         "target": target, "work_type": work_type}
    level, score, factors = estimate_difficulty(p)

    autonomy = infer_autonomy(level, factors)
    priority = infer_priority(text)
    workflow = infer_workflow(target, repos)

    title = _title(text)
    slug = _slug(title)
    folder = work_type if confidence != "low" else "triage"
    if folder == "triage":
        proposed = f"draft/triage/{slug}.md"
    elif target != "?":
        proposed = f"draft/{folder}/{target}/{slug}.md"
    else:
        proposed = f"draft/triage/{slug}.md"
        folder = "triage"

    # `Type:` matches the destination folder (PyAutoMind convention). For a
    # low-confidence triage filing that means `Type: triage`, not the provisional
    # guess — the guess still rides in the IntakeDecision's `work_type` field.
    header = _render_header(title, folder, target_display, repos, level,
                            autonomy, priority)
    return {
        "source": source,
        "title": title,
        "work_type": work_type,
        "classification_confidence": confidence,
        "type_signals": type_hits,
        "target": target,
        "target_display": target_display,
        "repos_affected": repos,
        "difficulty": level,
        "difficulty_score": score,
        "difficulty_factors": factors,
        "autonomy": autonomy,
        "priority": priority,
        "workflow": workflow,
        "proposed_path": proposed,
        "header": header,
        "risks": _risks(level, factors, confidence, target),
        "next_action": _next_action(proposed, confidence),
    }


def _render_header(title, work_type, target_display, repos, level, autonomy, priority):
    lines = [f"# {title}", "", f"Type: {work_type}", f"Target: {target_display}"]
    if repos:
        lines.append("Repos:")
        lines += [f"- {REPO_DISPLAY.get(r, r)}" for r in repos]
    lines += [f"Difficulty: {level}", f"Autonomy: {autonomy}",
              f"Priority: {priority}", "Status: formalised"]
    return "\n".join(lines)


def _risks(level, factors, confidence, target):
    out = []
    if confidence == "low":
        out.append("Low classification confidence — filed to triage/ for a human "
                   "to re-home once the work type is clear.")
    if target == "?":
        out.append("No target repo resolved — add an @RepoName reference or set "
                   "Target: before start_dev.")
    if factors["architectural_risk"]:
        out.append("Architectural / API risk keywords present — review scope before build.")
    if level in ("large", "too-large"):
        out.append("Large: expect to split into phased PRs at start_dev time.")
    if not out:
        out.append("Low risk; ready to formalise.")
    return out


def _next_action(proposed, confidence):
    if confidence == "low":
        return (f"Re-run with a clearer description or --apply to file {proposed} "
                "in triage/ for manual re-homing.")
    return (f"Review the header, then `--apply` to write {proposed}; "
            "afterwards `/start_dev {}` routes it.".format(proposed))


# --- apply (the only writing path) -------------------------------------------
def write_prompt(mind: Path, decision: dict, body_text: str, source_note: str):
    """Write the formal prompt file. Returns the path written (relative to mind)."""
    rel = Path(decision["proposed_path"])
    dest = mind / rel
    if dest.exists():
        stamp = _dt.date.today().isoformat().replace("-", "")
        dest = dest.with_name(f"{dest.stem}_{stamp}{dest.suffix}")
        rel = dest.relative_to(mind)
    dest.parent.mkdir(parents=True, exist_ok=True)
    date = _dt.date.today().isoformat()
    note = (f"\n\n<!-- formalised by the Intake (Conception) Agent on {date} "
            f"from {source_note} -->\n")
    dest.write_text(decision["header"] + "\n\n" + body_text.strip() + note,
                    encoding="utf-8")
    return str(rel)


# --- census + dashboard ---------------------------------------------------------
# The header convention this agent writes (see _render_header); census parses the
# same fields back out of every filed prompt. Legacy prompts pre-date the header,
# so every field is optional — absence is reported, never fatal.
HEADER_FIELDS = ("type", "target", "difficulty", "autonomy", "priority", "status")

# `Fix:`-anchored PR reference in a draft prompt's body — the idiom a session
# writes when it fixes the bug but forgets to advance the prompt's lifecycle
# (the 2026-08-21 numba psf_weighted_data case: fixed + merged overnight,
# still advertised as top-priority backlog). Line-anchored so a prompt merely
# *citing* a PR as context is never flagged.
_FIX_PR_RE = re.compile(r"^Fix:.*(?:PR\s*#\d+|/pull/\d+)",
                        re.MULTILINE | re.IGNORECASE)


def parse_header(text: str) -> dict:
    """Extract the light metadata header (`Field: value` lines) from a prompt.

    Only scans the top of the file so a stray "Status:" deep in prose does not
    fire; first occurrence of each field wins. No YAML — the blessed convention.
    `Epic:`/`Phase:` are optional epic-membership fields (dashboard grouping);
    `Filed:`/`Issued:` are the prompt's own date, keyed by the state it was in
    when that happened (PyAutoMind REFERENCE.md "Task dates"). None are in
    HEADER_FIELDS, so their absence is never header hygiene.
    """
    fields = {}
    for line in text.splitlines()[:30]:
        m = re.match(r"(Type|Target|Difficulty|Autonomy|Priority|Status|"
                     r"Issued|Filed|Epic|Phase):\s*(\S.*)",
                     line.strip())
        if m:
            fields.setdefault(m.group(1).lower(), m.group(2).strip())
    return fields


def _prefix_match(path: str, prefix: str) -> bool:
    """Match a census path against a user prefix, with or without `draft/`."""
    sans = path[len("draft/"):] if path.startswith("draft/") else path
    return path.startswith(prefix) or sans.startswith(prefix)


# The registry files (`active.md`, `parked.md`, `planned.md`) are the Mind's
# record of work that is no longer merely filed: an H2 slug per task, then
# `- key: value` bullets (REFERENCE.md "active.md schema"). Values run to
# paragraphs of prose, so the dashboard takes the first line of each and
# truncates — the registry file itself stays the full record.
_REG_HEAD = re.compile(r"^##\s+(\S.*?)\s*$")
_REG_FIELD = re.compile(r"^-\s+([a-z][a-z-]*):\s*(.*)$")
_ISSUE_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# The Mind dates a task the moment it leaves the backlog (PyAutoMind
# REFERENCE.md "Task dates"). The KEY names the event, so a merged feed can say
# what each date means; most-specific event first, so a task that was filed and
# later issued dates from its issue. A date sitting in some other field's prose
# is deliberately not read — that is the un-parseable habit the convention
# replaced.
DATE_KEYS = ("issued", "registered", "started", "planned", "filed", "parked",
             "found", "completed", "shipped")


def _header_date(header: dict) -> str:
    """A prompt's own date from its `Issued:` / `Filed:` header, else ''.

    `Issued:` wins when a prompt carries both — it is the later, more specific
    event, and an issued prompt keeps the `Filed:` it had as a draft."""
    for key in ("issued", "filed"):
        m = _ISO_DATE.search(header.get(key) or "")
        if m:
            return m.group(1)
    return ""


def _entry_date(fields: dict) -> tuple:
    """(date, event) for a registry entry, or ('', '') when it carries none."""
    for key in DATE_KEYS:
        m = _ISO_DATE.search(fields.get(key) or "")
        if m:
            return m.group(1), key
    return "", ""


def parse_registry(path: Path) -> list:
    """Parse one registry file into `[{slug, issue, issue_no, status, prompt}]`.

    Tolerant by design: these files are hand-edited by many sessions, so an
    entry missing every field still yields a record (a slug alone is the task
    name a human picks from). Absent file -> empty list.
    """
    if not path.is_file():
        return []
    entries, cur = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        head = _REG_HEAD.match(line)
        if head:
            cur = {"slug": head.group(1), "issue": "", "issue_no": "",
                   "status": "", "prompt": "", "fields": {},
                   "date": "", "event": ""}
            entries.append(cur)
            continue
        if cur is None:
            continue
        field = _REG_FIELD.match(line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip()
        cur["fields"].setdefault(key, value)
        if key in ("issue", "status", "prompt") and not cur[key]:
            cur[key] = value
            if key == "issue":
                # The value often trails prose ("…/issues/20 (build gated)"),
                # so link the matched URL, never the whole field.
                m = _ISSUE_URL.search(value)
                if m:
                    cur["issue"], cur["issue_no"] = m.group(0), m.group(1)
    for e in entries:
        e["date"], e["event"] = _entry_date(e["fields"])
    return entries


# `epics.md` — the Mind's registry of long-running multi-phase programmes.
# Same H2-slug + `- key: value` shape as active.md, but the fields differ:
# `ledger:` names the epic's canonical state file (may live in another repo),
# `title:`/`status:`/`notes:` are display prose. The dashboard's job is only
# to hand a session enough to WORK OUT where the epic stands — the ledger
# stays the single source of truth.
_EPIC_FIELDS = ("title", "ledger", "status", "notes")


def parse_epics(path: Path) -> list:
    """Parse `epics.md` into `[{slug, title, ledger, status, notes}]`.

    Tolerant like parse_registry: a slug alone still yields a record; absent
    file -> empty list (a freshly-spawned Mind has no epics).
    """
    if not path.is_file():
        return []
    entries, cur = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        head = _REG_HEAD.match(line)
        if head:
            cur = {"slug": head.group(1)}
            cur.update({k: "" for k in _EPIC_FIELDS})
            entries.append(cur)
            continue
        if cur is None:
            continue
        field = _REG_FIELD.match(line)
        if field and field.group(1) in _EPIC_FIELDS and not cur[field.group(1)]:
            cur[field.group(1)] = field.group(2).strip()
    return entries


def _epic_prompt(e: dict) -> str:
    """The one-tap resume prompt: work out where the epic is, then continue.

    Deliberately a procedure, not a snapshot — any phase/issue state baked in
    here would go stale the moment the epic advances, which is exactly the
    problem the button exists to solve."""
    name = e.get("title") or e.get("slug", "this")
    ledger = e.get("ledger", "")
    parts = [f"Continue the '{name}' epic."]
    if ledger:
        parts.append(
            f"Its canonical state lives in {ledger} — read that ledger (and "
            "any DECISIONS/RESULTS files beside it) first.")
    parts.append(
        "Cross-check this epic's entry in PyAutoMind/epics.md, any related "
        "rows in PyAutoMind/active.md, and the referenced repos' open issues "
        "and PRs, to work out the last completed phase and what is currently "
        "in flight. Then pick the next logical step and continue it through "
        "the normal workflow (/start_dev — filing the phase's prompt first "
        "if none exists), updating the ledger as the work advances.")
    if e.get("notes"):
        parts.append(f"Note: {e['notes']}")
    return " ".join(parts)


def _clip(text: str, limit: int = 130) -> str:
    """First line of a registry value, clipped at a word boundary."""
    text = text.strip().splitlines()[0].strip() if text.strip() else ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" .,;:—-") + "…"


# --- the recent feed -----------------------------------------------------------
# The dashboard answers "what should I do now?" everywhere else on the page.
# This one section answers "what has been happening to the work in hand?" — the
# single question a task page laid out by STATE cannot answer, because a task's
# recency is orthogonal to which bucket it sits in. Merging the buckets by date
# puts the week's issuing, parking and filing in one place.
#
# Live work ONLY. The `complete/` ledger is not in this feed: it is a thousand
# records deep and ships ~200 a month, so including it made the table a list of
# receipts — twenty things nobody can act on, on the page whose whole job is
# work in hand. `complete/index.md` is where shipped work is read.
# How deep the feed goes, and how much of it is on screen at once. The table
# is a glance, not a log: ten rows answer "what has been happening?" without
# pushing the Epics below a scroll, and the rest is one tap away — so a quiet
# week still shows a fortnight of context and a busy one does not bury it.
RECENT_MAX = 50
RECENT_PAGE = 10

# The verb each event reads as in the feed. Past tense throughout — every row
# is something that already happened.
EVENT_LABEL = {"issued": "issued", "registered": "issued", "started": "started",
               "planned": "planned", "filed": "filed", "parked": "parked",
               "found": "found"}


def _anchor(heading: str) -> str:
    """GitHub's heading anchor for an `## <slug>` registry entry."""
    return re.sub(r"[^a-z0-9-]+", "-", heading.lower()).strip("-")


def recent_events(c: dict, limit: int = RECENT_MAX) -> list:
    """The newest events on the work in hand, newest first.

    One row per task, not per event: a task that was filed and later issued
    appears once, on its latest date (which is what `_entry_date` already picks
    per entry).

    Undated rows are absent rather than sorted to the bottom: `lifecycle.py
    dates` is where a missing date gets reported, and padding this table with
    unknowns would bury the answer it exists to give.
    """
    events = []
    for r in c.get("in_flight") or []:
        if r.get("date"):
            events.append({"date": r["date"], "event": r.get("event") or "issued",
                           "title": r["title"], "path": r["path"],
                           "payload": f"/start_dev {r['path']}"})
    # The backlog is the LARGEST pool of work the Mind holds — 150 prompts
    # against a handful of live rows — so a feed that skipped it could see
    # almost none of what has been happening. Epic members stay out, as they do
    # in every pick list on the page: they are worked in order through their
    # epic, and a Recent row hands out a standalone `/start_dev`.
    for r in c.get("records") or []:
        if r.get("date") and not r.get("epic"):
            events.append({"date": r["date"], "event": "filed",
                           "title": r["title"], "path": r["path"],
                           "payload": f"/start_dev {r['path']}"})
    for key, verb in (("parked", "resume"), ("planned", "start")):
        for e in c.get(key) or []:
            if e.get("date"):
                events.append({"date": e["date"],
                               "event": e.get("event") or key,
                               "title": e["slug"],
                               # The entry's own heading anchor — a registry
                               # file is long enough that landing at its top is
                               # not the same as landing on the task.
                               "path": f"{key}.md#{_anchor(e['slug'])}",
                               "payload": _registry_payload(e, key, verb)})
    events.sort(key=lambda e: (e["date"], e["title"]), reverse=True)
    for e in events:
        e["event"] = EVENT_LABEL.get(e["event"], e["event"])
    return events[:limit]


def census(mind: Path) -> dict:
    """Inventory the Mind's work — filed prompts plus the registry's live rows.

    Read-only, always. The backlog leg walks the WORK_TYPES folders under
    `draft/` (incl. `triage/`), one record per prompt file. The registry leg
    itemises what has left the backlog: `active/` prompts (issued — an open
    GitHub issue), and the `parked.md` / `planned.md` rows. This is the Mind's
    *work* view — health belongs to the Heart, never here.
    """
    records, hygiene, drift = [], [], []
    for wt in WORK_TYPES:
        folder = mind / "draft" / wt
        if not folder.is_dir():
            continue
        for f in sorted(folder.rglob("*.md")):
            if f.name == "README.md":
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            rel = f.relative_to(mind)
            header = parse_header(text)
            missing = [h for h in HEADER_FIELDS if h not in header]
            try:
                phase = int(header.get("phase", ""))
            except ValueError:
                phase = None
            records.append({
                "path": str(rel),
                "work_type": wt,
                # Folder after the work-type = target repo/domain (authoritative
                # — a header Target: is free prose and must not override the
                # taxonomy). rel is draft/<work-type>/<target>/<name>.md.
                "target": rel.parts[2] if len(rel.parts) > 3 else "-",
                "title": _title(text),
                "difficulty": header.get("difficulty", "-"),
                "autonomy": header.get("autonomy", "-"),
                "priority": header.get("priority", "-"),
                "status": header.get("status", "-"),
                "epic": header.get("epic", ""),
                "phase": phase,
                # `Filed:` normally; `Issued:` only on a prompt that has been
                # issued and moved back, which is still the later event.
                "date": _header_date(header),
                "header": header,
                "missing": missing,
            })
            if len(missing) == len(HEADER_FIELDS):
                hygiene.append(f"{rel} — no metadata header (pre-dates intake)")
            if _FIX_PR_RE.search(text):
                drift.append(f"{rel} — body records a fix PR, but the prompt "
                             "never left draft/ (reconcile its lifecycle)")

    def _count(key):
        out = {}
        for r in records:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    parked = parse_registry(mind / "parked.md")
    planned = parse_registry(mind / "planned.md")
    # A registry row may name the prompt it drives (`- prompt: active/x.md`);
    # that is the only reliable issue link for an issued prompt, since an issue
    # URL in the prose body is as likely to be a cross-reference as the task's
    # own issue.
    by_prompt = {}
    for e in parse_registry(mind / "active.md") + parked + planned:
        if e["prompt"] and e["prompt"] not in by_prompt:
            by_prompt[e["prompt"]] = e

    # A parked task's prompt file legitimately stays in active/ (parked.md
    # holds "started, then parked" work), so a bare active/ glob would list it
    # under BOTH In flight and Parked — inflating the in-flight count with
    # tasks that are deliberately not in flight.
    parked_prompts = {e["prompt"] for e in parked if e["prompt"]}

    in_flight = []
    active = mind / "active"
    for f in sorted(active.glob("*.md")) if active.is_dir() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = str(f.relative_to(mind))
        if rel in parked_prompts:
            continue
        header = parse_header(text)
        row = by_prompt.get(rel, {})
        # The registry row is the live record, so its date wins; the prompt's
        # own `Issued:` header is the fallback that keeps an orphan (no row
        # claims it) dated rather than dropping it out of the recent feed.
        date, event = row.get("date", ""), row.get("event", "")
        if not date:
            date, event = _header_date(header), "issued"
        in_flight.append({
            "path": rel,
            "title": _title(text),
            "target": header.get("target", "-"),
            "priority": header.get("priority", "-"),
            "date": date,
            "event": event,
            "issue": row.get("issue", ""),
            "issue_no": row.get("issue_no", ""),
            # The registry row only. A prompt's own `Status:` header is written
            # at conception ("filed"/"formalised") and is stale the moment the
            # task is issued, so it would report the opposite of live state.
            "status": row.get("status", ""),
        })

    c = {
        "generated": _dt.date.today().isoformat(),
        "home": _mind_home(mind),
        "total": len(records),
        "issued_count": len(in_flight),
        "by_work_type": _count("work_type"),
        "by_target": _count("target"),
        "by_difficulty": _count("difficulty"),
        "by_priority": _count("priority"),
        "records": records,
        "in_flight": in_flight,
        "epics": parse_epics(mind / "epics.md"),
        "parked": parked,
        "planned": planned,
        "hygiene": hygiene,
        "drift": drift,
    }
    c["recent"] = recent_events(c)
    return c


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def _mind_home(mind: Path) -> str:
    """The Mind repo's GitHub home (`https://github.com/<org>/PyAutoMind`).

    Read from `repos.yaml` — the single source of repo identity — so no
    tenant org name is baked into organ code (the tenant-firewall rule: a
    fork's Mind carries its own org there). Empty string when unknown; the
    renderers then degrade to relative links and skip the Pages pointer.
    """
    f = mind / "repos.yaml"
    if not f.is_file():
        return ""
    m = re.search(r"^\s{2}PyAutoMind:\s*\n\s+github:\s*([^\s#]+)",
                  f.read_text(encoding="utf-8", errors="replace"), re.M)
    return f"https://github.com/{m.group(1)}" if m else ""


def _pages_url(home: str) -> str:
    """The GitHub Pages site URL for a repo home, `''` when underivable."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", home)
    return f"https://{m.group(1).lower()}.github.io/{m.group(2)}/" if m else ""


def _board_links(home: str) -> list:
    """The cross-board footer nav every one-tap board carries: (name, url)
    pairs for the sibling boards, from PyAutoBrain's declared config surface
    (config/policy.yaml `board: boards:`), skipping this page's own entry.

    Stdlib regex on the one-pair-per-line block, not yaml — this renderer
    also runs bare in PyAutoMind's dashboard_refresh workflow, which installs
    nothing. The owner comes from the census home, so no org is named here.
    """
    m = re.match(r"https://github\.com/([^/]+)/", home or "")
    policy = Path(__file__).resolve().parents[3] / "config" / "policy.yaml"
    if not m or not policy.is_file():
        return []
    owner = m.group(1).lower()
    block = re.search(r"^  boards:\n((?:    \w+: \S+\n)+)",
                      policy.read_text(encoding="utf-8"), re.M)
    if not block:
        return []
    pairs = re.findall(r"^    (\w+): (\S+)$", block.group(1), re.M)
    return [(name, f"https://{owner}.github.io/{repo}/")
            for name, repo in pairs if name != "mind"]


def _summary_label(value: str) -> str:
    """Task text rendered inside a `<summary>` — HTML, not markdown.

    GitHub does not process markdown inside `<summary>`, so the text is
    HTML-escaped and the one markdown idiom Mind titles actually use —
    `code` spans — is translated to `<code>` tags by hand. Comment markers
    (some untriaged prompts open with `<!--`, which `_title` faithfully
    reports) are stripped rather than escaped: rendered literally they would
    just be noise in the row.
    """
    value = str(value).replace("<!--", "").replace("-->", "").strip()
    value = (value.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;")) or "Untitled"
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", value)


# Pick order. The dashboard exists to be *chosen from*, so every list is sorted
# most-pickable first: urgent before routine, small before enormous. Unknown
# (`-`, the headerless prompts) sorts last rather than being hidden.
PRIORITY_RANK = {"high": 0, "medium": 1, "normal": 2, "low": 3}
DIFFICULTY_RANK = {"small": 0, "medium": 1, "large": 2, "too-large": 3}
PICK_LIST_MAX = 12


def _pick_key(r: dict) -> tuple:
    return (PRIORITY_RANK.get(r["priority"], 9),
            DIFFICULTY_RANK.get(r["difficulty"], 9),
            r["target"], r["path"])


def _task_row(summary: str, payload: str) -> str:
    """One task as a single collapsed row: `▸ 📋 <task text>`.

    The page is read on GitHub (often a phone), where the only clipboard
    affordance static markdown can offer is the copy button GitHub renders on
    fenced code blocks. So every task row is a `<details>` whose summary IS
    the task line — the 📋 toggle sits at the left of the text, costing no
    extra line and no repeated label — and whose hidden body is the fenced
    message that routes Claude to the task: tap the row, tap copy, paste into
    a Claude Code chat. The blank lines around the fence and after
    `</details>` are what make GitHub's renderer treat the fence as markdown
    and the next row as a new element rather than raw HTML — do not remove
    them. The summary is HTML (see `_summary_label`); markdown would not
    render there.
    """
    return "\n".join([f"<details><summary>📋 {summary}</summary>",
                      "",
                      "```",
                      payload,
                      "```",
                      "",
                      "</details>"])


def _items(chunks: list) -> list:
    """Blank-separate task rows so each `</details>` HTML block ends before
    the next row starts (see `_task_row`)."""
    out = []
    for chunk in chunks:
        out += [chunk, ""]
    return out[:-1] if out else []


def _registry_payload(e: dict, key: str, verb: str) -> str:
    """The copy payload for a parked/planned registry row.

    A registry row may name its prompt file; without one there is no
    start_dev target, so route the slug as free prose instead.
    """
    prompt = (e["prompt"].split() or [""])[0]
    if prompt.endswith(".md"):
        return f"/start_dev {prompt}"
    return (f"/route {verb} the {key} PyAutoMind task "
            f"{e['slug']} — its record is in {key}.md")


def _bullet(r: dict) -> str:
    """One backlog prompt as a row — the phone-readable unit of this page.

    A row wraps; a five-column table does not. GitHub's mobile view scrolls
    wide tables sideways, which makes a 133-row backlog unusable on a phone,
    so the metadata rides after an em dash instead of in columns. The title is
    an `<a>` because the row lives in a `<summary>`; its href is repo-root-
    relative, which resolves correctly from the page's own blob URL.
    """
    facets = " · ".join(_summary_label(x) for x in
                        (r["target"], r["difficulty"],
                         r["autonomy"], r["priority"]) if x != "-")
    head = f"<a href=\"{r['path']}\">{_summary_label(r['title'])}</a>"
    if facets:
        head += f" — {facets}"
    return _task_row(head, f"/start_dev {r['path']}")


def _epic_members(c: dict) -> dict:
    """Backlog prompts grouped by their `Epic:` header slug, phase-ordered.

    Members are worked in order *through the epic*, so the dashboard pulls
    them out of the pick lists and work-type sections and shows them only
    inside their epic's group. Phase-less members sort after phased ones by
    filename. A member naming a slug that is not in `epics.md` still groups —
    a typo shows up on the page instead of silently rendering standalone.
    """
    groups: dict = {}
    for r in c["records"]:
        if r.get("epic"):
            groups.setdefault(r["epic"], []).append(r)
    for rows in groups.values():
        rows.sort(key=lambda r: (r["phase"] is None,
                                 r["phase"] if r["phase"] is not None else 0,
                                 r["path"]))
    return groups


RECENT_BLURB = (
    "The {n} newest things to happen to the work in hand, newest first — "
    "issued, parked, filed. Every other section on this page is laid out by "
    "state, which is exactly why none of them can answer \u201cwhat has been "
    "happening?\u201d. Shipped work is not here: it is read from "
    "`complete/index.md`, and a thousand records deep it would crowd out "
    "everything anyone can still act on.")

RECENT_PAGING_NOTE = (
    " Showing the newest {page}; \u2026 opens the next {page}.")


def _dated(row: dict) -> str:
    """`— issued 2026-08-19`, the facet every live task row now carries.

    The date is worth showing where the task IS, not only in the Recent feed:
    a status line reads very differently against a row issued yesterday than
    against one issued in May. Empty for an undated row rather than a
    placeholder — `lifecycle.py dates` is where the gap gets reported."""
    if not row.get("date"):
        return ""
    event = EVENT_LABEL.get(row.get("event", ""), row.get("event") or "dated")
    return f" — {event} {row['date']}"


def _recent_blurb(rows: list) -> str:
    """The section's prose — the paging sentence only when there IS paging."""
    text = RECENT_BLURB.format(n=len(rows))
    if len(rows) > RECENT_PAGE:
        text += RECENT_PAGING_NOTE.format(page=RECENT_PAGE)
    return text


RECENT_TABLE_HEAD = ["| Date | Event | Task |", "|------|-------|------|"]


def _recent_rows(rows: list) -> list:
    return [f"| {r['date']} | {r['event']} | {_cell(_recent_link(r))} |"
            for r in rows]


def _recent_pages(rows: list, page: int = RECENT_PAGE) -> list:
    """The feed as nested `<details>`: a page on screen, the rest one tap in.

    GitHub strips the JavaScript the Pages twin uses for this, so the markdown
    page reveals with the one interactive element it does render — `<details>`,
    NESTED, so each tap shows the next page and leaves another `…` behind it.
    Sibling blocks would let a reader open page 4 without page 3, which is not
    what "show me more" means when the list is ordered by date.

    Each page carries its own header row: a markdown table cannot span an HTML
    block boundary, so the alternative is a headerless slab of pipes. The blank
    lines are load-bearing — without them GitHub treats the table as raw text
    inside the `<details>` (same rule as `_task_row`).
    """
    head, rest = rows[:page], rows[page:]
    block = RECENT_TABLE_HEAD + _recent_rows(head)
    if not rest:
        return block
    shown = min(page, len(rest))
    return block + ["",
                    f"<details><summary>… {shown} more "
                    f"({len(rest)} left)</summary>",
                    ""] + _recent_pages(rest, page) + ["", "</details>"]


def _recent_link(e: dict) -> str:
    """The task cell of a Recent row — its title, linked to where it lives."""
    return f"<a href=\"{e['path']}\">{_summary_label(_clip(e['title'], 70))}</a>"


EPIC_ORDER_CAUTION = ("Members are worked in order through the epic's ledger "
                      "— continue the epic rather than starting one standalone.")


def render_dashboard(c: dict) -> str:
    """Render the census as the Mind's task page (`dashboard.md`).

    Tasks only, by design: no readiness verdicts, no test state — that is the
    Heart's dashboard (`/health`). Two rules shape the layout: it must be
    *pickable* (the top of the page answers "what should I do now?", not "how
    many prompts are there?"), and it must read on a phone (rows over wide
    tables, long sections behind `<details>`, and every task a single
    collapsed row whose 📋 toggle hides its copy block, so picking one from a
    phone is copy → paste into a Claude chat, not retyping a path — see
    `_task_row`). Links are repo-root-relative so they resolve from the
    page's GitHub blob URL.
    """
    records = sorted(c["records"], key=_pick_key)
    L = [
        "# PyAutoMind Dashboard",
        "",
        f"<!-- generated by `pyauto-brain intake dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        "",
    ]
    pages = _pages_url(c.get("home", ""))
    if pages:
        L += [f"This is the markdown version of the "
              f"[PyAutoMind Dashboard]({pages}), which puts a task's command "
              "on your clipboard with a single tap of 📋.", ""]
    L += [
        "Every task the Mind is holding, on one page: what is in flight, what "
        "is parked, and the whole backlog to pick from. Pick a task and run "
        "its `/start_dev` command in a Claude Code chat to start it. "
        "[Recent](#recent) is the same work by date — what has been happening "
        "rather than what to do next.",
        "",
        "| Where | Count |",
        "|-------|------:|",
        f"| [In flight](#in-flight) (`active/`) | {c['issued_count']} |",
        f"| [Parked](#parked) (`parked.md`) | {len(c['parked'])} |",
        f"| [Planned](#planned) (`planned.md`) | {len(c['planned'])} |",
        f"| [Backlog](#backlog) (`draft/`) | {c['total']} |",
        "",
    ]
    if c.get("drift"):
        L += ["> ⚠️ **Needs lifecycle reconciliation** — these draft prompts "
              "record a fix PR in their body: the work looks done, but the "
              "prompt never advanced, so it still renders as backlog:", ""]
        L += [f"> - `{d}`" for d in c["drift"]]
        L += [""]
    L += ["## Start here", ""]

    # Epic members never appear in the pick lists or the work-type sections —
    # they are worked in order through their epic (bottom of the page).
    members = _epic_members(c)
    standalone = [r for r in records if not r.get("epic")]
    high = [r for r in standalone if r["priority"] == "high"]
    quick = [r for r in standalone
             if r["difficulty"] == "small" and r["autonomy"] == "safe"]
    for title, note, rows in (
        ("Highest priority", "filed as `high`", high),
        ("Quick wins", "small enough, and safe enough to run unattended", quick),
    ):
        shown = rows[:PICK_LIST_MAX]
        more = f" — showing {len(shown)} of {len(rows)}" if len(rows) > len(shown) else ""
        L += [f"**{title}** ({note}){more}", ""]
        L += _items([_bullet(r) for r in shown]) or ["- _(none right now)_"]
        L += [""]

    L += ["## In flight", "",
          "Issued — each has an open GitHub issue and usually a branch. The "
          "full record for each is in [`active.md`](active.md).", ""]
    flight = []
    for r in c["in_flight"]:
        head = f"<a href=\"{r['path']}\">{_summary_label(r['title'])}</a>"
        if r["issue_no"]:
            head += f" — <a href=\"{r['issue']}\">issue #{r['issue_no']}</a>"
        head += _dated(r)
        if r["status"]:
            head += f" — {_summary_label(_clip(r['status']))}"
        flight.append(_task_row(head, f"/start_dev {r['path']}"))
    L += _items(flight) or ["- _(nothing in flight)_"]
    L += [""]

    for key, heading, verb, blurb in (
        ("parked", "Parked", "resume",
         "Started or scoped, not currently in flight — "
         "resume by moving the row back to `active.md`. "
         "Full detail in [`parked.md`](parked.md)."),
        ("planned", "Planned", "start",
         "Scoped but not started; some are not yet prompt "
         "files. Full detail in [`planned.md`](planned.md)."),
    ):
        rows = c[key]
        L += [f"## {heading}", "", blurb, "",
              "<details>", f"<summary><b>{len(rows)}</b> task(s)</summary>", ""]
        items = []
        for e in rows:
            head = f"<b>{_summary_label(e['slug'])}</b>"
            if e["issue_no"]:
                head += f" — <a href=\"{e['issue']}\">issue #{e['issue_no']}</a>"
            head += _dated(e)
            if e["status"]:
                head += f" — {_summary_label(_clip(e['status']))}"
            items.append(_task_row(head, _registry_payload(e, key, verb)))
        L += _items(items) or ["- _(none)_"]
        L += ["", "</details>", ""]

    n_members = sum(len(v) for v in members.values())
    member_note = (f" **{n_members}** of them belong to an epic and are "
                   "listed only under [Epics](#epics) below."
                   if n_members else "")
    L += [f"## Backlog", "",
          f"**{c['total']}** filed prompts, not started. Each section is sorted "
          f"most-pickable first (priority, then size).{member_note}", ""]
    for wt in c["by_work_type"]:
        rows = [r for r in standalone if r["work_type"] == wt]
        if not rows:
            continue
        L += ["<details>", f"<summary><b>{wt}</b> — {len(rows)}</summary>", ""]
        L += _items([_bullet(r) for r in rows])
        L += ["", "</details>", ""]

    # Recency is orthogonal to state, so it gets its own table rather than a
    # column on any section above. A table, not the page's usual copy rows:
    # this section is read, not picked from — the task's own section is where
    # it is picked up.
    recent = c.get("recent") or []
    if recent:
        L += ["## Recent", "", _recent_blurb(recent), ""]
        L += _recent_pages(recent)
        L += ["", "_Dates come from each task's registry entry — "
              "`lifecycle.py dates` reports anything undated._", ""]

    # Epics live at the bottom, whole: each epic's resume prompt sits with its
    # queued member prompts, grouped and phase-ordered, so nobody picks a
    # member standalone out of order from a work-type section above.
    known = {e["slug"] for e in c.get("epics") or []}
    stray = [s for s in members if s not in known]
    if c.get("epics") or stray:
        L += ["## Epics", "",
              "Long-running multi-phase programmes. Each epic's 📋 prompt has "
              "Claude read its ledger, work out where it stands, and continue "
              f"from the next logical point. {EPIC_ORDER_CAUTION} "
              "Full record in [`epics.md`](epics.md).", ""]
        for e in c.get("epics") or []:
            rows = members.get(e["slug"], [])
            head = f"<b>{_summary_label(e.get('title') or e['slug'])}</b>"
            if e.get("ledger"):
                head += f" — ledger: `{e['ledger']}`"
            if e.get("status"):
                head += f" — {_summary_label(_clip(e['status']))}"
            resume = _task_row(head, _epic_prompt(e))
            if not rows:
                L += _items([resume]) + [""]
                continue
            L += ["<details>",
                  f"<summary><b>{_summary_label(e.get('title') or e['slug'])}"
                  f"</b> — {len(rows)} queued prompt(s), in order</summary>", ""]
            L += _items([resume] + [_bullet(r) for r in rows])
            L += ["", "</details>", ""]
        for slug in stray:
            rows = members[slug]
            L += ["<details>",
                  f"<summary><b>{_summary_label(slug)}</b> — {len(rows)} "
                  "queued prompt(s) — ⚠️ not in `epics.md`</summary>", ""]
            L += _items([_bullet(r) for r in rows])
            L += ["", "</details>", ""]

    if c["hygiene"]:
        L += ["## Hygiene", "",
              f"{len(c['hygiene'])} prompt(s) without a metadata header — they "
              "show no facets above. Re-home or re-run intake on them when "
              "touched.", "",
              "<details>", "<summary>Headerless prompts</summary>", ""]
        L += [f"- `{h.split(' — ')[0]}`" for h in c["hygiene"]]
        L += ["", "</details>"]

    boards = _board_links(c.get("home", ""))
    if boards:
        L += ["", "Boards: " + " · ".join(f"[{n}]({u})" for n, u in boards)]
    return "\n".join(L).rstrip("\n") + "\n"


_HTML_CSS = """\
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2328;--muted:#59636e;
 --line:#d1d9e0;--btn:#f6f8fa;--ok:#1a7f37;--accent:#0969da}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#f0f6fc;
 --muted:#9198a1;--line:#3d444d;--btn:#151b23;--ok:#3fb950;--accent:#4493f8}}
*{box-sizing:border-box}
body{margin:0 auto;max-width:44rem;padding:1rem 1rem 4rem;background:var(--bg);
 color:var(--fg);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",
 Helvetica,Arial,sans-serif}
h1{font-size:1.35rem;margin:.4rem 0}
h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid var(--line);
 padding-bottom:.3rem}
h3{font-size:1rem;margin:1.2rem 0 .2rem}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:var(--muted)}
.facets{color:var(--muted);font-size:.85em}
.mdsrc{font-size:.85em}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
 background:var(--btn);padding:.1em .3em;border-radius:4px}
.task{display:flex;gap:.6rem;align-items:flex-start;padding:.45rem 0;
 border-bottom:1px solid var(--line)}
.task p{margin:.25rem 0 0;flex:1;overflow-wrap:anywhere}
button.copy{flex:0 0 auto;width:2.6rem;height:2.6rem;font-size:1.1rem;
 border:1px solid var(--line);border-radius:8px;background:var(--btn);
 cursor:pointer;color:var(--fg)}
button.copy.ok{color:var(--ok);border-color:var(--ok)}
details{margin:.5rem 0}
summary{cursor:pointer;font-weight:600;padding:.4rem 0}
table.recent{width:100%;border-collapse:collapse;font-size:.95em}
table.recent td{border-bottom:1px solid var(--line);padding:.45rem .4rem .45rem 0;
 vertical-align:top;overflow-wrap:anywhere}
table.recent td.when{white-space:nowrap;color:var(--muted);font-variant-numeric:
 tabular-nums}
table.recent td.what{white-space:nowrap;color:var(--muted);font-size:.85em;
 padding-top:.58rem}
table.recent td.pick{width:2.6rem;padding-right:0}
table.recent button.copy{width:2.2rem;height:2.2rem;font-size:.95rem}
button.more{display:block;width:100%;margin:.6rem 0;padding:.5rem;
 border:1px solid var(--line);border-radius:8px;background:var(--btn);
 color:var(--muted);cursor:pointer;font:inherit;font-size:.9em}
button.more:hover{color:var(--fg)}
"""

# One tap on 📋 → the command is on the clipboard; the button flashes ✓. The
# textarea path covers browsers without the async clipboard API.
_HTML_JS = """\
async function copyCmd(b){
  const cmd=b.dataset.cmd;
  try{await navigator.clipboard.writeText(cmd);}
  catch(e){const t=document.createElement("textarea");t.value=cmd;
    document.body.appendChild(t);t.select();document.execCommand("copy");
    t.remove();}
  b.textContent="\\u2713";b.classList.add("ok");
  setTimeout(()=>{b.textContent="\\ud83d\\udccb";b.classList.remove("ok");},1200);}
document.addEventListener("click",e=>{
  const b=e.target.closest("button.copy");if(b)copyCmd(b);});
// Recent shows one page and reveals the next on each tap of the \u2026 button,
// which retires itself once the feed is exhausted. Every row is already in the
// DOM, so this never re-renders or re-sorts anything.
document.addEventListener("click",e=>{
  const b=e.target.closest("button.more");if(!b)return;
  const t=document.querySelector("table.recent");if(!t)return;
  const hidden=[...t.querySelectorAll("tr[hidden]")];
  const page=Number(b.dataset.page)||10;
  hidden.slice(0,page).forEach(r=>r.removeAttribute("hidden"));
  const left=hidden.length-Math.min(page,hidden.length);
  if(left<=0){b.remove();return;}
  b.textContent="\u2026 "+Math.min(page,left)+" more ("+left+" left)";});
"""


def _attr(value: str) -> str:
    """Escape a string for a double-quoted HTML attribute."""
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _html_task(text_html: str, payload: str) -> str:
    """One task row on the HTML page: a real copy button, then the text."""
    return (f'<div class="task"><button class="copy" '
            f'data-cmd="{_attr(payload)}" aria-label="Copy the Claude '
            f'command">📋</button><p>{text_html}</p></div>')


def render_dashboard_html(c: dict) -> str:
    """Render the census as `dashboard.html` — the one-tap-copy twin.

    Same content as `render_dashboard`, different constraint: this page is
    served by GitHub Pages (see PyAutoMind's `pages_dashboard.yml`), so it may
    carry the JavaScript that GitHub's markdown rendering strips — a real
    copy-to-clipboard button per task, which the markdown page cannot have (in
    the GitHub mobile app fenced blocks offer no copy affordance at all). Links
    are absolute (from the census `home`) because Pages serves this file away
    from the repo blobs; with no home they fall back to relative paths. The
    Hygiene section stays markdown-only — this page exists to pick from, not
    to audit. Self-contained by design: inline CSS/JS, no external assets.
    """
    records = sorted(c["records"], key=_pick_key)
    home = c.get("home", "")
    blob = f"{home}/blob/main/" if home else ""

    def link(path, text_html):
        return f'<a href="{_attr(blob + path)}">{text_html}</a>'

    def record_row(r):
        text = link(r["path"], _summary_label(r["title"]))
        facets = " · ".join(_summary_label(x) for x in
                            (r["target"], r["difficulty"],
                             r["autonomy"], r["priority"]) if x != "-")
        if facets:
            text += f' — <span class="facets">{facets}</span>'
        return _html_task(text, f"/start_dev {r['path']}")

    H = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>PyAutoMind Dashboard</title>",
        f"<!-- generated by `pyauto-brain intake dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        f"<style>{_HTML_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>📋 PyAutoMind Dashboard</h1>",
        "<p>Every task the Mind is holding. Tap a task's 📋 and its "
        "<code>/start_dev</code> command is on your clipboard — paste it into "
        "a Claude Code chat to route Claude straight to that task. "
        '<a href="#recent">Recent</a> is the same work by date — what has been '
        "happening rather than what to do next.</p>",
        f'<p class="muted">In flight {c["issued_count"]} · '
        f'Parked {len(c["parked"])} · Planned {len(c["planned"])} · '
        f'Backlog {c["total"]}'
        + (f' · {link("dashboard.md", "markdown version")}' if home else "")
        + "</p>",
    ]
    if c.get("drift"):
        H += ['<p>⚠️ <b>Needs lifecycle reconciliation</b> — draft prompts '
              "whose body records a fix PR (done, never advanced):</p>", "<ul>"]
        H += [f"<li><code>{_attr(d)}</code></li>" for d in c["drift"]]
        H += ["</ul>"]
    H += ["<h2>Start here</h2>"]

    members = _epic_members(c)
    standalone = [r for r in records if not r.get("epic")]
    high = [r for r in standalone if r["priority"] == "high"]
    quick = [r for r in standalone
             if r["difficulty"] == "small" and r["autonomy"] == "safe"]
    for title, note, rows in (
        ("Highest priority", "filed as high", high),
        ("Quick wins", "small enough, and safe enough to run unattended", quick),
    ):
        shown = rows[:PICK_LIST_MAX]
        more = (f" — showing {len(shown)} of {len(rows)}"
                if len(rows) > len(shown) else "")
        H += [f'<h3>{title} <span class="facets">({note}){more}</span></h3>']
        H += [record_row(r) for r in shown] or ['<p class="muted">(none right now)</p>']

    def h2(title, src):
        # Every section links the markdown file it is rendered from — the
        # registry file is the full record, the page is the view.
        a = (f' <a class="mdsrc" href="{_attr(blob + src)}">markdown '
             "version</a>") if blob else ""
        return f"<h2>{title}{a}</h2>"

    H += [h2("In flight", "active.md"),
          '<p class="muted">Issued — each has an open GitHub issue and '
          "usually a branch.</p>"]
    for r in c["in_flight"]:
        text = link(r["path"], _summary_label(r["title"]))
        if r["issue_no"]:
            text += f' — <a href="{_attr(r["issue"])}">issue #{r["issue_no"]}</a>'
        if r.get("date"):
            text += f'<span class="facets">{_dated(r)}</span>'
        if r["status"]:
            text += (f' — <span class="facets">'
                     f'{_summary_label(_clip(r["status"]))}</span>')
        H.append(_html_task(text, f"/start_dev {r['path']}"))
    if not c["in_flight"]:
        H.append('<p class="muted">(nothing in flight)</p>')

    for key, heading, verb in (("parked", "Parked", "resume"),
                               ("planned", "Planned", "start")):
        rows = c[key]
        H += [h2(heading, f"{key}.md"), "<details>",
              f"<summary>{len(rows)} task(s)</summary>"]
        for e in rows:
            text = f"<b>{_summary_label(e['slug'])}</b>"
            if e["issue_no"]:
                text += (f' — <a href="{_attr(e["issue"])}">'
                         f'issue #{e["issue_no"]}</a>')
            if e.get("date"):
                text += f'<span class="facets">{_dated(e)}</span>'
            if e["status"]:
                text += (f' — <span class="facets">'
                         f'{_summary_label(_clip(e["status"]))}</span>')
            H.append(_html_task(text, _registry_payload(e, key, verb)))
        if not rows:
            H.append('<p class="muted">(none)</p>')
        H.append("</details>")

    n_members = sum(len(v) for v in members.values())
    member_note = (f" {n_members} of them belong to an epic and are listed "
                   "only under Epics below." if n_members else "")
    H += [h2("Backlog", "draft").replace("/blob/main/draft", "/tree/main/draft"),
          f'<p class="muted">{c["total"]} filed prompts, not started — '
          f"sorted most-pickable first (priority, then size).{member_note}</p>"]
    for wt in c["by_work_type"]:
        rows = [r for r in standalone if r["work_type"] == wt]
        if not rows:
            continue
        H += ["<details>", f"<summary>{wt} — {len(rows)}</summary>"]
        H += [record_row(r) for r in rows]
        H += ["</details>"]

    recent = c.get("recent") or []
    if recent:
        H += ['<a id="recent"></a>' + h2("Recent", "dashboard.md#recent"),
              # `_summary_label` turns the blurb's `code` spans into <code>;
              # markdown backticks render literally on this page.
              f'<p class="muted">{_summary_label(_recent_blurb(recent))}</p>',
              '<table class="recent">']
        for i, r in enumerate(recent):
            # Every row ships in the DOM; the ones past the first page start
            # hidden, so revealing them is a flag flip rather than a re-render
            # — and a reader with JS off sees the whole feed rather than ten
            # rows and a dead button.
            H += ["<tr hidden>" if i >= RECENT_PAGE else "<tr>",
                  f'<td class="when">{r["date"]}</td>',
                  f'<td class="what">{_summary_label(r["event"])}</td>',
                  f'<td>{link(r["path"], _summary_label(_clip(r["title"], 70)))}</td>',
                  f'<td class="pick"><button class="copy" '
                  f'data-cmd="{_attr(r["payload"])}" aria-label="Copy the '
                  f'Claude command">📋</button></td>',
                  "</tr>"]
        H += ["</table>"]
        rest = len(recent) - RECENT_PAGE
        if rest > 0:
            H += [f'<button class="more" data-page="{RECENT_PAGE}">'
                  f'… {min(RECENT_PAGE, rest)} more ({rest} left)</button>']

    known = {e["slug"] for e in c.get("epics") or []}
    stray = [s for s in members if s not in known]
    if c.get("epics") or stray:
        H += [h2("Epics", "epics.md"),
              '<p class="muted">Long-running multi-phase programmes — 📋 '
              "copies a prompt that works out where the epic stands from its "
              f"ledger and continues it from the next logical point. "
              f"{EPIC_ORDER_CAUTION}</p>"]
        for e in c.get("epics") or []:
            rows = members.get(e["slug"], [])
            text = f"<b>{_summary_label(e.get('title') or e['slug'])}</b>"
            if e.get("ledger"):
                text += (f' — <span class="facets">ledger: '
                         f"<code>{_attr(e['ledger'])}</code></span>")
            if e.get("status"):
                text += (f' — <span class="facets">'
                         f'{_summary_label(_clip(e["status"]))}</span>')
            resume = _html_task(text, _epic_prompt(e))
            if not rows:
                H.append(resume)
                continue
            H += ["<details>",
                  f"<summary>{_summary_label(e.get('title') or e['slug'])} — "
                  f"{len(rows)} queued prompt(s), in order</summary>",
                  resume]
            H += [record_row(r) for r in rows]
            H += ["</details>"]
        for slug in stray:
            rows = members[slug]
            H += ["<details>",
                  f"<summary>{_summary_label(slug)} — {len(rows)} queued "
                  "prompt(s) — ⚠️ not in epics.md</summary>"]
            H += [record_row(r) for r in rows]
            H += ["</details>"]

    boards = _board_links(home)
    if boards:
        nav = " · ".join(f'<a href="{_attr(u)}">{n}</a>' for n, u in boards)
        H.append(f'<p class="muted">Boards: {nav}</p>')
    H += [f"<script>{_HTML_JS}</script>", "</body>", "</html>"]
    return "\n".join(H) + "\n"


def _dashboard_body(page: str) -> str:
    """The page minus its generation stamp — what `--check` compares.

    The stamp changes every day the generator runs; comparing it would make
    every re-render look like drift and the self-heal push a daily commit.
    """
    return "\n".join(l for l in page.splitlines()
                     if not l.startswith("<!-- generated by"))


def emit_census(c: dict):
    def _fmt(counts, top=None):
        items = list(counts.items())[:top]
        s = " · ".join(f"{k} {n}" for k, n in items)
        return s + (" · …" if top and len(counts) > top else "")

    print("== Mind census ==")
    print(f"Filed prompts:   {c['total']}   (already issued: {c['issued_count']})")
    print(f"Registry:        in flight {c['issued_count']} · parked "
          f"{len(c['parked'])} · planned {len(c['planned'])}")
    print(f"By work-type:    {_fmt(c['by_work_type'])}")
    print(f"By target:       {_fmt(c['by_target'], top=8)}")
    print(f"By difficulty:   {_fmt(c['by_difficulty'])}")
    print(f"By priority:     {_fmt(c['by_priority'])}")
    print(f"Hygiene:         {len(c['hygiene'])} prompt(s) without a metadata "
          "header (--json lists them)")


# --- formalise (retroactive conception) ----------------------------------------
# The backlog's raw prompts are intended word-vomit — conception deferred, not
# defects (hence *formalise*, not "repair"). Formalise derives the missing header
# fields and inserts them without touching a single existing line of prose.
_FIELD_LINE = re.compile(
    r"(Type|Target|Difficulty|Autonomy|Priority|Status):\s*\S")


def _derive_fields(text: str, work_type: str, target: str) -> dict:
    """Derive a full header for a prompt body, folder identity authoritative.

    Type/Target come from the taxonomy folder; Difficulty/Autonomy/Priority run
    the same sizing-faculty path `analyse` uses at conception time.
    """
    repos = _repos_in(text)
    tgt = normalise_repo(target) if target != "-" else "?"
    if tgt in KNOWN_REPOS and tgt not in repos:
        repos = sorted(set(repos) | {tgt})
    p = {"text": text, "repos": repos, "words": len(text.split()),
         "target": target, "work_type": work_type}
    level, _score, factors = estimate_difficulty(p)
    return {
        "type": work_type,
        "target": REPO_DISPLAY.get(tgt, target if target != "-" else "?"),
        "difficulty": level,
        "autonomy": infer_autonomy(level, factors),
        "priority": infer_priority(text),
        "status": "formalised",
    }


def _insert_fields(text: str, add: dict, has_header: bool, title: str) -> str:
    """Insert the missing `Field: value` lines, preserving every existing line.

    Partial header -> append after the last recognised field line in the leading
    block (non-field lines like `Repos:` / `Milestone:` stay put). No header but
    a leading `# heading` -> insert below it. Neither -> prepend a derived
    `# <title>` so the file lands on the blessed shape.
    """
    lines = text.splitlines()
    field_lines = [f"{f.capitalize()}: {add[f]}" for f in HEADER_FIELDS if f in add]
    if has_header:
        last = max(i for i, ln in enumerate(lines[:30])
                   if _FIELD_LINE.match(ln.strip()))
        lines[last + 1:last + 1] = field_lines
    else:
        first = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
        if lines and lines[first].lstrip().startswith("#"):
            lines[first + 1:first + 1] = [""] + field_lines
        else:
            lines[:0] = [f"# {title}", ""] + field_lines + [""]
    # Preserve the file's own line endings — "verbatim" includes bytes, and a
    # CRLF prompt must not come back LF-normalised with every line rewritten.
    nl = "\r\n" if "\r\n" in text else "\n"
    return nl.join(lines) + (nl if text.endswith("\n") else "")


def formalise(mind: Path, prefix: str = "", apply: bool = False) -> dict:
    """Retroactively formalise headerless / incomplete backlog prompts in place.

    Reuses the census to select records with missing fields; writes ONLY under
    --apply. Never moves or deletes a file — a work-type disagreement between
    the body classifier and the taxonomy folder becomes a re-home *suggestion*
    for a human, because the folder is authoritative.
    """
    c = census(mind)
    proposals, suggestions = [], []
    for r in c["records"]:
        if prefix and not _prefix_match(r["path"], prefix):
            continue
        if not r["missing"]:
            continue
        path = mind / r["path"]
        # newline="" keeps \r\n intact — read_text's universal-newline mode
        # would silently translate it and defeat the verbatim write-back.
        with path.open(encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
        derived = _derive_fields(text, r["work_type"], r["target"])
        add = {f: derived[f] for f in r["missing"]}
        proposals.append({"path": r["path"], "title": r["title"],
                          "add": add, "keep": r["header"]})
        if apply:
            new = _insert_fields(text, add, bool(r["header"]), r["title"])
            stamp = (f"<!-- formalised retroactively by the Intake (Conception) "
                     f"Agent on {_dt.date.today().isoformat()} -->")
            if "formalised retroactively" not in new:
                nl = "\r\n" if "\r\n" in new else "\n"
                new = new.rstrip("\r\n") + nl + nl + stamp + nl
            path.write_text(new, encoding="utf-8", newline="")
        wt_guess, conf, _hits_ = classify_work_type(text)
        if (conf != "low" and wt_guess != r["work_type"]
                and r["work_type"] != "triage"):
            suggestions.append(f"{r['path']} — classifier reads as {wt_guess} "
                               f"({conf}); filed under {r['work_type']}/")
    return {
        "generated": _dt.date.today().isoformat(),
        "scanned": c["total"],
        "formalised": len(proposals),
        "applied": bool(apply),
        "proposals": proposals,
        "rehome_suggestions": suggestions,
    }


def emit_formalise(res: dict):
    verb = "formalised" if res["applied"] else "to formalise"
    print(f"== Intake formalise: {res['formalised']} prompt(s) {verb} "
          f"(of {res['scanned']} scanned) ==")
    for p in res["proposals"]:
        adds = " · ".join(f"{f.capitalize()}: {v}" for f, v in p["add"].items())
        print(f"  {p['path']}")
        print(f"      + {adds}")
    if res["rehome_suggestions"]:
        print(f"Re-home suggestions ({len(res['rehome_suggestions'])}) — "
              "folder stays authoritative; move by hand if the classifier is right:")
        for s in res["rehome_suggestions"]:
            print(f"  - {s}")
    if not res["applied"]:
        print("\n(dry-run — re-run `intake --apply formalise` to write the headers)")


# --- reconcile (shipped-but-stale audit) ----------------------------------------
# A prompt's Status: header is NOT a completeness signal — formalise preserves an
# existing Status verbatim, so shipped work can still read "Status: planned" (the
# PyAutoHeart M0-M5 cluster sat exactly like that). Reconcile cross-references
# the backlog against the Mind's shipped-state records and RANKS suspects for a
# human to retire. Read-only, always: retiring a prompt (to the complete/ archive)
# stays a human act, and the final verification — the target repo's git log /
# merged PRs — stays out of scope by design.
_STOPWORDS = frozenset(
    "the a an of to in for and or is are be with on by via from into as at it "
    "this that use using make add new fix update support get set can we i you "
    "our my need should will when once each all its".split())
# Wording in a completion-record reference line that marks the prompt as a
# deferred follow-up (still open) rather than the shipped task itself.
_FOLLOWUP_WORDS = ("follow", "restore", "parked", "remain", "blocked", "later",
                   "next step", "next-step", "deferred")
# Wording that makes a reference line an assertion the work is DONE, rather than
# a passing mention. `jax-substructure-simulator.md` opens "the 4
# `jax_substructure/` prompts shipped to `main`" — that sentence resolves four
# prompts, and is the difference between a citation and a completion claim.
_SHIPPED_WORDS = ("shipped", "delivered", "merged", "completed", "closed out",
                  "close-out", "landed", "is done", "now on main")
#: A rare identifier says far more than a shared English word. Backticked
#: snake_case / CamelCase with at least two segments — `chunk_size`,
#: `_validate_convolve_over_sample_size`, `RectangularAdaptDensity`.
_IDENT_RE = re.compile(
    r"`([A-Za-z_][A-Za-z0-9_]*(?:_[A-Za-z0-9_]+)+"
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)`")
#: An identifier in this many records or more is vocabulary, not evidence.
_IDENT_COMMON_DF = 6
#: Ditto for stem tokens: `jax` is in ~100 records and links nothing.
_TOKEN_COMMON_DF = 12
_W_SHIPPED = 7.0        # a record asserting the work is done — on its own
                        # enough to qualify: `jax-substructure-simulator.md`
                        # saying "the 4 prompts shipped to main" resolved four
                        # prompts in one sentence, and nothing else flagged them.
_W_IDENT = 2.0          # per shared rare identifier beyond the first
_SUSPECT_THRESHOLD = 7.0
_HIGH_THRESHOLD = 12.0
# Tuned on the 2026-08-09 labelled set (PyAutoMind f25e154e, 148 prompts, five
# findings independently confirmed against upstream source). Result:
#
#   BEFORE   96 of 148 flagged (65%) — 52 "high" — biggest find NOT flagged
#   AFTER    31 of 148 flagged (21%) —  9 "high" — biggest find at rank 2
#
# Of the five findings, this ranker catches the two it can: the k x s series
# (rare-token fan-out, rank 2) and the nufft chunking prompt (shared rare
# identifiers). The other three are NOT ranker failures and must not be chased
# by lowering the bar:
#
#   * the test-mode umbrella states its own exit condition, which is what
#     PyAutoMind's `Closes-when:` header key grades — a different tool;
#   * the split-guard prompt had NO completion record at all (its evidence sat
#     inside a sibling PROMPT), so nothing Mind-local could see it;
#   * the latent prompt left no Mind trace whatsoever — the fix shipped upstream
#     without a record. Only reading the target repo finds that shape.
#
# Every attempt to force those three in cost precision without gaining truth:
# a loose `<work-type>/<target>/` series match pulled the umbrella in at 31%
# flagged, but also FALSELY flagged test_mode_bypass_ordered_assertion_ties off
# references to four unrelated sibling prompts — a prompt the sweep confirmed is
# NOT shipped, and exactly the mis-grade this tool must never make.


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower())
            if len(w) > 2 and w not in _STOPWORDS}


def _idents(text: str) -> set:
    return set(_IDENT_RE.findall(text))


# --- the upstream read (--repo) -------------------------------------------------
# Leg 3 of the staleness work (PyAutoBrain#223). Everything above this line is
# Mind-local: it cross-references `draft/` against `complete/` and `active/`.
# That is structurally blind to two of the five findings the 2026-08-09 sweep
# confirmed — one whose evidence sat in a sibling PROMPT rather than a record,
# and one whose fix shipped upstream with NO record written at all. Re-ranking
# cannot reach them; only reading the target repo can.
#
# THIS IS THE ONLY NETWORK ACCESS IN PyAutoBrain. Every other conductor and
# faculty is stdlib-only and offline, and the default `reconcile` path stays
# that way — `--repo` is strictly opt-in, and `test_default_path_is_offline`
# pins it. The upstream read goes through the `source_reader` seam so the
# hermetic tests never clone anything.
#
# What it must NEVER do is call a prompt shipped. `test_mode_bypass_ordered_
# assertion_ties.md` names five identifiers and ALL FIVE are on PyAutoFit main,
# yet the prompt is confirmed not shipped: main catches `exc.FitException` in
# the TEST_MODE bypass — which looks exactly like the requested fix — but the
# catch wraps only the likelihood call, while `model.instance_from_vector`
# (where `check_assertions` actually raises) sits on the line BEFORE the `try`.
# Presence of a name is not presence of the fix. So this leg contributes
# evidence and a `needs-review` band, never a verdict.
_W_UPSTREAM = 1.5       # per upstream identifier beyond the first. Deliberately
                        # below _W_SHIPPED (7.0): an upstream hit must never on
                        # its own carry a prompt into the top band, because the
                        # trap above would ride it there.
_UPSTREAM_MIN_IDENTS = 2   # one shared name is a coincidence, not a signal


def _upstream_noise() -> set:
    """Identifiers whose presence upstream says nothing about a prompt.

    Two measured noise classes, from the first run against PyAutoFit:

      * **Python builtins** — `TypeError` is in 37 files of PyAutoFit. A prompt
        mentioning it has not thereby been shipped.
      * **Repo names** — `autofit_workspace` (26 files), `autolens_workspace`.
        Every repo names its siblings; that is vocabulary, not evidence.

    Filtering by upstream file-spread instead was tried and rejected: the counts
    do not separate. `instance_from_vector` (22 files) is a REAL signal and sits
    right below `autofit_workspace` (26) which is noise, so any threshold that
    drops the noise also drops one of the trap's own identifiers.
    """
    import builtins

    return set(dir(builtins)) | set(KNOWN_REPOS)


def _body_map_slugs() -> dict:
    """normalised target -> `owner/repo`, from the Mind's body map.

    repos.yaml is the single source of repo identity, and `normalise_repo`
    already folds `PyAutoArray`/`pyautoarray`/`autoarray` together — reuse both
    rather than adding a third mapping.
    """
    import yaml

    data = yaml.safe_load(BODY_MAP_PATH.read_text())
    out = {}
    for name, spec in data["repos"].items():
        slug = spec.get("github", "")
        if slug:
            out[normalise_repo(name)] = slug
    return out


def _target_candidates(mind: Path, target: str) -> list:
    """Repos actually referenced by the prompts filed under `draft/**/<target>/`.

    Used only to make the refusal below useful: `--repo priors` should say which
    repos those six prompts are about, not just "no".
    """
    found = set()
    for wt in WORK_TYPES:
        folder = mind / "draft" / wt / target
        if not folder.is_dir():
            continue
        for f in folder.rglob("*.md"):
            text = f.read_text(encoding="utf-8", errors="replace")
            for m in re.findall(r"@([A-Za-z_][A-Za-z0-9_]*)", text):
                key = normalise_repo(m)
                if key in KNOWN_REPOS:
                    found.add(key)
    return sorted(found)


def resolve_repo(mind: Path, target: str) -> tuple:
    """`target` -> (`owner/repo`, ""), or ("", <error>) if it is not one repo.

    The second folder of a prompt path is a target *or domain*: `autoarray` is a
    repo, but `workspaces`, `health_fixes`, `priors` and `graphical_ep` are topic
    clusters spanning several. Those are among the LARGEST buckets in `draft/`
    (`workspaces` alone is 23 prompts across four work-types), so guessing one
    repo for them would produce confident nonsense over the biggest part of the
    backlog. Refuse instead, and name the real candidates.
    """
    key = normalise_repo(target)
    slugs = _body_map_slugs()
    if key in slugs:
        return slugs[key], ""
    cands = _target_candidates(mind, target)
    if cands:
        hint = ("  the prompts filed under it reference: " + ", ".join(cands)
                + "\n  re-run --repo with one of those.")
    else:
        hint = ("  no @RepoName references found in the prompts filed under it"
                "\n  re-run --repo with a repo name from the body map.")
    return "", (f"--repo {target!r} is not a single repository in the body map "
                f"(PyAutoMind/repos.yaml).\n{hint}")


def _clone_upstream(slug: str, cache: Path) -> tuple:
    """Cached shallow clone of `slug`'s default branch -> (path, sha).

    Plain `--depth 1`, NOT the `--filter=blob:none` treeless clone the parent
    prompt suggested: this leg greps the source, and a treeless clone refetches
    every blob on demand to answer that — a false economy. GIT_LFS_SKIP_SMUDGE
    keeps an LFS-using repo from aborting at the smudge filter.
    """
    import subprocess

    dest = cache / slug.replace("/", "__")
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}

    def _git(*args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, env=env,
                              capture_output=True, text=True, timeout=600)

    if (dest / ".git").is_dir():
        _git("fetch", "--depth", "1", "origin", cwd=dest)
        _git("reset", "--hard", "FETCH_HEAD", cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = _git("clone", "--depth", "1",
                 f"https://github.com/{slug}", str(dest))
        if r.returncode != 0:
            raise RuntimeError(f"clone of {slug} failed: {r.stderr.strip()}")
    sha = _git("rev-parse", "HEAD", cwd=dest).stdout.strip()
    return dest, sha


def _grep_source(root: Path, idents: set) -> dict:
    """ident -> ['<relpath>:<lineno>', …] over the source files under `root`.

    One pass over the tree scoring every identifier at once: the alternative,
    one grep per identifier per prompt, is O(prompts x idents) walks of the
    same checkout.
    """
    if not idents:
        return {}
    pat = re.compile(r"\b(" + "|".join(re.escape(i) for i in sorted(idents))
                     + r")\b")
    hits: dict = {}
    for f in root.rglob("*"):
        if not f.is_file() or ".git" in f.parts:
            continue
        if f.suffix not in (".py", ".pyi", ".sh", ".yaml", ".yml", ".cfg",
                            ".toml", ".rst", ".md", ".ipynb"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not pat.search(text):
            continue
        rel = f.relative_to(root)
        for n, line in enumerate(text.splitlines(), 1):
            for m in pat.finditer(line):
                hits.setdefault(m.group(1), [])
                if len(hits[m.group(1)]) < 3:      # 3 lines is enough to judge
                    hits[m.group(1)].append(f"{rel}:{n}")
    return hits


def upstream_reader(mind: Path, target: str, cache: Path = None):
    """Build the `source_reader` seam for `reconcile(repo=…)`.

    Returns `(reader, sha, slug, err)`. `reader(idents) -> {ident: [file:line]}`.
    Kept separate from `reconcile` so the tests can inject a fake tree and stay
    hermetic — nothing under `tests/` ever clones.
    """
    slug, err = resolve_repo(mind, target)
    if err:
        return None, "", "", err
    cache = cache or Path(os.environ.get(
        "PYAUTO_BRAIN_CACHE", Path.home() / ".pyauto-brain" / "upstream"))
    try:
        root, sha = _clone_upstream(slug, cache)
    except Exception as exc:                      # network/git failure
        return None, "", slug, f"could not read {slug}: {exc}"
    return (lambda idents: _grep_source(root, idents)), sha, slug, ""


def reconcile(mind: Path, prefix: str = "", source_reader=None,
              upstream_meta: dict = None) -> dict:
    """Rank backlog prompts that look already-shipped, for a human to retire.

    Mind-local signals per prompt: a completion-record line referencing its
    path (follow-up wording downgrades it), a duplicate basename in `active/`
    or the `complete/` archive, token overlap with a completed task's header /
    archive record, and a hand-set Status the formalise pass deliberately
    preserved. Never writes anything.

    `source_reader` is the optional upstream leg (`--repo`): a callable taking
    the identifiers a prompt names and returning `{ident: ['file:line', …]}`
    from the target repo's source. It ADDS evidence and can raise a prompt into
    the `needs-review` band; it never produces a shipped verdict, and it is
    never consulted unless the caller passes it. Default: offline.
    """
    c = census(mind)
    comp_dir = mind / "complete"
    comp_files = ([p for p in comp_dir.rglob("*.md")
                   if "archive" not in p.parts
                   and p.name not in ("AGENTS.md", "index.md")]
                  if comp_dir.is_dir() else [])
    comp_names = {p.name for p in comp_files}
    # reference lines + `## <slug>` topic headers now live inside the dated
    # records (the monolithic complete.md ledger was retired — issue #81)
    comp_lines: list = []
    comp_bodies: dict = {}
    for p in comp_files:
        body = p.read_text(encoding="utf-8", errors="replace")
        comp_bodies[p.name] = body
        comp_lines.extend(body.splitlines())

    # Document frequency over the records: how ORDINARY a token/identifier is.
    # Without this every prompt matches on `jax`, `test`, `workspace` and the
    # ranking is noise — the 2026-08-09 measurement flagged 96 of 148.
    token_df: dict = {}
    ident_df: dict = {}
    for name, body in comp_bodies.items():
        for w in _tokens(name.replace("-", " ").replace(".md", "")) | _tokens(body):
            token_df[w] = token_df.get(w, 0) + 1
        for i in _idents(body):
            ident_df[i] = ident_df.get(i, 0) + 1
    headers = [(ln[3:].strip(), _tokens(ln[3:].replace("-", " ")))
               for ln in comp_lines
               if ln.startswith("## ") and ln[3:].strip() != "Original prompt"]
    headers += [(f"complete/{p.relative_to(comp_dir)}",
                 _tokens(p.stem.replace("_", " "))) for p in comp_files]
    # Record STEMS specifically: a rare token appearing in several record stems
    # is a phased series, which is a far stronger claim than one in their prose.
    header_stems = [_tokens(p.stem.replace("-", " ")) for p in comp_files]
    n_records = max(len(comp_files), 1)
    active = mind / "active"
    issued_names = ({p.name for p in active.glob("*.md")}
                    if active.is_dir() else set())
    _noise = _upstream_noise() if source_reader is not None else set()

    suspects = []
    for r in c["records"]:
        if prefix and not _prefix_match(r["path"], prefix):
            continue
        path = r["path"]
        base = path.rsplit("/", 1)[-1]
        sans_wt = path.split("/", 1)[1] if "/" in path else path
        findings = []
        score = 0.0

        # 1. A record line that NAMES this prompt and CLAIMS it is done. A bare
        #    mention is not evidence — measured on the 2026-08-09 labelled set,
        #    treating any reference as high confidence produced 52 of 148 highs
        #    and buried the true positives.
        # A record may resolve a whole FOLDER of prompts at once —
        # `jax-substructure-simulator.md` opens "the 4 `jax_substructure/`
        # prompts shipped to `main`", which retires four files in one sentence.
        # But `<work-type>/<target>/` is also just a path prefix that every
        # sibling reference contains, so matching it bare made a prompt "named"
        # by any mention of its neighbours (measured: it falsely flagged
        # test_mode_bypass_ordered_assertion_ties off references to four
        # unrelated bug/autofit/ prompts). Require the line to be talking about
        # the folder's prompts as a group.
        series = f"{r['work_type']}/{r.get('target', '')}/"
        for ln in comp_lines:
            low = ln.lower()
            named = base in ln or sans_wt in ln
            if not named and series in ln and "prompt" in low:
                named = True
            if not named:
                continue
            if any(w in low for w in _FOLLOWUP_WORDS):
                findings.append(("referenced-followup", ln.strip()))
            elif any(w in low for w in _SHIPPED_WORDS):
                findings.append(("record-says-shipped", ln.strip()))
                score += _W_SHIPPED
            else:
                # Evidence, not score. A record merely NAMING a prompt was the
                # single biggest source of noise in the 2026-08-09 measurement:
                # it alone produced 52 of 148 "high" verdicts and buried every
                # true positive among them.
                findings.append(("referenced", ln.strip()))

        if base in issued_names:
            findings.append(("issued-duplicate", f"active/{base} already exists"))
            score += _W_SHIPPED
        if base in comp_names:
            findings.append(("complete-duplicate",
                             f"{base} already in the complete/ archive"))
            score += _W_SHIPPED

        # 2. Rare stem tokens, IDF-weighted, with a fan-out bonus. Raw Jaccard
        #    missed the biggest find of the 2026-08-09 sweep:
        #    `oversampling_kxs_coupling` against `kxs-core` scores 0.25, under
        #    any workable threshold. The real signal is that ONE very rare token
        #    (`kxs`, in 7 of 947 records) appears in SIX record stems — a series
        #    that shipped in phases. Requiring two shared tokens, the obvious
        #    first try, scores that case exactly 0.
        sig = _tokens(base.replace("_", " ")) | _tokens(r["title"])
        tok_score, evidence, best_fan = 0.0, [], 0
        for w in sig:
            d = token_df.get(w, 0)
            if not (0 < d <= _TOKEN_COMMON_DF):
                continue
            fan = sum(1 for st in header_stems if w in st)
            if not fan:
                continue
            best_fan = max(best_fan, fan)
            tok_score += math.log(n_records / d) * (2.0 if fan >= 3 else 1.0)
            evidence.append(f"{w} ({d} records" +
                            (f", {fan} in the stem" if fan >= 3 else "") + ")")
        if tok_score:
            score += tok_score
            findings.append(("rare-topic-overlap",
                             "rare tokens shared with the records: "
                             + ", ".join(sorted(evidence))))

        # 3. Rare identifiers the prompt names, appearing in a record body. This
        #    is what a human grader actually reads — `interferometer-jax-jit.md`
        #    naming `chunk_size` resolves the nufft prompt in one sentence.
        # census() deliberately does not carry the prompt body (it is serialised
        # into the dashboard JSON); read it here instead.
        try:
            prompt_text = (mind / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            prompt_text = ""
        pid = {i for i in _idents(prompt_text)
               if 0 < ident_df.get(i, 0) <= _IDENT_COMMON_DF}
        if pid:
            hits = {}
            for p, body in comp_bodies.items():
                shared = {i for i in pid if i in body}
                if len(shared) >= 2:
                    hits[p] = shared
            if hits:
                top = max(hits, key=lambda p: len(hits[p]))
                n = len(hits[top])
                score += _W_IDENT * (n - 1)   # 2 shared is weak, 7 is decisive
                findings.append(("shared-identifiers",
                                 f"record '{top}' names {n} of this prompt's "
                                 f"identifiers: {', '.join(sorted(hits[top])[:5])}"))

        # 4. The upstream leg (--repo): identifiers this prompt names that are
        #    ALREADY PRESENT in the target repo's source. This is the only leg
        #    that can see a prompt with no Mind-side trace at all.
        #
        #    It deliberately does NOT add to `score`. Presence of a name is not
        #    presence of the fix — test_mode_bypass_ordered_assertion_ties names
        #    five identifiers, all five are upstream, and the prompt is NOT
        #    shipped. Letting upstream hits feed `score` would carry exactly
        #    that prompt into the `high` band and make the one mis-grade this
        #    tool must never make. So upstream evidence gets its own weaker
        #    band and its own ordering key, and can never inflate a Mind-local
        #    verdict.
        upstream_score = 0.0
        if source_reader is not None:
            all_ids = {i for i in _idents(prompt_text)
                       if normalise_repo(i) not in _noise and i not in _noise}
            up = source_reader(all_ids) if all_ids else {}
            if len(up) >= _UPSTREAM_MIN_IDENTS:
                upstream_score = _W_UPSTREAM * (len(up) - 1)
                shown = sorted(up)[:5]
                findings.append((
                    "upstream-identifier-present",
                    f"{len(up)} of this prompt's identifiers already exist "
                    f"upstream: " + "; ".join(
                        f"{i} ({up[i][0]})" for i in shown)))

        # `Status:` alone is not evidence — it fired on every hand-set draft. Kept
        # as context on prompts something else already flagged, never as a reason.
        if (score > 0 or upstream_score > 0) and r["status"] not in ("-", "formalised"):
            findings.append(("stale-status",
                             f"Status: {r['status']} — hand-set; verify against "
                             "shipped state"))

        if score >= _SUSPECT_THRESHOLD or upstream_score > 0:
            if score >= _HIGH_THRESHOLD:
                conf = "high"
            elif score >= _SUSPECT_THRESHOLD:
                conf = "medium"
            else:
                # Upstream evidence only — the prompt has no Mind-side signal.
                # This is the band leg 3 exists to produce.
                conf = "needs-review"
            suspects.append({
                "path": path, "title": r["title"], "confidence": conf,
                "upstream_score": round(upstream_score, 2),
                "overlap_score": round(score, 2),
                "findings": [{"kind": k, "evidence": e} for k, e in findings],
            })

    # `needs-review` sorts BELOW the Mind-local bands: an upstream name-match is
    # weaker evidence than a record saying the work shipped, and the ordering
    # should say so.
    order = {"high": 0, "medium": 1, "low": 2, "needs-review": 3}
    suspects.sort(key=lambda s: (order[s["confidence"]], -s["overlap_score"],
                                 -s.get("upstream_score", 0.0), s["path"]))
    return {"generated": _dt.date.today().isoformat(), "scanned": c["total"],
            "upstream": upstream_meta or {}, "suspects": suspects}


def emit_reconcile(res: dict):
    print(f"== Intake reconcile: {len(res['suspects'])} suspect(s) of "
          f"{res['scanned']} scanned ==")
    up = res.get("upstream") or {}
    if up:
        # The sha is what makes a verdict re-checkable: "these names were on
        # main at THIS commit" is a claim someone can go and re-run.
        print(f"   upstream: {up['slug']} @ {up['sha'][:12]} "
              f"(read {up['when']})")
    if not res["suspects"]:
        print("  backlog reconciles clean against the complete/ records "
              "and active/.")
    # Column width follows the widest band actually present, so the default
    # (Mind-local) run stays byte-identical to what it printed before the
    # upstream leg existed — only a run that emits `needs-review` widens.
    width = max((len(s["confidence"]) for s in res["suspects"]), default=6)
    width = max(width, 6)
    for s in res["suspects"]:
        print(f"[{s['confidence']:>{width}}] {s['path']}")
        for f in s["findings"]:
            ev = f["evidence"]
            if len(ev) > 160:
                ev = ev[:157] + "…"
            print(f"{' ' * (width + 3)}{f['kind']}: {ev}")
    print("\nRetiring a prompt stays human: verify against the target repo's "
          "git log / merged\nPRs, then retire it to the complete/ archive by hand.")
    if up:
        print("`needs-review` means the prompt NAMES things that exist upstream "
              "— NOT that it\nshipped. A fix can land next to the name without "
              "being the fix the prompt asks for;\nread the cited lines before "
              "retiring anything.")


# --- ideas.md scanning --------------------------------------------------------
def scan_ideas(mind: Path):
    """Yield (bullet_text, context_header) for substantive ideas.md lines."""
    f = mind / "ideas.md"
    if not f.is_file():
        return []
    out, ctx = [], ""
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or set(s) <= set("-# "):
            continue
        if s.endswith(":") and not s.startswith("-"):
            ctx = s.rstrip(":")
            continue
        text = s.lstrip("-*").strip()
        if text.startswith("[formalised"):   # already reconciled — skip
            continue
        if len(text) < 4:
            continue
        out.append((text, ctx))
    return out


def mark_ideas(mind: Path, formalised: dict):
    """Conservatively annotate formalised ideas.md bullets in place.

    Rewrites each formalised bullet line as `- [formalised -> <path>] <text>` —
    it never deletes the original text, so nothing is lost until a human (or a
    later, trusted pass) prunes it.
    """
    f = mind / "ideas.md"
    if not f.is_file():
        return
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    out = []
    for raw in lines:
        content = raw.strip().lstrip("-*").strip()
        if content in formalised and not content.startswith("[formalised"):
            indent = raw[:len(raw) - len(raw.lstrip())]
            out.append(f"{indent}- [formalised -> {formalised[content]}] {content}")
        else:
            out.append(raw)
    f.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- emit ---------------------------------------------------------------------
def emit_human(d: dict):
    print("== IntakeDecision ==")
    print(f"Source:               {d['source']}")
    print(f"Title:                {d['title']}")
    print(f"Work-type:            {d['work_type']}  (confidence: {d['classification_confidence']})")
    print(f"Target:               {d['target_display']}")
    print(f"Repos resolved:       {', '.join(d['repos_affected']) or '(none)'}")
    print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    print(f"Autonomy:             {d['autonomy']}")
    print(f"Priority:             {d['priority']}")
    print(f"Workflow:             {d['workflow']}")
    print(f"Proposed path:        {d['proposed_path']}")
    print("Header to be written:")
    for ln in d["header"].splitlines():
        print(f"  {ln}")
    print("Risks / notes:")
    for r in d["risks"]:
        print(f"  - {r}")
    print(f"Next action:          {d['next_action']}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="intake", add_help=True)
    ap.add_argument("--mind", required=True)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--apply", action="store_true",
                    help="write the formal prompt file(s); default is dry-run")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cl = sub.add_parser("classify", help="classify raw text or a file")
    cl.add_argument("text", nargs="*", help="raw idea text")
    cl.add_argument("--file", default="", help="read raw text from a file")

    sub.add_parser("ideas", help="scan ideas.md and propose one prompt per bullet")

    sub.add_parser("census", help="inventory all filed prompts (always read-only)")

    db = sub.add_parser("dashboard", help="render the census as the Mind task "
                                          "page; --apply writes dashboard.md "
                                          "+ its one-tap-copy dashboard.html")
    db.add_argument("--check", action="store_true",
                    help="exit 1 if the committed dashboard.md has drifted from "
                         "what this run renders (the generation date is ignored, "
                         "so a re-render on an unchanged Mind is not drift)")

    fm = sub.add_parser("formalise", help="retroactively header the backlog "
                                          "prompts census flags; --apply writes")
    fm.add_argument("prefix", nargs="?", default="",
                    help="only formalise prompts under this path prefix "
                         "(e.g. bug/)")

    rc = sub.add_parser("reconcile", help="rank backlog prompts that look "
                                          "already-shipped (always read-only)")
    rc.add_argument("prefix", nargs="?", default="",
                    help="only reconcile prompts under this path prefix")
    rc.add_argument("--repo", default="",
                    help="ALSO read this target repo's source for identifiers "
                         "the prompts name (the only leg that sees prompts with "
                         "no Mind-side trace). Opt-in: the default path makes no "
                         "network access. Ranks for review; never says shipped.")

    a = ap.parse_args(argv)
    mind = Path(a.mind)

    if a.cmd == "formalise":
        res = formalise(mind, prefix=a.prefix, apply=a.apply)
        print(json.dumps(res, indent=2)) if a.as_json else emit_formalise(res)
        return 0

    if a.cmd == "reconcile":
        if a.apply:
            print("intake reconcile is read-only — retiring prompts stays "
                  "human (--apply ignored).", file=sys.stderr)
        reader, meta = None, None
        if a.repo:
            reader, sha, slug, err = upstream_reader(mind, a.repo)
            if err:
                print(f"intake reconcile: {err}", file=sys.stderr)
                return 5
            meta = {"slug": slug, "sha": sha,
                    "when": _dt.date.today().isoformat()}
        res = reconcile(mind, prefix=a.prefix, source_reader=reader,
                        upstream_meta=meta)
        print(json.dumps(res, indent=2)) if a.as_json else emit_reconcile(res)
        return 0

    if a.cmd == "census":
        c = census(mind)
        print(json.dumps(c, indent=2)) if a.as_json else emit_census(c)
        return 0

    if a.cmd == "dashboard":
        c = census(mind)
        # Two renderings of one census: the markdown page GitHub renders in
        # the repo, and its one-tap-copy HTML twin GitHub Pages serves.
        pages = {"dashboard.md": render_dashboard(c),
                 "dashboard.html": render_dashboard_html(c)}
        if a.check:
            stale = []
            for name, want in pages.items():
                target = mind / name
                on_disk = (target.read_text(encoding="utf-8")
                           if target.is_file() else "")
                if _dashboard_body(on_disk) != _dashboard_body(want):
                    stale.append(name)
            if not stale:
                print("dashboard.md + dashboard.html are current")
                return 0
            print(f"{' + '.join(stale)} stale — regenerate with "
                  "`pyauto-brain intake dashboard --apply`", file=sys.stderr)
            return 1
        written = None
        if a.apply:
            for name, want in pages.items():
                (mind / name).write_text(want, encoding="utf-8")
            written = " + ".join(pages)
        if a.as_json:
            summary = {k: v for k, v in c.items() if k != "records"}
            print(json.dumps({"census": summary, "page": pages["dashboard.md"],
                              "html": pages["dashboard.html"],
                              "written": written}, indent=2))
        elif written:
            print(f"Wrote: {written} ({c['total']} prompts, "
                  f"{len(c['hygiene'])} hygiene flag(s))")
        else:
            print(pages["dashboard.md"], end="")
        return 0

    if a.cmd == "classify":
        if a.file:
            src_path = Path(a.file)
            if not src_path.is_file():
                print(f"intake: file not found: {src_path}", file=sys.stderr)
                return 4
            text = src_path.read_text(encoding="utf-8", errors="replace")
            source = f"file:{a.file}"
        elif a.text:
            text = " ".join(a.text)
            source = "user-intake"
        else:
            text = sys.stdin.read()
            source = "stdin"
        if not text.strip():
            print("intake: no input text to classify.", file=sys.stderr)
            return 4
        decision = analyse(text, source)
        if a.apply:
            written = write_prompt(mind, decision, text, source)
            decision["written"] = written
        if a.as_json:
            print(json.dumps(decision, indent=2))
        else:
            emit_human(decision)
            if a.apply:
                print(f"\nWrote: {decision['written']}")
        return 0

    if a.cmd == "ideas":
        bullets = scan_ideas(mind)
        if not bullets:
            print("intake: no un-formalised ideas found in ideas.md.", file=sys.stderr)
            return 4
        results = []
        formalised = {}
        for text, ctx in bullets:
            ctx_text = f"{ctx}: {text}" if ctx else text
            d = analyse(ctx_text, f"ideas.md ({ctx or 'top'})")
            if a.apply:
                d["written"] = write_prompt(mind, d, ctx_text, d["source"])
                formalised[text] = d["written"]
            results.append(d)
        if a.apply and formalised:
            mark_ideas(mind, formalised)
        if a.as_json:
            print(json.dumps(results, indent=2))
        else:
            print(f"== Intake: {len(results)} idea(s) from ideas.md ==")
            for d in results:
                mark = f" -> WROTE {d['written']}" if a.apply else ""
                print(f"  [{d['work_type']}/{d['target']}, {d['difficulty']}, "
                      f"conf {d['classification_confidence']}] {d['title']}"
                      f"  =>  {d['proposed_path']}{mark}")
            if not a.apply:
                print("\n(dry-run — re-run `intake ideas --apply` to write these + "
                      "mark the bullets in ideas.md)")
        return 0

    return 5


if __name__ == "__main__":
    sys.exit(main())

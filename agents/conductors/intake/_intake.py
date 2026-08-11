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


def parse_header(text: str) -> dict:
    """Extract the light metadata header (`Field: value` lines) from a prompt.

    Only scans the top of the file so a stray "Status:" deep in prose does not
    fire; first occurrence of each field wins. No YAML — the blessed convention.
    """
    fields = {}
    for line in text.splitlines()[:30]:
        m = re.match(r"(Type|Target|Difficulty|Autonomy|Priority|Status):\s*(\S.*)",
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
                   "status": "", "prompt": ""}
            entries.append(cur)
            continue
        if cur is None:
            continue
        field = _REG_FIELD.match(line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip()
        if key in ("issue", "status", "prompt") and not cur[key]:
            cur[key] = value
            if key == "issue":
                # The value often trails prose ("…/issues/20 (build gated)"),
                # so link the matched URL, never the whole field.
                m = _ISSUE_URL.search(value)
                if m:
                    cur["issue"], cur["issue_no"] = m.group(0), m.group(1)
    return entries


def _clip(text: str, limit: int = 130) -> str:
    """First line of a registry value, clipped at a word boundary."""
    text = text.strip().splitlines()[0].strip() if text.strip() else ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" .,;:—-") + "…"


def census(mind: Path) -> dict:
    """Inventory the Mind's work — filed prompts plus the registry's live rows.

    Read-only, always. The backlog leg walks the WORK_TYPES folders under
    `draft/` (incl. `triage/`), one record per prompt file. The registry leg
    itemises what has left the backlog: `active/` prompts (issued — an open
    GitHub issue), and the `parked.md` / `planned.md` rows. This is the Mind's
    *work* view — health belongs to the Heart, never here.
    """
    records, hygiene = [], []
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
                "header": header,
                "missing": missing,
            })
            if len(missing) == len(HEADER_FIELDS):
                hygiene.append(f"{rel} — no metadata header (pre-dates intake)")

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

    in_flight = []
    active = mind / "active"
    for f in sorted(active.glob("*.md")) if active.is_dir() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = str(f.relative_to(mind))
        header = parse_header(text)
        row = by_prompt.get(rel, {})
        in_flight.append({
            "path": rel,
            "title": _title(text),
            "target": header.get("target", "-"),
            "priority": header.get("priority", "-"),
            "issue": row.get("issue", ""),
            "issue_no": row.get("issue_no", ""),
            # The registry row only. A prompt's own `Status:` header is written
            # at conception ("filed"/"formalised") and is stale the moment the
            # task is issued, so it would report the opposite of live state.
            "status": row.get("status", ""),
        })

    return {
        "generated": _dt.date.today().isoformat(),
        "total": len(records),
        "issued_count": len(in_flight),
        "by_work_type": _count("work_type"),
        "by_target": _count("target"),
        "by_difficulty": _count("difficulty"),
        "by_priority": _count("priority"),
        "records": records,
        "in_flight": in_flight,
        "parked": parked,
        "planned": planned,
        "hygiene": hygiene,
    }


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def _label(value: str) -> str:
    """Link text for a markdown bullet, made safe to render.

    Brackets would end the link early, and a stray `<!--` (some untriaged
    prompts open with an HTML comment, which `_title` faithfully reports) would
    comment out the rest of the page in GitHub's renderer.
    """
    value = str(value).replace("<!--", "").replace("-->", "").strip()
    return value.replace("[", r"\[").replace("]", r"\]") or "Untitled"


# Pick order. The dashboard exists to be *chosen from*, so every list is sorted
# most-pickable first: urgent before routine, small before enormous. Unknown
# (`-`, the headerless prompts) sorts last rather than being hidden.
PRIORITY_RANK = {"high": 0, "medium": 1, "normal": 2, "low": 3}
DIFFICULTY_RANK = {"small": 0, "medium": 1, "large": 2, "too-large": 3}
PICK_LIST_MAX = 12
# Live GitHub views, for the half of this page a static file cannot hold: the
# issues themselves. Org-wide searches, so a new repo needs no edit here.
GH_SEARCH = "https://github.com/search?q=org%3APyAutoLabs+is%3A{kind}+is%3Aopen&type={kind}s"


def _pick_key(r: dict) -> tuple:
    return (PRIORITY_RANK.get(r["priority"], 9),
            DIFFICULTY_RANK.get(r["difficulty"], 9),
            r["target"], r["path"])


def _bullet(r: dict) -> str:
    """One backlog prompt as a bullet — the phone-readable unit of this page.

    A bullet wraps; a five-column table does not. GitHub's mobile view scrolls
    wide tables sideways, which makes a 133-row backlog unusable on a phone,
    so the metadata rides after an em dash instead of in columns.
    """
    facets = " · ".join(x for x in (r["target"], r["difficulty"],
                                    r["autonomy"], r["priority"]) if x != "-")
    return f"- [{_label(r['title'])}]({r['path']})" + (f" — {facets}" if facets else "")


def render_dashboard(c: dict) -> str:
    """Render the census as the Mind's task page (`dashboard.md`).

    Tasks only, by design: no readiness verdicts, no test state — that is the
    Heart's dashboard (`/health`). Two rules shape the layout: it must be
    *pickable* (the top of the page answers "what should I do now?", not "how
    many prompts are there?"), and it must read on a phone (bullets over wide
    tables, long sections behind `<details>`). Links are repo-root-relative so
    they resolve in GitHub's web and mobile markdown views alike.
    """
    records = sorted(c["records"], key=_pick_key)
    L = [
        "# PyAutoMind task dashboard",
        "",
        f"<!-- generated by `pyauto-brain intake dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        "",
        "Every task the Mind is holding, on one page: what is in flight, what "
        "is parked, and the whole backlog to pick from. Pick a line, then run "
        "`/start_dev <prompt-path>` to start it.",
        "",
        "Tasks only — the organism's health lives with the Heart (`/health`), "
        "not here.",
        "",
        "| Where | Count |",
        "|-------|------:|",
        f"| [In flight](#in-flight) (`active/`) | {c['issued_count']} |",
        f"| [Parked](#parked) (`parked.md`) | {len(c['parked'])} |",
        f"| [Planned](#planned) (`planned.md`) | {len(c['planned'])} |",
        f"| [Backlog](#backlog) (`draft/`) | {c['total']} |",
        "",
        f"Live on GitHub: [open issues]({GH_SEARCH.format(kind='issue')}) · "
        f"[open pull requests]({GH_SEARCH.format(kind='pr')})",
        "",
        "## Start here",
        "",
    ]

    high = [r for r in records if r["priority"] == "high"]
    quick = [r for r in records
             if r["difficulty"] == "small" and r["autonomy"] == "safe"]
    for title, note, rows in (
        ("Highest priority", "filed as `high`", high),
        ("Quick wins", "small enough, and safe enough to run unattended", quick),
    ):
        shown = rows[:PICK_LIST_MAX]
        more = f" — showing {len(shown)} of {len(rows)}" if len(rows) > len(shown) else ""
        L += [f"**{title}** ({note}){more}", ""]
        L += [_bullet(r) for r in shown] or ["- _(none right now)_"]
        L += [""]

    L += ["## In flight", "",
          "Issued — each has an open GitHub issue and usually a branch. The "
          "full record for each is in [`active.md`](active.md).", ""]
    for r in c["in_flight"]:
        issue = f" — [issue #{r['issue_no']}]({r['issue']})" if r["issue_no"] else ""
        status = f" — {_clip(r['status'])}" if r["status"] else ""
        L.append(f"- [{_label(r['title'])}]({r['path']}){issue}{status}")
    L += ([] if c["in_flight"] else ["- _(nothing in flight)_"]) + [""]

    for key, heading, blurb in (
        ("parked", "Parked", "Started or scoped, not currently in flight — "
                             "resume by moving the row back to `active.md`. "
                             "Full detail in [`parked.md`](parked.md)."),
        ("planned", "Planned", "Scoped but not started; some are not yet prompt "
                               "files. Full detail in [`planned.md`](planned.md)."),
    ):
        rows = c[key]
        L += [f"## {heading}", "", blurb, "",
              "<details>", f"<summary><b>{len(rows)}</b> task(s)</summary>", ""]
        for e in rows:
            issue = f" — [issue #{e['issue_no']}]({e['issue']})" if e["issue_no"] else ""
            status = f" — {_clip(e['status'])}" if e["status"] else ""
            L.append(f"- **{_label(e['slug'])}**{issue}{status}")
        L += ([] if rows else ["- _(none)_"]) + ["", "</details>", ""]

    L += [f"## Backlog", "",
          f"**{c['total']}** filed prompts, not started. Each section is sorted "
          "most-pickable first (priority, then size).", ""]
    for wt, n in c["by_work_type"].items():
        rows = [r for r in records if r["work_type"] == wt]
        L += ["<details>", f"<summary><b>{wt}</b> — {n}</summary>", ""]
        L += [_bullet(r) for r in rows]
        L += ["", "</details>", ""]

    if c["hygiene"]:
        L += ["## Hygiene", "",
              f"{len(c['hygiene'])} prompt(s) without a metadata header — they "
              "show no facets above. Re-home or re-run intake on them when "
              "touched.", "",
              "<details>", "<summary>Headerless prompts</summary>", ""]
        L += [f"- `{h.split(' — ')[0]}`" for h in c["hygiene"]]
        L += ["", "</details>"]
    return "\n".join(L).rstrip("\n") + "\n"


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
                                          "page; --apply writes dashboard.md")
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
        page = render_dashboard(c)
        if a.check:
            target = mind / "dashboard.md"
            on_disk = target.read_text(encoding="utf-8") if target.is_file() else ""
            if _dashboard_body(on_disk) == _dashboard_body(page):
                print("dashboard.md is current")
                return 0
            print("dashboard.md is stale — regenerate with "
                  "`pyauto-brain intake dashboard --apply`", file=sys.stderr)
            return 1
        written = None
        if a.apply:
            (mind / "dashboard.md").write_text(page, encoding="utf-8")
            written = "dashboard.md"
        if a.as_json:
            summary = {k: v for k, v in c.items() if k != "records"}
            print(json.dumps({"census": summary, "page": page, "written": written},
                             indent=2))
        elif written:
            print(f"Wrote: {written} ({c['total']} prompts, "
                  f"{len(c['hygiene'])} hygiene flag(s))")
        else:
            print(page, end="")
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

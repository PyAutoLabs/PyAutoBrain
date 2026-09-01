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
the Feature Agent later trusts the same number — unless the author already
declared one in the raw text, which outranks the estimate (see "human-declared
header fields").

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
    WORK_TYPES, HUMAN_REVIEW, MANUAL_ONLY_WORK_TYPES,
    LIBRARY_REPOS, WORKSPACE_REPOS, ORGANISM_REPOS, KNOWN_REPOS,
    RISK_KEYWORDS, AMBIGUITY_KEYWORDS, normalise_repo, declared_header,
    declared_inline, effective_difficulty, strip_declarations, _hits,
    effective_consequence, effective_unattended, effective_review_minutes,
    policy as _sizing_policy, BODY_MAP_PATH,
    _body_map_specs as _sizing_specs,
)

# The shared board theme: the one place that answers "what does a one-tap board
# look like". Presentation only — the stylesheet, the hero, the pills — so this
# page and the Brain board are visibly the same family (board/_theme.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "board"))
from _theme import (  # noqa: E402
    JS as _THEME_JS, boards_footer, css as _theme_css, hero, pills, stats,
)

THEME_ORGAN = "mind"  # whose logo this page wears

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
#
# Derived from the body map, which already holds every repo's name in its real
# capitalisation — a hand-kept copy here would be the same drift #287 closed in
# the alias table one map over, and it already had the beginnings of it: keys the
# router could reach (`pyautohands`, and the CTI/Reduce libraries) had no row, so
# a header came out as `Target: pyautohands`. Only the rows a body map cannot
# know are written out: the pre-rename spellings and the workspace bucket.
def _repo_display() -> dict:
    out = {
        normalise_repo(name): name
        for name in _sizing_specs()
    }
    out.update({
        "autoconf": out.get("autonerves", "autonerves"),      # pre-rename spelling
        "pyautobuild": out.get("pyautohands", "pyautohands"),  # pre-rename spelling
        "autobuild": out.get("pyautohands", "pyautohands"),    # pre-rename package
        "workspaces": "workspaces",                            # a bucket, not a repo
    })
    return out


REPO_DISPLAY = _repo_display()
PRIORITY_HIGH = ["urgent", "asap", "blocker", "blocking", "critical", "important",
                 "high priority", "must fix", "regression"]
PRIORITY_LOW = ["someday", "nice to have", "eventually", "low priority", "minor",
                "when there is time", "backlog"]


def _slug(text: str, maxwords: int = 7) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    slug = "_".join(words[:maxwords])
    return slug[:48].strip("_") or "untitled"


# Words that must never be the last one in a truncated title. A cut landing
# on "the" or "which" reads as a rendering bug rather than a summary — the
# page said "kernel-CDF numba fast path (the" for months.
_DANGLING = {
    "a", "an", "and", "are", "as", "at", "but", "by", "can", "for", "from",
    "if", "in", "into", "is", "it", "its", "of", "on", "or", "our", "over",
    "one", "other", "per", "so", "than", "that", "the", "their", "then",
    "this", "to", "up", "via", "we", "what", "when", "which", "while",
    "with", "without",
}
TITLE_WORDS = 12


def _shorten(words: list) -> str:
    """`words` cut to a title, ending somewhere a reader can stop.

    Trailing function words are dropped, an orphaned opening bracket is
    dropped with the fragment it opened, and an unpaired backtick is dropped
    so the code span cannot bleed into the rest of the page. An ellipsis
    marks that there was more — a silent cut is indistinguishable from a
    title that simply ends badly.
    """
    kept = list(words[:TITLE_WORDS])
    while kept and kept[-1].lower().strip("(,;:—-") in _DANGLING:
        kept.pop()
    out = " ".join(kept).rstrip(" ,;:—-([{")
    if out.count("(") > out.count(")"):
        out = out[:out.rindex("(")].rstrip(" ,;:—-")
    if out.count("`") % 2:
        out = out[:out.rindex("`")].rstrip(" ,;:—-")
    # Every guard above can eat the whole thing (a title that opens with a
    # bracket, say) — fall back to the plain cut rather than to nothing.
    return (out or " ".join(words[:TITLE_WORDS])) + "…"


def _title(text: str) -> str:
    """First markdown heading, else first non-empty line, trimmed to a title."""
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = s.lstrip("#").strip().rstrip(":").rstrip(".")
        # Keep it title-length: first sentence / ~12 words.
        s = re.split(r"(?<=[a-z])[.?!]\s", s)[0]
        words = s.split()
        if not words:
            return "Untitled"
        return " ".join(words) if len(words) <= TITLE_WORDS else _shorten(words)
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
    """Return (work_type, confidence, per_type_hits).

    `MANUAL_ONLY_WORK_TYPES` (today: `human_review`) can never come out of here.
    They are not a reading of the prose — they are a human saying "this needs my
    eyes" — so they are filtered out of the signal sets rather than merely
    absent from them, and only a `Type:` declaration reaches them.
    """
    scores = {}
    for wt, sigs in WORK_TYPE_SIGNALS.items():
        if wt in MANUAL_ONLY_WORK_TYPES:
            continue
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
    """safe | supervised | human-required.

    `repo_count > 1` used to force `supervised` here, and it is why 120 of the
    137 backlog prompts carried that level on 2026-08-30: nearly every real task
    in this organism names a library plus its workspace, or a library plus a
    downstream repo. Repo count is *blast radius*, and blast radius is already
    priced — `estimate_difficulty` adds 2 points per repo beyond the first. This
    field is supposed to encode something else: whether a HUMAN'S JUDGEMENT is
    required. A change touching four repos mechanically needs no more judgement
    than the same change touching one.

    So `repo_count` is removed and NOTHING replaces it. The first draft of this
    change added `human_judgement` as a supervised trigger in its place, on the
    reasoning that ambiguity is what actually predicts a park. Measured over the
    backlog, that made things WORSE — `safe` fell from 30 to 24, because the
    ambiguity keywords ("unclear", "investigate", "explore", "research",
    "decide") fire on 63% of prompts and catch well-written ones indiscriminately.
    It was the same mistake as the rule it replaced: a loose proxy standing in
    for a judgement it does not measure. Dropping `repo_count` alone takes `safe`
    from 30 to 55.

    CHANGED 2026-08-30 as a dated EXPERIMENT, not a graduation — see
    AUTONOMY.md "Multi-repo autonomy experiment". Deliberately not justified by
    the calibration log's 238 rows and zero `rejected`: those rows are July
    human-in-session work (about seven cover all of August, against 332
    completions), `rejected` is structurally unreachable in that log, and every
    clean row was produced *with this guard switched on* — by a review that
    raised the work-type caps precisely BECAUSE this heuristic stayed
    conservative. Evidence collected under a safety device cannot license
    removing the device.
    """
    if factors["human_judgement"] and factors["repos_affected"] == 0:
        return "human-required"          # unscoped / needs a design decision
    if factors["architectural_risk"] or level in ("large", "too-large"):
        return "supervised"
    return "safe"


def analyse(text: str, source: str, themes=None):
    """Classify raw text into a full IntakeDecision (never writes).

    `themes` is the optional `Themes:` keyword list the caller assigns at
    formalisation (primary first). Absent, any `Themes:` block the raw input
    already carries is kept; absent that too, the prompt is simply un-themed —
    formalisation never waits on a theme.
    """
    repos = _repos_in(text)
    # What the input DECLARES outranks what its prose merely suggests — the same
    # rule the feature and bug conductors apply (the faculty owns it). Raw
    # conception input may carry a full header block (a pasted prompt) or state
    # a key mid-sentence, so both readers run; header lines win a tie.
    inline, decl_spans = declared_inline(text)
    header = declared_header(text)
    declared = {k: v for k, v in {
        "difficulty": header["declared_difficulty"] or inline.get("difficulty"),
        "autonomy": header["declared_autonomy"] or inline.get("autonomy"),
        "priority": header["priority"] or inline.get("priority"),
        "type": header["declared_type"] or inline.get("type"),
    }.items() if v}

    work_type, confidence, type_hits = classify_work_type(text)
    if declared.get("type"):
        work_type, confidence = declared["type"], "high"
    target, target_display, repos = infer_target(text, repos)

    # Build a prompt-shaped dict the shared sizing faculty understands.
    p = {"text": text, "repos": repos, "words": len(text.split()),
         "target": target, "work_type": work_type,
         "declared_difficulty": declared.get("difficulty")}
    level, score, factors, estimated = effective_difficulty(p)

    # The review-cost model (sizing faculty). `Witness:` is the one field that
    # can never be derived: it is a promise about evidence the work will
    # produce, and a plausible-sounding invented one would defeat the whole
    # mechanism — the value of the field is that its ABSENCE is informative.
    # So it is read if declared and left absent otherwise, which correctly
    # grades the prompt `judge`.
    p["witness"] = header.get("witness")
    p["declared_consequence"] = header.get("declared_consequence")
    p["declared_unattended"] = header.get("declared_unattended")
    p["declared_review_minutes"] = header.get("declared_review_minutes")
    p["declared_autonomy"] = header["declared_autonomy"] or inline.get("autonomy")
    consequence, consequence_why, consequence_derived = effective_consequence(p, factors)
    unattended, unattended_why, unattended_derived = effective_unattended(
        p, level, factors, estimated)
    review_minutes, review_minutes_derived = effective_review_minutes(
        p, consequence, level)

    autonomy = declared.get("autonomy") or infer_autonomy(level, factors)
    priority = declared.get("priority") or infer_priority(text)
    workflow = infer_workflow(target, repos)

    themes = [k for k in dict.fromkeys(_theme_key(t) for t in (themes or []))
              if k] or parse_theme_list(text)

    title = _title(strip_declarations(text, decl_spans))
    slug = _slug(title)
    folder = work_type if confidence != "low" else "triage"
    if folder == HUMAN_REVIEW:
        # A declared human review is never demoted. `triage/` means "nobody has
        # classified this"; here a human has, and the thing being reviewed is
        # shipped work whose target may live in a completion record rather than
        # in an @RepoName the body happens to repeat. Unresolved target files
        # flat under the work-type, the way triage/ does.
        proposed = (f"draft/{folder}/{target}/{slug}.md" if target != "?"
                    else f"draft/{folder}/{slug}.md")
    elif folder == "triage":
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
                            autonomy, priority, themes,
                            consequence=consequence, witness=p["witness"],
                            review_minutes=review_minutes,
                            unattended=unattended)
    return {
        "source": source,
        "title": title,
        "work_type": work_type,
        "classification_confidence": confidence,
        "work_type_source": "declared" if declared.get("type") else "inferred",
        "type_signals": type_hits,
        "target": target,
        "target_display": target_display,
        "repos_affected": repos,
        "themes": themes,
        "difficulty": level,
        "difficulty_score": score,
        "difficulty_factors": factors,
        "difficulty_declared": declared.get("difficulty"),
        "difficulty_derived": estimated,
        "difficulty_disagreement": (
            "difficulty" in declared and estimated != level
        ),
        "difficulty_source": "declared" if "difficulty" in declared else "estimated",
        "autonomy": autonomy,
        "autonomy_source": "declared" if "autonomy" in declared else "inferred",
        "consequence": consequence,
        "consequence_derived": consequence_derived,
        "consequence_why": consequence_why,
        "witness": p["witness"],
        "review_minutes": review_minutes,
        "review_minutes_derived": review_minutes_derived,
        "unattended": unattended,
        "unattended_derived": unattended_derived,
        "unattended_why": unattended_why,
        "priority": priority,
        "priority_source": "declared" if "priority" in declared else "inferred",
        "declared_fields": declared,
        "workflow": workflow,
        "proposed_path": proposed,
        "header": header,
        "risks": _risks(level, factors, confidence, target, declared, estimated,
                        witness=p["witness"], consequence=consequence),
        "next_action": _next_action(proposed, confidence, folder),
    }


def _render_header(title, work_type, target_display, repos, level, autonomy,
                   priority, themes=None, consequence=None, witness=None,
                   review_minutes=None, unattended=None):
    lines = [f"# {title}", "", f"Type: {work_type}", f"Target: {target_display}"]
    if repos:
        lines.append("Repos:")
        lines += [f"- {REPO_DISPLAY.get(r, r)}" for r in repos]
    # `Themes:` rides directly under `Repos:` — the same list shape, and the
    # pair reads as "where the code lives, then what the work is about"
    # (vocabulary: `PyAutoMind/themes.md`). Optional and never blocking: a
    # prompt formalises with or without it, and the auto-bundler falls back to
    # `Target:` for anything un-themed.
    if themes:
        lines.append("Themes:")
        lines += [f"- {t}" for t in themes]
    lines += [f"Difficulty: {level}", f"Autonomy: {autonomy}",
              f"Priority: {priority}", "Status: formalised"]
    # The review-cost model rides below the difficulty block: what the work
    # costs the organism, then what it costs the human. `Witness:` is written
    # ONLY when the author supplied one — see the note in `analyse`.
    if consequence:
        lines.append(f"Consequence: {consequence}")
    if witness:
        lines.append(f"Witness: {witness}")
    if review_minutes is not None:
        lines.append(f"Review-minutes: {review_minutes}")
    if unattended:
        lines.append(f"Unattended: {unattended}")
    return "\n".join(lines)


def _risks(level, factors, confidence, target, declared=None, estimated=None,
           witness=None, consequence=None):
    out = []
    declared = declared or {}
    if "difficulty" in declared and declared["difficulty"] != estimated:
        out.append(f"Difficulty {declared['difficulty']} declared in the raw text "
                   f"— it overrides the heuristic estimate ({estimated}).")
    for field in ("autonomy", "priority"):
        if field in declared:
            out.append(f"{field.capitalize()} {declared[field]} declared in the raw "
                       f"text — taken as written, not inferred.")
    if witness is None and consequence == "judge":
        out.append("No Witness: declared — this grades `judge` (a PI's "
                   "quarter-hour) whatever its size. Naming one machine-checkable "
                   "claim now is what makes the work reviewable in minutes later.")
    if confidence == "low":
        out.append("Low classification confidence — filed to triage/ for a human "
                   "to re-home once the work type is clear.")
    if declared.get("type") in MANUAL_ONLY_WORK_TYPES:
        out.append(f"Type {declared['type']} declared — it is never inferred, so "
                   "this filing exists because a human asked for it.")
    if target == "?" and declared.get("type") != HUMAN_REVIEW:
        out.append("No target repo resolved — add an @RepoName reference or set "
                   "Target: before start_dev.")
    if factors["architectural_risk"]:
        out.append("Architectural / API risk keywords present — review scope before build.")
    if level in ("large", "too-large"):
        out.append("Large: expect to split into phased PRs at start_dev time.")
    if not out:
        out.append("Low risk; ready to formalise.")
    return out


def _next_action(proposed, confidence, work_type=None):
    if confidence == "low":
        return (f"Re-run with a clearer description or --apply to file {proposed} "
                "in triage/ for manual re-homing.")
    if work_type == HUMAN_REVIEW:
        # A human review has no dev leg to route: the work already shipped.
        # It waits on the Human review section of the Mind dashboard until a
        # person reads it and signs it off.
        return (f"Review the header, then `--apply` to write {proposed}; "
                "afterwards it stands on the dashboard's Human review section "
                "until you sign it off.")
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
# `consequence` and `review-minutes` join the hygiene set: both are DERIVED, so
# `intake formalise` can fill them in place like any other missing field.
#
# `witness` and `unattended` deliberately do NOT. `formalise` writes every field
# it finds missing, and a `Witness:` cannot be derived — it is a promise about
# evidence the work will produce. An auto-written one would be plausible prose
# with nothing behind it, which is strictly worse than none: the entire value of
# the field is that its ABSENCE is informative, and a backlog of invented
# witnesses would grade `notify` while offering a reviewer nothing to check.
# (`unattended` stays out for the ordinary reason — it is derived on read and
# never needs storing.) The dashboard reports missing witnesses as its own
# hygiene row instead, where the fix is a human writing one.
HEADER_FIELDS = ("type", "target", "difficulty", "autonomy", "priority", "status",
                 "consequence", "review-minutes")

# `Fix:`-anchored PR reference in a draft prompt's body — the idiom a session
# writes when it fixes the bug but forgets to advance the prompt's lifecycle
# (the 2026-08-21 numba psf_weighted_data case: fixed + merged overnight,
# still advertised as top-priority backlog). Line-anchored so a prompt merely
# *citing* a PR as context is never flagged.
_FIX_PR_RE = re.compile(r"^Fix:.*(?:PR\s*#\d+|/pull/\d+)",
                        re.MULTILINE | re.IGNORECASE)

# The other half of the same failure: a session finishes the work, writes the
# outcome into the prompt's own `Status:` header — `shipped`, `superseded`,
# `absorbed` — and then leaves the file in `draft/`, where it keeps rendering as
# pickable backlog. Read off the parsed header (not the body) so a prompt that
# merely *describes* shipped sibling work is never flagged.
DONE_STATUSES = ("shipped", "superseded", "absorbed", "complete", "completed",
                 "done", "retired")


def parse_header(text: str) -> dict:
    """Extract the light metadata header (`Field: value` lines) from a prompt.

    Only scans the top of the file so a stray "Status:" deep in prose does not
    fire; first occurrence of each field wins. No YAML — the blessed convention.
    `Epic:`/`Phase:` are optional epic-membership fields (dashboard grouping),
    `Bundle:` the same for a pinned bundle (`bundles.md`); `Blocked-by:` is the
    declared gate the dashboard reads as "not startable on its own";
    `Filed:`/`Issued:` are the prompt's own date, keyed by the state it was in
    when that happened (PyAutoMind REFERENCE.md "Task dates"). None are in
    HEADER_FIELDS, so their absence is never header hygiene.
    """
    fields = {}
    for line in text.splitlines()[:30]:
        m = re.match(r"(Type|Target|Difficulty|Autonomy|Priority|Status|"
                     r"Issued|Filed|Epic|Phase|Bundle|Blocked-by|"
                     r"Consequence|Witness|Review-minutes|Unattended|Lane):\s*(\S.*)",
                     line.strip())
        if m:
            fields.setdefault(m.group(1).lower(), m.group(2).strip())
    return fields


def _done_status(header: dict) -> str:
    """The first word of a `Status:` header that declares the work finished.

    Returns `""` for a status that is merely *about* finished work (`phases 1-3
    SHIPPED; phase 4 open`, `split (phases 1-2 SHIPPED; phase 3 open)`): only a
    status that *opens* on a done-word means the prompt itself is spent. Empty
    string is falsey, so callers read as a plain condition.
    """
    first = header.get("status", "").strip().lower().lstrip("*_`").split()
    return first[0].rstrip(":;,.") if first and \
        first[0].rstrip(":;,.") in DONE_STATUSES else ""


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


# `bundles.md` — the Mind's registry of PINNED bundles: sets of INDEPENDENT
# prompts a human has decided are worth doing in one orchestrated session.
# Same H2-slug + `- key: value` shape as epics.md, plus a `members:` list of
# prompt paths written as `  - <path>` bullets (the active.md `repos:` idiom).
#
# A bundle is NOT an epic. An epic is ordered and phase-gated — one phase at a
# time, worked through its ledger — so its members are pulled OUT of every pick
# list. A bundle is a flat set of independent tasks that happen to suit one
# session: they can be worked in any order, so members stay in their usual
# sections and a bundle is an additional VIEW of the backlog, never a
# replacement for it.
_BUNDLE_FIELDS = ("title", "rationale", "status")

# One member of a pinned bundle: an indented bullet under `- members:`. Top-
# level `- key: value` lines close the list (they match _REG_FIELD first).
_MEMBER_BULLET = re.compile(r"^\s+-\s+(\S+)")


def parse_bundles(path: Path) -> list:
    """Parse `bundles.md` into `[{slug, title, members, rationale, status}]`.

    Tolerant like parse_epics: a slug alone still yields a record; absent file
    -> empty list (a freshly-spawned Mind has no bundles). `- members:` opens
    a list — every indented `  - <path>` bullet under it is one prompt path,
    and the next top-level `- key:` field closes it.
    """
    if not path.is_file():
        return []
    entries, cur, in_members = [], None, False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        head = _REG_HEAD.match(line)
        if head:
            cur = {"slug": head.group(1), "members": [], "origin": "pinned"}
            cur.update({k: "" for k in _BUNDLE_FIELDS})
            entries.append(cur)
            in_members = False
            continue
        if cur is None:
            continue
        field = _REG_FIELD.match(line)
        if field:
            in_members = field.group(1) == "members"
            if field.group(1) in _BUNDLE_FIELDS and not cur[field.group(1)]:
                cur[field.group(1)] = field.group(2).strip()
            continue
        member = _MEMBER_BULLET.match(line)
        if in_members and member:
            cur["members"].append(member.group(1))
    return entries


# --- themes: what the work is ABOUT ------------------------------------------
# `Target:` says where a prompt's code LIVES — a mechanical key (one worktree
# per repo), which made the auto-bundler read as "three things that live in
# autoarray". `Themes:` says what the work is ABOUT, which is the useful
# grouping and is routinely cross-repo. Same list shape as `Repos:`: a bare
# `Themes:` line then `- keyword` bullets, first bullet = the PRIMARY theme.
_LIST_BULLET = re.compile(r"^\s*-\s+(\S.*?)\s*$")


def parse_list_header(text: str, field: str) -> list:
    """The `Repos:` / `Themes:` list header: a bare `Field:` then `- ` bullets.

    Scans only the top of the file — the same window `parse_header` reads — so
    a fenced example deep in a prompt's prose can never declare anything. The
    list closes at the first line that is not a bullet: the header block is
    contiguous by construction (see `_render_header`).
    """
    out, collecting = [], False
    head = re.compile(rf"^{field}:\s*$", re.I)
    for line in text.splitlines()[:30]:
        if head.match(line.strip()):
            collecting = True
            continue
        if not collecting:
            continue
        m = _LIST_BULLET.match(line)
        if not m:
            break
        out.append(m.group(1))
    return out


def _theme_key(value: str) -> str:
    """One `Themes:` bullet normalised to a vocabulary keyword."""
    return value.split("#")[0].strip().strip("`*_").strip().lower()


def parse_theme_list(text: str) -> list:
    """A prompt's `Themes:` keywords — normalised, de-duplicated, order kept.

    Order is the whole signal: the first keyword is the grouping key, the rest
    are packing affinity, so this must never sort.
    """
    out = []
    for raw in parse_list_header(text, "Themes"):
        key = _theme_key(raw)
        if key and key not in out:
            out.append(key)
    return out


# `themes.md` — the Mind's controlled vocabulary for `Themes:`: prose plus one
# `- <keyword>: <meaning>` bullet each, so a human adds a theme by editing one
# markdown list and PyAutoBrain never holds a second copy of it.
_THEME_ENTRY = re.compile(r"^-\s+`?([A-Za-z0-9][A-Za-z0-9._-]*)`?\s*:\s*(\S.*)$")


def parse_themes(mind: Path) -> dict:
    """Parse `<mind>/themes.md` into `{keyword: one-line meaning}`.

    Tolerant like `parse_epics`, with one deliberate consequence: an absent or
    empty file yields `{}`, which DISABLES the unknown-keyword warning rather
    than flagging every keyword in the backlog. A freshly-spawned Mind has no
    vocabulary yet, and a renderer that shouted at all of it would be noise.
    """
    f = Path(mind) / "themes.md"
    if not f.is_file():
        return {}
    out: dict = {}
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _THEME_ENTRY.match(line.strip())
        if m:
            out.setdefault(m.group(1).lower(), m.group(2).strip())
    return out


def unknown_themes(themes: list, vocab: dict) -> list:
    """The keywords a prompt declares that `themes.md` does not know."""
    if not vocab:
        return []
    return [t for t in themes if t not in vocab]


# What a bundle COSTS. One session carries a few independent tasks; the cap is
# what stops a "bundle" becoming a to-do list. Points rather than a count,
# because four small tasks and one large one are not the same session:
# small=1, medium=2, large=4 — and cap 8, which is exactly the two shapes the
# design names (1 large + 3 small = 7; 4 medium = 8) and nothing bigger. At
# most one large member, so the cap can never be spent on two of them.
# Unknown difficulty (`-`, the headerless prompts) counts as medium: the middle
# estimate, never the free one.
BUNDLE_SIZE_POINTS = {"small": 1, "medium": 2, "large": 4}
BUNDLE_UNKNOWN_POINTS = 2
BUNDLE_POINT_CAP = 8
BUNDLE_MAX_MEMBERS = 4
BUNDLE_MAX_LARGE = 1
BUNDLE_MIN_MEMBERS = 2

# How many AUTO bundles reach the page. Same rule as PICK_LIST_MAX below and
# for the same reason: a section is read to be picked from, and one card per
# repo in the Mind is an inventory, not a pick list. Pinned bundles are never
# capped — a human put them there. The cut is ranked, not arbitrary (see
# `bundle_cards`), and the footer says what was left off and how to keep it.
BUNDLE_LIST_MAX = 8


def _bundle_points(rows: list) -> int:
    """A bundle's total size in points (see BUNDLE_SIZE_POINTS)."""
    return sum(BUNDLE_SIZE_POINTS.get(r.get("difficulty", "-"),
                                      BUNDLE_UNKNOWN_POINTS) for r in rows)


def _auto_excluded(r: dict, pinned: set) -> str:
    """Why a draft prompt cannot join an AUTO bundle — `''` when it can.

    A bundle is worked with the members running as independent, mostly
    unattended subagent tasks, so anything that is not independently startable
    stays out: epic members (worked in phase order through their epic), a
    prompt a human already pinned or headed `Bundle:` (it belongs to that
    bundle, not to a computed one), a declared `Blocked-by:` gate, a task whose
    autonomy says a human must drive it, and `too-large` work that is a session
    on its own. `Blocked-by:` reads as UNRESOLVED here whatever GitHub says:
    this renderer never makes a network call (it runs bare in PyAutoMind's
    `dashboard_refresh.yml`), and proposing a gated task is the more expensive
    mistake. A prompt with no target folder (`-`) cannot be grouped by repo at
    all, so it is not proposed either.
    """
    if r.get("epic"):
        return "epic member"
    if r["path"] in pinned or r.get("bundle"):
        return "pinned"
    if (r.get("header") or {}).get("blocked-by"):
        return "blocked-by"
    if r.get("autonomy") == "human-required":
        return "human-required"
    if r.get("difficulty") == "too-large":
        return "too-large"
    if r.get("target", "-") == "-":
        return "no target"
    return ""


def _jaccard(a: list, b: list) -> float:
    """Keyword overlap of two theme lists; 0.0 when either side is empty."""
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def _pool_key(r: dict) -> tuple:
    """The auto-bundler's grouping key: PRIMARY THEME, else `Target`.

    `("theme", <first Themes: bullet>)` when the prompt declares one — the
    topical key, and cross-repo by design. `("target", <folder>)` otherwise,
    which is exactly what the bundler keyed on before themes existed, so an
    un-themed backlog groups unchanged. Every prompt has exactly one key, so
    it lands in at most one auto bundle.
    """
    themes = r.get("themes") or []
    return ("theme", themes[0]) if themes else ("target", r["target"])


def _pack_by_affinity(rows: list) -> list:
    """Pack one pool into bundles under the size caps, by keyword affinity.

    Seed with the most pickable member (priority, then path); then repeatedly
    add whichever remaining candidate that still FITS shares the most keywords
    with the seed (Jaccard over the whole `Themes:` list), ties broken by
    priority, then by sharing the seed's repo, then by path. When nothing fits,
    the bundle closes and the next seeds from what is left — so a large pool
    splits by what the work is about rather than by filename order.

    Not "close the pack at the first thing that does not fit": a candidate that
    is too big is skipped, not terminal, or two large tasks in a row would
    leave the first alone in a pack of one (which is then dropped — the
    highest-priority member of the pool, silently missing from the page).

    With no themes anywhere every overlap is 0.0 and the tie-breaks reduce to
    priority-then-path, which is the first-fit pass this replaced, member for
    member.
    """
    rest = sorted(rows, key=lambda r: (PRIORITY_RANK.get(r["priority"], 9),
                                       r["path"]))
    packs = []
    while rest:
        seed, rest = rest[0], rest[1:]
        pack = [seed]
        points = BUNDLE_SIZE_POINTS.get(seed["difficulty"], BUNDLE_UNKNOWN_POINTS)
        large = 1 if seed["difficulty"] == "large" else 0
        while True:
            best, best_i = None, -1
            for i, r in enumerate(rest):
                cost = BUNDLE_SIZE_POINTS.get(r["difficulty"],
                                              BUNDLE_UNKNOWN_POINTS)
                is_large = 1 if r["difficulty"] == "large" else 0
                if (points + cost > BUNDLE_POINT_CAP
                        or len(pack) >= BUNDLE_MAX_MEMBERS
                        or large + is_large > BUNDLE_MAX_LARGE):
                    continue
                rank = (-_jaccard(seed.get("themes") or [],
                                  r.get("themes") or []),
                        PRIORITY_RANK.get(r["priority"], 9),
                        0 if r["target"] == seed["target"] else 1,
                        r["path"])
                if best is None or rank < best:
                    best, best_i = rank, i
            if best_i < 0:
                break
            r = rest.pop(best_i)
            pack.append(r)
            points += BUNDLE_SIZE_POINTS.get(r["difficulty"],
                                             BUNDLE_UNKNOWN_POINTS)
            large += 1 if r["difficulty"] == "large" else 0
        packs.append(pack)
    return packs


def _shared_secondaries(pack: list, primary: str) -> list:
    """The keywords EVERY member of a pack carries, minus the primary theme.

    Ordered by the seed's own list, because that is the order a human wrote
    and the only one that is not an alphabetisation of somebody's tags.
    """
    shared = set.intersection(*[set(m.get("themes") or []) for m in pack])
    return [t for t in (pack[0].get("themes") or [])
            if t != primary and t in shared]


def _theme_title(theme: str, pack: list, n: int) -> str:
    """`mge · jax-gradient` — the primary theme plus what every member shares.

    Numbered only from the second bundle of a pool onwards: a bundle is picked
    BY NAME (the title rides in the copied prompt), so two cards may not carry
    the same one, but the common single-bundle pool should read as its theme
    and nothing else.
    """
    title = " · ".join([theme] + _shared_secondaries(pack, theme))
    return title if n == 1 else f"{title} — bundle {n}"


def _unknown_in(rows: list) -> list:
    """Every `Themes:` keyword a card's members carry that `themes.md` lacks."""
    out = []
    for r in rows:
        for t in r.get("unknown_themes") or []:
            if t not in out:
                out.append(t)
    return sorted(out)


def auto_bundles(c: dict) -> list:
    """Propose bundles from the backlog — deterministic, and render-only.

    Never written back to `bundles.md`: only human pins are persisted, so the
    nightly re-render commits no churn and a proposal that stops making sense
    simply stops being proposed. Same input -> same output, always.

    Prompts are pooled by `_pool_key` — primary theme when they declare one,
    target repo when they do not — and each pool is packed by `_pack_by_affinity`
    under the size cap. A pack of one is not a bundle, so it is dropped rather
    than shown.
    """
    pinned = {m for b in (c.get("bundles") or []) for m in b["members"]}
    groups: dict = {}
    for r in c.get("records") or []:
        if not _auto_excluded(r, pinned):
            groups.setdefault(_pool_key(r), []).append(r)
    out, used = [], {}
    # Pools sort by their key TEXT, theme and target alike, so a mixed backlog
    # interleaves alphabetically rather than listing every theme before every
    # repo — and a Mind with no themes at all keeps exactly its old order.
    for kind, key in sorted(groups, key=lambda k: (k[1], k[0])):
        for pack in _pack_by_affinity(groups[(kind, key)]):
            if len(pack) < BUNDLE_MIN_MEMBERS:
                continue
            # Numbered per KEY TEXT rather than per pool, so a theme and a
            # target that happen to share a name cannot mint the same slug.
            used[key] = n = used.get(key, 0) + 1
            out.append({
                "slug": f"auto-{key}-{n}",
                # Numbered, not described: two proposals over the same repo
                # would otherwise carry the same name on the page and in the
                # copied prompt, and a bundle is picked by name.
                "title": (_theme_title(key, pack, n) if kind == "theme"
                          else f"{key} — bundle {n}"),
                "origin": "auto", "pool": kind,
                "theme": key if kind == "theme" else "",
                "target": key if kind == "target" else "",
                "members": pack, "rationale": "", "status": "",
                "unknown": False, "unknown_themes": _unknown_in(pack),
                "points": _bundle_points(pack),
            })
    return out


def bundle_prompt(b: dict) -> str:
    """The one-tap orchestration prompt: run this whole bundle in one session.

    A procedure, not a snapshot — like `_epic_prompt`, everything that could go
    stale (issue numbers, branch names, who is left) is worked out by the
    session from the member prompts themselves. The contract it states is the
    `start_bundle` skill's, in short form: one issue per member (the no-bulk-
    issue rule still holds), one shared worktree per repo, per-task PRs so
    `/prm` closes each member out unchanged.
    """
    members = [m["path"] for m in b["members"]]
    L = [f"You are the architect (Fable) for the PyAutoMind bundle "
         f"'{b.get('title') or b['slug']}' — {len(members)} INDEPENDENT tasks "
         "run in one orchestrated session.",
         "",
         "Members:"]
    L += [f"- {p}" for p in members]
    if b.get("rationale"):
        L += ["", f"Why they are bundled: {b['rationale']}"]
    L += [
        "",
        "Contract (the `start_bundle` skill is the full body):",
        "1. Read each member prompt above in full, and plan all of them "
        "before editing anything. The members are independent — if any turns "
        "out to depend on another, say so and drop it from the bundle.",
        "2. Run `/start_dev <member prompt>` for EACH member: one plan, one "
        "issue, one registry entry per member. Never file them as a bulk "
        "issue queue and never merge them into one issue.",
        "3. One shared worktree per repo, not one per member: run "
        "`/start_library` (or `/start_workspace`) once, naming the bundle as "
        "the task and listing every member's repos. A worktree holds one "
        "branch at a time, so inside it members are worked one at a time, "
        "each on its own `feature/<member-task>` branch cut from "
        "`origin/main`; members in different repos may run in parallel.",
        "4. Delegate the implementation of each member to an Opus subagent "
        "via the Agent tool (`Agent(model=\"opus\", …)`), one subagent per "
        "member, with the member's issue plan, the worktree path and the "
        "branch to use. You plan, judge and talk to the user; the subagents "
        "edit, test and report back.",
        "5. Ship each member on its own: `/ship_library` or "
        "`/ship_workspace`, ONE PR per task, so `/prm` closes each member out "
        "unchanged. Never one PR for the bundle.",
        "6. Report per member: issue, branch, PR, and pass/fail counts.",
    ]
    return "\n".join(L)


def bundle_cards(c: dict) -> list:
    """Every bundle the page renders: pinned first (registry order), then auto.

    One place computes this so `render_dashboard` and its HTML twin cannot
    drift apart. Pinned members are prompt paths in `bundles.md` plus any
    prompt whose own header says `Bundle: <slug>`; a path that resolves to no
    filed prompt still renders (as itself), because a bundle naming a prompt
    that has moved is exactly the drift worth seeing. A `Bundle:` slug that is
    in no registry entry gets its own card flagged `unknown` — the same
    loud-not-silent treatment an unregistered `Epic:` gets.

    Auto bundles are then RANKED and capped at `BUNDLE_LIST_MAX`: most urgent
    member first (a bundle is only as pickable as its most urgent task), then
    the biggest session, then slug as a stable tie-break. Ranking before
    cutting is the whole point — an alphabetical cut would show whichever
    repos sort early rather than whichever sessions are worth running.
    """
    by_path = {r["path"]: r for r in c.get("records") or []}
    declared: dict = {}
    for r in c.get("records") or []:
        if r.get("bundle"):
            declared.setdefault(r["bundle"], []).append(r)

    def _resolve(paths):
        rows = []
        for p in paths:
            rows.append(by_path.get(p) or {
                "path": p, "title": p, "difficulty": "-", "priority": "-",
                "status": "-", "work_type": "-", "target": "-",
                "autonomy": "-", "missing": []})
        return rows

    cards = []
    for b in c.get("bundles") or []:
        rows = _resolve(b["members"])
        seen = {r["path"] for r in rows}
        rows += sorted((r for r in declared.get(b["slug"], [])
                        if r["path"] not in seen), key=lambda r: r["path"])
        cards.append({**b, "members": rows, "unknown": False,
                      "unknown_themes": _unknown_in(rows),
                      "points": _bundle_points(rows)})
    known = {b["slug"] for b in c.get("bundles") or []}
    for slug in sorted(s for s in declared if s not in known):
        rows = sorted(declared[slug], key=lambda r: r["path"])
        cards.append({"slug": slug, "title": slug, "origin": "pinned",
                      "members": rows, "rationale": "", "status": "",
                      "unknown": True, "unknown_themes": _unknown_in(rows),
                      "points": _bundle_points(rows)})
    auto = auto_bundles(c)
    ranked = sorted(auto, key=lambda b: (
        min(PRIORITY_RANK.get(m.get("priority", "-"), 9) for m in b["members"]),
        -b["points"], b["slug"]))
    shown = ranked[:BUNDLE_LIST_MAX]
    for b in shown:
        # What the footer needs, carried on the cards rather than recomputed:
        # both renderers ask the same question and must give the same answer.
        b["auto_total"] = len(auto)
    return cards + shown


def _bundle_footer(cards: list) -> str:
    """`Showing 8 of 20 auto bundles …` — `''` when nothing was left off.

    A cut is only honest if the page says it happened, and pinning is the
    answer to "but I wanted that one", so the line carries both.
    """
    shown = [b for b in cards if b["origin"] == "auto"]
    total = max((b.get("auto_total", 0) for b in shown), default=0)
    if total <= len(shown):
        return ""
    return (f"Showing {len(shown)} of {total} auto bundles — pin one in "
            "`bundles.md` to keep it on the page.")


def _bundle_head(b: dict) -> str:
    """A bundle card's summary line: name, size, where it came from."""
    origin = "auto — proposed" if b["origin"] == "auto" else "pinned"
    head = (f"<b>{_summary_label(b.get('title') or b['slug'])}</b> — "
            f"{len(b['members'])} task(s) · {b['points']} pts · {origin}")
    if b.get("status"):
        head += f" — {_summary_label(_clip(b['status']))}"
    return head


BUNDLE_TABLE_HEAD = ["| Prompt | Difficulty | Priority | Status |",
                     "|--------|------------|----------|--------|"]

# A theme-keyed bundle is cross-repo by design, so its members must say WHERE
# each task lives. A target-keyed (fallback) or pinned card does not get the
# column: every row would carry the same value, and a constant column is noise.
BUNDLE_TABLE_HEAD_REPO = ["| Prompt | Repo | Difficulty | Priority | Status |",
                          "|--------|------|------------|----------|--------|"]

BUNDLE_BLURB = (
    "Sets of INDEPENDENT tasks that make sense in one orchestrated session: "
    "an architect session plans them, subagents implement them, and every "
    "member still gets its own issue and its own PR — so `/prm` closes each "
    "one out unchanged. Not an epic: nothing here is ordered or phase-gated, "
    "and every member also appears in its usual section above — a bundle is "
    "an extra view of the backlog, never a replacement. Pinned bundles "
    "are the human record in `bundles.md`; auto bundles are recomputed "
    "from the backlog every time this page is rendered and are proposals, "
    "never records.")

BUNDLE_RUN_LABEL = ("<b>Run this bundle</b> — one session, one issue and one "
                    "PR per member")


def _bundle_rows_md(b: dict) -> list:
    """A bundle's members as a table: what each one costs and where it stands.

    The page's other lists are rows-not-tables because a 133-row backlog has to
    read on a phone (`_bullet`); a bundle has at most four members, and the
    question here is not "which do I pick?" but "what am I taking on in one
    session?" — which is a comparison, and comparisons are tables.
    """
    repo = b.get("pool") == "theme"
    rows = list(BUNDLE_TABLE_HEAD_REPO if repo else BUNDLE_TABLE_HEAD)
    for r in b["members"]:
        link = f"<a href=\"{r['path']}\">{_summary_label(_clip(r['title'], 70))}</a>"
        cells = [_cell(link)]
        if repo:
            cells.append(_cell(_summary_label(r.get("target", "-"))))
        cells += [_cell(r.get("difficulty", "-")), _cell(r.get("priority", "-")),
                  _cell(_summary_label(_clip(r.get("status", "-"), 40)))]
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def _bundle_section(cards: list) -> list:
    """The `## Bundles` section of `dashboard.md`."""
    L = ["## Bundles", "",
         BUNDLE_BLURB + " Full record in [`bundles.md`](bundles.md).", ""]
    for b in cards:
        head = _bundle_head(b)
        if b.get("unknown"):
            head += " — ⚠️ not in `bundles.md`"
        if b.get("unknown_themes"):
            head += (" — ⚠️ theme(s) not in `themes.md`: "
                     + _summary_label(", ".join(b["unknown_themes"])))
        L += ["<details>", f"<summary>{head}</summary>", ""]
        L += _items([_task_row(BUNDLE_RUN_LABEL, bundle_prompt(b))])
        if b.get("rationale"):
            L += ["", _summary_label(b["rationale"])]
        L += [""] + _bundle_rows_md(b) + ["", "</details>", ""]
    footer = _bundle_footer(cards)
    if footer:
        L += [f"_{footer}_", ""]
    return L


# Bundle members render as a real table on the Pages twin, and the shared board
# theme styles only `table.recent` — so the rule travels with the section
# rather than with the page head, which keeps the head byte-identical on a Mind
# that has no bundles at all.
_BUNDLE_CSS = """\
table.bundle{width:100%;border-collapse:collapse;font-size:.95em;
 margin:.1rem 0 .7rem}
table.bundle td,table.bundle th{border-bottom:1px solid var(--line);
 padding:.35rem .5rem;text-align:left}
table.bundle th{color:var(--muted);font-weight:600;font-size:.85em}
table.bundle td.facet{white-space:nowrap;color:var(--muted);font-size:.85em}
"""


def _bundle_section_html(cards: list, blob: str) -> list:
    """The Bundles section of `dashboard.html` — same cards, real copy buttons."""
    H = [f"<style>{_BUNDLE_CSS}</style>",
         f'<p class="muted">{_summary_label(BUNDLE_BLURB)}</p>']
    for b in cards:
        head = _bundle_head(b)
        if b.get("unknown"):
            head += " — ⚠️ not in bundles.md"
        if b.get("unknown_themes"):
            head += (" — ⚠️ theme(s) not in themes.md: "
                     + _summary_label(", ".join(b["unknown_themes"])))
        H += ["<details>", f"<summary>{head}</summary>",
              _html_task(BUNDLE_RUN_LABEL, bundle_prompt(b))]
        if b.get("rationale"):
            H.append(f'<p class="muted">{_summary_label(b["rationale"])}</p>')
        repo = b.get("pool") == "theme"
        H += ['<table class="bundle">',
              "<tr><th>Prompt</th>" + ("<th>Repo</th>" if repo else "")
              + "<th>Difficulty</th><th>Priority</th>"
              "<th>Status</th></tr>"]
        for r in b["members"]:
            H += ["<tr>",
                  f'<td><a href="{_attr(blob + r["path"])}">'
                  f'{_summary_label(_clip(r["title"], 70))}</a></td>']
            if repo:
                H.append('<td class="facet">'
                         f'{_summary_label(r.get("target", "-"))}</td>')
            H += [
                  f'<td class="facet">{_summary_label(r.get("difficulty", "-"))}</td>',
                  f'<td class="facet">{_summary_label(r.get("priority", "-"))}</td>',
                  f'<td class="facet">'
                  f'{_summary_label(_clip(r.get("status", "-"), 40))}</td>',
                  "</tr>"]
        H += ["</table>", "</details>"]
    footer = _bundle_footer(cards)
    if footer:
        H.append(f'<p class="muted">{_summary_label(footer)}</p>')
    return H


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
               "found": "found", "review": "flagged for review"}


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
    # Flagging a task for review IS an event on the work in hand, and it hands
    # out its own payload rather than a `/start_dev` (there is nothing to start).
    for r in c.get("human_review") or []:
        if r.get("date"):
            events.append({"date": r["date"], "event": "review",
                           "title": r["title"], "path": r["path"],
                           "payload": _review_payload(r)})
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
    records, hygiene, drift, theme_flags = [], [], [], []
    witness_flags = []
    # `human_review/` prompts are collected apart from the backlog: they are not
    # work to pick up, they are shipped work waiting on a person. Keeping them
    # out of `records` keeps them out of the pick lists, the work-type sections,
    # the bundler, the epics and the backlog count in one move.
    reviews = []
    vocab = parse_themes(mind)
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
            themes = parse_theme_list(text)
            stray = unknown_themes(themes, vocab)
            try:
                phase = int(header.get("phase", ""))
            except ValueError:
                phase = None
            (reviews if wt == HUMAN_REVIEW else records).append({
                "path": str(rel),
                "work_type": wt,
                # Only human_review rows read this; for a backlog prompt the
                # date's event is "filed", which `recent_events` supplies.
                "event": "review" if wt == HUMAN_REVIEW else "",
                # Folder after the work-type = target repo/domain (authoritative
                # — a header Target: is free prose and must not override the
                # taxonomy). rel is draft/<work-type>/<target>/<name>.md.
                "target": rel.parts[2] if len(rel.parts) > 3 else "-",
                "title": _title(text),
                "difficulty": header.get("difficulty", "-"),
                "autonomy": header.get("autonomy", "-"),
                # The review-cost model (sizing faculty). `witness` is the only
                # one that can be genuinely absent on a graded prompt — nothing
                # derives it — and its absence is what makes the prompt `judge`.
                "consequence": header.get("consequence", "-"),
                "witness": header.get("witness", ""),
                "review_minutes": header.get("review-minutes", "-"),
                "unattended": header.get("unattended", "-"),
                # Where it can run. Absent means `any` — the common case, and a
                # missing lane must never be read as "nowhere".
                "lane": header.get("lane", "any"),
                "priority": header.get("priority", "-"),
                "status": header.get("status", "-"),
                "epic": header.get("epic", ""),
                "phase": phase,
                # Bundle membership a human PINNED in the prompt itself; auto
                # bundles never write here (see `auto_bundles`).
                "bundle": header.get("bundle", ""),
                # What the work is ABOUT (`themes.md` vocabulary); the first
                # keyword is the auto-bundler's grouping key.
                "themes": themes,
                "unknown_themes": stray,
                # `Filed:` normally; `Issued:` only on a prompt that has been
                # issued and moved back, which is still the later event.
                "date": _header_date(header),
                "header": header,
                "missing": missing,
            })
            if len(missing) == len(HEADER_FIELDS):
                hygiene.append(f"{rel} — no metadata header (pre-dates intake)")
            if not header.get("witness"):
                witness_flags.append(str(rel))
            if stray:
                theme_flags.append(f"{rel} — unknown theme keyword(s): "
                                   + ", ".join(stray))
            if wt == HUMAN_REVIEW:
                # The drift checks below read "this body names a merged PR /
                # calls itself shipped, so the prompt should have advanced".
                # For a human review both are the premise, not drift: the work
                # shipped, and the prompt exists to have someone check it.
                continue
            if _FIX_PR_RE.search(text):
                drift.append(f"{rel} — body records a fix PR, but the prompt "
                             "never left draft/ (reconcile its lifecycle)")
            elif _done_status(header):
                drift.append(f"{rel} — its own `Status:` says "
                             f"{_done_status(header)}, but the prompt never "
                             "left draft/ (reconcile its lifecycle)")

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
        # Shipped work a human asked to check — never part of `records`, so
        # never part of the backlog count above (see the collection loop).
        "human_review": sorted(reviews, key=_pick_key),
        "in_flight": in_flight,
        "epics": parse_epics(mind / "epics.md"),
        "bundles": parse_bundles(mind / "bundles.md"),
        "theme_vocab": vocab,
        "theme_flags": theme_flags,
        "witness_flags": witness_flags,
        "parked": parked,
        "planned": planned,
        "hygiene": hygiene,
        "drift": drift,
        # Render-only, and never fatal: a Mind with no Cortex beside it draws
        # no badge and says nothing about it.
        "cortex_gates": cortex_gates(mind),
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


# --------------------------------------------------------- the Cortex badge ---
# A development task that a science phase is gated on has a second reader
# waiting on it, and nothing on this page said so: the Cortex's own board knows
# which issues it is waiting for, but the person choosing what to work on reads
# the Mind's. So the in-flight rows carry a badge naming the phase they gate.
#
# Render-only, and deliberately cheap: no new import (`_intake` already
# hard-fails without a Mind checkout; it must not also require a Cortex one),
# no schema of the Cortex's beyond two lines of its phase header, and an absent
# or unreadable Cortex is silence rather than an error.
CORTEX_REPO = "PyAutoCortex"
CORTEX_HEADER_LINES = 30  # PyAutoCortex/scripts/cortex.py HEADER_LINES

#: A local copy of `PyAutoCortex/scripts/cortex.py:105-108` GATE_REF_RE (itself
#: a copy of `PyAutoMind/scripts/lifecycle.py`'s). The lookbehind is what
#: rejects `owner/Repo#N` — another owner is spelled as a URL.
CORTEX_GATE_REF_RE = re.compile(
    r"https://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)"
    r"|(?<![\w/])([A-Za-z_][\w.]*)#(\d+)\b"
)


def _cortex_root(mind: Path):
    """`$PYAUTO_CORTEX`, then beside the Mind. `None` when there is none."""
    env = os.environ.get("PYAUTO_CORTEX", "").strip()
    for candidate in ([Path(env).expanduser()] if env else
                      []) + [mind.parent / CORTEX_REPO]:
        if (candidate / "phases").is_dir():
            return candidate
    return None


def _issue_url(url: str) -> str:
    """The canonical issues URL — a PR *is* an issue, as the Cortex grades it."""
    return re.sub(r"/pull/(\d+)$", r"/issues/\1", (url or "").strip())


def cortex_gates(mind: Path) -> dict:
    """`{issue url: [phase rel, …]}` — every Cortex phase gated on an issue.

    The short `Repo#N` form takes its owner from the Mind's own `repos.yaml`
    (through `_mind_home`), never from a literal: a fork's Mind and its Cortex
    carry the same owner, and organ code names no tenant.
    """
    root = _cortex_root(mind)
    if root is None:
        return {}
    home = _mind_home(mind)
    owner = home.split("/")[3] if home.count("/") >= 4 else ""
    out: dict = {}
    try:
        files = sorted((root / "phases").rglob("*.md"))
    except OSError:
        return {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            rel = f.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        value = ""
        for line in text.split("\n")[:CORTEX_HEADER_LINES]:
            if line.startswith("## "):  # the header block is over
                break
            m = re.match(r"^Gates:(?:[ \t]+(.*?))?[ \t]*$", line)
            if m:
                value = m.group(1) or ""
                break
        for token in (t.strip() for t in value.split(",")):
            m = CORTEX_GATE_REF_RE.fullmatch(token) if token else None
            if not m:
                continue
            org, repo, num, short_repo, short_num = m.groups()
            if org:
                url = f"https://github.com/{org}/{repo}/issues/{num}"
            elif owner:
                url = f"https://github.com/{owner}/{short_repo}/issues/{short_num}"
            else:
                continue
            out.setdefault(url, []).append(rel)
    return out


def _gated_phases(c: dict, row: dict) -> list:
    """The Cortex phases this in-flight row gates, in file order."""
    issue = _issue_url(row.get("issue", ""))
    return (c.get("cortex_gates") or {}).get(issue, []) if issue else []


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


# --- human review -------------------------------------------------------------
# `human_review/` prompts are the one section of the page that is not work to
# start. The task already shipped; what is outstanding is a person reading it
# and saying it is sound. So its 📋 hands out a read-and-report prompt rather
# than a `/start_dev`, and it ends by naming both exits — sign off (retire the
# prompt) or don't (file the follow-up) — because a review that stops at
# "looks fine" leaves the row on the board forever.
HUMAN_REVIEW_BLURB = (
    "Shipped work waiting on **you** — tasks a human asked to check before "
    "calling them done. Nothing lands here on its own: a task only gets a "
    "review row when someone files one (`/intake` with `Type: human review`), "
    "so an empty section means nothing has been flagged, not that nothing "
    "shipped."
)

HUMAN_REVIEW_PAYLOAD = """\
Walk me through the completed work described in `{path}` so I can sign it off.

1. Read the prompt: what was asked, and what it claims shipped.
2. Find the evidence — the merged PR(s), the commits, the `complete/` record —
   and read the actual diff, not the description of it.
3. Report what changed, what it does NOT cover, and anything you would have
   done differently. Call out behaviour changes and test gaps explicitly.

Change nothing while reviewing. When I sign it off, retire the prompt from the
PyAutoMind checkout (`python3 scripts/lifecycle.py record <slug> --date
<YYYY-MM-DD> --from-file <body> --apply`, then `git rm` the prompt) and
regenerate the dashboard. If I do not sign it off, file the follow-up with
`/intake` instead.
"""


def _review_payload(r: dict) -> str:
    return HUMAN_REVIEW_PAYLOAD.format(path=r["path"])


def _review_head(r: dict) -> str:
    """One human-review row's text — `_bullet`'s shape, minus difficulty.

    Difficulty sizes the work of BUILDING a thing; nothing was built here, so
    it would be noise. The date takes its place: how long a review has been
    waiting is exactly what a human reading this section wants to know.
    """
    facets = " · ".join(_summary_label(x) for x in
                        (r["target"], r["autonomy"], r["priority"]) if x != "-")
    head = f"<a href=\"{r['path']}\">{_summary_label(r['title'])}</a>"
    if facets:
        head += f" — {facets}"
    return head + _dated(r)


# --- freshness banner ----------------------------------------------------------
# The page is only as current as the files it is generated from, and the way it
# goes wrong is asymmetric: `dashboard_refresh.yml` self-heals a stale *render*
# on every push to main, but nothing self-heals a stale *prompt* — a task that
# shipped without its prompt advancing to complete/ keeps rendering as pickable
# backlog until a human reconciles it. So the banner states the generation date
# and hands over the whole reconcile-then-regenerate chore as one copyable
# message, in the same 📋 idiom as every task row.
REFRESH_PAYLOAD = """\
Bring the PyAutoMind dashboard up to date. Work in the PyAutoMind checkout:

1. `git fetch origin && git status`. If behind `origin/main`, `git pull --ff-only`
   before touching anything.
2. `python3 scripts/lifecycle.py check`, `orphans`, and `index --check`. Fix
   whatever drift they report.
3. Reconcile finished work — this is the part nothing automates. For every prompt
   under `draft/` and `active/`, decide whether it is already done: a `Status:`
   header saying shipped/superseded/absorbed, a merged PR named in its body, or a
   record in `complete/` whose scope already covers it (check `complete/index.md`
   and grep the dated buckets). Treat a same-subject record as evidence, not
   proof — read both and confirm the scope really matches before retiring a
   prompt.
4. For each one that IS done, write its record and retire the prompt:
   `python3 scripts/lifecycle.py record <slug> --date <YYYY-MM-DD> --from-file
   <body> --apply`, where <body> ends with `## Original prompt` followed by the
   prompt's full text. Then `git rm` the prompt file and repoint every
   cross-reference to it (grep the slug across `draft/`, `active/`, `epics.md`
   and the registry files).
5. Regenerate the page: `pyauto-brain intake --apply dashboard`. Never hand-edit
   `dashboard.md` or `dashboard.html` — they are generated.
6. Commit and push to `main`, so `dashboard_refresh.yml` agrees with the tree.

Report what you retired, what you deliberately left in the backlog and why, and
anything you could not verify."""

REFRESH_BLURB = (
    "generated from `active/`, `draft/` and the registry files, so it is only "
    "as current as they are. `dashboard_refresh.yml` re-renders it on every "
    "push to `main` — that heals a stale page, but not a stale prompt: a task "
    "that shipped without its prompt advancing to `complete/` keeps rendering "
    "here as pickable backlog. Reconciling those is the refresh below."
)


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


def _fits_a_slot(records: list) -> list:
    """The pick list for a human working in a bounded review slot.

    It replaced "Quick wins" (`difficulty == small and autonomy == safe`), which
    was near-empty: ten prompts in the whole backlog carried `safe`, so the
    surface that exists to hand out unattended work had almost nothing to hand
    out. The two questions that actually matter are different ones — can it
    finish without me, and what will it cost me to review — and the sizing
    faculty now answers both.

    Ordered by review-minutes ASCENDING rather than by priority: this list is
    read when the human has a slot to fill and wants to know what fits in it.
    `Highest priority` above is where importance is answered.
    """
    def cost(r):
        try:
            return int(r.get("review_minutes", "-"))
        except (TypeError, ValueError):
            return 99          # ungraded sorts last, never hidden
    ready = [r for r in records if r.get("unattended") == "ready"]
    return sorted(ready, key=lambda r: (cost(r), _pick_key(r)))


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
        f"> **Last updated {c['generated']}.** This page is {REFRESH_BLURB}",
        "",
        _task_row("<b>Refresh this page</b> — reconcile finished prompts, "
                  "then regenerate", REFRESH_PAYLOAD),
        "",
        "| Where | Count |",
        "|-------|------:|",
        f"| [In flight](#in-flight) (`active/`) | {c['issued_count']} |",
        f"| [Human review](#human-review) (`draft/human_review/`) | "
        f"{len(c.get('human_review') or [])} |",
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
    quick = _fits_a_slot(standalone)
    for title, note, rows in (
        ("Highest priority", "filed as `high`", high),
        ("Fits a slot", "ready to run unattended, cheapest to review first",
         quick),
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
        for rel in _gated_phases(c, r):
            head += f" — ⚠️ gates a Cortex phase → {rel}"
        flight.append(_task_row(head, f"/start_dev {r['path']}"))
    L += _items(flight) or ["- _(nothing in flight)_"]
    L += [""]

    # Directly under In flight: both are live obligations, and a review that
    # sank below the 140-prompt backlog would never be read.
    reviews = c.get("human_review") or []
    L += ["## Human review", "", HUMAN_REVIEW_BLURB, ""]
    L += _items([_task_row(_review_head(r), _review_payload(r))
                 for r in reviews]) or ["- _(nothing awaiting review)_"]
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

    # Bundles read the backlog ABOVE a second way — as sessions rather than
    # as tasks — so they sit directly under it, before the page turns to
    # "what has been happening". Members are not removed from anything above:
    # a bundle is an extra view, never a replacement (unlike an epic).
    cards = bundle_cards(c)
    if cards:
        L += _bundle_section(cards)

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

    # Hygiene is the page's only audit section: what a human should tidy, not
    # what to pick. Each flag class is its own count line + `<details>` list.
    blocks = []
    if c["hygiene"]:
        blocks.append(
            [f"{len(c['hygiene'])} prompt(s) without a metadata header — they "
             "show no facets above. Re-home or re-run intake on them when "
             "touched.", "",
             "<details>", "<summary>Headerless prompts</summary>", ""]
            + [f"- `{h.split(' — ')[0]}`" for h in c["hygiene"]]
            + ["", "</details>"])
    if c.get("witness_flags"):
        n = len(c["witness_flags"])
        blocks.append(
            [f"{n} prompt(s) with no `Witness:` — the machine-checkable claim "
             "that would make the work reviewable in minutes. Absent, a prompt "
             "grades `judge` (a PI's quarter-hour) whatever its size, which is "
             "the intended default and not a bug. Nothing derives or backfills "
             "a witness — an invented one is plausible prose with nothing "
             "behind it — so this is a human writing one, a prompt at a time.",
             "",
             "<details>", "<summary>Prompts with no witness</summary>", ""]
            + [f"- `{w}`" for w in c["witness_flags"][:40]]
            + ([f"- _… and {n - 40} more_"] if n > 40 else [])
            + ["", "</details>"])
    if c.get("theme_flags"):
        blocks.append(
            [f"{len(c['theme_flags'])} prompt(s) with unknown theme "
             "keyword(s) — not in [`themes.md`](themes.md), so they group "
             "loudly rather than silently. Correct the prompt, or add the "
             "keyword to the vocabulary.", "",
             "<details>", "<summary>Unknown theme keywords</summary>", ""]
            + [f"- `{t}`" for t in c["theme_flags"]]
            + ["", "</details>"])
    if blocks:
        L += ["## Hygiene", ""]
        for i, block in enumerate(blocks):
            L += ([""] if i else []) + block

    boards = _board_links(c.get("home", ""))
    if boards:
        L += ["", "Boards: " + " · ".join(f"[{n}]({u})" for n, u in boards)]
    return "\n".join(L).rstrip("\n") + "\n"


# The dashboard-only half of the page script: the shared clipboard
# handler lives in the board theme, this reveals the Recent feed a page
# at a time.
# The freshness banner is a dashboard-only element (no other organ board carries
# one), so its rule lives here rather than in the shared theme.
_FRESH_CSS = """\
.fresh{margin:0 0 1.2rem;padding:.7rem .9rem .4rem;border:1px solid var(--edge);
 border-radius:11px;background:var(--tint)}
.fresh>p{margin:0 0 .3rem}
.fresh .task{border-bottom:0}
"""

_MORE_JS = """\
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


def _md_inline(text: str) -> str:
    """Render the inline markdown this module authors (`code` spans only) as HTML.

    The freshness blurb is written once and rendered on both pages; the markdown
    page takes it verbatim, this turns its backticks into `<code>` and its
    `**bold**` into `<b>` so the HTML twin does not print them literally.
    Deliberately not a markdown parser — it handles exactly the two constructs
    the blurbs this module authors actually use.
    """
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


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
        text = link(r["path"], _summary_label(r["title"])) + pills(
            *(_summary_label(x) for x in (r["target"], r["difficulty"],
                                          r["autonomy"], r["priority"])),
            work_type=r["work_type"])
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
        f"<style>{_theme_css(THEME_ORGAN)}{_FRESH_CSS}</style>",
        "</head>",
        "<body>",
        hero(THEME_ORGAN, "Dashboard",
             "Every task the Mind is holding. Tap a task's 📋 and its "
             "<code>/start_dev</code> command is on your clipboard — paste it "
             "into a Claude Code chat to route Claude straight to that task. "
             '<a href="#recent">Recent</a> is the same work by date — what has '
             "been happening rather than what to do next."),
        # The four numbers a human wants before reading a single row.
        stats((c["issued_count"], "In flight"),
              (len(c.get("human_review") or []), "Human review"),
              (len(c["parked"]), "Parked"),
              (len(c["planned"]), "Planned"), (c["total"], "Backlog")),
    ]
    H += [f'<div class="fresh"><p><b>Last updated {c["generated"]}.</b> '
          f'This page is {_md_inline(REFRESH_BLURB)}</p>',
          _html_task("<b>Refresh this page</b> — reconcile finished prompts, "
                     "then regenerate", REFRESH_PAYLOAD),
          "</div>"]
    if home:
        H.append(f'<p class="muted mdsrc">'
                 f'{link("dashboard.md", "markdown version")} · '
                 f'{link("README.md", "GitHub Page")}</p>')
    if c.get("drift"):
        H += ['<p>⚠️ <b>Needs lifecycle reconciliation</b> — draft prompts '
              "whose body records a fix PR (done, never advanced):</p>", "<ul>"]
        H += [f"<li><code>{_attr(d)}</code></li>" for d in c["drift"]]
        H += ["</ul>"]
    H += ["<h2>Start here</h2>"]

    members = _epic_members(c)
    standalone = [r for r in records if not r.get("epic")]
    high = [r for r in standalone if r["priority"] == "high"]
    quick = _fits_a_slot(standalone)
    for title, note, rows in (
        ("Highest priority", "filed as high", high),
        ("Fits a slot", "ready to run unattended, cheapest to review first",
         quick),
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
        gated = _gated_phases(c, r)
        if gated:
            text += pills(*[(f"gates a Cortex phase → {rel}", "y")
                            for rel in gated])
        H.append(_html_task(text, f"/start_dev {r['path']}"))
    if not c["in_flight"]:
        H.append('<p class="muted">(nothing in flight)</p>')

    reviews = c.get("human_review") or []
    H += ['<a id="human-review"></a>'
          + h2("Human review", "draft/human_review").replace(
              "/blob/main/draft", "/tree/main/draft"),
          f'<p class="muted">{_md_inline(HUMAN_REVIEW_BLURB)}</p>']
    for r in reviews:
        text = link(r["path"], _summary_label(r["title"]))
        text += pills(*(_summary_label(x) for x in
                        (r["target"], r["autonomy"], r["priority"])),
                      work_type=HUMAN_REVIEW)
        if r.get("date"):
            text += f'<span class="facets">{_dated(r)}</span>'
        H.append(_html_task(text, _review_payload(r)))
    if not reviews:
        H.append('<p class="muted">(nothing awaiting review)</p>')

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

    cards = bundle_cards(c)
    if cards:
        H += [h2("Bundles", "bundles.md")] + _bundle_section_html(cards, blob)

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

    footer = boards_footer(dict(_board_links(home)), THEME_ORGAN)
    if footer:
        H.append(footer)
    H += [f"<script>{_THEME_JS}{_MORE_JS}</script>", "</body>", "</html>"]
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
    print(f"Human review:    {len(c.get('human_review') or [])} shipped task(s) "
          "flagged for a human to sign off")
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
    # Same precedence as conception: what the author already stated wins.
    inline, _spans = declared_inline(text)
    header = declared_header(text)
    declared = {k: v for k, v in {
        "difficulty": header["declared_difficulty"] or inline.get("difficulty"),
        "autonomy": header["declared_autonomy"] or inline.get("autonomy"),
        "priority": header["priority"] or inline.get("priority"),
    }.items() if v}
    p = {"text": text, "repos": repos, "words": len(text.split()),
         "target": target, "work_type": work_type,
         "declared_difficulty": declared.get("difficulty")}
    level, _score, factors, _derived = effective_difficulty(p)
    return {
        "type": work_type,
        "target": REPO_DISPLAY.get(tgt, target if target != "-" else "?"),
        "difficulty": level,
        "autonomy": declared.get("autonomy") or infer_autonomy(level, factors),
        "priority": declared.get("priority") or infer_priority(text),
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


# --- literal quotes and named paths (legs 4 and 5) ------------------------------
#: Fence languages whose content is SOURCE, mapped to the file extension it
#: would live in. Deliberately narrow. A prompt quoting a traceback, a pytest
#: summary or a log excerpt writes it in a BARE fence or one tagged `text`, and
#: those lines are absent from every repo by construction — scoring them would
#: make leg 4 fire on every prompt that quotes its own evidence. Requiring an
#: explicit source language is what keeps the absence signal honest.
_FENCE_LANGS = {
    "python": ".py", "py": ".py",
    "bash": ".sh", "sh": ".sh", "shell": ".sh", "zsh": ".sh",
    "yaml": ".yaml", "yml": ".yaml",
    "toml": ".toml", "cfg": ".cfg", "ini": ".cfg",
}
#: A path a prompt names, e.g. `scripts/interferometer/jax_likelihood/mge.py`.
#: The left edge is a lookbehind, NOT `\b`: a word boundary cannot match before
#: a leading dot, so `\b` silently truncated `.github/workflows/release.yml` to
#: `github/workflows/release.yml` — a path that then resolves against no file in
#: the checkout. Dot-directories are exactly where CI recipes live, which is
#: half of what these prompts are about.
_PATH_RE = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:py|pyi|sh|yaml|yml|toml|cfg|txt|ipynb))\b")
#: `PyAutoFit#1473` / `some_workspace#266` — a tracking reference.
_ISSUE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)#(\d{1,5})\b")
#: Mind-internal paths are cross-references between prompts and records, not
#: shared upstream artefacts. Two prompts both citing `draft/…` say nothing.
_MIND_DIRS = ("draft/", "active/", "complete/", "scripts/lifecycle.py")


def _looks_like_source(line: str) -> bool:
    """Is this fenced line plausibly a line OF a source file?

    Length and punctuation only — the discrimination that matters is the fence
    language above, and (for leg 4) that the prompt also names a file which
    actually exists upstream. This just drops fence padding and one-word lines.
    """
    s = line.strip()
    return 8 <= len(s) <= 200 and any(ch in s for ch in "=(){}[]\"':/,")


def _quoted_source_lines(text: str) -> dict:
    """`.ext` -> {literal line, …} for every source-tagged fence in a prompt."""
    out: dict = {}
    inside, ext = False, None
    for line in text.splitlines():
        m = re.match(r"^\s*```+\s*([A-Za-z0-9_+.-]*)\s*$", line)
        if m:
            inside, ext = (False, None) if inside else (
                True, _FENCE_LANGS.get(m.group(1).lower()))
            continue
        if inside and ext and _looks_like_source(line):
            out.setdefault(ext, set()).add(line.strip())
    return out


def _named_paths(text: str, mind_internal: bool = False) -> set:
    """Source paths a prompt names. Mind-internal paths dropped by default."""
    found = set(_PATH_RE.findall(text))
    if mind_internal:
        return found
    return {f for f in found if not any(f.startswith(d) for d in _MIND_DIRS)}


#: Files under `draft/` that describe a folder's prompts rather than being one.
_INDEX_NAMES = ("README.md", "index.md", "AGENTS.md")


def _indexed_together(mind: Path, a: str, b: str, base_a: str, base_b: str) -> bool:
    """Does an index in these prompts' common folder name them both?"""
    folder = a.rsplit("/", 1)[0]
    if folder != b.rsplit("/", 1)[0]:
        return False
    for name in _INDEX_NAMES:
        f = mind / folder / name
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if base_a in text and base_b in text:
            return True
    return False


def _qualified_path(path: str) -> bool:
    """Is this path specific enough to be evidence that two prompts share work?

    A bare basename is not. `start_here.py` and `modeling.py` are workspace-wide
    conventions repeated across hundreds of example folders — a prompt naming
    one has said nothing about which work it is. Requiring a directory component
    is what separates `interferometer/jax_likelihood/mge.py` (one file in one
    repo) from `mge.py` (dozens). `X.py` and friends are prose placeholders.
    """
    return "/" in path and len(Path(path).stem) > 2


def _issue_refs(text: str) -> set:
    """`{'PyAutoFit#1473', …}`, repo name normalised so `#1473` alone is ignored."""
    return {f"{normalise_repo(repo)}#{num}" for repo, num in _ISSUE_RE.findall(text)}


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

# --- leg 4: the absence signal --------------------------------------------------
# Leg 3 above tests PRESENCE — "the prompt names things that exist upstream" —
# and that is structurally blind to the shape that motivated this leg.
# `smoke_install_stale_jax_pin.md` shipped on 2026-08-23 (a workspace-test
# repo, issue #266 / PR #268) with NO Mind-side trace at all: no active.md
# entry, no active/ move, no complete/ record. It kept rendering as pickable
# backlog and was re-picked four days later. Both guards were run against it
# directly and both passed it: `lifecycle.py check` (its invariant is about
# active.md slugs, and a task that skips Mind state is in neither place) and
# `intake reconcile maintenance/ci --repo <that repo>`, pointed straight at it —
# 0 suspects of 132 scanned. It named `smoke_install.sh`, which still exists, so
# presence said nothing.
#
# The defect it described was an ABSENCE. It quoted a literal line —
# `pip install "jax<0.7" "jaxlib<0.7"` — and that line is GONE upstream. A
# backlog prompt quoting a source line that no longer exists in a file it names
# is close to a proof the work shipped.
#
# Three filters keep it from firing on every prompt that quotes its own
# evidence, and all three must hold:
#
#   1. the fence carries an explicit SOURCE language (_FENCE_LANGS). A quoted
#      traceback, pytest summary or log excerpt goes in a bare or `text` fence,
#      and those are absent from every repo by construction.
#   2. the prompt names a file that EXISTS upstream with that extension. Without
#      an anchor the question "absent from what?" has no answer.
#   3. the line is absent from the WHOLE tree, not just that file — otherwise a
#      refactor that moved a line reads as a shipped fix.
#
# Like leg 3 it feeds `upstream_score`, never `score`: a quoted line can vanish
# for reasons other than the prompt shipping (an unrelated refactor, a reworded
# quote), so it ranks for review and never retires.
_W_QUOTE_ABSENT = 4.0   # per absent quoted line. Above _W_UPSTREAM (1.5): the
                        # prompt's own argument is that absence is the stronger
                        # evidence, and the ordering inside `needs-review`
                        # should say so. Still below _W_SHIPPED (7.0), which is
                        # a Mind-local band this leg must never reach.

# --- leg 5: duplicate candidates ------------------------------------------------
# Every signal above scores a prompt against the completion ARCHIVE. Nothing
# scored the live prompts against EACH OTHER, and near-duplicate filings are a
# standing hazard of a backlog this size that several independent sessions file
# into.
#
# Measured case: `bug/workspaces/jax_likelihood_pins_stale_by_1e4.md` (filed
# 08-14) and `bug/autolens/jax_likelihood_smoke_pins_stale.md` (filed 08-19) —
# same three scripts, same failing smoke gate, written five days apart by
# sessions that did not know about each other. The 08-19 copy was verified and
# retired on 08-26; the 08-14 copy kept rendering as pickable backlog until a
# drift audit found it on 08-27. No guard saw it: neither was ever `active/`, so
# no lifecycle invariant applied, and reconcile compares prompt text to RECORD
# text — the record covering it carried the twin's words, not its own.
#
# Shared upstream file paths are the load-bearing signal: two prompts naming the
# same source files are almost never independent work. Identifiers and issue
# references corroborate. Mutual reference is the precision filter — a phased
# parent and its child name each other, and that is a series, not a duplicate.
_W_DUP_PATH = 4.0       # per shared upstream source path
_W_DUP_IDENT = 1.0      # per shared rare identifier
_W_DUP_ISSUE = 2.0      # per shared tracking reference
_DUP_THRESHOLD = 8.0
#: An identifier this many live prompts or more name is backlog vocabulary.
_DUP_IDENT_COMMON = 4
#: Ditto for paths — and this one is load-bearing. Measured on the 2026-08-27
#: backlog (134 prompts): scoring every shared path flagged 36 pairs, and the
#: noise was almost entirely BARE BASENAMES. `start_here.py`, `modeling.py`,
#: `simulator.py`, `no_run.yaml`, `smoke_tests.txt` are workspace-wide filenames
#: that dozens of unrelated prompts name; two prompts sharing `start_here.py`
#: share a convention, not a task. Same discrimination `_TOKEN_COMMON_DF` and
#: `_IDENT_COMMON_DF` already make against the records.
_DUP_PATH_COMMON = 4


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


_QUOTE_SUFFIXES = (".py", ".pyi", ".sh", ".yaml", ".yml", ".toml", ".cfg")


def _check_quotes(root: Path, named: set, quoted: dict) -> dict:
    """Leg 4: which lines a prompt quotes are GONE from the files it names.

    `named` are path fragments the prompt mentions; `quoted` is
    `{'.ext': {line, …}}` from its source-tagged fences. Returns
    `{"files": [rel, …], "absent": [(line, rel), …]}` — `files` is the anchor
    (the named paths that actually exist upstream), `absent` the lines that
    occur in NONE of them and nowhere else in the tree either.

    A line found elsewhere in the tree is reported as neither: it moved, and a
    moved line is a refactor, not a shipped fix.
    """
    resolved: dict = {}
    for cand in sorted(named):
        if len(resolved) >= 12:            # a prompt naming more is a survey
            break
        for f in root.rglob("*"):
            if not f.is_file() or ".git" in f.parts:
                continue
            if f.as_posix().endswith("/" + cand) or f.name == cand:
                resolved[cand] = f
                break
    if not resolved:
        return {"files": [], "absent": []}

    # One read of each resolved file, plus one lazy pass over the tree only for
    # the lines that were not found in them.
    bodies = {}
    for cand, f in resolved.items():
        try:
            bodies[cand] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            bodies[cand] = ""

    missing: dict = {}
    for ext, lines in quoted.items():
        anchors = {c: b for c, b in bodies.items()
                   if Path(c).suffix == ext}
        if not anchors:
            continue                        # nothing of that kind was named
        gone = {ln for ln in lines
                if not any(ln in b for b in anchors.values())}
        # THE ANCHOR MUST BE CORROBORATED. If not one of the lines this prompt
        # quotes for `ext` is present in the file(s) it names, the anchor is
        # unproven and absence means nothing — measured against the live backlog,
        # this is what separates the signal from its two loudest false positives:
        #
        #   * PROPOSED code. `einstein_radius_jit_native_seed_finder.md` quotes
        #     23 lines of a JAX-native seed finder it wants WRITTEN. All 23 are
        #     absent because none has ever existed, and it scored higher than
        #     every true positive.
        #   * The WRONG REPO. A prompt read against a repo it is not about
        #     quotes lines absent from it by construction.
        #
        # One quoted line still present proves the prompt is talking about this
        # file, in this checkout — and then a sibling line's absence is a change
        # that happened. The motivating case passes it exactly: the PyAuto
        # install line is still in `smoke_install.sh`, and the jax pin is gone.
        if len(gone) == len(lines):
            continue
        for line in gone:
            missing[line] = sorted(anchors)[0]
    if missing:
        # Absent from the named file is not enough — the line may have moved.
        for f in root.rglob("*"):
            if not missing:
                break
            if (not f.is_file() or ".git" in f.parts
                    or f.suffix not in _QUOTE_SUFFIXES):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in [ln for ln in missing if ln in text]:
                del missing[line]
    # Two named candidates can resolve to one file (`smoke_install.sh` and
    # `<repo>/.github/scripts/smoke_install.sh` are the same
    # anchor) — report the anchor once.
    return {"files": sorted({f.relative_to(root).as_posix()
                             for f in resolved.values()}),
            "absent": sorted(missing.items())}


class _UpstreamReader:
    """The `--repo` seam: identifier presence (leg 3) and quote absence (leg 4).

    Callable for leg 3 so every existing caller and test fake keeps working; leg
    4 hangs off `.quotes`, and `reconcile` probes for it with `getattr`. A fake
    that is a plain lambda therefore exercises leg 3 alone, which is what the
    hermetic tests written before this leg existed expect.
    """

    def __init__(self, root: Path, slug: str = ""):
        self._root = root
        self.slug = slug

    def __call__(self, idents: set) -> dict:
        return _grep_source(self._root, idents)

    def quotes(self, named: set, quoted: dict) -> dict:
        return _check_quotes(self._root, named, quoted)


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
    return _UpstreamReader(root, slug), sha, slug, ""


def duplicate_candidates(mind: Path, records: list, prefix: str = "") -> list:
    """Leg 5: pairs of LIVE prompts that look like the same work filed twice.

    Offline and Mind-local. Scores every unordered pair on the artefacts both
    name — upstream source paths, rare identifiers, tracking references — and
    returns the pairs over `_DUP_THRESHOLD`, strongest first.

    Two filters carry the precision:

      * **Mutual reference disqualifies.** A phased parent and its child name
        each other, as do deliberate siblings; that is a series, and reconcile
        must not offer to merge one. The measured duplicate pair named neither
        the other, which is exactly why it survived.
      * **Rare identifiers only.** An identifier `_DUP_IDENT_COMMON` or more
        live prompts share is backlog vocabulary, the same reasoning `ident_df`
        applies against the records.

    Advisory, like every other reconcile output: merging or retiring a prompt
    stays a human act.
    """
    import itertools

    texts: dict = {}
    for r in records:
        if prefix and not _prefix_match(r["path"], prefix):
            continue
        if r["path"].rsplit("/", 1)[-1] in _INDEX_NAMES:
            continue            # an index is not a filing; it describes them
        try:
            texts[r["path"]] = (mind / r["path"]).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            continue

    ident_pdf: dict = {}
    path_pdf: dict = {}
    feats: dict = {}
    for path, text in texts.items():
        idents = _idents(text)
        named = {f for f in _named_paths(text) if _qualified_path(f)}
        feats[path] = {
            "paths": named,
            "idents": idents,
            "issues": _issue_refs(text),
            "base": path.rsplit("/", 1)[-1],
            "text": text,
        }
        for i in idents:
            ident_pdf[i] = ident_pdf.get(i, 0) + 1
        for f in named:
            path_pdf[f] = path_pdf.get(f, 0) + 1

    out = []
    for a, b in itertools.combinations(sorted(feats), 2):
        fa, fb = feats[a], feats[b]
        # Mutual reference: these two prompts know about each other.
        if fa["base"] in fb["text"] or fb["base"] in fa["text"]:
            continue
        # A DECLARED series knows about itself without any member naming
        # another. `draft/bug/health_fixes/` holds four prompts split out of one
        # health run — they share their failing scripts because they were split
        # by CAUSE, not by script — and the folder's own README.md names all
        # four. That index IS the declaration, and it is the same reasoning
        # leg 1 applies to a record that resolves a folder of prompts as a
        # group. Without it the trio yields three pairs of already-known work.
        if _indexed_together(mind, a, b, fa["base"], fb["base"]):
            continue
        shared_paths = sorted(f for f in fa["paths"] & fb["paths"]
                              if path_pdf.get(f, 0) <= _DUP_PATH_COMMON)
        shared_idents = sorted(i for i in fa["idents"] & fb["idents"]
                               if ident_pdf.get(i, 0) <= _DUP_IDENT_COMMON)
        shared_issues = sorted(fa["issues"] & fb["issues"])
        score = (_W_DUP_PATH * len(shared_paths)
                 + _W_DUP_IDENT * len(shared_idents)
                 + _W_DUP_ISSUE * len(shared_issues))
        if score < _DUP_THRESHOLD:
            continue
        shared = []
        if shared_paths:
            shared.append(("shared-paths", ", ".join(shared_paths[:5])))
        if shared_idents:
            shared.append(("shared-identifiers", ", ".join(shared_idents[:5])))
        if shared_issues:
            shared.append(("shared-issues", ", ".join(shared_issues[:5])))
        out.append({"paths": [a, b], "score": round(score, 2),
                    "shared": [{"kind": k, "evidence": e} for k, e in shared]})
    out.sort(key=lambda d: (-d["score"], d["paths"]))
    return out


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

            # 4b. The absence signal: lines this prompt QUOTES that are gone
            #     from a file it names. The only leg that fires on a prompt
            #     which shipped leaving no Mind-side trace AND whose named
            #     files still exist — the shape leg 3 is blind to.
            quotes = getattr(source_reader, "quotes", None)
            if quotes is not None:
                named = _named_paths(prompt_text)
                quoted = _quoted_source_lines(prompt_text)
                # A prompt that never mentions the repo being read is not about
                # it, and its quotes are absent from it by construction. The
                # `Repos:` header had this answer all along, while `--repo` had
                # to be told the target by hand.
                slug = getattr(source_reader, "slug", "")
                about = (not slug) or normalise_repo(slug.rsplit("/", 1)[-1]) in {
                    normalise_repo(x) for x in re.findall(
                        r"[@`/\s]([A-Za-z_][A-Za-z0-9_]*)", prompt_text)}
                q = (quotes(named, quoted)
                     if (named and quoted and about) else {})
                absent = q.get("absent") or []
                if absent:
                    upstream_score += _W_QUOTE_ABSENT * len(absent)
                    findings.append((
                        "upstream-quote-absent",
                        f"{len(absent)} line(s) this prompt quotes are gone "
                        f"from the file(s) it names ("
                        + ", ".join(q["files"][:3]) + "): "
                        + "; ".join(repr(ln) for ln, _ in absent[:3])))

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
            "upstream": upstream_meta or {}, "suspects": suspects,
            "duplicates": duplicate_candidates(mind, c["records"], prefix)}


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
    dups = res.get("duplicates") or []
    if dups:
        print(f"\n== Duplicate candidates: {len(dups)} pair(s) ==")
        print("  Live prompts naming the same artefacts, neither referencing "
              "the other.")
        for d in dups:
            print(f"[{d['score']:>6}] {d['paths'][0]}")
            print(f"{' ' * 9}{d['paths'][1]}")
            for s in d["shared"]:
                ev = s["evidence"]
                if len(ev) > 160:
                    ev = ev[:157] + "\u2026"
                print(f"{' ' * 9}{s['kind']}: {ev}")
    print("\nRetiring a prompt stays human: verify against the target repo's "
          "git log / merged\nPRs, then retire it to the complete/ archive by hand.")
    if dups:
        print("A duplicate candidate is a PAIR to read together, not a verdict: "
              "two prompts can\nshare files and still be different work. Merge "
              "or retire by hand.")
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
    wt_mark = ("declared" if d.get("work_type_source") == "declared"
               else f"confidence: {d['classification_confidence']}")
    print(f"Work-type:            {d['work_type']}  ({wt_mark})")
    print(f"Target:               {d['target_display']}")
    print(f"Repos resolved:       {', '.join(d['repos_affected']) or '(none)'}")
    if d.get("difficulty_source") == "declared":
        print(f"Difficulty:           {d['difficulty']} (declared; heuristic derived "
              f"{d['difficulty_derived']}, score {d['difficulty_score']})")
    else:
        print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    for field in ("autonomy", "priority"):
        mark = " (declared)" if d.get(f"{field}_source") == "declared" else ""
        print(f"{field.capitalize() + ':':<22}{d[field]}{mark}")
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
    cl.add_argument("--themes", default="",
                    help="comma-separated Themes: keywords, primary first "
                         "(vocabulary: PyAutoMind/themes.md)")

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
        decision = analyse(text, source, [t for t in (
            getattr(a, "themes", "") or "").split(",") if t.strip()])
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

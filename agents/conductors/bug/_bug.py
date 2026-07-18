#!/usr/bin/env python3
"""agents/conductors/bug/_bug.py — analysis core for the PyAutoBrain Bug Agent.

The Bug Agent is the *immune system* of PyAutoBrain: it recognises a pathogen (a
bug, regression, failing test or PyAutoHeart finding), tells it from benign self,
types the threat, recalls prior cases (PyAutoMemory), and produces a structured
BugDecision that the existing workflow (start_dev -> start_library/start_workspace
-> ship_library/ship_workspace) consumes. It does NOT implement code.

This module is the deterministic part: it discovers bug prompts, classifies each
(severity/scope/type/confidence), locates the likely owner, reasons about the
*fix locus* (source-first, never degrade a user-facing workspace script), and — in
health mode — routes a live verdict + filed PyAutoHeart issues to bug/health_fixes/.

It reuses the Feature Agent's core by import (minimal-refactor share): repo/target
parsing, the difficulty heuristic, PyAutoMemory routing, and in-flight down-ranking
all come from _feature.py so the two agents cannot drift. It is stdlib-only, does no
network or Git (bug.sh feeds it the verdict + Heart issues), and never writes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Reuse the Feature Agent's deterministic core rather than copying it (the user
# picked "share, minimal refactor"). Only the bug-specific reasoning lives here.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "feature"))
import _feature as F  # noqa: E402

# --- bug classification taxonomy (mirrors BUG_TAXONOMY.md) -------------------
# Repos that are neither library nor workspace: fixes here are *infrastructure*
# (the organs themselves), not library-source or workspace work.
INFRA_TARGETS = {
    "pyautobrain": "PyAutoBrain", "pyautoheart": "PyAutoHeart",
    "pyautobuild": "PyAutoHands", "autobuild": "PyAutoHands",
    "pyautomind": "PyAutoMind", "pyautomemory": "PyAutoMemory",
}

# A file path referenced in the prompt (e.g. @PyAutoArray/.../inversion.py, foo.yaml).
# Used to detect single-file scope.
FILE_RE = re.compile(r"[\w./@-]+\.(?:py|md|yaml|yml|rst|ipynb|cfg|toml|sh)\b")

# type -> word-boundary-prefix signals (matched with _feature._hits). Signals are
# deliberately specific: generic words ("workflow", "pipeline") appear in ordinary
# science prompts and would mis-type a real defect, so they are omitted (a specific
# marker like "docstring" for docs-error is kept — it is not generic).
TYPE_SIGNALS = {
    "flaky": ["flaky", "intermittent", "non-determin", "race condition", "sometimes fail"],
    "release-error": ["pypi", "wheel", "testpypi", "colab url", "release-block",
                      "release timeout", "tag_and_merge"],
    "config-error": ["yaml", "env var", "environment variable", "no_run",
                     "config/build", "config file"],
    "wrong-result": ["wrong", "incorrect", "mismatch", "offset", "inaccurate",
                     "misalign", "divergence", "parity", "not positive-definite",
                     "wrong formula", "wrong value"],
    "runtime-error": ["traceback", "exception", "crash", "raise ", "segfault",
                      "error:", "attributeerror", "keyerror", "valueerror",
                      "typeerror", "nan", "overflow"],
    "test-failure": ["failing test", "test fail", "pytest", "assertion", "unit test"],
    "docs-error": ["docstring", "typo", "broken link", ".rst", "autosummary"],
    "workflow-error": ["start_dev", "ship_", "worktree", "slash command", "skill file"],
}
# Ordered specific -> generic; first hit wins. Genuine-defect types (runtime,
# wrong-result, test-failure) rank above administrative ones (docs, workflow).
TYPE_ORDER = ["flaky", "release-error", "config-error", "runtime-error",
              "wrong-result", "test-failure", "docs-error", "workflow-error"]

SEVERITY_SIGNALS = {
    "critical": ["crash", "release-block", "data loss", "all scripts", "cannot install",
                 "broken release", "blocks release", "timeout"],
    "high": ["regression", "wrong result", "incorrect", "fails on main", "blocks",
             "diverge", "not positive-definite", "nan"],
    "low": ["typo", "cosmetic", "minor", "docstring", "small offset", "nit"],
}


def classify(p: dict, factors: dict) -> dict:
    """Type the threat: severity | scope | type | confidence."""
    text = p["text"]

    # type — first signal group with a hit, else the work-type hint, else unknown.
    btype = "unknown"
    for t in TYPE_ORDER:
        if F._hits(text, TYPE_SIGNALS[t]):
            btype = t
            break

    # severity — explicit signal beats the default; blast radius nudges upward.
    severity = "medium"
    if F._hits(text, SEVERITY_SIGNALS["critical"]):
        severity = "critical"
    elif F._hits(text, SEVERITY_SIGNALS["high"]):
        severity = "high"
    elif F._hits(text, SEVERITY_SIGNALS["low"]):
        severity = "low"
    if factors["repos_affected"] >= 3 and severity in ("low", "medium"):
        severity = "high"

    # scope — from the repo blast radius; single-file when ≤1 repo and the prompt
    # points at exactly one file.
    n = factors["repos_affected"]
    n_files = len({m.lstrip("@") for m in FILE_RE.findall(text)})
    if n >= 3:
        scope = "ecosystem"
    elif n == 2:
        scope = "multi-repo"
    elif n_files == 1:
        scope = "single-file"
    else:
        scope = "single-repo"

    # confidence — high when the type is clear and a repro is implied; low when the
    # report is ambiguous or the type could not be resolved.
    confidence = "medium"
    if btype != "unknown" and not factors["human_judgement"]:
        confidence = "high"
    if btype == "unknown" or factors["human_judgement"]:
        confidence = "low"

    return {"severity": severity, "scope": scope, "type": btype,
            "confidence": confidence}


def reproduction(p: dict, cls: dict, heart_check: str | None) -> str:
    """known / unknown / a PyAutoHeart check — never run here, only identified."""
    if heart_check:
        return f"PyAutoHeart check: {heart_check} (reproduce via the vitals faculty)"
    text = p["text"].lower()
    if cls["type"] == "test-failure" or "pytest" in text or "failing test" in text:
        return "known: identify + run the failing test (via the vitals faculty; not here)"
    if "traceback" in text or "```" in p["text"]:
        return "known: from the reported traceback / error in the prompt"
    if cls["confidence"] == "low":
        return "unknown: establish a reliable reproduction before patching"
    return "known: reproduce the reported behaviour on a clean main checkout first"


def likely_owner(p: dict, factors: dict) -> str:
    """The repo or workflow that most likely owns the defect."""
    infra = INFRA_TARGETS.get(F.normalise_repo(p["target"]))
    if infra:
        return f"{infra} (infrastructure)"
    libs = factors["library_repos"]
    wsp = factors["workspace_repos"]
    if libs:
        return ", ".join(libs) + (" (+ workspace)" if wsp else "")
    if wsp:
        return ", ".join(wsp)
    return "unresolved — locate the owning repo before planning"


def fix_locus(p: dict, factors: dict, cls: dict) -> dict:
    """WHERE the fix belongs — the immune system's targeted-response decision.

    Strong prior: prefer a *general* library-source fix; a user-facing workspace
    script is documentation and must not be degraded to squash a symptom (that is
    the autoimmune failure mode). Returns {locus, note}.
    """
    infra = INFRA_TARGETS.get(F.normalise_repo(p["target"]))
    if infra:
        return {"locus": f"infrastructure ({infra})",
                "note": "fix the organ itself; keep health/exec/reasoning boundaries intact."}
    libs = factors["library_repos"]
    wsp = factors["workspace_repos"]

    if libs:
        note = ("general fix in library source resolves the whole class of failure.")
        if wsp:
            note += (" Do NOT edit the workspace scripts to mask it — they are "
                     "user-facing documentation (no injected env-vars / hard-coded "
                     "paths / os.environ mutation / silent guards).")
        return {"locus": "library source (general fix)", "note": note}

    if wsp:
        if cls["type"] == "config-error":
            return {"locus": "workspace config (config/build/*.yaml)",
                    "note": "use the sanctioned knobs (env_vars.yaml / no_run.yaml), "
                            "never inline edits to the script body."}
        return {"locus": "workspace source-first (verify a library fix cannot generalise it)",
                "note": "workspace scripts are documentation: only edit the script if the "
                        "defect truly lives there, and never in a way that reduces clarity. "
                        "First ask whether the real defect is upstream in library source."}

    return {"locus": "unresolved", "note": "locate the owning repo before deciding the fix locus."}


def fix_strategy(level: str, cls: dict, factors: dict, rehome: str | None) -> str:
    """direct | investigate-first | split-into-phases | defer/re-home."""
    if rehome:
        return f"defer/re-home (looks like a {rehome}/ task, not a bug)"
    if cls["confidence"] == "low" or factors["human_judgement"]:
        return "investigate-first (reproduce + confirm root cause before patching)"
    if level in ("large", "too-large"):
        return "split-into-phases (prefer several small shippable fix PRs)"
    return "direct fix"


def recommended_workflow(p: dict, factors: dict) -> str:
    """library | workspace | combined | infrastructure — from the repo blast radius.

    Unlike the Feature Agent (which passes a bug/ work-type straight through as the
    label), the Bug Agent always maps to a *development path*: a bug still ships via
    start_library / start_workspace. A bug with no repo resolved is investigation on
    the most-likely owner, never a research re-home.
    """
    if INFRA_TARGETS.get(F.normalise_repo(p["target"])):
        return "infrastructure"
    lib, wsp = factors["library_repos"], factors["workspace_repos"]
    if lib and wsp:
        return "combined"
    if lib:
        return "library"
    if wsp:
        return "workspace"
    return "library"  # unresolved defaults to library source — most bugs live there


def health_validation(workflow: str, factors: dict) -> str:
    """Which health signals to confirm via the vitals faculty before shipping.

    The ship gate is GREEN, or YELLOW with explicit acknowledgement (per the
    ship_* readiness policy) — never a check the Bug Agent re-runs itself.
    """
    checks = ["unit tests (lib-tests)"] if workflow in ("library", "combined", "infrastructure") else []
    if workflow in ("workspace", "combined"):
        checks.append("workspace/integration validation (test_run)")
    checks.append("pyauto-heart readiness GREEN/YELLOW before ship")
    return "Consult the vitals faculty after patching: " + ", ".join(checks) + \
           ". The Bug Agent never re-runs these itself."


def re_home_check(p: dict) -> str | None:
    """If a bug/ prompt is really a feature/refactor/docs/research task, say so."""
    wt = p["work_type"]
    if wt != "bug":
        return None
    text = p["text"].lower()
    # A genuine defect signal keeps it a bug even if other words also fire.
    defect = F._hits(text, ["bug", "regression", "crash", "traceback", "wrong",
                            "incorrect", "fail", "exception", "broken"])
    if F._hits(text, ["new feature", "add support for", "implement a new", "capability"]):
        return "feature"
    if F._hits(text, ["refactor", "restructure", "rename", "clean up", "tidy"]) and not defect:
        return "refactor"
    if F._hits(text, ["docstring", "tutorial", "typo", "broken link", ".rst",
                      "documentation"]) and not defect:
        return "docs"
    if F._hits(text, ["unclear", "investigate", "explore", "open question",
                      "not sure", "design decision", "research"]) and not defect:
        return "research"
    return None


def analyse_bug(p: dict, heart_check: str | None = None) -> dict:
    level, score, factors = F.estimate_difficulty(p)
    cls = classify(p, factors)
    workflow = recommended_workflow(p, factors)
    mishome = re_home_check(p)
    locus = fix_locus(p, factors, cls)
    return {
        "selected_task": p["path"],
        "work_type": p["work_type"],
        "target": p["target"],
        "repos_affected": p["repos"],
        "classification": cls,
        "likely_owner": likely_owner(p, factors),
        "reproduction": reproduction(p, cls, heart_check),
        "memory_context": F.memory_context(p),
        "fix_locus": locus,
        "fix_strategy": fix_strategy(level, cls, factors, mishome),
        "recommended_workflow": workflow,
        "rehome_suggestion": mishome,
        "difficulty": level,
        "difficulty_score": score,
        "difficulty_factors": factors,
        "health_validation": health_validation(workflow, factors),
        "risks": F.risks(level, factors, workflow),
    }


def _next_action(d: dict) -> str:
    if d["rehome_suggestion"]:
        return f"Re-home under {d['rehome_suggestion']}/ — this is not (only) a bug."
    if d["fix_strategy"].startswith("investigate"):
        return f"Reproduce {d['selected_task']} on clean main, confirm root cause, then start_dev."
    if d["fix_strategy"].startswith("split"):
        return "Split into small fix phases, then run start_dev on phase 1."
    return f"Run start_dev on {d['selected_task']} (workflow: {d['recommended_workflow']})."


# --- discovery + selection (bug/**) ------------------------------------------
def discover_bugs(mind: Path):
    bug = mind / "bug"
    return sorted(bug.rglob("*.md")) if bug.is_dir() else []


def _referenced_bug_paths(mind: Path):
    """Bug prompt paths mentioned in active.md / planned.md (in-flight work).

    The Feature Agent's `_referenced_paths` only matches `feature/…` paths, so the
    Bug Agent needs its own `bug/…`-aware scan to down-rank work already moving.
    """
    refs = set()
    for n in ("active.md", "planned.md"):
        f = mind / n
        if f.is_file():
            for m in re.findall(r"[\w./-]*bug/[\w./-]+\.md", f.read_text(errors="replace")):
                refs.add(m.split("PyAutoMind/")[-1].lstrip("/"))
    return refs


SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def select_bug(mind: Path, constraint: dict, limit: int):
    prompts = [p for p in discover_bugs(mind) if p.name.lower() != "readme.md"]
    in_flight = _referenced_bug_paths(mind)
    rows = []
    for path in prompts:
        p = F.parse_prompt(path, mind)
        level, score, factors = F.estimate_difficulty(p)
        cls = classify(p, factors)
        rows.append({
            "path": p["path"], "difficulty": level, "score": score,
            "severity": cls["severity"], "type": cls["type"],
            "in_flight": p["path"] in in_flight,
            "factors": factors,
        })

    want = constraint.get("difficulty")
    model = constraint.get("model")
    budget = constraint.get("budget")

    def keyfn(r):
        penalty = 100 if r["in_flight"] else 0
        # A bug list is a triage queue, so the default (and --impact) is
        # severity-first — critical bugs surface before an easy medium one.
        if constraint.get("ambitious"):
            return (penalty, SEV_RANK[r["severity"]], -r["score"])
        # easy / weak-model / budget -> smallest first, worse severity breaking ties.
        if want in ("easy", "small") or model == "weak" or budget:
            return (penalty, r["score"], SEV_RANK[r["severity"]])
        return (penalty, SEV_RANK[r["severity"]], r["score"])

    candidates = rows
    if want and want != "easy":
        candidates = [r for r in rows if r["difficulty"] == want] or rows
    elif want == "easy":
        candidates = [r for r in rows if r["difficulty"] in ("small", "medium")] or rows
    if model == "weak" or budget:
        candidates = [r for r in candidates if r["difficulty"] in ("small", "medium")] or candidates

    return sorted(candidates, key=keyfn)[:limit], len(prompts)


# --- emit ---------------------------------------------------------------------
def emit_human(mode: str, d: dict):
    c = d["classification"]
    print("== BugDecision ==")
    print(f"Bug:                  {d['selected_task']}")
    print(f"Mode:                 {mode}")
    print(f"Classification:       severity={c['severity']}  scope={c['scope']}  "
          f"type={c['type']}  confidence={c['confidence']}")
    print(f"Likely owner:         {d['likely_owner']}")
    print(f"Reproduction:         {d['reproduction']}")
    if d["memory_context"]:
        print("Relevant context (PyAutoMemory — consult, do not invent):")
        for wiki, kws in d["memory_context"].items():
            print(f"  - {wiki}/index.md  ({', '.join(kws)})")
    else:
        print("Relevant context:     none matched")
    print(f"Fix locus:            {d['fix_locus']['locus']}")
    print(f"                      ↳ {d['fix_locus']['note']}")
    print(f"Fix strategy:         {d['fix_strategy']}")
    print(f"Recommended workflow: {d['recommended_workflow']}", end="")
    print(f"  [re-home as {d['rehome_suggestion']}/]" if d["rehome_suggestion"] else "")
    print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    print(f"Health validation:    {d['health_validation']}")
    print("Risks:")
    for r in d["risks"]:
        print(f"  - {r}")
    print(f"Next action:          {_next_action(d)}")


def hint_heart_category(issue: dict) -> str:
    """A first-pass category *hint* for a filed PyAutoHeart issue.

    From the issue title + labels only (never re-running a Heart check): one of
    real-bug / config / flaky / expected. It is a hint the reasoning layer confirms
    before routing — not an authoritative verdict.
    """
    hay = (issue.get("title", "") + " " +
           " ".join(l.get("name", "") for l in issue.get("labels", []))).lower()
    if F._hits(hay, ["url-check", "broken", "forbidden url"]):
        return "config (URL hygiene)"
    if F._hits(hay, ["flaky", "intermittent", "timeout"]):
        return "flaky/timeout — confirm before treating as a defect"
    if F._hits(hay, ["fail", "regression", "error", "not positive", "wrong"]):
        return "likely real-bug"
    if F._hits(hay, ["degraded", "health", "readiness"]):
        return "expected/rollup — triage its child findings, not the umbrella issue"
    return "unknown — inspect the issue before routing"


def emit_health(mode: str, verdict: str, issues: list, mind: Path):
    print("== BugDecision (health-issue mode) ==")
    print(f"Mode:                 {mode}")
    print(f"Live vitals verdict:  {verdict.upper()}  (consulted via the vitals faculty)")
    hf = mind / "bug" / "health_fixes"
    print(f"Health-fix prompts:   {'present' if hf.is_dir() else 'absent'} at PyAutoMind/bug/health_fixes/")
    if not issues:
        print("Filed PyAutoHeart issues: none open (or gh unavailable).")
    else:
        print(f"Filed PyAutoHeart issues ({len(issues)} open) — category hint per finding "
              "(confirm before routing):")
        for it in issues:
            print(f"  - #{it.get('number')}  {it.get('title','').strip()}")
            print(f"      hint: {hint_heart_category(it)}")
    print("Next action:          For each finding the hint marks a real defect, write a "
          "PyAutoMind/bug/health_fixes/<name>.md prompt and run start_dev; leave "
          "flaky/expected findings for the Health conductor. Confirm with the vitals "
          "faculty (never query Heart directly).")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bug", add_help=True)
    ap.add_argument("--mind", required=True)
    ap.add_argument("--memory", default="")
    ap.add_argument("--json", action="store_true", dest="as_json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("specific")
    sp.add_argument("task")
    sp.add_argument("--heart-check", default="")

    se = sub.add_parser("select")
    se.add_argument("--difficulty", default="")
    se.add_argument("--model", default="")
    se.add_argument("--budget", action="store_true")
    se.add_argument("--ambitious", action="store_true")
    se.add_argument("--impact", action="store_true")
    se.add_argument("--limit", type=int, default=5)

    he = sub.add_parser("health")
    he.add_argument("--verdict", default="unknown")
    he.add_argument("--heart-issues", default="")  # path to `gh issue list --json` output

    a = ap.parse_args(argv)
    mind = Path(a.mind)

    if a.cmd == "specific":
        task = Path(a.task)
        if not task.is_absolute():
            task = mind / a.task
        if not task.is_file():
            print(f"bug agent: task not found: {task}", file=sys.stderr)
            return 5
        d = analyse_bug(F.parse_prompt(task, mind), a.heart_check or None)
        d["mode"] = "specific"
        if a.as_json:
            print(json.dumps({**d, "next_action": _next_action(d)}, indent=2))
        else:
            emit_human("specific", d)
        return 0

    if a.cmd == "health":
        issues = []
        if a.heart_issues and Path(a.heart_issues).is_file():
            try:
                issues = json.loads(Path(a.heart_issues).read_text() or "[]")
            except Exception:
                issues = []
        if a.as_json:
            enriched = [{"number": it.get("number"), "title": it.get("title"),
                         "url": it.get("url"), "category_hint": hint_heart_category(it)}
                        for it in issues]
            print(json.dumps({"mode": "health-issue", "verdict": a.verdict,
                              "heart_issues": enriched}, indent=2))
        else:
            emit_health("health-issue", a.verdict, issues, mind)
        return 0

    # select / difficulty-constrained
    constraint = {"difficulty": a.difficulty, "model": a.model, "budget": a.budget,
                  "ambitious": a.ambitious, "impact": a.impact}
    mode = "difficulty-constrained" if (a.difficulty or a.model or a.budget
                                        or a.ambitious or a.impact) else "selection"
    ranked, total = select_bug(mind, constraint, a.limit)
    if not ranked:
        print("bug agent: no bug prompts found in PyAutoMind/bug/.", file=sys.stderr)
        return 4

    if a.as_json:
        top = F.parse_prompt(mind / ranked[0]["path"], mind)
        d = analyse_bug(top)
        d["mode"] = mode
        d["shortlist"] = ranked
        d["candidates_considered"] = total
        print(json.dumps({**d, "next_action": _next_action(d)}, indent=2))
        return 0

    print(f"== Bug task {mode} ({total} bug prompts considered) ==")
    print("Shortlist (recommendation — severity-first, in-flight down-ranked):")
    for i, r in enumerate(ranked):
        flag = "  [in-flight, down-ranked]" if r["in_flight"] else ""
        print(f"  {i+1}. {r['path']}  [{r['severity']}, {r['type']}, "
              f"{r['difficulty']}/score {r['score']}]{flag}")
    print()
    d = analyse_bug(F.parse_prompt(mind / ranked[0]["path"], mind))
    print("Recommended pick (ranked by severity then the active constraint):")
    emit_human(mode, d)
    print("\nWhy this bug: highest-ranked after severity weighting and down-ranking "
          "in-flight work; confirm against PyAutoMind priorities and a vitals check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

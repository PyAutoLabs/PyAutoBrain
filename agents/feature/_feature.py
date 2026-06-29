#!/usr/bin/env python3
"""agents/feature/_feature.py — analysis core for the PyAutoBrain Feature Agent.

The Feature Agent is the "growth function" of PyAutoBrain: it reasons over the
feature intent stored in PyAutoMind and decides *how the organism should grow*.
It does NOT implement code — it produces a structured FeatureDecision that the
existing development workflow (start_dev -> start_library/start_workspace ->
ship_library/ship_workspace) can consume.

This module is the deterministic part: it discovers feature prompts, classifies
their work-type / target repos, estimates difficulty, decides phasing, and maps
the task to relevant PyAutoMemory sub-wikis. The richer judgement (priorities,
dependencies, health) is documented in AGENTS.md and applied by the reasoning
layer on top of this scaffold. feature.sh is the entrypoint that resolves the
PyAutoMind / PyAutoMemory checkouts and calls into here.

It is intentionally dependency-free (stdlib only) and never writes anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# --- the PyAutoMind taxonomy (mirrors PyAutoMind/ROUTING.md) -----------------
# work-type folder -> the kind of work and the recommended re-home when a
# feature prompt is mis-filed. The Feature Agent helps keep PyAutoMind organised.
WORK_TYPES = {
    "feature": "new user-facing or scientific capability",
    "bug": "incorrect behaviour, crash or regression",
    "refactor": "internal restructuring, no behaviour change",
    "docs": "documentation, tutorials, notebooks, examples",
    "test": "test coverage, smoke tests, validation",
    "release": "packaging, versions, deployment, readiness",
    "maintenance": "dependency updates, hygiene, small tech debt",
    "research": "exploratory scientific/algorithmic investigation",
    "experiment": "prototype, spike, proof-of-concept",
    "triage": "classification still unclear",
}

# Targets that are source *libraries* (work classifies as library vs workspace).
LIBRARY_REPOS = {
    "pyautoconf", "pyautofit", "pyautoarray", "pyautogalaxy", "pyautolens",
    "autoconf", "autofit", "autoarray", "autogalaxy", "autolens",
}
# Targets / @-mentions that are workspaces, tutorials or example repos.
WORKSPACE_REPOS = {
    "autolens_workspace", "autogalaxy_workspace", "autofit_workspace",
    "autolens_workspace_test", "autogalaxy_workspace_test", "autofit_workspace_test",
    "howtolens", "howtogalaxy", "howtofit", "autolens_assistant",
    "autolens_profiling", "workspaces",
}
# Normalise an @-mention or folder name to a canonical key.
REPO_ALIASES = {
    "aa": "autoarray", "af": "autofit", "ag": "autogalaxy", "al": "autolens",
    "pyautoarray": "autoarray", "pyautofit": "autofit", "pyautoconf": "autoconf",
    "pyautogalaxy": "autogalaxy", "pyautolens": "autolens",
}

# --- PyAutoMemory sub-wiki routing -------------------------------------------
# Map target/keywords -> the PyAutoMemory sub-wiki that holds relevant context.
# Source of truth for the sub-wiki list: PyAutoMemory/index.md.
MEMORY_WIKIS = {
    "lensing_wiki": ["lens", "deflection", "source reconstruction", "caustic",
                     "einstein", "subhalo", "substructure", "time delay",
                     "cosmography", "shear", "multipole", "mass sheet", "slacs",
                     "tdcosmo", "h0licow", "macromodel"],
    "smbh_wiki": ["black hole", "smbh", "binary", "recoil", "nanograv",
                  "gravitational wave background"],
    "cti_wiki": ["charge transfer", "cti", "trap", "arctic", "vis calibration"],
    "methods_wiki": ["bayesian", "sampler", "nautilus", "dynesty", "emcee",
                     "mcmc", "nested sampling", "likelihood", "jax", "nufft",
                     "interpolat", "graphical model", "expectation propagation",
                     "deep learning", "sbi", "simulation based inference",
                     "probabilistic", "optimis", "gradient", "regularis"],
    "galaxies_wiki": ["galaxy formation", "bulge", "disk", "morphology", "mge",
                      "stellar halo", "ifu", "kinematic", "elliptical", "cosmos"],
}
# Default sub-wiki to consult per library target when no keyword fires.
TARGET_DEFAULT_WIKI = {
    "autolens": "lensing_wiki", "autogalaxy": "galaxies_wiki",
    "autofit": "methods_wiki", "autoarray": "methods_wiki",
    "autoconf": "methods_wiki",
}

SCIENCE_KEYWORDS = sorted({kw for kws in MEMORY_WIKIS.values() for kw in kws})
RISK_KEYWORDS = ["api", "breaking", "backwards", "migrat", "deprecat",
                 "cross-repo", "interface", "refactor", "rename", "public api"]
AMBIGUITY_KEYWORDS = ["unclear", "investigate", "explore", "research", "decide",
                      "figure out", "not sure", "tbd", "open question", "design",
                      "proof of concept", "prototype", "spike", "?"]
TEST_KEYWORDS = ["test", "smoke", "parity", "jax", "likelihood", "vmap",
                 "validation", "regression"]


def normalise_repo(name: str) -> str:
    # Take the head token before any '.' or '/': an @-mention may be an API path
    # (e.g. @aa.decorators.to_vector_yx -> aa) or a repo path, not just a name.
    key = re.split(r"[./]", name.strip().lstrip("@").lower(), 1)[0]
    return REPO_ALIASES.get(key, key)


KNOWN_REPOS = LIBRARY_REPOS | WORKSPACE_REPOS


def parse_prompt(path: Path, mind: Path):
    """Read a prompt file and extract structure: work-type, target, repos, body."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        rel = path.relative_to(mind)
        parts = rel.parts
    except ValueError:
        parts = path.parts
    work_type = parts[0] if parts else "?"
    target = parts[1] if len(parts) > 1 else "?"

    mentions = {normalise_repo(m) for m in re.findall(r"@[A-Za-z0-9._/-]+", text)}
    # Keep only mentions that resolve to a repo we know — drops project refs
    # (@z_projects), bare libraries (@jax) and noise, so the repo count is real.
    repos = {m for m in mentions if m in KNOWN_REPOS}
    if target not in ("?", "workspaces") and target not in WORK_TYPES:
        t = normalise_repo(target)
        if t in KNOWN_REPOS:
            repos.add(t)

    return {
        "path": str(path.relative_to(mind)) if _within(path, mind) else str(path),
        "work_type": work_type,
        "target": target,
        "repos": sorted(repos),
        "text": text,
        "lines": text.count("\n") + 1,
        "words": len(text.split()),
    }


def _within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _hits(text: str, keywords) -> list:
    """Keyword hits using word-boundary *prefix* matching.

    A leading \\b stops short tokens ("cti", "api", "mge") matching inside other
    words ("function", "rapid"), while leaving the end open so stems still fire
    ("interpolat" -> "interpolation", "migrat" -> "migration").
    """
    low = text.lower()
    out = []
    for k in keywords:
        if re.search(r"\b" + re.escape(k), low):
            out.append(k)
    return out


def estimate_difficulty(p: dict):
    """Heuristic difficulty estimate -> (level, score, factors).

    Considers: repos affected, prompt size, scientific complexity, architectural
    risk, test burden, and whether human judgement / memory context is needed.
    """
    text = p["text"]
    lib = [r for r in p["repos"] if r in LIBRARY_REPOS]
    wsp = [r for r in p["repos"] if r in WORKSPACE_REPOS]
    repo_count = len(set(p["repos"]))
    science = _hits(text, SCIENCE_KEYWORDS)
    risk = _hits(text, RISK_KEYWORDS)
    tests = _hits(text, TEST_KEYWORDS)
    ambiguity = _hits(text, AMBIGUITY_KEYWORDS)

    score = 0
    score += max(0, repo_count - 1) * 2          # multi-repo is the big driver
    score += 2 if (lib and wsp) else 0           # library+workspace coordination
    score += min(p["words"] // 150, 4)           # size of the description
    score += min(len(science), 3)                # scientific complexity
    score += min(len(risk) * 2, 4)               # architectural risk
    score += 1 if tests else 0                   # test burden
    score += 1 if science else 0                 # memory context likely needed

    if score <= 2:
        level = "small"
    elif score <= 5:
        level = "medium"
    elif score <= 9:
        level = "large"
    else:
        level = "too-large"

    factors = {
        "repos_affected": repo_count,
        "library_repos": lib,
        "workspace_repos": wsp,
        "library_and_workspace": bool(lib and wsp),
        "size_words": p["words"],
        "scientific_complexity": science,
        "architectural_risk": risk,
        "test_burden": tests,
        "human_judgement": ambiguity,
        "memory_context_required": bool(science),
    }
    return level, score, factors


def recommend_workflow(p: dict, factors: dict):
    """Map the task to a development path / re-home suggestion."""
    wt = p["work_type"]
    if wt in ("research", "experiment", "bug", "refactor") and wt != "feature":
        # Already correctly homed in a non-feature category.
        return wt, None

    lib = factors["library_repos"]
    wsp = factors["workspace_repos"]

    # Re-home suggestions for mis-filed feature prompts.
    rehome = None
    if factors["human_judgement"] and not (lib or wsp):
        rehome = "research"
    if lib and wsp:
        return "combined", rehome
    if lib:
        return "library", rehome
    if wsp:
        return "workspace", rehome
    # No repo resolved — most likely needs scoping first.
    return "research", (rehome or "research")


def memory_context(p: dict):
    """Return the PyAutoMemory sub-wikis worth consulting for this task."""
    text = p["text"]
    hits = {}
    for wiki, kws in MEMORY_WIKIS.items():
        matched = _hits(text, kws)
        if matched:
            hits[wiki] = matched
    for r in p["repos"]:
        d = TARGET_DEFAULT_WIKI.get(r)
        if d and d not in hits:
            hits.setdefault(d, []).append(f"(default for {r})")
    return hits


def phase_decision(level: str, factors: dict, p: dict):
    """direct | split-into-phases | research-first | defer, plus phase stubs."""
    if factors["human_judgement"] and not (factors["library_repos"] or factors["workspace_repos"]):
        return "research-first", []
    if level == "too-large":
        # Phase stubs live in the prompt's own target folder (mirrors the
        # feature/autofit/sbi_phase_1_design.md example in the spec).
        target = p["target"] if p["target"] not in ("?",) else (p["repos"] or ["misc"])[0]
        stem = Path(p["path"]).stem
        stubs = [
            f"feature/{target}/{stem}_phase_1_design.md",
            f"feature/{target}/{stem}_phase_2_core_api.md",
            f"feature/{target}/{stem}_phase_3_workspace_examples.md",
            f"feature/{target}/{stem}_phase_4_docs.md",
        ]
        return "split-into-phases", stubs
    if level == "large":
        return "split-into-phases", []
    return "direct", []


def execution_plan(workflow: str, factors: dict):
    """Steps compatible with the existing start_dev / ship_* workflow."""
    if workflow == "library":
        return ["start_dev <prompt>", "start_library", "ship_library"]
    if workflow == "workspace":
        return ["start_dev <prompt>", "start_workspace", "ship_workspace"]
    if workflow == "combined":
        return ["start_dev <prompt>", "start_library", "ship_library",
                "start_workspace (uses the library PR's API-change summary)",
                "ship_workspace"]
    if workflow in ("research", "experiment"):
        return [f"re-home as a {workflow}/ task in PyAutoMind, then scope before start_dev"]
    return [f"re-home as a {workflow}/ task, then run start_dev once scoped"]


def health_consideration(level: str, factors: dict, workflow: str):
    reasons = []
    if factors["repos_affected"] > 1:
        reasons.append("affects multiple repositories")
    if factors["architectural_risk"]:
        reasons.append("carries architectural / API risk")
    if level in ("large", "too-large"):
        reasons.append("is large")
    if workflow == "combined":
        reasons.append("requires coordinated library + workspace PRs")
    if not reasons:
        return "Optional: tree is likely fit; consult the Health Agent if recent CI is unknown."
    return ("Consult the Health Agent (pyauto-brain health) before starting — this task "
            + ", ".join(reasons) + ".")


def risks(level: str, factors: dict, workflow: str):
    out = []
    if factors["library_and_workspace"]:
        out.append("Library/workspace coordination: ship the library PR first so the "
                   "workspace can consume its API-change summary.")
    if factors["architectural_risk"]:
        out.append("Public-API change may ripple to downstream repos.")
    if level == "too-large":
        out.append("Too large for one PR — a single fragile PR risks review/merge stalls.")
    if factors["human_judgement"]:
        out.append("Scientific/architectural ambiguity — needs scoping before code.")
    if not out:
        out.append("Low risk; standard review applies.")
    return out


def analyse(p: dict):
    level, score, factors = estimate_difficulty(p)
    workflow, rehome = recommend_workflow(p, factors)
    mem = memory_context(p)
    phase, stubs = phase_decision(level, factors, p)
    return {
        "selected_task": p["path"],
        "work_type": p["work_type"],
        "target": p["target"],
        "repos_affected": p["repos"],
        "difficulty": level,
        "difficulty_score": score,
        "difficulty_factors": factors,
        "recommended_workflow": workflow,
        "rehome_suggestion": rehome,
        "memory_context": mem,
        "phase_decision": phase,
        "phase_stubs": stubs,
        "execution_plan": execution_plan(workflow, factors),
        "health_considerations": health_consideration(level, factors, workflow),
        "risks": risks(level, factors, workflow),
    }


# --- task discovery + selection ----------------------------------------------
def discover(mind: Path):
    feat = mind / "feature"
    if not feat.is_dir():
        return []
    return sorted(feat.rglob("*.md"))


def _referenced_paths(mind: Path, *names):
    """Prompt paths mentioned in active.md / planned.md (recent / in-flight work)."""
    refs = set()
    for n in names:
        f = mind / n
        if f.is_file():
            for m in re.findall(r"[\w./-]*feature/[\w./-]+\.md", f.read_text(errors="replace")):
                refs.add(m.split("PyAutoMind/")[-1].lstrip("/"))
    return refs


DIFF_ORDER = {"small": 0, "medium": 1, "large": 2, "too-large": 3}


def select(mind: Path, constraint: dict, limit: int):
    prompts = discover(mind)
    in_flight = _referenced_paths(mind, "active.md", "planned.md")
    rows = []
    for path in prompts:
        p = parse_prompt(path, mind)
        level, score, factors = estimate_difficulty(p)
        impact = score + (2 if factors["library_and_workspace"] else 0) \
            + len(factors["scientific_complexity"])
        rows.append({
            "path": p["path"], "difficulty": level, "score": score,
            "impact": impact, "repos": p["repos"],
            "in_flight": p["path"] in in_flight,
            "factors": factors,
        })

    # Constraint-driven ranking. The script *recommends*; priorities/health/
    # dependencies are layered on by the reasoning agent (see AGENTS.md).
    want = constraint.get("difficulty")
    model = constraint.get("model")
    budget = constraint.get("budget")
    impact_pref = constraint.get("impact")

    def keyfn(r):
        # Down-rank in-flight work so we never just resurface active tasks.
        penalty = 100 if r["in_flight"] else 0
        if impact_pref:
            return (penalty, -r["impact"])
        if model == "strong" or constraint.get("ambitious"):
            return (penalty, -r["score"])
        if model == "weak" or budget or want in ("easy", "small"):
            return (penalty, r["score"])
        return (penalty, r["score"])  # default: easiest-first, stable

    candidates = rows
    if want and want not in ("easy",):
        candidates = [r for r in rows if r["difficulty"] == want] or rows
    elif want == "easy":
        candidates = [r for r in rows if r["difficulty"] in ("small", "medium")] or rows
    if model == "weak" or budget:
        candidates = [r for r in candidates if r["difficulty"] in ("small", "medium")] or candidates

    candidates = sorted(candidates, key=keyfn)
    return candidates[:limit], len(prompts)


# --- emit ---------------------------------------------------------------------
def emit_human(mode: str, decision: dict):
    d = decision
    print("== FeatureDecision ==")
    print(f"Selected task:        {d['selected_task']}")
    print(f"Mode:                 {mode}")
    print(f"Work-type / target:   {d['work_type']} / {d['target']}")
    print(f"Repos affected:       {', '.join(d['repos_affected']) or '(none resolved)'}")
    print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    print(f"Recommended workflow: {d['recommended_workflow']}", end="")
    print(f"  [re-home as {d['rehome_suggestion']}/]" if d["rehome_suggestion"] else "")
    if d["memory_context"]:
        print("Relevant context (PyAutoMemory — consult, do not invent):")
        for wiki, kws in d["memory_context"].items():
            print(f"  - {wiki}/index.md  ({', '.join(kws)})")
    else:
        print("Relevant context:     none matched (no scientific context required)")
    print(f"Phase decision:       {d['phase_decision']}")
    for s in d["phase_stubs"]:
        print(f"  - {s}")
    print("Execution plan:")
    for step in d["execution_plan"]:
        print(f"  - {step}")
    print(f"Health considerations:{chr(10)}  {d['health_considerations']}")
    print("Risks:")
    for r in d["risks"]:
        print(f"  - {r}")
    nxt = _next_action(d)
    print(f"Next action:          {nxt}")


def _next_action(d: dict):
    if d["rehome_suggestion"]:
        return f"Re-home this prompt under {d['rehome_suggestion']}/ and scope it before development."
    if d["phase_decision"] == "split-into-phases":
        return "Write the phased feature prompts, then run start_dev on phase 1."
    if d["phase_decision"] == "research-first":
        return "Open a research/ task to resolve the open questions before implementation."
    return f"Run start_dev on {d['selected_task']} (workflow: {d['recommended_workflow']})."


def main(argv=None):
    ap = argparse.ArgumentParser(prog="feature", add_help=True)
    ap.add_argument("--mind", required=True)
    ap.add_argument("--memory", default="")
    ap.add_argument("--json", action="store_true", dest="as_json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("specific")
    sp.add_argument("task")

    se = sub.add_parser("select")
    se.add_argument("--difficulty", default="")
    se.add_argument("--model", default="")
    se.add_argument("--budget", action="store_true")
    se.add_argument("--ambitious", action="store_true")
    se.add_argument("--impact", action="store_true")
    se.add_argument("--limit", type=int, default=5)

    a = ap.parse_args(argv)
    mind = Path(a.mind)

    if a.cmd == "specific":
        task = Path(a.task)
        if not task.is_absolute():
            task = (mind / a.task)
        if not task.is_file():
            print(f"feature agent: task not found: {task}", file=sys.stderr)
            return 5
        decision = analyse(parse_prompt(task, mind))
        decision["mode"] = "specific"
        if a.as_json:
            print(json.dumps({**decision, "next_action": _next_action(decision)}, indent=2))
        else:
            emit_human("specific", decision)
        return 0

    # select / difficulty-constrained
    constraint = {"difficulty": a.difficulty, "model": a.model,
                  "budget": a.budget, "ambitious": a.ambitious, "impact": a.impact}
    mode = "difficulty-constrained" if (a.difficulty or a.model or a.budget
                                        or a.ambitious or a.impact) else "selection"
    ranked, total = select(mind, constraint, a.limit)
    if not ranked:
        print("feature agent: no feature prompts found in PyAutoMind.", file=sys.stderr)
        return 4

    if a.as_json:
        top = parse_prompt(mind / ranked[0]["path"], mind)
        decision = analyse(top)
        decision["mode"] = mode
        decision["shortlist"] = ranked
        decision["candidates_considered"] = total
        print(json.dumps({**decision, "next_action": _next_action(decision)}, indent=2))
        return 0

    print(f"== Feature task {mode} ({total} feature prompts considered) ==")
    print("Shortlist (recommendation — apply priorities/dependencies/health on top):")
    for i, r in enumerate(ranked):
        flag = "  [in-flight, down-ranked]" if r["in_flight"] else ""
        print(f"  {i+1}. {r['path']}  [{r['difficulty']}, score {r['score']}, "
              f"impact {r['impact']}]{flag}")
    print()
    chosen = parse_prompt(mind / ranked[0]["path"], mind)
    decision = analyse(chosen)
    print("Recommended pick (not merely the first prompt — ranked by the constraint):")
    emit_human(mode, decision)
    print("\nWhy this task: highest-ranked under the active constraint after "
          "down-ranking in-flight work; confirm against PyAutoMind priorities "
          "(planned.md / active.md) and a Health Agent check before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

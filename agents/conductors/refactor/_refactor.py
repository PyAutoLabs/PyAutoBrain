#!/usr/bin/env python3
"""agents/conductors/refactor/_refactor.py — analysis core for the Refactor Agent.

The Refactor Agent is the *renewal function* of PyAutoBrain: it selects and
plans **behaviour-preserving** internal restructuring from PyAutoMind's
`refactor/*` backlog and emits a structured RefactorDecision the standard
workflow (`start_dev [--auto] -> start_library -> ship_library`) consumes. It
does NOT implement code and never writes.

It reuses the Feature Agent's core by import (the Bug Agent's minimal-
refactor-share pattern): prompt parsing, repo/target resolution and the sizing
faculty's difficulty heuristic come from `_feature.py` / `_sizing.py`, so the
conductors cannot drift. What is *specific* here is the refactor reasoning:
the behaviour-preservation invariant + witnesses, the public-API guard (a
refactor that changes public API is misclassified), and the candidates miner.

Stdlib-only; exit codes: 0 decision · 4 no input/backlog · 5 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "feature"))
from _feature import analyse  # noqa: E402  (pulls _sizing onto the path too)
from _sizing import parse_prompt, policy as _sizing_policy  # noqa: E402

# Public-API-change smells: a "refactor" prompt matching these is suspect —
# it belongs in feature/ (or bug/) and must not run at `safe`.
API_CHANGE_PATTERNS = [
    r"\brenam\w+ .{0,40}\b(public|api|class|function|method|argument)\b",
    r"\bremov\w+ .{0,40}\b(public|api|argument|parameter|kwarg)\b",
    r"\b(change|new|break)\w* .{0,30}\bsignature\b",
    r"\bdeprecat\w+\b",
    r"\bbackwards?[- ]incompat\w+\b",
]

# Normalised repo name -> the test dir that witnesses behaviour preservation
# (repos arrive normalised by _sizing.normalise_repo: lowercase, no Py prefix).
TEST_WITNESS = _sizing_policy()["test_witness"]

REFACTOR_IDEA_WORDS = ("refactor", "restructur", "clean up", "cleanup",
                       "simplif", "dedupl", "extract", "consolidat")


def api_guard(text: str) -> tuple[str, list[str]]:
    hits = [p for p in API_CHANGE_PATTERNS if re.search(p, text, re.IGNORECASE)]
    return ("SUSPECT-API-CHANGE" if hits else "none-expected"), hits


def behaviour_preservation(repos: list[str]) -> dict:
    witnesses = {r: TEST_WITNESS[r] for r in repos if r in TEST_WITNESS}
    unwitnessed = [r for r in repos if r not in TEST_WITNESS]
    return {
        "invariant": "all public behaviour observable through the affected "
                     "repos' test suites is unchanged",
        "witnesses": witnesses,
        "unwitnessed_repos": unwitnessed,
        "note": ("strengthen tests first (file a test/ prompt) before "
                 "refactoring unwitnessed repos" if unwitnessed else ""),
    }


def decide(prompt_path: Path, mind: Path) -> dict:
    p = parse_prompt(prompt_path, mind)
    base = analyse(p)
    text = prompt_path.read_text(encoding="utf-8", errors="replace")
    guard, guard_hits = api_guard(text)
    m = re.search(r"^Autonomy:\s*(\S+)", text, re.MULTILINE)
    header_autonomy = m.group(1) if m else "supervised"
    effective = "safe" if guard == "none-expected" else "human-required"
    if header_autonomy == "human-required":
        effective = "human-required"
    d = {
        "agent": "refactor",
        "selected_task": base["selected_task"],
        "work_type": base["work_type"],
        "target": base["target"],
        "repos_affected": base["repos_affected"],
        "difficulty": base["difficulty"],
        "difficulty_score": base["difficulty_score"],
        "behaviour_preservation": behaviour_preservation(base["repos_affected"]),
        "api_guard": guard,
        "api_guard_hits": guard_hits,
        "effective_autonomy": effective,
        "rehome_suggestion": ("feature/ or bug/ — prompt implies public-API "
                              "change; a refactor must be behaviour-preserving"
                              if guard != "none-expected"
                              else base["rehome_suggestion"]),
        "execution_plan": [
            "start_dev <prompt> [--auto]",
            "start_library",
            "ship_library (four-leg autonomous-ship gate under --auto)",
        ],
        "risks": base["risks"],
        "next_action": ("re-route: file under feature/ (API change implied); "
                        "do not run at safe"
                        if guard != "none-expected"
                        else "run start_dev on the prompt (safe-capable)"),
    }
    return d


def discover(mind: Path) -> list[Path]:
    root = mind / "refactor"
    return sorted(root.rglob("*.md")) if root.is_dir() else []


def candidates(mind: Path) -> dict:
    backlog = [str(p.relative_to(mind)) for p in discover(mind)]
    idea_hits = []
    ideas = mind / "ideas.md"
    if ideas.is_file():
        for line in ideas.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip().lstrip("-*").strip()
            if not s or s.startswith("[formalised"):
                continue
            if any(w in s.lower() for w in REFACTOR_IDEA_WORDS):
                idea_hits.append(s)
    return {
        "agent": "refactor",
        "mode": "candidates",
        "backlog": backlog,
        "ideas_md_candidates": idea_hits,
        "next_action": "formalise a candidate via /intake (this agent files nothing)",
    }


def emit_human(d: dict) -> None:
    if d.get("mode") == "candidates":
        print("== RefactorDecision (candidates — read-only) ==")
        print(f"Backlog ({len(d['backlog'])}):")
        for b in d["backlog"]:
            print(f"  - {b}")
        print(f"ideas.md refactor-shaped bullets ({len(d['ideas_md_candidates'])}):")
        for i in d["ideas_md_candidates"]:
            print(f"  - {i}")
        print(f"Next action:          {d['next_action']}")
        return
    print("== RefactorDecision ==")
    print(f"Selected task:        {d['selected_task']}")
    print(f"Work-type / target:   {d['work_type']} / {d['target']}")
    print(f"Repos affected:       {', '.join(d['repos_affected']) or '?'}")
    print(f"Difficulty:           {d['difficulty']} (score {d['difficulty_score']})")
    bp = d["behaviour_preservation"]
    print(f"Invariant:            {bp['invariant']}")
    print(f"Witnesses:            {bp['witnesses'] or 'NONE'}"
          + (f"  [unwitnessed: {', '.join(bp['unwitnessed_repos'])}]"
             if bp["unwitnessed_repos"] else ""))
    if bp["note"]:
        print(f"  ! {bp['note']}")
    print(f"API guard:            {d['api_guard']}")
    print(f"Effective autonomy:   {d['effective_autonomy']} (cap: refactor -> safe)")
    if d["rehome_suggestion"]:
        print(f"Re-home suggestion:   {d['rehome_suggestion']}")
    print("Execution plan:")
    for step in d["execution_plan"]:
        print(f"  - {step}")
    print(f"Next action:          {d['next_action']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="refactor")
    ap.add_argument("--mind", required=True)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("target", nargs="?", default="",
                    help="a refactor/<target>/<name>.md path, 'candidates', or "
                         "empty for selection mode")
    a = ap.parse_args(argv)
    mind = Path(a.mind)

    if a.target == "candidates":
        d = candidates(mind)
    elif a.target:
        path = mind / a.target
        if not path.is_file():
            print(f"refactor: prompt not found: {path}", file=sys.stderr)
            return 4
        d = decide(path, mind)
    else:
        backlog = discover(mind)
        if not backlog:
            print("refactor: no prompts under refactor/ — try 'candidates'",
                  file=sys.stderr)
            return 4
        decisions = [decide(p, mind) for p in backlog]
        clean = [x for x in decisions if x["api_guard"] == "none-expected"]
        pool = clean or decisions
        order = {"small": 0, "medium": 1, "large": 2, "too-large": 3}
        pool.sort(key=lambda x: order.get(x["difficulty"], 9))
        d = pool[0]
        d["selection_pool"] = [x["selected_task"] for x in decisions]

    print(json.dumps(d, indent=2)) if a.as_json else emit_human(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())

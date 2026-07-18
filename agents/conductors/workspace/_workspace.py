#!/usr/bin/env python3
"""agents/conductors/workspace/_workspace.py — core for the Workspace Agent.

The Voice — the organism's expressive function. v0 is DECISION ONLY: it reads
intent (raw text or a PyAutoMind prompt file) or a workspace repo's example
catalogue, and emits a WorkspaceDecision / WorkspaceSurvey. It never edits
source, never writes files — authoring is executed by the ordinary
start_dev → start_workspace → ship_workspace flow this decision routes into.

Two audience registers, one agent (the founding assessment:
PyAutoMind active/workspace_examples_agent.md):

  workspace  reference examples for practitioners (*_workspace repos)
  howto      narrative teaching for first-time learners (HowTo* repos)

The format spec is never restated here — the decision points at the canonical
sources (the sibling example script it names, PyAutoHands's notebook
generation, WORKFLOW.md's tutorial-prose split).

Stdlib-only. Exit codes: 0 decision · 4 inputs unresolvable · 5 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", Path.home() / "Code" / "PyAutoLabs"))

# Library package -> (workspace repo, HowTo repo). PyAutoReduce's workspace is
# being born (the founding demonstrated-need case); it has no HowTo yet.
FAMILIES = {
    "autofit": ("autofit_workspace", "HowToFit"),
    "autogalaxy": ("autogalaxy_workspace", "HowToGalaxy"),
    "autolens": ("autolens_workspace", "HowToLens"),
    "autoreduce": ("autoreduce_workspace", None),
}

# When a target workspace does not exist on disk yet (a newborn like
# autoreduce_workspace), structure suggestions are anchored on this sibling.
FALLBACK_SIBLING = "autolens_workspace"

# Signals that the reader is there to LEARN, not to look something up —
# they flip the register to howto (a HowTo* target repo always does).
HOWTO_WORDS = (
    "howto", "chapter", "first-time", "first time", "beginner", "undergrad",
    "new phd", "lecture", "teaching", "learner", "course",
)

# Keyword -> example-package hints, checked against the target repo's real
# scripts/ tree (the repo's own folders always win; this list only ranks them).
PLACEMENT_HINTS = (
    ("interferometer", ("interferometer", "alma", "visibilit", "uv-plane")),
    ("point_source", ("point_source", "point source", "quasar", "supernova")),
    ("multi", ("multi", "multi-band", "multiband", "multi-dataset")),
    ("group", ("group",)),
    ("cluster", ("cluster",)),
    ("weak", ("weak lensing", "weak-lensing", "weak")),
    ("guides", ("guide", "aggregator", "results", "api overview")),
    ("imaging", ("imaging", "ccd", "image data")),
)

CHECKLIST_SHARED = [
    "contents + docstring format: every top-level docstring becomes a markdown "
    "cell at notebook generation — mirror the named sibling script, do not "
    "invent structure",
    "docs are minimal, not maximal: a flag/value plus a one-line note, never a "
    "ported runnable block",
    "new library output.yaml keys must be mirrored into the workspace config",
    "ground every API symbol against the installed stack (the PyAuto API gate "
    "blocks stale symbols)",
]
CHECKLIST_REGISTER = {
    "workspace": [
        "standalone and task-oriented: a practitioner lands here from a search "
        "— no dependence on having read anything else",
    ],
    "howto": [
        "narrative and cumulative: assumes only the previous chapters; define "
        "every term at first use for a first-time learner",
        "prefer physical intuition before API — the reader is here to learn "
        "the subject, not the package",
    ],
}


def fail(code, msg):
    print(f"workspace: {msg}", file=sys.stderr)
    sys.exit(code)


def read_intent(arg):
    """The intent text: a PyAutoMind prompt path if it resolves, else raw text."""
    for base in (Path(arg), PYAUTO_ROOT / "PyAutoMind" / arg):
        if base.is_file():
            return base.read_text(encoding="utf-8"), str(base)
    return arg, None


def detect_register(text, target_repo):
    if target_repo and target_repo.startswith("HowTo"):
        return "howto"
    low = text.lower()
    if any(w in low for w in HOWTO_WORDS):
        return "howto"
    return "workspace"


def detect_family(text):
    """The library family the intent talks about, by longest-match repo or
    package mention; None when nothing matches."""
    low = text.lower()
    # Explicit repo mentions win (workspace, HowTo or library repo).
    for pkg, (ws, howto) in FAMILIES.items():
        mentions = [ws, howto or "", f"pyauto{pkg[4:]}"]
        if any(m and m.lower() in low for m in mentions):
            return pkg
    # Bare package words, most specific (longest) first so "autolens" is not
    # claimed by a shorter overlapping name.
    for pkg in sorted(FAMILIES, key=len, reverse=True):
        if re.search(rf"\b{pkg}\b", low):
            return pkg
    return None


def scripts_root(repo):
    return PYAUTO_ROOT / repo / "scripts"


def example_packages(repo):
    root = scripts_root(repo)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")
    )


def suggest_placement(text, packages):
    low = text.lower()
    for package, hints in PLACEMENT_HINTS:
        if package in packages and any(h in low for h in hints):
            return package
    # HowTo repos: an existing chapter mentioned by number.
    m = re.search(r"chapter[_ ](\d+)", low)
    if m:
        for package in packages:
            if package.startswith(f"chapter_{m.group(1)}"):
                return package
    return None


def build_decision(args):
    text, prompt_path = read_intent(args.intent)
    family = detect_family(text)
    if family is None:
        fail(4, "cannot resolve a library family (autofit/autogalaxy/autolens/"
                "autoreduce) from the intent — name the library or workspace repo")
    workspace_repo, howto_repo = FAMILIES[family]

    # An explicitly mentioned repo is the target; otherwise the register picks
    # between the family's workspace and HowTo repos.
    low = text.lower()
    explicit = next(
        (r for r in (howto_repo, workspace_repo) if r and r.lower() in low), None
    )
    register = detect_register(text, explicit)
    target = explicit or (howto_repo if register == "howto" else workspace_repo)
    notes = []
    if register == "howto" and target == workspace_repo and howto_repo is None:
        notes.append(f"family '{family}' has no HowTo repo yet — howto register "
                     f"targets the workspace repo until one is born")

    packages = example_packages(target)
    anchor = target
    if not packages:
        anchor = FALLBACK_SIBLING
        packages = example_packages(anchor)
        notes.append(f"{target} has no scripts/ tree on disk — structure "
                     f"anchored on {anchor} (the newborn mirrors it)")
    placement = suggest_placement(text, packages)

    sibling = None
    if placement:
        sibling = f"{anchor}/scripts/{placement}/"

    prose_tier = "judgment"
    if "_workspace_test" in low or "workspace_test" in low:
        prose_tier = "execution"
        notes.append("workspace_test scripts are code-heavy/doc-light — "
                     "execution tier per WORKFLOW.md")

    title = text.strip().splitlines()[0].lstrip("# ").strip()[:88]
    return {
        "title": title,
        "prompt_path": prompt_path,
        "family": family,
        "target_repo": target,
        "register": register,
        "placement": placement,
        "example_packages": packages,
        "sibling_to_mirror": sibling,
        "prose_tier": prose_tier,
        "format_checklist": CHECKLIST_SHARED + CHECKLIST_REGISTER[register],
        "format_grounding": [
            "the sibling example script (structure is copied, never invented)",
            "PyAutoHands notebook generation (docstring cells -> .ipynb)",
            "PyAutoBrain/skills/WORKFLOW.md — tutorial-prose split",
        ],
        "notes": notes,
        "next_action": (
            "route into start_dev (workflow: workspace) → start_workspace → "
            "author → ship_workspace; this decision writes nothing"
        ),
    }


def print_decision(d):
    print("== WorkspaceDecision (v0 — decision only, writes nothing) ==")
    print(f"Intent:               {d['title']}")
    if d["prompt_path"]:
        print(f"Prompt file:          {d['prompt_path']}")
    print(f"Family:               {d['family']}")
    print(f"Target repo:          {d['target_repo']}")
    print(f"Register:             {d['register']}")
    print(f"Placement:            {d['placement'] or '(no package matched — pick from below)'}")
    print(f"Example packages:     {', '.join(d['example_packages']) or '(none found)'}")
    print(f"Sibling to mirror:    {d['sibling_to_mirror'] or '(pick one after placement)'}")
    print(f"Prose tier:           {d['prose_tier']}")
    print("Format checklist:")
    for item in d["format_checklist"]:
        print(f"  - {item}")
    print("Format grounding (read these, never restate them):")
    for item in d["format_grounding"]:
        print(f"  - {item}")
    for n in d["notes"]:
        print(f"Note:                 {n}")
    print(f"Next action:          {d['next_action']}")


def count_scripts(path):
    return sum(1 for _ in path.rglob("*.py"))


def build_survey(args):
    target = args.repo
    root = scripts_root(target)
    packages = {p: count_scripts(scripts_root(target) / p)
                for p in example_packages(target)}
    if not root.is_dir():
        fail(4, f"'{target}' has no scripts/ tree under {PYAUTO_ROOT} — nothing "
                f"to survey (use `--against` on the sibling to plan a newborn)")

    survey = {
        "repo": target,
        "packages": packages,
        "total_scripts": sum(packages.values()),
    }
    if args.against:
        sibling = {p: count_scripts(scripts_root(args.against) / p)
                   for p in example_packages(args.against)}
        if not sibling:
            fail(4, f"sibling '{args.against}' has no scripts/ tree under {PYAUTO_ROOT}")
        survey["against"] = args.against
        survey["missing_packages"] = sorted(set(sibling) - set(packages))
        survey["extra_packages"] = sorted(set(packages) - set(sibling))
        survey["shared_packages"] = {
            p: {"repo": packages[p], "sibling": sibling[p]}
            for p in sorted(set(packages) & set(sibling))
        }
    return survey


def print_survey(s):
    print(f"== WorkspaceSurvey — {s['repo']} ==")
    print(f"Total scripts:        {s['total_scripts']}")
    print("Packages:")
    for p, n in s["packages"].items():
        print(f"  - {p:20s} {n:4d} script(s)")
    if "against" in s:
        print(f"Against sibling:      {s['against']}")
        for p in s["missing_packages"]:
            print(f"  ✗ missing package: {p}")
        for p in s["extra_packages"]:
            print(f"  + extra package:   {p}")
        for p, c in s["shared_packages"].items():
            print(f"  = {p:20s} {c['repo']:4d} vs {c['sibling']:4d}")


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "survey":
        parser = argparse.ArgumentParser(prog="workspace survey")
        parser.add_argument("repo", help="workspace/HowTo repo to inventory")
        parser.add_argument("--against", default=None,
                            help="sibling workspace repo to diff structure against")
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(argv[1:])
        survey = build_survey(args)
        print(json.dumps(survey, indent=2)) if args.json else print_survey(survey)
        sys.exit(0)

    parser = argparse.ArgumentParser(prog="workspace", description=__doc__)
    parser.add_argument("intent", nargs="?", default=None,
                        help="raw intent text, or a PyAutoMind prompt path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.intent or not args.intent.strip():
        fail(5, "no intent given — pass raw text, a PyAutoMind prompt path, or "
                "`survey <repo>`")
    decision = build_decision(args)
    print(json.dumps(decision, indent=2)) if args.json else print_decision(decision)
    sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""agents/conductors/clone/_clone.py — core for the Clone (Mitosis) Agent, v0.

v0 is DECISION ONLY (DESIGN.md "Phased implementation"): the `analyze` mode —
domain analysis, template-boundary partition, generation plan — emitting a
CloneDecision. It writes no repo, no file, no GitHub state; `--apply` (v1,
lightweight-seed births via PyAutoBuild) exits 5 with a pointer.

The generic-vs-domain partition is OWNED BY THE REFERENCE ASSISTANT
(`modes/maintainer.md`, "Assistant-as-template") — this agent reads that
section as its seed and translates its named sets into the path patterns
below. A reference file no pattern covers is reported `unclassified`:
deliberate pressure that keeps the reference's boundary notes complete
(fix the reference or extend the seed; never guess here).

The clone-mode question is MANDATORY and never defaulted:
  exact-clone | differentiated-sibling | lightweight-seed

Stdlib-only. Exit codes: 0 decision · 4 inputs unresolvable · 5 bad usage.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", Path.home() / "Code" / "PyAutoLabs"))

SEED_SECTION = "## Assistant-as-template"
SEED_MARKERS = (
    "**Generic assistant infrastructure**",
    "**PyAutoLens-specific content**",
    "**Mixed**",
)

# Path-pattern translation of the reference's three named sets (first match
# wins across GENERIC → DOMAIN → MIXED). Mirrors the prose of the
# Assistant-as-template section; when the section names something new, add
# its pattern here — unclassified files are how the gap surfaces.
GENERIC_PATTERNS = [
    "AGENTS.md", "CLAUDE.md", "LICENSE", ".gitignore", ".gitattributes",
    "Makefile", "__init__.py", "activate.sh", "version.txt",
    "CITATIONS.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md",
    "modes/*",                    # Teacher/Assistant mode machinery
    "skills/_style.md", "skills/_bootstrap_skill.md", "skills/README.md",
    "skills/start-new-project*", "skills/contribute-upstream*",
    "sources.yaml", "sources/*",  # the source-registry pattern
    "autoassistant/*",            # API gate + wiki-currency tooling
    ".github/*",                  # wiki-currency / citation workflows
    "wiki/README.md", "wiki/project/*",   # project wiki rules + profile template
    "scripts/AGENTS.md", "scripts/CLAUDE.md",
    # Harness mirrors of the generic machinery (.claude/, .gemini/):
    ".claude/hooks/*", ".claude/settings.json", ".gemini/*",
    ".claude/skills/_*", ".claude/skills/start-new-project*",
    ".claude/skills/contribute-upstream*",
]
DOMAIN_PATTERNS = [
    "skills/al_*.md",             # every al_* skill body
    ".claude/skills/al_*.md",     # ... and their harness mirrors
    "skills/init-slam.md", ".claude/skills/init-slam.md",  # SLAM = lensing
    "wiki/core/*", "wiki/literature/*",
    "dataset/*",
    "README.md",                  # science framing + the three example prompts
    "hpc/*",
]
MIXED_PATTERNS = [
    "llms.txt", "llms-full.txt",
    "config/*",
]

ACTIONS = {
    "generic": "copy (name substitutions only)",
    "domain": "regenerate or stub per clone mode — never copied blind",
    "mixed": "copy then adapt (named substitutions)",
}

VALIDATION_PLAN = [
    "newborn symbol audit (autoassistant API gate against the domain library)",
    "link sweep (no dangling wiki/skill cross-references)",
    "wiki-currency check (sources clone @ main, doc-pin truth)",
    "chat-surface smoke (llms.txt bootstrap on each supported surface)",
]


def fail(code, msg):
    print(f"clone: {msg}", file=sys.stderr)
    sys.exit(code)


def repo_root(name):
    path = PYAUTO_ROOT / name
    if not (path / ".git").exists():
        fail(4, f"repo '{name}' not checked out at {path}")
    return path


def head_sha(repo):
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    )
    return out.stdout.strip() or "unknown"


def tracked_files(repo):
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def check_seed_section(reference_root):
    maintainer = reference_root / "modes" / "maintainer.md"
    if not maintainer.exists():
        fail(4, f"reference has no modes/maintainer.md ({maintainer})")
    text = maintainer.read_text(errors="replace")
    if SEED_SECTION not in text or not all(m in text for m in SEED_MARKERS):
        fail(4,
             "the reference's 'Assistant-as-template' section (the partition "
             "seed this agent reads) is missing or restructured — realign the "
             "patterns in _clone.py with the reference before cloning")


def match_any(path, patterns):
    return any(
        fnmatch.fnmatch(path, p) or (p.endswith("/*") and path.startswith(p[:-1]))
        for p in patterns
    )


def partition(reference_root):
    sets = {"generic": [], "domain": [], "mixed": [], "unclassified": []}
    for path in tracked_files(reference_root):
        if match_any(path, GENERIC_PATTERNS):
            sets["generic"].append(path)
        elif match_any(path, DOMAIN_PATTERNS):
            sets["domain"].append(path)
        elif match_any(path, MIXED_PATTERNS):
            sets["mixed"].append(path)
        else:
            sets["unclassified"].append(path)
    return sets


def library_package(library_root):
    for child in sorted(library_root.iterdir()):
        init = child / "__init__.py"
        if child.is_dir() and init.exists() and "__version__" in init.read_text(errors="replace"):
            return child.name
    fail(4, f"no package with __version__ found under {library_root}")


def public_api(library_root, package):
    init = library_root / package / "__init__.py"
    tree = ast.parse(init.read_text(errors="replace"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if not name.startswith("_") and name != "*":
                    names.add(name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
    return sorted(names)


def workspace_shape(workspace_root):
    scripts = workspace_root / "scripts"
    if not scripts.is_dir():
        return {"script_dirs": [], "n_scripts": 0, "start_here": False}
    dirs = sorted(d.name for d in scripts.iterdir() if d.is_dir() and not d.name.startswith("_"))
    n = len(list(scripts.rglob("*.py")))
    return {
        "script_dirs": dirs,
        "n_scripts": n,
        "start_here": (scripts / "start_here.py").exists(),
    }


def howto_shape(howto_root):
    chapters = sorted({
        d.name for d in howto_root.rglob("chapter*")
        if d.is_dir() and ".git" not in d.parts
    })
    return {"chapters": chapters}


def build_decision(args):
    library_root = repo_root(args.library)
    workspace_root_ = repo_root(args.workspace)
    howto_root = repo_root(args.howto) if args.howto else None
    reference_root = repo_root(args.reference)

    check_seed_section(reference_root)
    sets = partition(reference_root)

    package = library_package(library_root)
    api = public_api(library_root, package)
    target = f"{package}_assistant"

    risks = []
    if sets["unclassified"]:
        risks.append(
            f"{len(sets['unclassified'])} reference file(s) unclassified — the "
            "reference's boundary notes (or this agent's patterns) have a gap; "
            "fix there before any --apply"
        )
    if not args.howto:
        risks.append("no HowTo repo given — teaching-corpus signal missing for regeneration")
    ws = workspace_shape(workspace_root_)
    if not ws["start_here"] and "start_here" not in " ".join(ws["script_dirs"]):
        risks.append("workspace has no scripts/start_here.py — weak front-door signal")
    if (PYAUTO_ROOT / target).exists():
        risks.append(f"target '{target}' already exists locally — name collision")

    return {
        "sources": {
            "library": f"{args.library} @ {head_sha(library_root)} (package {package})",
            "workspace": f"{args.workspace} @ {head_sha(workspace_root_)}",
            "howto": f"{args.howto} @ {head_sha(howto_root)}" if howto_root else None,
        },
        "reference": f"{args.reference} @ {head_sha(reference_root)}",
        "target": target,
        "clone_mode_question": (
            "exact-clone | differentiated-sibling | lightweight-seed "
            "(mandatory — a human answers before any --apply)"
        ),
        "domain_analysis": {
            "public_api": {"count": len(api), "sample": api[:12]},
            "workspace": ws,
            "howto": howto_shape(howto_root) if howto_root else None,
        },
        "partition": {k: len(v) for k, v in sets.items()},
        "unclassified": sets["unclassified"],
        "generation_plan": {
            k: {"files": len(sets[k]), "action": ACTIONS[k]} for k in ACTIONS
        },
        "validation_plan": VALIDATION_PLAN,
        "risks": risks or ["none identified"],
        "next_action": (
            "human confirms the clone mode → v1 hands the plan to PyAutoBuild "
            "(lightweight-seed first); v0 writes nothing"
        ),
    }


def print_decision(d):
    print("== CloneDecision (v0 — analyze, writes nothing) ==")
    print(f"Library:              {d['sources']['library']}")
    print(f"Workspace:            {d['sources']['workspace']}")
    print(f"HowTo:                {d['sources']['howto'] or '(none)'}")
    print(f"Reference assistant:  {d['reference']}")
    print(f"Target:               {d['target']}")
    print(f"Clone mode:           {d['clone_mode_question']}")
    api = d["domain_analysis"]["public_api"]
    print(f"Public API:           {api['count']} symbols (e.g. {', '.join(api['sample'][:6])})")
    ws = d["domain_analysis"]["workspace"]
    print(f"Workspace shape:      {ws['n_scripts']} scripts; dirs: {', '.join(ws['script_dirs'][:8])}")
    if d["domain_analysis"]["howto"]:
        print(f"HowTo chapters:       {', '.join(d['domain_analysis']['howto']['chapters'])}")
    p = d["partition"]
    print(f"Partition:            generic {p['generic']} · domain {p['domain']} · "
          f"mixed {p['mixed']} · unclassified {p['unclassified']}")
    for path in d["unclassified"]:
        print(f"  ✗ unclassified: {path}")
    print("Generation plan:")
    for k, v in d["generation_plan"].items():
        print(f"  - {k:8s} {v['files']:4d} file(s) → {v['action']}")
    print("Validation plan (Heart legs the newborn must pass):")
    for leg in d["validation_plan"]:
        print(f"  - {leg}")
    print("Risks:")
    for r in d["risks"]:
        print(f"  - {r}")
    print(f"Next action:          {d['next_action']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", help="source library repo, e.g. PyAutoFit")
    parser.add_argument("--workspace", required=True, help="the library's workspace repo")
    parser.add_argument("--howto", default=None, help="optional HowTo repo")
    parser.add_argument("--reference", default="autolens_assistant",
                        help="reference assistant repo (default: autolens_assistant)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.apply:
        fail(5, "--apply is v1 (lightweight-seed births via PyAutoBuild) — "
                "v0 is decision-only; see agents/conductors/clone/DESIGN.md")

    decision = build_decision(args)
    if args.json:
        print(json.dumps(decision, indent=2))
    else:
        print_decision(decision)
    sys.exit(0)


if __name__ == "__main__":
    main()

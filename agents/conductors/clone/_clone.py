#!/usr/bin/env python3
"""agents/conductors/clone/_clone.py — core for the Clone (Mitosis) Agent, v0.

analyze (default) is decision only. v1 adds `--apply --mode
lightweight-seed`: the agent writes its generation plan as JSON and hands
execution to PyAutoHands's `clone_seed.py` primitive (repo creation
PRIVATE-first; the newborn's publish gate is Heart's newborn-validation
checklist). The agent itself still writes no repo and no GitHub state — the
mandatory clone-mode question is answered by the human typing `--mode`.
Other modes (exact-clone, differentiated-sibling) are v2 and exit 5.

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

# The generic-vs-domain seam is OWNED BY THE REFERENCE ASSISTANT and differs
# between references — a domain assistant (autolens_assistant) ships its domain
# in `al_*` skills and a lensing-API `wiki/core/`, whereas the domain-agnostic
# base (autofit_assistant) keeps `af_*` inference skills and a *statistics*
# `wiki/core/` as GENERIC and leaves domain content to be grown. So each
# supported reference names its own markers + path-pattern sets below; add a
# profile when a new reference is used as a template. Within a profile the
# first match wins across GENERIC → DOMAIN → MIXED; an uncovered reference file
# is reported `unclassified` — deliberate pressure that keeps the boundary
# notes complete (fix the reference or extend its profile; never guess here).

# Framework/infrastructure shared by every assistant, regardless of domain.
_SHARED_GENERIC = [
    "AGENTS.md", "CLAUDE.md", "LICENSE", ".gitignore", ".gitattributes",
    "Makefile", "__init__.py", "activate.sh", "version.txt",
    "CITATIONS.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md",
    "modes/*",                    # Teacher/Assistant mode machinery
    "skills/_style.md", "skills/_bootstrap_skill.md", "skills/README.md",
    "skills/start-new-project*", "skills/contribute-upstream*",
    "sources.yaml", "sources/*",  # the source-registry pattern
    "autoassistant/*",            # API gate + wiki-currency + benchmark tooling
    ".mcp.json",                  # wires the results-inspector MCP, which is
                                  # `autoassistant.mcp` — generic tooling above,
                                  # so the wiring carries no domain either
    "benchmarks/AGENTS.md",       # benchmark run/record contract
    ".github/*",                  # wiki-currency / citation workflows
    "wiki/README.md", "wiki/project/*",   # project wiki rules + profile template
    "scripts/AGENTS.md", "scripts/CLAUDE.md", "scripts/README.md",
    # Harness mirrors of the generic machinery (.claude/, .gemini/):
    ".claude/hooks/*", ".claude/settings.json", ".gemini/*",
    ".claude/skills/_*", ".claude/skills/start-new-project*",
    ".claude/skills/contribute-upstream*",
]

# Domain content a newborn regenerates/stubs rather than copies blind, shared
# by every reference (per-clone example data, science framing, HPC recipes).
# NB: `wiki/literature/` is reference-specific — a real paper corpus (domain)
# in a domain assistant, but the near-empty framework scaffold (generic) in the
# domain-agnostic base — so each profile places it, not this shared set.
_SHARED_DOMAIN = [
    "dataset/*",
    "README.md",                  # science framing + the example prompts
    "hpc/*",
    "benchmarks/prompts/*",       # prompt cards — a new domain writes its own
    # A newborn starts with empty runs/ and regenerates RESULTS.md.
    "benchmarks/runs/*", "benchmarks/RESULTS.md",
]

_SHARED_MIXED = [
    "llms.txt", "llms-full.txt",
    "config/*",
    "benchmarks/README.md",       # protocol generic, benchmark table domain
]

REFERENCE_PROFILES = {
    # A domain assistant: its domain lives in `al_*` skills + a lensing-API
    # `wiki/core/`, so those are DOMAIN (regenerated per clone).
    "autolens_assistant": {
        "markers": (
            "**Generic assistant infrastructure**",
            "**PyAutoLens-specific content**",
            "**Mixed**",
        ),
        "generic": _SHARED_GENERIC,
        "domain": [
            "skills/al_*.md",             # every al_* skill body
            ".claude/skills/al_*.md",     # ... and their harness mirrors
            "skills/init-slam.md", ".claude/skills/init-slam.md",  # SLAM = lensing
            # The euclid mode: a survey-specific pipeline register (its skills
            # + its own sub-wiki). Lensing science throughout — a newborn grows
            # whatever survey modes its own domain has, if any.
            "skills/euclid_*.md", ".claude/skills/euclid_*.md",
            "wiki/euclid/*",
            "wiki/core/*",                # lensing-API reference
            "wiki/literature/*",          # a shipped lensing paper corpus
            "paper/*",                    # this assistant's own JOSS paper
            "scripts/*.py",               # bundled science scripts (a named lens)
            *_SHARED_DOMAIN,
        ],
        "mixed": _SHARED_MIXED,
        "scaffold_dirs": ["wiki/core", "wiki/literature", "dataset", "hpc"],
    },
    # The domain-agnostic base: `af_*` inference skills and the *statistics*
    # `wiki/core/` are GENERIC infrastructure kept verbatim; only the example
    # datasets, science framing and HPC recipes are domain content to regrow.
    "autofit_assistant": {
        "markers": (
            "**Generic assistant infrastructure**",
            "**Domain-specific content**",
            "**Mixed**",
        ),
        "generic": [
            *_SHARED_GENERIC,
            "skills/af_*.md",             # generic inference skills
            ".claude/skills/af_*.md",     # ... and their harness mirrors
            "wiki/core/*",                # statistics/inference reference
            "wiki/literature/*",          # the near-empty literature scaffold
        ],
        "domain": list(_SHARED_DOMAIN),
        "mixed": _SHARED_MIXED,
        "scaffold_dirs": ["dataset", "hpc"],
    },
}

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


def reference_profile(reference_name):
    profile = REFERENCE_PROFILES.get(reference_name)
    if profile is None:
        fail(4,
             f"no clone profile for reference '{reference_name}' — supported "
             f"references: {', '.join(sorted(REFERENCE_PROFILES))}. Add a "
             "profile to REFERENCE_PROFILES (and an 'Assistant-as-template' "
             "section to the reference's modes/maintainer.md) before cloning.")
    return profile


def check_seed_section(reference_root, profile):
    maintainer = reference_root / "modes" / "maintainer.md"
    if not maintainer.exists():
        fail(4, f"reference has no modes/maintainer.md ({maintainer})")
    text = maintainer.read_text(errors="replace")
    if SEED_SECTION not in text or not all(m in text for m in profile["markers"]):
        fail(4,
             "the reference's 'Assistant-as-template' section (the partition "
             "seed this agent reads) is missing or restructured — realign the "
             "reference's profile in _clone.py with its maintainer.md before "
             "cloning")


def match_any(path, patterns):
    return any(
        fnmatch.fnmatch(path, p) or (p.endswith("/*") and path.startswith(p[:-1]))
        for p in patterns
    )


def partition(reference_root, profile):
    sets = {"generic": [], "domain": [], "mixed": [], "unclassified": []}
    for path in tracked_files(reference_root):
        if match_any(path, profile["generic"]):
            sets["generic"].append(path)
        elif match_any(path, profile["domain"]):
            sets["domain"].append(path)
        elif match_any(path, profile["mixed"]):
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
    profile = reference_profile(args.reference)

    check_seed_section(reference_root, profile)
    sets = partition(reference_root, profile)

    package = library_package(library_root)
    api = public_api(library_root, package)
    # A domain assistant's name comes from its domain (--target ic50_assistant),
    # not its library; default to the library-derived name for back-compat.
    target = args.target or f"{package}_assistant"

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
            "human confirms the clone mode + the repo-creation gate (name / "
            "owner / visibility), then re-run with --apply --mode "
            "lightweight-seed to hand the plan to Build (--no-push builds the "
            "seed tree only); this run wrote nothing"
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


def reference_library(reference_name):
    """The reference assistant's own domain (package, LibraryRepo) pair,
    derived from its name (e.g. autolens_assistant -> autolens, PyAutoLens)."""
    package = reference_name.replace("_assistant", "")
    want = f"pyauto{package[4:]}" if package.startswith("auto") else None
    for child in sorted(PYAUTO_ROOT.iterdir()):
        if child.is_dir() and child.name.lower() == want:
            return package, child.name
    fail(4, f"cannot resolve the reference's library repo for '{reference_name}'")


def repo_owner(repo_root):
    out = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    url = out.stdout.strip().removesuffix(".git")
    return url.rstrip("/").split("/")[-2].split(":")[-1]


def apply_seed(args, decision):
    """v1: emit the generation plan and hand execution to Build (clone_seed)."""
    import tempfile

    reference_root = repo_root(args.reference)
    library_root = repo_root(args.library)
    profile = reference_profile(args.reference)
    ref_pkg, ref_lib = reference_library(args.reference)
    target_pkg = library_package(library_root)
    target = decision["target"]

    sets = partition(reference_root, profile)
    if sets["unclassified"]:
        fail(4, "unclassified reference files — fix the boundary before a birth")

    plan = {
        "target": target,
        "owner": args.owner or repo_owner(reference_root),
        "reference_path": str(reference_root),
        "substitutions": [
            # repo identity first (most specific): the full assistant name,
            # e.g. autofit_assistant -> ic50_assistant
            [args.reference, target],
            # skill prefix (al_ -> af_): package initials, e.g.
            # autolens -> al, autofit -> af. Word-anchored: unanchored, this
            # two-letter rule also rewrites the `al_` inside `total_draws`,
            # `external_shear` and `radial_minimum` (it did, in autocti_assistant
            # — PyAutoBrain#150).
            [f"{ref_pkg[0]}{ref_pkg[4]}_", f"{target_pkg[0]}{target_pkg[4]}_", "word"],
            [ref_lib, args.library],       # PyAutoLens -> PyAutoFit
            [ref_pkg, target_pkg],         # autolens -> autofit
        ],
        "generic": sets["generic"],
        "mixed": sets["mixed"],
        "domain": sets["domain"],
        "scaffold_dirs": profile["scaffold_dirs"],
    }
    plan_path = Path(tempfile.mkstemp(prefix="clone_plan_", suffix=".json")[1])
    plan_path.write_text(json.dumps(plan, indent=2))

    seed_script = PYAUTO_ROOT / "PyAutoHands" / "autobuild" / "clone_seed.py"
    if not seed_script.exists():
        fail(4, f"Build primitive not found: {seed_script}")
    cmd = [sys.executable, str(seed_script), str(plan_path)]
    if not args.no_push:
        cmd.append("--push")
    print(f"\n== handing the plan to Build: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        fail(4, "Build's clone_seed failed — see its output")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", help="source library repo, e.g. PyAutoFit")
    parser.add_argument("--workspace", required=True, help="the library's workspace repo")
    parser.add_argument("--howto", default=None, help="optional HowTo repo")
    parser.add_argument("--reference", default="autolens_assistant",
                        help="reference assistant repo (default: autolens_assistant)")
    parser.add_argument("--target", default=None,
                        help="newborn assistant name (e.g. ic50_assistant); "
                             "default: <library-package>_assistant. A domain "
                             "assistant's name comes from its domain, not its "
                             "library, so set this when they differ.")
    parser.add_argument("--owner", default=None,
                        help="GitHub owner to create the newborn under "
                             "(default: the reference's owner)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mode", choices=["lightweight-seed"], default=None,
                        help="the clone mode (mandatory with --apply; typing it "
                             "is the human's answer to the clone-mode question)")
    parser.add_argument("--no-push", action="store_true",
                        help="with --apply: build the seed tree only, do not "
                             "create/push the repo")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.apply and args.mode != "lightweight-seed":
        fail(5, "--apply requires --mode lightweight-seed (the human-answered "
                "clone-mode question); exact-clone / differentiated-sibling "
                "are v2 — see agents/conductors/clone/DESIGN.md")

    decision = build_decision(args)
    if args.json:
        print(json.dumps(decision, indent=2))
    else:
        print_decision(decision)

    if args.apply:
        apply_seed(args, decision)
    sys.exit(0)


if __name__ == "__main__":
    main()

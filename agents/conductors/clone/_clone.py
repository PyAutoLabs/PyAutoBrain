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

`sync` is the SECOND mode, and it is not a birth: it keeps assistants that were
already born from drifting apart on the files the boundary calls generic. It is
NOT a blind overwrite — it takes the REFERENCE's own diff over a commit range,
restricted to the `_SHARED_GENERIC` set, rewrites the names in it for each
sibling, and applies it as a patch. A hunk that no longer fits the sibling is
REJECTED and reported, never resolved silently: a sibling's domain adaptations
outrank the reference's text, and only a human decides what a conflict means.
Dry run by default; `--apply` writes (and leaves `.rej` files for the human).

Stdlib-only (GNU `patch` for the apply). Exit codes: 0 decision / clean sync ·
1 sync completed with rejected hunks · 4 inputs unresolvable · 5 bad usage.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Workspace root via the one shared resolver (agents/_pyauto_root.py, mirrored
# by bin/_pyauto_root.sh): PYAUTO_ROOT, else beside this checkout, else the
# developer box. Naming an absolute workspace path as the *default* here
# resolved into
# a non-existent tree in a remote session and reported empty rather than
# failing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import _pyauto_root  # noqa: E402

PYAUTO_ROOT = _pyauto_root.pyauto_root()

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
    "AI_POLICY.md", "CITATIONS.md", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md",
    "AGENTS_CHAT.md",             # chat-mode counterpart of AGENTS.md: the same
                                  # skeleton with the shell-dependent rules cut,
                                  # so it clones on the same terms as AGENTS.md
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
    "llms-chat.txt",              # generated paste bundle: same seam as llms.txt
    "FREE_TIER_SETUP.md",         # per-platform chat setup — the platform
                                  # mechanics clone verbatim, the worked prompts
                                  # and dataset names are domain
    "CHOOSING_YOUR_AI_TOOL.md",   # the other half of that free-tier chat
                                  # surface: which tool to use and how to set it
                                  # up clones verbatim, the domain naming and
                                  # worked examples do not
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
            "docs/*",                     # README figure assets (named-lens
                                          # imagery + the script that renders
                                          # it) — a newborn regrows its own
            "wiki/core/*",                # lensing-API reference
            "wiki/literature/*",          # a shipped lensing paper corpus
            "paper/*",                    # this assistant's own JOSS paper
            "scripts/*.py",               # bundled science scripts (a named lens)
            # Generated chat knowledge pack: concatenated al_* skill bodies +
            # wiki/core pages + a snapshot of the lensing stack's API surface.
            # Every input is domain, so a newborn regenerates it from its own
            # content (`make chat-bundle`) rather than copying this one.
            "chat_pack/*",
            *_SHARED_DOMAIN,
        ],
        "mixed": _SHARED_MIXED,
        "scaffold_dirs": ["wiki/core", "wiki/literature", "dataset", "hpc", "chat_pack"],
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
            # `external_shear` and `radial_minimum` (it did, in a sibling
            # assistant clone — PyAutoBrain#150).
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

    seed_script = PYAUTO_ROOT / "PyAutoHands" / "autohands" / "clone_seed.py"
    if not seed_script.exists():
        fail(4, f"Build primitive not found: {seed_script}")
    cmd = [sys.executable, str(seed_script), str(plan_path)]
    if not args.no_push:
        cmd.append("--push")
    print(f"\n== handing the plan to Build: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        fail(4, "Build's clone_seed failed — see its output")


# ---------------------------------------------------------------------------
# sync — keep the born siblings from drifting on the generic files
#
# Birth copies the reference once; nothing re-synced afterwards, so the four
# copies of `skills/start-new-project.md` and `wiki/project/*` grew four
# distinct hashes. This mode replays the REFERENCE's own diff over a commit
# range onto each sibling, restricted to that reference's generic set, with the
# same name substitutions birth uses. It applies with GNU `patch`, so a hunk
# whose context the sibling has adapted away is REJECTED and listed rather than
# forced: the sibling's domain adaptation outranks the reference's prose, and
# only a human decides what a conflict means.
#
# "Since the sibling's last sync" is read from the sibling's own git history: a
# sync commit carries the trailer `Clone-sync: <reference>@<sha>`. No new state
# file, and the pointer travels with the commit that consumed the patch.
# ---------------------------------------------------------------------------

SYNC_TRAILER = "Clone-sync"


def substitute(text, subs):
    """Apply name-substitution rules to `text`.

    Mirrors PyAutoHands `clone_seed.substitute` — the birth-side implementation
    of the same contract — so a synced line reads exactly as a born one would.
    A rule is `(old, new)` or `(old, new, "word")`; the latter requires `old` to
    start at a word boundary, because the two-letter skill prefixes (`al_`,
    `af_`) otherwise match inside `total_draws` / `external_shear`.
    """
    for rule in subs:
        old, new = rule[0], rule[1]
        if len(rule) > 2 and rule[2] == "word":
            text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(old)}", new, text)
        else:
            text = text.replace(old, new)
    return text


def sync_substitutions(reference_name, target_name):
    """The reference -> sibling rename rules, most specific first.

    Birth omits the UPPERCASE rule, so a newborn inherits the reference's
    `$<REFERENCE>_ASSISTANT` env-var name in its generated project scaffold —
    still visible in a sibling born before this. Sync carries the rule, so
    newly synced lines are right even where the old ones are not; sync only
    ever touches the lines in the patch, so it does not retro-fix them.
    """
    ref_pkg, ref_lib = reference_library(reference_name)
    tgt_pkg, tgt_lib = reference_library(target_name)
    return [
        (reference_name, target_name),
        (f"{ref_pkg[0]}{ref_pkg[4]}_", f"{tgt_pkg[0]}{tgt_pkg[4]}_", "word"),
        (ref_lib, tgt_lib),
        (ref_pkg.upper(), tgt_pkg.upper()),
        (ref_pkg, tgt_pkg),
    ]


def git(repo, *args, check=False):
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
    )
    if check and out.returncode != 0:
        fail(4, f"git {' '.join(args)} failed in {repo}: {out.stderr.strip()}")
    return out


def discover_targets(reference_name):
    """Sibling assistants checked out beside the reference."""
    return sorted(
        child.name
        for child in PYAUTO_ROOT.iterdir()
        if child.is_dir()
        and child.name.endswith("_assistant")
        and child.name != reference_name
        and (child / ".git").exists()
    )


def last_sync_rev(target_root, reference_name):
    """The reference sha recorded by this sibling's most recent sync commit."""
    out = git(target_root, "log", "-n", "1",
              f"--grep=^{SYNC_TRAILER}: {reference_name}@", "--format=%B")
    match = re.search(
        rf"^{SYNC_TRAILER}: {re.escape(reference_name)}@(\S+)",
        out.stdout, re.MULTILINE,
    )
    return match.group(1) if match else None


def changed_generic_files(reference_root, profile, since, until):
    """(path, status) for every generic file the reference changed in range."""
    out = git(reference_root, "diff", "--name-status", f"{since}..{until}",
              check=True)
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if match_any(path, profile["generic"]):
            rows.append((path, status[0]))
    return sorted(rows)


def substituted_patch(reference_root, since, until, path, subs):
    """The reference's diff for one path, renamed for the target.

    Only the CONTENT lines are substituted (` `, `+`, `-`), never the `---` /
    `+++` / `diff --git` headers or the `@@` ranges: the generic paths are the
    same in every sibling, and rewriting a header would send the hunk to a file
    that does not exist.
    """
    out = git(reference_root, "diff", f"{since}..{until}", "--", path, check=True)
    lines = []
    for line in out.stdout.splitlines(keepends=True):
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "@@",
                            "new file mode", "deleted file mode",
                            "old mode", "new mode", "similarity index",
                            "rename from", "rename to")):
            lines.append(line)
        else:
            lines.append(substitute(line, subs))
    return "".join(lines)


def apply_patch(target_root, patch_text, dry_run):
    """Run GNU patch; return (status, detail).

    status is one of: applied · created · already-applied · rejected · error.
    """
    if shutil.which("patch") is None:
        fail(4, "GNU `patch` not found on PATH — sync applies patches with it")
    handle, name = tempfile.mkstemp(prefix="clone_sync_", suffix=".patch")
    Path(name).write_text(patch_text)
    cmd = ["patch", "-p1", "--forward", "--fuzz=3",
           "--no-backup-if-mismatch", "-i", name]
    if dry_run:
        cmd.insert(1, "--dry-run")
    out = subprocess.run(cmd, cwd=str(target_root), capture_output=True, text=True)
    Path(name).unlink(missing_ok=True)
    text = out.stdout + out.stderr
    failed = re.findall(r"Hunk #(\d+) FAILED", text)
    if failed:
        return "rejected", f"hunks {', '.join('#' + h for h in failed)} rejected"
    if "Reversed (or previously applied) patch detected" in text:
        return "already-applied", "sibling already carries this change"
    if out.returncode != 0:
        return "error", text.strip().splitlines()[-1] if text.strip() else "patch failed"
    return "applied", ""


def run_sync(args):
    reference_root = repo_root(args.reference)
    profile = reference_profile(args.reference)
    until = args.until
    targets = args.target or discover_targets(args.reference)
    if not targets:
        fail(4, f"no sibling assistants found beside {args.reference}")

    report = {
        "reference": f"{args.reference} @ {head_sha(reference_root)}",
        "until": until,
        "dry_run": not args.apply,
        "targets": {},
    }
    rejected_any = False

    for name in targets:
        target_root = repo_root(name)
        since = args.since or last_sync_rev(target_root, args.reference)
        if since is None:
            report["targets"][name] = {
                "since": None,
                "error": (
                    f"no --since given and no `{SYNC_TRAILER}: {args.reference}@<sha>` "
                    "trailer in this sibling's history — pass --since <rev> for "
                    "the first sync"
                ),
                "files": [],
            }
            rejected_any = True
            continue

        subs = sync_substitutions(args.reference, name)
        files = []
        for path, status in changed_generic_files(reference_root, profile, since, until):
            if status in ("R", "D"):
                files.append({"path": path, "result": "unsupported",
                              "detail": f"reference {status} (rename/delete) — do it by hand"})
                rejected_any = True
                continue
            exists = (target_root / path).exists()
            if status == "M" and not exists:
                files.append({"path": path, "result": "absent",
                              "detail": "file not present in this sibling"})
                continue
            if status == "A" and exists:
                files.append({"path": path, "result": "skipped",
                              "detail": "reference ADDED this file and the sibling "
                                        "already has one — compare the two by hand"})
                continue
            patch_text = substituted_patch(reference_root, since, until, path, subs)
            if not patch_text.strip():
                files.append({"path": path, "result": "unchanged", "detail": ""})
                continue
            result, detail = apply_patch(target_root, patch_text, dry_run=not args.apply)
            if status == "A" and result == "applied":
                result = "created"
            if result in ("rejected", "error"):
                rejected_any = True
            files.append({"path": path, "result": result, "detail": detail})

        report["targets"][name] = {"since": since, "files": files}

    report["next_action"] = (
        "review the report; re-run with --apply to write (rejected hunks land as "
        "`.rej` files a human resolves), and put "
        f"`{SYNC_TRAILER}: {args.reference}@{head_sha(reference_root)}` in the "
        "sibling's sync commit so the next run knows where it got to"
        if not args.apply else
        "resolve any `.rej` files by hand, delete them, then commit with "
        f"`{SYNC_TRAILER}: {args.reference}@{head_sha(reference_root)}` in the message"
    )
    return report, rejected_any


_SYNC_GLYPH = {
    "applied": "OK ", "created": "NEW", "unchanged": "-- ",
    "already-applied": "== ", "absent": "?? ", "skipped": "?? ",
    "rejected": "XX ",
    "error": "XX ", "unsupported": "XX ",
}


def print_sync(report):
    mode = "dry run — writes nothing" if report["dry_run"] else "APPLY — writes"
    print(f"== CloneSync ({mode}) ==")
    print(f"Reference:  {report['reference']}")
    print(f"Until:      {report['until']}")
    for name, block in report["targets"].items():
        print(f"\n{name}  (since {block['since'] or '?'})")
        if block.get("error"):
            print(f"  XX  {block['error']}")
            continue
        if not block["files"]:
            print("  -- nothing generic changed in range")
            continue
        for row in block["files"]:
            detail = f" — {row['detail']}" if row["detail"] else ""
            print(f"  {_SYNC_GLYPH[row['result']]} {row['path']:<48s} "
                  f"{row['result']}{detail}")
        counts = {}
        for row in block["files"]:
            counts[row["result"]] = counts.get(row["result"], 0) + 1
        print("  summary: " + " · ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    print(f"\nNext action: {report['next_action']}")


def sync_main(argv):
    parser = argparse.ArgumentParser(
        prog="pyauto-brain clone sync",
        description="Re-apply the reference assistant's generic-file changes to "
                    "its born siblings as a reviewable patch (dry run by default).",
    )
    parser.add_argument("--reference", default="autolens_assistant",
                        help="the reference assistant the diff comes from "
                             "(default: autolens_assistant)")
    parser.add_argument("--target", action="append", default=None,
                        help="sibling to sync (repeatable; default: every "
                             "*_assistant checked out beside the reference)")
    parser.add_argument("--since", default=None,
                        help="reference rev to diff from (default: the sha in "
                             f"each sibling's last `{SYNC_TRAILER}:` commit trailer)")
    parser.add_argument("--until", default="HEAD",
                        help="reference rev to diff to (default: HEAD)")
    parser.add_argument("--apply", action="store_true",
                        help="write the patches (default: dry run)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report, rejected = run_sync(args)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_sync(report)
    sys.exit(1 if rejected else 0)


def main():
    # `sync` is a mode, not a library: it takes no library/workspace pair, so it
    # gets its own parser rather than optional-ing out every analyze argument.
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        sync_main(sys.argv[2:])

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

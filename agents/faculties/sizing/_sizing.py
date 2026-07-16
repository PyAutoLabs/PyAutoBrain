#!/usr/bin/env python3
"""agents/faculties/sizing/_sizing.py — the shared sizing substrate.

The **sizing faculty** is a read-only opinion sink (it never writes, never
dispatches): given a PyAutoMind prompt, it parses its structure and estimates how
hard the work is. Both conductors that reason over Mind intent consult it:

  - the **Feature Agent** (`agents/conductors/feature/`) sizes a task at
    *selection / planning* time;
  - the **Intake Agent** (`agents/conductors/intake/`) sizes a task at
    *conception* time and persists the estimate into the prompt's `Difficulty:`
    header, so the number you see up front is the same one the Feature Agent
    acts on later.

Keeping the heuristic here — one definition, imported by both — is the whole
point: a value Intake persists that the Feature Agent silently recomputed with a
divergent copy would be a drift bug. This module therefore also owns the shared
prompt-parsing primitives and the PyAutoMind taxonomy/vocabulary both agents key
off (mirrors PyAutoMind/ROUTING.md).

It is intentionally dependency-free (stdlib only) and never writes anything.

Calibration status: reviewed 2026-07-09 against the first 59 rows of
PyAutoMind/autonomy_log.md (AUTONOMY.md "Calibration review — 2026-07-09").
The conception heuristics held — zero rejected outcomes; the work-type cap,
not this estimate, was the binding clamp — so the scoring below is unchanged.
`too-large` is a routing signal, not a difficulty grade: such prompts go to a
decomposition pass, never straight to dispatch (intake AGENTS.md).
"""
from __future__ import annotations

import re
from pathlib import Path

# --- the PyAutoMind taxonomy (mirrors PyAutoMind/ROUTING.md) -----------------
# work-type folder -> the kind of work it holds.
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

# --- policy + body-map loaders (the extraction seam, PyAutoBrain#75) ---------
# Vocabulary lives in PyAutoBrain/config/policy.yaml (a declared config
# surface an adopting fork replaces); repo IDENTITY derives from the body map
# (PyAutoMind/repos.yaml) at runtime. Both loads are strict — these tables
# are load-bearing for routing, so a missing file is a setup bug that must
# fail loudly, never silently degrade.

BRAIN_HOME = Path(__file__).resolve().parents[3]
POLICY_PATH = BRAIN_HOME / "config" / "policy.yaml"
BODY_MAP_PATH = BRAIN_HOME.parent / "PyAutoMind" / "repos.yaml"

_POLICY_CACHE: dict = {}


def policy() -> dict:
    if not _POLICY_CACHE:
        import yaml

        _POLICY_CACHE.update(yaml.safe_load(POLICY_PATH.read_text()))
    return _POLICY_CACHE


def _body_map_categories() -> dict:
    """repo name -> category, from the body map (the single source of repo
    identity)."""
    import yaml

    data = yaml.safe_load(BODY_MAP_PATH.read_text())
    return {name: spec["category"] for name, spec in data["repos"].items()}


def _target_sets() -> tuple[set, set, set]:
    cats = _body_map_categories()
    pol = policy()
    grouping = pol["sizing_categories"]

    def names_for(kind):
        wanted = set(grouping[kind])
        out = set()
        for name, cat in cats.items():
            if cat in wanted:
                out.add(name.lower())
                if name.lower().startswith("pyauto"):
                    out.add(name.lower()[2:])  # PyAutoFit -> autofit package form
        return out

    libraries = names_for("library")
    workspaces = names_for("workspace") | set(pol["extra_workspace_targets"])
    organism = names_for("organism") | set(pol["extra_organism_targets"])
    return libraries, workspaces, organism


# Targets that are source *libraries* (work classifies as library vs workspace),
# workspaces/tutorials/example repos, and the organism's own organs — all
# derived from the body map's categories per the policy's grouping.
LIBRARY_REPOS, WORKSPACE_REPOS, ORGANISM_REPOS = _target_sets()

# Normalise an @-mention or folder name to a canonical key.
REPO_ALIASES = policy()["repo_aliases"]

# --- PyAutoMemory sub-wiki routing (shared science vocabulary) ----------------
# Map keywords -> the PyAutoMemory sub-wiki that holds relevant context. This is
# also the canonical *science vocabulary* difficulty scoring keys off (see
# SCIENCE_KEYWORDS), so it lives here in the shared substrate rather than being
# duplicated. Source of truth for the sub-wiki list: PyAutoMemory/index.md.
MEMORY_WIKIS = policy()["memory_wikis"]

SCIENCE_KEYWORDS = sorted({kw for kws in MEMORY_WIKIS.values() for kw in kws})
RISK_KEYWORDS = ["api", "breaking", "backwards", "migrat", "deprecat",
                 "cross-repo", "interface", "refactor", "rename", "public api"]
AMBIGUITY_KEYWORDS = ["unclear", "investigate", "explore", "research", "decide",
                      "figure out", "not sure", "tbd", "open question", "design",
                      "proof of concept", "prototype", "spike", "?"]
TEST_KEYWORDS = ["test", "smoke", "parity", "jax", "likelihood", "vmap",
                 "validation", "regression"]

KNOWN_REPOS = LIBRARY_REPOS | WORKSPACE_REPOS | ORGANISM_REPOS


def normalise_repo(name: str) -> str:
    # Take the head token before any '.' or '/': an @-mention may be an API path
    # (e.g. @aa.decorators.to_vector_yx -> aa) or a repo path, not just a name.
    key = re.split(r"[./]", name.strip().lstrip("@").lower(), 1)[0]
    return REPO_ALIASES.get(key, key)


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


def parse_prompt(path: Path, mind: Path):
    """Read a prompt file and extract structure: work-type, target, repos, body."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        rel = path.relative_to(mind)
        parts = rel.parts
    except ValueError:
        parts = path.parts
    # Lifecycle layout (Mind #71): backlog prompts live under draft/ — the
    # taxonomy folders (<work-type>/<target>/) sit below the state folder.
    if parts and parts[0] == "draft":
        parts = parts[1:]
    work_type = parts[0] if parts else "?"
    target = parts[1] if len(parts) > 1 else "?"

    mentions = {normalise_repo(m) for m in re.findall(r"@[A-Za-z0-9._/-]+", text)}
    # Keep only mentions that resolve to a repo we know — drops project refs
    # (@z_projects), bare libraries (@jax) and noise, so the repo count is real.
    repos = {m for m in mentions if m in KNOWN_REPOS}
    # An intake-written header lists the resolved repos explicitly — trust it
    # alongside @-mentions (bodies often name repos without the @ sigil).
    header_block = re.search(r"^Repos:\n((?:- .+\n)+)", text, re.M)
    if header_block:
        for ln in header_block.group(1).splitlines():
            r = normalise_repo(ln[1:].strip())
            if r in KNOWN_REPOS:
                repos.add(r)
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


def estimate_difficulty(p: dict):
    """Heuristic difficulty estimate -> (level, score, factors).

    Considers: repos affected, prompt size, scientific complexity, architectural
    risk, test burden, and whether human judgement / memory context is needed.
    """
    text = p["text"]
    lib = [r for r in p["repos"] if r in LIBRARY_REPOS]
    wsp = [r for r in p["repos"] if r in WORKSPACE_REPOS]
    org = [r for r in p["repos"] if r in ORGANISM_REPOS]
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
        "organism_repos": org,
        "library_and_workspace": bool(lib and wsp),
        "size_words": p["words"],
        "scientific_complexity": science,
        "architectural_risk": risk,
        "test_burden": tests,
        "human_judgement": ambiguity,
        "memory_context_required": bool(science),
    }
    return level, score, factors

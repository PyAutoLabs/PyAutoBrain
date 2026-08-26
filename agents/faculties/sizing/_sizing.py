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

`estimate_difficulty` is the heuristic; `effective_difficulty` is the PRECEDENCE
RULE over it — a difficulty the author DECLARED wins, with the derived level
returned alongside so a disagreement stays visible. The rule lives here, not in
the conductors: each conductor that reconciled it for itself was one more chance
to forget, and three of them did (PyAutoBrain#217, then #274). `declared_header`
reads the keys a filed prompt declares; `declared_inline` reads the same keys out
of unheadered conception prose. Neither reads a code fence — a prompt QUOTING a
header is documenting it, not declaring it.

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


_BODY_MAP_CACHE: dict = {}


def _body_map_specs() -> dict:
    """repo name -> its full body-map spec (the single source of repo identity).

    Cached: every call site below reads it, and it is a file the process never
    writes.
    """
    if not _BODY_MAP_CACHE:
        import yaml

        _BODY_MAP_CACHE.update(yaml.safe_load(BODY_MAP_PATH.read_text())["repos"])
    return _BODY_MAP_CACHE


def _body_map_categories() -> dict:
    """repo name -> category, from the body map (the single source of repo
    identity)."""
    return {name: spec["category"] for name, spec in _body_map_specs().items()}


# --- the canonical-key rule (PyAutoBrain#287) --------------------------------
# One repo, one key. A prompt may spell a repo three ways — `@PyAutoFit`,
# `@autofit`, `PyAutoFit/` — and every one of them has to reach the SAME key, or
# whichever spelling the author happened to type silently decides whether the
# policy maps (test_witness, target_default_wiki, ...) resolve. Seven repos hit
# that split before it was closed here — one at #267, two more at #269, and the
# bare organ spellings plus one project repo at #287.
#
# THE RULE (first written down at #269, now executable): the canonical key is
# the package the repo SHIPS where it ships one, and the repo name where it does
# not. That asymmetry is not arbitrary — it is what prompts actually write. A
# library is named by its import (`@autofit`); an organ ships no package, so the
# only name it has is the repo's (`@PyAutoBrain`).
#
# The authority for "does it ship a package" is the body map's `package:` field —
# repo identity, declared once, where identity lives.


def _hand_aliases() -> dict:
    """The alias rows a body map cannot derive.

    Two kinds only: the short forms prompts use for the libraries (`aa`, `af`),
    and the pre-rename spellings that keep ~150 archived Mind prompts routing to
    the repo they now name (`pyautobuild` -> the Hands, and the Nerves repo's
    former name). Neither is inferable from a body map that records only what
    the organism is called TODAY.
    """
    return policy()["repo_aliases"]


def canonical_key(name: str, spec: dict | None = None) -> str:
    """The one key every spelling of body-map repo `name` must reach."""
    if spec is None:
        spec = _body_map_specs().get(name, {})
    package = spec.get("package")
    if package:
        return package.lower()
    # Fallback for a body map that predates `package:` (an adopting fork, or
    # this repo's own CI, which pins the sibling Mind checkout to `main`): the
    # hand table still carries the library rows, so the answer is the same one
    # `package:` gives. Kept deliberately — it is what lets the Brain half of
    # #287 stand alone instead of going red until the Mind half merges.
    low = name.lower()
    return _hand_aliases().get(low, low)


def spellings_of(name: str, spec: dict | None = None) -> set:
    """Every form of `name` that `_target_sets` registers as a known target.

    The repo name, the `PyAuto`-stripped bare form, and the package it ships.
    These are the spellings a guard must prove all reach one key; they are NOT
    every string that could mention the repo (an org-qualified path like
    `@<org>/<repo>` is handled by `normalise_repo`'s truncation).
    """
    if spec is None:
        spec = _body_map_specs().get(name, {})
    low = name.lower()
    out = {low}
    if low.startswith("pyauto"):
        out.add(low[2:])
    if spec.get("package"):
        out.add(spec["package"].lower())
    return out


def unreachable_repos() -> dict:
    """Body-map repos an @-mention can never name -> why.

    ``normalise_repo`` truncates at the first ``.`` or ``/`` (so `@aa.decorators`
    and an org-qualified `@<org>/<repo>` path both resolve to their head token).
    A repo whose NAME contains one of those separators therefore cannot survive
    normalisation, and registering it as a known target would be a lie: nothing
    could ever resolve to it. Aliasing the truncated head instead would be worse
    than the lie — where the head happens to be the ORG's own name, every
    org-qualified mention would start resolving to that one repo.

    Derived from the names themselves, so it stays right for any body map rather
    than being a hand-kept exclusion list (PyAutoBrain#287).
    """
    return {
        name: "name contains a '.' or '/', which normalise_repo truncates — "
              "no @-mention can reach it"
        for name in _body_map_specs()
        if re.split(r"[./]", name, maxsplit=1)[0] != name
    }


def _derived_aliases() -> dict:
    """Every registered spelling of every body-map repo -> its canonical key.

    This is the half of ``repo_aliases`` that must NOT be typed by hand. The
    known-target set was always derived from the body map while the alias table
    was maintained by hand, so the two drifted silently and the gap surfaced only
    as a wrong-but-plausible conductor message — "strengthen tests first" for a
    repo with a full suite (PyAutoBrain#267, #269, #287). Deriving the join means
    a repo added to the body map arrives with its spellings already joined.
    """
    grouping = policy()["sizing_categories"]
    registered = {cat for kinds in grouping.values() for cat in kinds}
    unreachable = unreachable_repos()
    out = {}
    for name, spec in _body_map_specs().items():
        if spec["category"] not in registered or name in unreachable:
            continue
        canonical = canonical_key(name, spec)
        for spelling in spellings_of(name, spec):
            out[spelling] = canonical
    return out


def _repo_aliases() -> dict:
    """The effective alias table: derived join + the rows only a human can know.

    A hand row that CONTRADICTS the derivation is drift, and drift in this table
    is exactly what #287 is about — so it raises here rather than quietly
    winning. A hand row the derivation does not cover (a short form, a rename)
    passes through untouched.
    """
    derived = _derived_aliases()
    hand = _hand_aliases()
    conflicts = {
        alias: (derived[alias], hand[alias])
        for alias in hand
        if alias in derived and hand[alias] != derived[alias]
    }
    if conflicts:
        raise ValueError(
            "config/policy.yaml repo_aliases contradicts the body map "
            "(alias -> (derived, hand)): "
            f"{conflicts}. The body map's `package:` field is the authority for "
            "a repo's canonical key; fix the hand row or the package name."
        )
    return {**derived, **hand}


def _target_sets() -> tuple[set, set, set]:
    specs = _body_map_specs()
    pol = policy()
    grouping = pol["sizing_categories"]
    unreachable = unreachable_repos()

    def names_for(kind):
        wanted = set(grouping[kind])
        out = set()
        for name, spec in specs.items():
            # An unreachable repo is deliberately NOT registered: a known target
            # nothing can resolve to is the same silent lie as a split spelling.
            if spec["category"] in wanted and name not in unreachable:
                out |= spellings_of(name, spec)
                out.add(canonical_key(name, spec))
        return out

    libraries = names_for("library")
    workspaces = names_for("workspace") | set(pol["extra_workspace_targets"])
    organism = names_for("organism") | set(pol["extra_organism_targets"])
    return libraries, workspaces, organism


# Normalise an @-mention or folder name to a canonical key. Built before the
# target sets because `canonical_key`'s pre-`package:` fallback reads the hand
# table, and the sets register the canonical key it returns.
REPO_ALIASES = _repo_aliases()

# Targets that are source *libraries* (work classifies as library vs workspace),
# workspaces/tutorials/example repos, and the organism's own organs — all
# derived from the body map's categories per the policy's grouping.
LIBRARY_REPOS, WORKSPACE_REPOS, ORGANISM_REPOS = _target_sets()

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


def discover_prompts(mind: Path, work_type: str) -> list[Path]:
    """Every backlog prompt of one work-type, across the Mind lifecycle layout.

    The discovery counterpart to `parse_prompt`, and shared for the same reason:
    three conductors (feature / bug / refactor) each held a private copy rooted
    at the pre-#71 `mind/<work-type>/`, so from the day the split closed
    (2026-07-13) all three selection modes silently returned "no prompts found"
    against a live backlog.

    Covers the two regimes that hold *backlog* prompts, mirroring `parse_prompt`:

      - `draft/<work-type>/<target>/*.md` — the current layout (PyAutoMind#71);
      - `<work-type>/<target>/*.md`       — legacy flat, pre-migration.

    `active/` is deliberately NOT discovered: it is flat (so its paths carry no
    work-type to filter on) and holds issued, in-flight work, whereas selection
    answers "what should I start next". `complete/` — records, not backlog — is
    excluded by construction, since neither root above can reach into it.
    """
    seen, out = set(), []
    for root in (mind / "draft" / work_type, mind / work_type):
        if not root.is_dir():
            continue
        for p in root.rglob("*.md"):
            # READMEs document a folder; they are never themselves tasks.
            if p.name.lower() == "readme.md":
                continue
            key = p.resolve()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return sorted(out)


def empty_discovery_reason(mind: Path, work_type: str) -> str:
    """Explain an empty `discover_prompts` result — is it a bare backlog or a bad root?

    A flat "no prompts found" reads identically whether the backlog is genuinely
    empty or discovery is pointed somewhere wrong. That ambiguity is what let
    PyAutoBrain#211 survive four weeks: three conductors reported an empty
    backlog while sitting on 87 prompts, and the message a broken root produced
    was the message an empty backlog produced. Diagnosing the empty case is
    therefore not cosmetic — it is the signal that bug lacked.

    Diagnosis only; callers keep their own exit codes.
    """
    if not mind.is_dir():
        return f"PyAutoMind path is not a directory: {mind}"

    draft = mind / "draft"
    # A Mind always carries its registry; `draft/` alone can be absent on a
    # freshly-spawned one that has taken no work yet.
    if not draft.is_dir() and not (mind / "active.md").is_file():
        return (f"{mind} does not look like a PyAutoMind checkout "
                f"(no draft/ and no active.md) — check PYAUTO_MIND")

    roots = [r for r in (draft / work_type, mind / work_type) if r.is_dir()]
    if not roots:
        known = sorted(p.name for p in draft.iterdir() if p.is_dir()) if draft.is_dir() else []
        have = f"; work-types present: {', '.join(known)}" if known else ""
        return (f"no '{work_type}' work-type folder under {mind}/draft/ "
                f"(nor a legacy flat {work_type}/){have}")

    where = ", ".join(str(r.relative_to(mind)) for r in roots)
    return f"{where} exists under {mind} but holds no prompts (backlog genuinely empty)"


# --- the declared metadata header -------------------------------------------
#
# PyAutoMind/REFERENCE.md ("Optional metadata header") defines these keys and
# states the contract this parser exists to honour: Intake persists `Difficulty:`
# "so the value shown up front is the one the Feature Agent later acts on".
# Parsing them here — beside the derivation — keeps declared and derived in one
# place, and gives the bug/refactor conductors the same reading for free.
DIFFICULTY_LEVELS = ("small", "medium", "large", "too-large")
AUTONOMY_LEVELS = ("safe", "supervised", "human-required")
# `medium` is not a documented Priority: value but occurs in the live backlog;
# read it as normal rather than dropping the prompt's stated intent.
PRIORITY_RANK = {"high": 0, "normal": 1, "medium": 1, "low": 2}
DEFAULT_PRIORITY_RANK = 1

_HEADER_KEY_RE = re.compile(
    r"^\s*(difficulty|type|autonomy|status|priority|blocked-by|closes-when)"
    r"\s*:\s*(.+?)\s*$", re.I
)


def _strip_trailing_comment(value: str) -> str:
    """Header values may carry a trailing `# note` (the live backlog does, e.g.
    `Blocked-by: PyAutoFit#1334   # WP1 gate (MERGED)`). Split on ` #` so a
    `Repo#123` ref — which has no space before the hash — survives intact."""
    return value.split(" #", 1)[0].strip()


def declared_header(text: str) -> dict:
    """The header keys a prompt *declares*, as opposed to what we infer.

    Fenced blocks are documentation, not declarations — a prompt that quotes
    another prompt's header in a ```-block (the bug prompt for this very fix
    does exactly that) must not be read as declaring it. Same rule, and the
    same reason, as PyAutoMind `lifecycle.py:draft_gate_refs`.
    """
    out = {"declared_difficulty": None, "declared_type": None,
           "declared_autonomy": None, "status": None,
           "priority": None, "blocked_by": [], "closes_when": []}
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADER_KEY_RE.match(line)
        if not m:
            continue
        key, value = m.group(1).lower(), _strip_trailing_comment(m.group(2))
        if not value:
            continue
        if key == "difficulty":
            v = value.lower()
            if v in DIFFICULTY_LEVELS and out["declared_difficulty"] is None:
                out["declared_difficulty"] = v
        elif key == "type":
            v = value.lower()
            if v in WORK_TYPES and out["declared_type"] is None:
                out["declared_type"] = v
        elif key == "autonomy":
            v = _norm_level(value)
            if v in AUTONOMY_LEVELS and out["declared_autonomy"] is None:
                out["declared_autonomy"] = v
        elif key == "status" and out["status"] is None:
            out["status"] = value.lower()
        elif key == "priority" and out["priority"] is None:
            out["priority"] = value.lower()
        elif key == "blocked-by":
            out["blocked_by"].append(value)
        elif key == "closes-when":
            out["closes_when"].append(value)
    return out


# --- declarations in unstructured prose ---------------------------------------
# `declared_header` reads header LINES, which is what a filed prompt carries.
# Conception input has no header yet: the ideas.md house style ends a bullet
# with "Difficulty large, supervised.", and a pasted report writes
# "… Difficulty: medium." mid-sentence. Same precedence, a looser reader — kept
# here beside the header reader so "what counts as a declaration" is defined
# once for every conductor.
_DIFFICULTY_ALT = r"too[-\s]large|small|medium|large"
_AUTONOMY_ALT = r"human[-\s]required|supervised|safe"
_PRIORITY_ALT = r"high|normal|low"
_TYPE_ALT = "|".join(sorted(WORK_TYPES, key=len, reverse=True))
# Between key and value: a colon/equals, "is", or nothing ("Difficulty large").
_DECL_SEP = r"\s*(?::|=|\bis\b)?\s*"
_DECLARATION = re.compile(
    rf"\bdifficulty{_DECL_SEP}({_DIFFICULTY_ALT})\b"
    rf"(?:\s*[,/&]?\s*(?:and\s+)?({_AUTONOMY_ALT})\b)?"
    rf"|\bautonomy{_DECL_SEP}({_AUTONOMY_ALT})\b"
    rf"|\bpriority{_DECL_SEP}({_PRIORITY_ALT})\b"
    rf"|\btype{_DECL_SEP}({_TYPE_ALT})\b",
    re.IGNORECASE)
_CODE_SPAN = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)


def _mask_code(text: str) -> str:
    """`text` with code spans blanked to spaces (offsets and lines preserved)."""
    return _CODE_SPAN.sub(lambda m: re.sub(r"\S", " ", m.group(0)), text)


def _norm_level(value: str) -> str:
    """"Too Large" / "human required" -> the canonical hyphenated header value."""
    return re.sub(r"[\s-]+", "-", value.strip().lower())


def declared_inline(text: str):
    """(fields, spans) — declarations made in prose, for unheadered raw input.

    Fenced blocks and inline code spans are masked first: a prompt that *quotes*
    a `Difficulty:` line (a repro, a transcript — the bug prompt for this very
    fix does exactly that) is documenting, not declaring. Same rule as
    `declared_header`. First declaration of each key wins; `spans` are its
    offsets in `text`, so a caller can keep the clause out of a derived title.
    """
    fields, spans = {}, []
    for m in _DECLARATION.finditer(_mask_code(text)):
        difficulty, trailing_autonomy, autonomy, priority, work_type = m.groups()
        if difficulty:
            fields.setdefault("difficulty", _norm_level(difficulty))
        if trailing_autonomy or autonomy:
            fields.setdefault("autonomy", _norm_level(trailing_autonomy or autonomy))
        if priority:
            fields.setdefault("priority", _norm_level(priority))
        if work_type:
            fields.setdefault("type", work_type.lower())
        spans.append(m.span())
    return fields, spans


def strip_declarations(text: str, spans: list) -> str:
    """`text` with the declaration clauses removed — for title derivation only.

    The prompt body itself stays verbatim (word-vomit is intent); this exists so
    "Fix the docstring. Difficulty: large." does not title the task — and name
    the file — after its own difficulty declaration.
    """
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        chars[start:end] = " " * (end - start)
    out = "".join(chars)
    # Tidy the punctuation the removed clause left stranded (title use only).
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    out = re.sub(r"([.,;:])(\s*[.,;:])+", r"\1", out)
    return out if re.search(r"\w", out) else text


def priority_rank(p: dict) -> int:
    return PRIORITY_RANK.get(p.get("priority") or "", DEFAULT_PRIORITY_RANK)


def declared_blocked(p: dict):
    """Why the prompt declares itself un-startable, or None.

    Deliberately conservative: this faculty is offline, so it cannot resolve
    whether a `Blocked-by:` gate has since closed — that is
    `PyAutoMind/scripts/lifecycle.py issues --drafts`, which talks to GitHub. An
    unresolved gate therefore reads as blocked. Being wrongly held back is cheap
    and visible (the prompt is still listed, in its own band); being wrongly
    recommended is the failure this exists to stop.
    """
    if (p.get("status") or "") == "blocked":
        return "Status: blocked"
    if p.get("blocked_by"):
        return "Blocked-by: " + "; ".join(p["blocked_by"])
    return None


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
    # active/ is FLAT (issued prompts, no taxonomy folders), so its path
    # carries no work-type/target at all — the header fallback below supplies
    # them there.
    if parts and parts[0] == "draft":
        parts = parts[1:]
    elif parts and parts[0] == "active":
        parts = ()
    work_type = parts[0] if parts else "?"
    target = parts[1] if len(parts) > 1 else "?"

    # Formalised prompts carry Type:/Target: header lines — authoritative
    # whenever the path yields no valid taxonomy (active/, stray layouts).
    if work_type not in WORK_TYPES:
        m = re.search(r"^Type:\s*([a-z_]+)\s*$", text, re.M)
        if m and m.group(1) in WORK_TYPES:
            work_type = m.group(1)
    if target == "?":
        m = re.search(r"^Target:\s*(\S+)\s*$", text, re.M)
        if m:
            t = normalise_repo(m.group(1))
            if t in KNOWN_REPOS or t == "workspaces":
                target = t

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
        **declared_header(text),
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


def effective_difficulty(p: dict):
    """(level, score, factors, derived_level) — the DECLARED level wins.

    The single precedence rule, defined here rather than per conductor. Three
    conductors size a prompt (feature, bug, intake) and each one that re-derived
    difficulty while ignoring `declared_difficulty` shipped the same bug
    (PyAutoBrain#217, then #274) — one heuristic with three reconciliations is
    three chances to forget one.

    REFERENCE.md promises that the `Difficulty:` Intake persists is "the value
    the Feature Agent later acts on", so a declared level overrides the
    re-derived one. Length is the heuristic's biggest input and a bad size proxy
    — a prompt is long when it carries a design, not when the work is large —
    which is exactly what declaring a level exists to correct. The derived score
    is kept (it still orders prompts within a level) and the derived LEVEL is
    returned alongside, so a disagreement is reported rather than silently
    resolved: it is evidence about the heuristic and worth seeing.
    """
    derived_level, score, factors = estimate_difficulty(p)
    return p.get("declared_difficulty") or derived_level, score, factors, derived_level


# --- runnable read-only entrypoint (parity with the other faculties) ---------
# The heuristic above is a shared *substrate* imported by intake + feature; this
# thin CLI lets a human (or `pyauto-brain sizing`) read the SizingSurface for one
# prompt without dispatching anything. It writes nothing.


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Sizing faculty — the SizingSurface for one PyAutoMind prompt."
    )
    ap.add_argument("prompt", help="path to a PyAutoMind prompt (.md)")
    ap.add_argument(
        "--mind",
        type=Path,
        default=BODY_MAP_PATH.parent,
        help="PyAutoMind root (defaults to the sibling checkout)",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    p = parse_prompt(Path(args.prompt).resolve(), args.mind.resolve())
    level, score, factors = estimate_difficulty(p)
    surface = {
        "path": p["path"],
        "work_type": p["work_type"],
        "target": p["target"],
        "repos": p["repos"],
        "lines": p["lines"],
        "words": p["words"],
        "difficulty": {"level": level, "score": score, "factors": factors},
    }
    if args.json:
        print(json.dumps(surface, indent=2))
        return
    print(f"SizingSurface: {p['path']}")
    print(f"  work-type : {p['work_type']}")
    print(f"  target    : {p['target']}")
    print(f"  repos     : {', '.join(p['repos']) or '(none)'}")
    print(f"  size      : {p['lines']} lines / {p['words']} words")
    print(f"  difficulty: {level} (score {score})")


if __name__ == "__main__":
    _main()

#!/usr/bin/env python3
"""agents/conductors/cortex/_cortex.py — core for the Cortex Agent.

The Cortex Agent is the *learning function* of PyAutoBrain: the conductor that
reasons over PyAutoCortex, the organ where the organism learns what is true.
The Cortex holds the state — science phases, their pre-registered witnesses,
their runs and the rulings of record; this conductor holds the reasoning: it
renders the Cortex board, grades the gates, admits ready phases into a laptop
slot and (phase 2b) scores what a pull brought back. It **never submits** and
never edits a ruling: the run is the human's act and the verdict is theirs.

The same split as Heart ↔ vitals and Gut ↔ hygiene — the organ keeps the
state, the conductor reasons over it.

Three constraints shape this module:

- **Stdlib only, and Mind-free.** The Cortex renderer runs bare inside the
  Cortex's own `dashboard_refresh.yml`, which installs nothing and checks out
  no PyAutoMind. So this module imports neither `_sizing` nor `_intake` (both
  hard-fail without a Mind checkout: `_sizing.py` reads the body map at
  import). The renderer helpers the Mind's page uses are *copied* here rather
  than imported, deliberately — the duplication is the price of a page that
  renders with one repo checked out.
- **The Cortex script is the API.** `<cortex_root>/scripts/cortex.py` is
  stdlib-only, has no import-time side effects and exposes pure functions
  (`load_phases`, `load_rulings`, `load_projects`, `gates_report`, …). It is
  imported at runtime from the resolved root, so this conductor always reasons
  with the schema the checkout it is pointed at actually implements.
- **No path is named here.** Science projects live outside the workspace; the
  one place that carries such a path is the Cortex's own `projects.yaml`, and
  every path this module prints is read from a row of it at runtime.

Verbs: `census [--json]` · `dashboard --check|--apply` · `plan [--budget N]
[--lane L]` · `gates [--grade] [--apply]` · `collect` (phase 2b).

Exit codes: 0 ok · 1 dashboard drift (the `dashboard_refresh.yml` contract) ·
2 bad args / no Cortex checkout · 3 the Cortex tree could not be read.
`gates` passes the Cortex script's own rc through (1 = an unreadable ref,
which fails closed).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[3]

# The one workspace-root resolver (agents/_pyauto_root.py, mirrored by
# bin/_pyauto_root.sh) — never a literal path.
sys.path.insert(0, str(BRAIN_HOME / "agents"))
import _pyauto_root  # noqa: E402

# The shared board theme: the one place that answers "what does a one-tap
# board look like". Presentation only — stylesheet, hero, pills, stats — so
# this page is visibly the same family as the Mind's and the Brain's.
sys.path.insert(0, str(BRAIN_HOME / "board"))
from _theme import (  # noqa: E402
    JS as _THEME_JS, boards_footer, css as _theme_css, hero, pills, stats,
)

THEME_ORGAN = "cortex"  # whose logo this page wears
CORTEX_REPO = "PyAutoCortex"  # an organ name, not an instance fact

# Exit codes — the `dashboard_refresh.yml` contract lives on these.
RC_OK, RC_DRIFT, RC_USAGE, RC_UNREADABLE = 0, 1, 2, 3

DEFAULT_REVIEW_BUDGET = 45  # one laptop slot's review-minutes (batch's default)
LOCAL_LANE = "local-dev"
RECENT_RULINGS = 12


class CortexUnavailable(Exception):
    """No usable PyAutoCortex checkout at the resolved root."""


# ----------------------------------------------------------------- roots ---
def resolve_root(explicit: str | None = None) -> Path:
    """Where the Cortex is: `--cortex` → `$PYAUTO_CORTEX` → beside this
    Brain checkout → `$PYAUTO_ROOT/<organ>`.

    Deliberately its own resolver rather than an extension of the Mind's:
    the two organs are resolved independently, so a session holding one and
    not the other still works.
    """
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("PYAUTO_CORTEX")
    if env:
        return Path(env).expanduser()
    sibling = BRAIN_HOME.parent / CORTEX_REPO
    if sibling.is_dir():
        return sibling
    return _pyauto_root.pyauto_root() / CORTEX_REPO


_SCRIPTS: dict[str, object] = {}


def find_script(root: Path) -> Path | None:
    """The `scripts/cortex.py` that governs the tree at `root`.

    A *data root* need not be a checkout: every verb in the Cortex's own
    script takes `root: Path`, so a fixture tree (`tests/fixtures/skeleton`)
    is a legitimate root with no `scripts/` of its own. So look in the root,
    then in its ancestors (the checkout the fixture lives in), then in the
    resolved checkout — the schema that reads a tree is the one shipped
    beside it.
    """
    for candidate in (root, *root.resolve().parents):
        script = candidate / "scripts" / "cortex.py"
        if script.is_file():
            return script
    fallback = resolve_root() / "scripts" / "cortex.py"
    return fallback if fallback.is_file() else None


def load_cortex(root: Path):
    """Import the Cortex's own schema module for the tree at `root`.

    Loaded by file location under a per-path module name so two checkouts can
    be read in one process without the first import shadowing the second. The
    script's directory also goes on `sys.path`, as the Cortex's own tooling
    expects.
    """
    if not root.is_dir():
        raise CortexUnavailable(
            f"no Cortex tree at {root}. Set PYAUTO_CORTEX, clone "
            f"{CORTEX_REPO} beside PyAutoBrain, or pass --cortex <dir>.")
    script = find_script(root)
    if script is None:
        raise CortexUnavailable(
            f"no Cortex checkout at {root} (expected "
            f"{root / 'scripts' / 'cortex.py'}). Set PYAUTO_CORTEX, clone "
            f"{CORTEX_REPO} beside PyAutoBrain, or pass --cortex <dir>.")
    key = str(script.resolve())
    if key in _SCRIPTS:
        return _SCRIPTS[key]
    parent = str(script.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(
        f"_cortex_script_{abs(hash(key))}", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SCRIPTS[key] = mod
    return mod


OWNER_IN_DOCS = re.compile(r"https://github\.com/([\w.-]+)/PyAuto[\w.-]*")


def _home(root: Path) -> str:
    """`https://github.com/<owner>/<organ>` for this checkout, `''` if unknown.

    The renderer must produce byte-identical pages on a laptop and inside the
    Cortex's own refresh workflow, or `--check` would report permanent drift
    and the self-heal would commit a page every night. So the owner is read
    from a **file that travels with the repo** — its own README/AGENTS links,
    the same declared surface the Mind's renderer reads out of `repos.yaml` —
    and only falls back to the git remote, which is not guaranteed readable in
    every CI container. No org is named here; a fork's Cortex carries its own.
    """
    for name in ("README.md", "AGENTS.md"):
        f = root / name
        if f.is_file():
            m = OWNER_IN_DOCS.search(f.read_text(encoding="utf-8",
                                                 errors="replace"))
            if m:
                return f"https://github.com/{m.group(1)}/{CORTEX_REPO}"
    return _home_from_git(root)


def _home_from_git(root: Path) -> str:
    """The fallback: the checkout's own `origin`. The toplevel guard keeps a
    fixture tree *inside* another repo from borrowing that repo's remote."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse",
                              "--show-toplevel"], capture_output=True,
                             text=True, timeout=20)
        if top.returncode != 0:
            return ""
        if Path(top.stdout.strip()).resolve() != root.resolve():
            return ""
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url",
                            "origin"], capture_output=True, text=True,
                           timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    url = r.stdout.strip()
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)"
                 r"([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else ""


# ------------------------------------------------------------- the census ---
# Phase states, grouped into the sections the board shows. A state that is in
# no group renders in no section (planned phases are scope, not work; dropped
# and accepted phases are history the rulings section carries).
AWAITING_STATES = ("pulled", "awaiting-ruling")
LIVE_STATES = ("submitted", "running")
FAILED_RUN_STATES = ("failed", "timeout", "void", "legacy_wrong")

# One section: (key, title, source path in the repo, blurb).
SECTIONS = (
    ("awaiting", "Awaiting ruling", "phases/",
     "Results are in and nothing is running — the human's verdict is the only "
     "thing outstanding. Ordered failures first, then the phases a ruling is "
     "required for, then the clean ones."),
    ("live", "Running / submitted", "phases/",
     "On the queue or on the machine. Wall is what the run lines record at the "
     "last refresh, against the phase's own budget."),
    ("ready", "Ready", "phases/",
     "Gate cleared, witness registered — these are what `cortex plan` admits "
     "into a laptop slot."),
    ("gated", "Gated", "phases/",
     "Waiting on development work. The daily grading job flips a phase to "
     "ready when every reference it names has closed."),
    ("rulings", "Recent rulings", "rulings/",
     "The ledger of record, newest first. A verdict recorded only outside the "
     "Cortex does not exist."),
    ("epics", "Epics", "epics.md",
     "Long-running programmes whose science half lives here; each card links "
     "its development half in the Mind."),
    ("projects", "Projects", "projects.yaml",
     "The science body map — where each project lives, what syncs it and "
     "where its witness lands."),
)

REFRESH_BLURB = (
    "generated from `phases/`, `rulings/`, `batches/`, `epics.md` and "
    "`projects.yaml`, so it is only as current as they are. "
    "`dashboard_refresh.yml` re-renders it on every push to `main`, and the "
    "daily gate grading flips cleared gates before it runs."
)


def _mins(value: str) -> int | None:
    """`H+:MM` → minutes, or None."""
    m = re.fullmatch(r"(\d+):(\d{2})", (value or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _int(value: str) -> int | None:
    v = (value or "").strip()
    return int(v) if v.isdigit() else None


# The batch record's own grammar, read here rather than through the Cortex
# script's `_record_members`: that helper keeps only the FIRST value of a
# repeated key, and `- refreshed:` is repeated once per pull — which is
# exactly the live-progress signal this board wants.
RECORD_KEY = re.compile(r"^- ([a-z][a-z0-9-]*):(?:\s+(.*?))?\s*$")
REFRESHED = re.compile(r"^(?P<at>\S+)(?:\s+[—-]+\s+(?P<note>.*))?$")


def read_record(text: str, member_re=None) -> dict:
    """One batch record as `{"keys": {k: [v, …]}, "members": [row, …]}`.

    Every value of every key is kept, in file order — the lossless reader the
    live-progress strip and (phase 2b) `collect` both need.
    """
    keys: dict[str, list[str]] = {}
    members: list[dict] = []
    in_members = False
    for lineno, raw in enumerate(text.split("\n"), 1):
        m = RECORD_KEY.match(raw)
        if m:
            in_members = m.group(1) == "members"
            keys.setdefault(m.group(1), []).append((m.group(2) or "").strip())
            continue
        if in_members and raw.startswith("  - "):
            row = {"lineno": lineno, "raw": raw}
            mm = member_re.match(raw.replace("--", "—")) if member_re else None
            if mm:
                row.update({k: (mm.groupdict().get(k) or "").strip()
                            for k in ("slug", "path", "runs", "minutes", "state")
                            if k in mm.groupdict()})
            members.append(row)
        elif raw.strip() and not raw.startswith("    ") and in_members:
            in_members = False
    return {"keys": keys, "members": members}


def _refresh_index(root: Path, mod) -> dict:
    """`{slug: {"at": …, "note": …, "slot": …}}` — the newest `refreshed:`
    line naming each phase slug, across every batch record."""
    index: dict[str, dict] = {}
    for path in mod.batch_records(root):
        slot = path.stem
        rec = read_record(path.read_text(encoding="utf-8"), mod.MEMBER_RE)
        slugs = [m.get("slug", "") for m in rec["members"] if m.get("slug")]
        for value in rec["keys"].get("refreshed", []):
            m = REFRESHED.match(value.strip())
            if not m:
                continue
            at, note = m.group("at"), (m.group("note") or "").strip()
            for slug in slugs:
                if slug and slug in note:
                    prev = index.get(slug)
                    if prev is None or at >= prev["at"]:
                        index[slug] = {"at": at, "note": note, "slot": slot}
    return index


def _phase_row(mod, ph, refreshed: dict) -> dict:
    refs, bad_refs = mod.gate_refs(ph.get("Gates"))
    runs = [{"ident": r.ident, "state": r.state, "partition": r.partition,
             "date": r.date, "wall": r.wall, "note": r.note}
            for r in ph.runs]
    walls = [_mins(r["wall"]) or 0 for r in runs]
    budget = ph.get("Budget")
    return {
        "rel": ph.rel,
        "slug": ph.slug,
        "title": ph.title or ph.slug,
        "project": ph.get("Project") or ph.project_dir,
        "phase": _int(ph.get("Phase")),
        "state": ph.state,
        "gates": refs,
        "bad_gates": bad_refs,
        "gates_cleared": ph.get("Gates-cleared"),
        "gate_override": ph.get("Gate-override"),
        "witness": ph.get("Witness"),
        "budget": budget,
        "budget_minutes": _mins(budget),
        "runs": runs,
        "wall_minutes": max(walls) if walls else 0,
        "ruling": ph.get("Ruling"),
        "epic": ph.get("Epic"),
        "lane": ph.get("Lane") or LOCAL_LANE,
        "review_minutes": _int(ph.get("Review-minutes")),
        "refreshed": refreshed.get(ph.slug),
        "failed_runs": [r["ident"] for r in runs
                        if r["state"] in FAILED_RUN_STATES],
    }


def _ruling_row(mod, r) -> dict:
    return {
        "id": r.id,
        "rel": r.rel,
        "title": (r.title or r.id).split(" — ", 1)[-1] if r.title else r.id,
        "verb": r.get("Ruling"),
        "phase": r.get("Phase"),
        "project": r.get("Project"),
        "batch": r.get("Batch"),
        "reviewed_at": r.get("Reviewed-at"),
        "supersedes": r.get("Supersedes"),
    }


EPIC_HEAD = re.compile(r"^## (\S+)\s*$")
EPIC_FIELD = re.compile(r"^- ([a-z-]+):\s*(.*?)\s*$")


def parse_epics(path: Path) -> list[dict]:
    """`epics.md` entries — `## <slug>` then `- key: value` lines. The Cortex
    half additionally carries `- mind-half:`, the slug of the Mind's entry."""
    if not path.is_file():
        return []
    entries: list[dict] = []
    cur: dict | None = None
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        # `epics.md` documents its own schema in a fenced block whose body is
        # a `## <slug>` template — reading that as an entry would put a ghost
        # card on the board of an empty Cortex.
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        head = EPIC_HEAD.match(line)
        if head:
            cur = {"slug": head.group(1)}
            entries.append(cur)
            continue
        field = EPIC_FIELD.match(line)
        if field and cur is not None:
            cur[field.group(1)] = field.group(2)
    return entries


def census(root: Path) -> dict:
    """Everything the board, the plan and the counts need, in one read."""
    mod = load_cortex(root)
    projects, project_problems = mod.load_projects(root)
    phases, phase_problems = mod.load_phases(root)
    rulings, ruling_problems = mod.load_rulings(root)
    refreshed = _refresh_index(root, mod)

    rows = [_phase_row(mod, ph, refreshed) for ph in phases]
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r["state"] or "?"] = by_state.get(r["state"] or "?", 0) + 1

    # A ruling that another ruling supersedes is not the standing verdict.
    successors = {r.get("Supersedes") for r in rulings if r.get("Supersedes")}
    ruling_rows = [_ruling_row(mod, r) for r in rulings]
    for row in ruling_rows:
        row["head"] = row["id"] not in successors
    ruling_rows.sort(key=lambda r: r["id"], reverse=True)

    awaiting = [r for r in rows if r["state"] in AWAITING_STATES]
    # failures → a ruling is required → clean, per the section's own promise.
    awaiting.sort(key=lambda r: (0 if r["failed_runs"] else
                                 1 if r["state"] == "awaiting-ruling" else 2,
                                 r["project"], r["phase"] or 0, r["rel"]))
    live = sorted([r for r in rows if r["state"] in LIVE_STATES],
                  key=lambda r: (r["project"], r["phase"] or 0, r["rel"]))
    ready = sorted([r for r in rows if r["state"] == "ready"],
                   key=lambda r: (r["review_minutes"] or 999, r["project"],
                                  r["phase"] or 0, r["rel"]))
    gated = sorted([r for r in rows if r["state"] == "gated"],
                   key=lambda r: (r["project"], r["phase"] or 0, r["rel"]))

    return {
        "root": str(root),
        "home": _home(root),
        "generated": _dt.date.today().isoformat(),
        "phases": rows,
        "by_state": by_state,
        "awaiting": awaiting,
        "live": live,
        "ready": ready,
        "gated": gated,
        "rulings": ruling_rows,
        "projects": projects,
        "epics": parse_epics(root / "epics.md"),
        "batches": [p.stem for p in mod.batch_records(root)],
        "reviews": [p.stem for p in mod.batch_reviews(root)],
        "problems": project_problems + phase_problems + ruling_problems,
    }


def section_counts(c: dict) -> list[tuple[str, str, int]]:
    """`(key, title, count)` for the counts table — the four live sections
    plus the ruling ledger. `board/_board.py` reads this table."""
    sizes = {"awaiting": len(c["awaiting"]), "live": len(c["live"]),
             "ready": len(c["ready"]), "gated": len(c["gated"]),
             "rulings": len(c["rulings"])}
    return [(key, title, sizes[key]) for key, title, _src, _blurb in SECTIONS
            if key in sizes]


# --------------------------------------------------------- render helpers ---
# Copied from the Mind's renderer rather than imported: `_intake.py` cannot be
# imported without a PyAutoMind checkout, and this page renders with only the
# Cortex and the Brain present.
def _cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def _attr(value: str) -> str:
    """Escape a string for a double-quoted HTML attribute."""
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _summary_label(value: str) -> str:
    """Text rendered inside a `<summary>` — HTML, not markdown."""
    value = str(value).replace("<!--", "").replace("-->", "").strip()
    value = _html.escape(value, quote=False) or "Untitled"
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", value)


def _md_inline(text: str) -> str:
    """The two inline markdown constructs this module authors, as HTML."""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


def _task_row(summary: str, payload: str) -> str:
    """One row as a collapsed `<details>` whose 📋 summary IS the line and
    whose body is the fenced payload GitHub renders a copy button on."""
    return "\n".join([f"<details><summary>📋 {summary}</summary>",
                      "",
                      "```",
                      payload,
                      "```",
                      "",
                      "</details>"])


def _items(chunks: list) -> list:
    out = []
    for chunk in chunks:
        out += [chunk, ""]
    return out[:-1] if out else []


def _html_task(text_html: str, payload: str) -> str:
    """One row on the HTML page: a real copy button, then the text."""
    return (f'<div class="task"><button class="copy" '
            f'data-cmd="{_attr(payload)}" aria-label="Copy the Claude '
            f'command">📋</button><p>{text_html}</p></div>')


def _pages_url(home: str) -> str:
    """The GitHub Pages site URL for a repo home, `''` when underivable."""
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)$", home)
    return f"https://{m.group(1).lower()}.github.io/{m.group(2)}/" if m else ""


def _board_links(home: str, current: str) -> list:
    """The cross-board footer nav, from PyAutoBrain's declared config surface
    (`config/policy.yaml` `board: boards:`), skipping this page's own entry.

    Stdlib regex on the one-pair-per-line block, not yaml — this renderer
    runs bare in the Cortex's refresh workflow, which installs nothing.
    """
    m = re.match(r"https://github\.com/([^/]+)/", home or "")
    policy = BRAIN_HOME / "config" / "policy.yaml"
    if not m or not policy.is_file():
        return []
    owner = m.group(1).lower()
    block = re.search(r"^  boards:\n((?:    \w+: \S+\n)+)",
                      policy.read_text(encoding="utf-8"), re.M)
    if not block:
        return []
    pairs = re.findall(r"^    (\w+): (\S+)$", block.group(1), re.M)
    return [(name, f"https://{owner}.github.io/{repo}/")
            for name, repo in pairs if name != current]


def _anchor(title: str) -> str:
    """GitHub's heading anchor for a section title."""
    slug = re.sub(r"[^a-z0-9 -]", "", title.lower())
    return slug.replace(" ", "-")


def _src_url(blob: str, src: str) -> str:
    """The GitHub URL of a section's source — `tree` for a directory."""
    if not blob:
        return src
    return (blob.replace("/blob/main/", "/tree/main/") + src) if src.endswith("/") \
        else blob + src


# ------------------------------------------------------------- the payloads ---
# Every row hands the reader the next command rather than a decision. The
# science verbs stay the Cortex script's and the run stays the human's.
def _ruling_payload(r: dict) -> str:
    return (f"Review the PyAutoCortex phase {r['rel']} and help me rule on it: "
            f"read its `## Witness` and the pulled evidence under its "
            f"`## Where to look`, score the witness, then draft the ruling "
            f"body for my approval and run `python3 scripts/cortex.py rule "
            f"{r['rel']} <accept|rerun|drop|leave-to-finish> --body <file>`.")


def _live_payload(r: dict, projects: dict) -> str:
    row = projects.get(r["project"], {})
    cli, path = row.get("sync_cli", ""), row.get("local_path", "")
    if cli and path and "jobs" in (row.get("sync_verbs") or []):
        return f"cd {path} && {cli} jobs"
    return (f"Report where the runs of the PyAutoCortex phase {r['rel']} "
            f"({', '.join(x['ident'] for x in r['runs']) or 'no runs'}) stand.")


def launch_payload(r: dict, projects: dict) -> list[str]:
    """The launch lines for a ready phase: the phase, the project's own
    submit verb, and the move that records the job id. No decision rides
    here — everything decided was decided when the plan was approved."""
    row = projects.get(r["project"], {})
    cli, path = row.get("sync_cli", ""), row.get("local_path", "")
    lines = [r["rel"]]
    if cli and path and "submit" in (row.get("sync_verbs") or []):
        lines.append(f"cd {path} && {cli} submit <script>")
    else:
        lines.append(f"# project {r['project']}: no `submit` verb in "
                     "projects.yaml — submit by hand")
    lines.append(f"python3 scripts/cortex.py move {r['rel']} submitted "
                 "--run <jobid>")
    return lines


def _ready_payload(r: dict, projects: dict) -> str:
    return "\n".join(launch_payload(r, projects))


def _gate_payload(r: dict) -> str:
    return ("python3 scripts/cortex.py gates --grade   # "
            + ", ".join(r["gates"]))


def _project_payload(key: str, row: dict) -> str:
    path = row.get("mirror") if row.get("mirror") not in ("", "none") else row.get("local_path", "")
    return f"Show me what is under {path} for the science project {key}."


def _epic_payload(e: dict) -> str:
    return (f"Work out where the Cortex half of the epic {e['slug']} stands "
            f"from {e.get('ledger') or 'phases/'} and tell me what its next "
            "phase is.")


# --------------------------------------------------------------- markdown ---
def _phase_head(r: dict) -> str:
    """The shared head of a phase row: title, link, the facts that decide."""
    head = f"<a href=\"{r['rel']}\">{_summary_label(r['title'])}</a>"
    facets = [f"{r['project']} phase {r['phase']}" if r["phase"] is not None
              else r["project"]]
    if r["budget"]:
        facets.append(f"budget {r['budget']}")
    if r["review_minutes"] is not None:
        facets.append(f"{r['review_minutes']} review-min")
    if r["runs"]:
        facets.append("runs " + ", ".join(x["ident"] for x in r["runs"]))
    return head + " — " + _summary_label(" · ".join(facets))


def _live_note(r: dict) -> str:
    """Budget vs elapsed plus the last refresh — the live-progress line."""
    bits = []
    if r["budget_minutes"]:
        pct = round(100 * r["wall_minutes"] / r["budget_minutes"])
        bits.append(f"wall {r['wall_minutes'] // 60}:{r['wall_minutes'] % 60:02d}"
                    f" of {r['budget']} ({pct}%)")
    if r["refreshed"]:
        bits.append(f"last refresh {r['refreshed']['at']}")
    return " · ".join(bits)


def _gate_note(r: dict) -> str:
    bits = [", ".join(r["gates"]) or "no refs"]
    if r["gate_override"]:
        bits.append("gate override")
    return " · ".join(bits)


def render_dashboard(c: dict) -> str:
    """The Cortex board as `dashboard.md`.

    Section order is the reading order of a slot: what needs a verdict, what
    is in flight, what could be launched, what is waiting on development —
    then the ledger, the programmes and the map.
    """
    home = c.get("home", "")
    blob = f"{home}/blob/main/" if home else ""
    titles = {key: title for key, title, _s, _b in SECTIONS}
    srcs = {key: src for key, _t, src, _b in SECTIONS}
    blurbs = {key: blurb for key, _t, _s, blurb in SECTIONS}

    def h2(key: str) -> list:
        # Every section links the markdown it is rendered from — the ledger
        # file is the record, this page is only the view.
        return [f"## {titles[key]}", "",
                f"[markdown version]({_src_url(blob, srcs[key])}) — "
                f"{blurbs[key]}", ""]

    L = [
        "# PyAutoCortex Dashboard",
        "",
        f"<!-- generated by `pyauto-brain cortex dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        "",
    ]
    pages = _pages_url(home)
    if pages:
        L += [f"This is the markdown version of the "
              f"[PyAutoCortex Dashboard]({pages}), which puts a phase's next "
              "command on your clipboard with a single tap of 📋.", ""]
    L += [
        "Every science phase the Cortex is holding, on one page: what is "
        "waiting on your verdict, what is running, what could be launched "
        "next and what is still gated on development work. The verdict is "
        "always yours — this page hands you the command, never the ruling.",
        "",
        f"> **Last updated {c['generated']}.** This page is {REFRESH_BLURB}",
        "",
        "| Where | Count |",
        "|-------|------:|",
    ]
    L += [f"| [{title}](#{_anchor(title)}) | {n} |"
          for _key, title, n in section_counts(c)]
    L += [""]
    if c["problems"]:
        L += ["> ⚠️ **The tree does not check** — `python3 scripts/cortex.py "
              "check` reports:", ""]
        L += [f"> - `{_cell(p)}`" for p in c["problems"][:10]]
        L += [""]

    L += h2("awaiting")
    L += _items([_task_row(_phase_head(r)
                           + (" — ⚠️ " + _summary_label(
                               "failed runs: " + ", ".join(r["failed_runs"]))
                              if r["failed_runs"] else ""),
                           _ruling_payload(r))
                 for r in c["awaiting"]]) or ["- _(nothing awaiting a ruling)_"]
    L += [""]

    L += h2("live")
    L += _items([_task_row(_phase_head(r) + (" — " + _summary_label(note)
                                             if (note := _live_note(r)) else ""),
                           _live_payload(r, c["projects"]))
                 for r in c["live"]]) or ["- _(nothing on the queue)_"]
    L += [""]

    L += h2("ready")
    L += _items([_task_row(_phase_head(r), _ready_payload(r, c["projects"]))
                 for r in c["ready"]]) or ["- _(nothing ready to launch)_"]
    L += [""]

    L += h2("gated")
    L += _items([_task_row(_phase_head(r) + " — " + _summary_label(_gate_note(r)),
                           _gate_payload(r))
                 for r in c["gated"]]) or ["- _(nothing gated)_"]
    L += [""]

    L += h2("rulings")
    if c["rulings"]:
        L += ["| Ruling | Verb | Phase | Batch |", "|---|---|---|---|"]
        for r in c["rulings"][:RECENT_RULINGS]:
            head = f"[{r['id']}]({r['rel']})" + ("" if r["head"] else " (superseded)")
            L.append(f"| {head} | {_cell(r['verb'] or '-')} | "
                     f"{_cell(r['phase'] or '-')} | {_cell(r['batch'] or '-')} |")
        L += [""]
    else:
        L += ["- _(no rulings yet)_", ""]

    L += h2("epics")
    epic_rows = []
    for e in c["epics"]:
        head = f"<b>{_summary_label(e.get('title') or e['slug'])}</b>"
        half = e.get("mind-half")
        if half and half != "none":
            head += f" — Mind half: <code>{_summary_label(half)}</code>"
        if e.get("ledger"):
            head += f" — ledger: <code>{_summary_label(e['ledger'])}</code>"
        if e.get("status"):
            head += f" — {_summary_label(e['status'])}"
        epic_rows.append(_task_row(head, _epic_payload(e)))
    L += _items(epic_rows) or ["- _(no epics yet)_"]
    L += [""]

    L += h2("projects")
    if c["projects"]:
        L += ["| Project | Status | Partition | Sync | Ledger | Witness |",
              "|---|---|---|---|---|---|"]
        for key, row in sorted(c["projects"].items()):
            L.append(f"| {_cell(key)} | {_cell(row.get('status', '-'))} | "
                     f"{_cell(row.get('partition', '-'))} | "
                     f"`{_cell(row.get('sync_cli', '-'))}` | "
                     f"`{_cell(row.get('ledger', '-'))}` | "
                     f"`{_cell(row.get('witness_file', '-'))}` |")
        L += [""]
    else:
        L += ["- _(the science body map is empty)_", ""]

    links = _board_links(home, THEME_ORGAN)
    if links:
        L += ["---", "",
              "Boards: " + " · ".join(f"[{name.title()}]({url})"
                                      for name, url in links), ""]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------- html ---
_FRESH_CSS = (".fresh{border-left:3px solid var(--edge);padding:.1rem .9rem;"
              "margin:1.2rem 0;background:var(--tint)}"
              ".fresh p{margin:.5rem 0}"
              "table.map{width:100%;border-collapse:collapse;font-size:.95em}"
              "table.map th{text-align:left;color:var(--muted);"
              "font-weight:600}"
              "table.map td,table.map th{border-bottom:1px solid var(--line);"
              "padding:.4rem .5rem .4rem 0;vertical-align:top}")


def render_dashboard_html(c: dict) -> str:
    """The one-tap-copy twin GitHub Pages serves — same content, real buttons."""
    home = c.get("home", "")
    blob = f"{home}/blob/main/" if home else ""
    titles = {key: title for key, title, _s, _b in SECTIONS}
    srcs = {key: src for key, _t, src, _b in SECTIONS}
    blurbs = {key: blurb for key, _t, _s, blurb in SECTIONS}

    def link(path, text_html):
        return f'<a href="{_attr(blob + path)}">{text_html}</a>'

    def h2(key):
        a = (f' <a class="mdsrc" href="{_attr(_src_url(blob, srcs[key]))}">'
             "markdown version</a>") if blob else ""
        return (f'<a id="{_anchor(titles[key])}"></a><h2>{titles[key]}{a}</h2>'
                f'<p class="muted">{_md_inline(blurbs[key])}</p>')

    def phase_head(r, tone_pills=()):
        head = link(r["rel"], _summary_label(r["title"]))
        head += pills(*tone_pills) if tone_pills else ""
        facets = [f"{r['project']} phase {r['phase']}" if r["phase"] is not None
                  else r["project"]]
        if r["budget"]:
            facets.append(f"budget {r['budget']}")
        if r["review_minutes"] is not None:
            facets.append(f"{r['review_minutes']} review-min")
        if r["runs"]:
            facets.append("runs " + ", ".join(x["ident"] for x in r["runs"]))
        return head + f'<span class="facets"> — {_summary_label(" · ".join(facets))}</span>'

    counts = section_counts(c)
    H = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>PyAutoCortex Dashboard</title>",
        f"<!-- generated by `pyauto-brain cortex dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        f"<style>{_theme_css(THEME_ORGAN)}{_FRESH_CSS}</style>",
        "</head>",
        "<body>",
        hero(THEME_ORGAN, "Dashboard",
             "Every science phase the Cortex is holding. Tap a phase's 📋 and "
             "its next command is on your clipboard. The verdict is always "
             "yours — this page hands you the command, never the ruling."),
        stats(*[(n, title) for _key, title, n in counts]),
    ]
    # One line, deliberately: the `--check` normaliser drops it whole so a
    # date change is not drift.
    H += [f'<div class="fresh"><p><b>Last updated {c["generated"]}.</b> This '
          f'page is {_md_inline(REFRESH_BLURB)}</p></div>']
    if home:
        H.append(f'<p class="muted mdsrc">'
                 f'{link("dashboard.md", "markdown version")} · '
                 f'{link("README.md", "GitHub Page")}</p>')
    if c["problems"]:
        H += ['<p>⚠️ <b>The tree does not check</b> — '
              "<code>scripts/cortex.py check</code> reports:</p>", "<ul>"]
        H += [f"<li><code>{_attr(p)}</code></li>" for p in c["problems"][:10]]
        H += ["</ul>"]

    H.append(h2("awaiting"))
    for r in c["awaiting"]:
        tone = ("failures", "r") if r["failed_runs"] else (r["state"], "y")
        H.append(_html_task(phase_head(r, (tone,)), _ruling_payload(r)))
    if not c["awaiting"]:
        H.append('<p class="muted">(nothing awaiting a ruling)</p>')

    H.append(h2("live"))
    for r in c["live"]:
        note = _live_note(r)
        text = phase_head(r, ((r["state"], "n"),))
        if note:
            text += f'<span class="facets"> — {_summary_label(note)}</span>'
        H.append(_html_task(text, _live_payload(r, c["projects"])))
    if not c["live"]:
        H.append('<p class="muted">(nothing on the queue)</p>')

    H.append(h2("ready"))
    for r in c["ready"]:
        H.append(_html_task(phase_head(r, (("ready", "g"),)),
                            _ready_payload(r, c["projects"])))
    if not c["ready"]:
        H.append('<p class="muted">(nothing ready to launch)</p>')

    H.append(h2("gated"))
    for r in c["gated"]:
        text = phase_head(r, tuple((ref, "y") for ref in r["gates"]))
        H.append(_html_task(text, _gate_payload(r)))
    if not c["gated"]:
        H.append('<p class="muted">(nothing gated)</p>')

    H.append(h2("rulings"))
    if c["rulings"]:
        H += ['<table class="map">',
              "<tr><th>Ruling</th><th>Verb</th><th>Phase</th><th>Batch</th></tr>"]
        for r in c["rulings"][:RECENT_RULINGS]:
            head = link(r["rel"], _summary_label(r["id"]))
            if not r["head"]:
                head += ' <span class="muted">(superseded)</span>'
            H.append(f"<tr><td>{head}</td>"
                     f"<td>{_summary_label(r['verb'] or '-')}</td>"
                     f"<td>{_summary_label(r['phase'] or '-')}</td>"
                     f"<td>{_summary_label(r['batch'] or '-')}</td></tr>")
        H.append("</table>")
    else:
        H.append('<p class="muted">(no rulings yet)</p>')

    H.append(h2("epics"))
    for e in c["epics"]:
        text = f"<b>{_summary_label(e.get('title') or e['slug'])}</b>"
        half = e.get("mind-half")
        if half and half != "none":
            # The epic's development half lives in the Mind; the card links it
            # so the two dashboards read as one programme.
            text += f'<span class="facets"> — Mind half: <code>{_summary_label(half)}</code></span>'
        if e.get("ledger"):
            text += f'<span class="facets"> — ledger: <code>{_summary_label(e["ledger"])}</code></span>'
        if e.get("status"):
            text += f'<span class="facets"> — {_summary_label(e["status"])}</span>'
        H.append(_html_task(text, _epic_payload(e)))
    if not c["epics"]:
        H.append('<p class="muted">(no epics yet)</p>')

    H.append(h2("projects"))
    if c["projects"]:
        H += ['<table class="map">',
              "<tr><th>Project</th><th>Status</th><th>Partition</th>"
              "<th>Sync</th><th>Witness</th></tr>"]
        for key, row in sorted(c["projects"].items()):
            H.append(f"<tr><td><b>{_summary_label(key)}</b></td>"
                     f"<td>{_summary_label(row.get('status', '-'))}</td>"
                     f"<td>{_summary_label(row.get('partition', '-'))}</td>"
                     f"<td><code>{_summary_label(row.get('sync_cli', '-'))}</code></td>"
                     f"<td><code>{_summary_label(row.get('witness_file', '-'))}</code></td>"
                     "</tr>")
        H.append("</table>")
    else:
        H.append('<p class="muted">(the science body map is empty)</p>')

    footer = boards_footer(dict(_board_links(home, THEME_ORGAN)), THEME_ORGAN)
    if footer:
        H.append(footer)
    H += [f"<script>{_THEME_JS}</script>", "</body>", "</html>"]
    return "\n".join(H) + "\n"


# The two lines that change on a re-render without the page changing: the
# generation comment and the visible freshness banner. The Mind's normaliser
# strips only the comment, which is why its `--check` drifts every day and
# self-heals with an empty commit; the Cortex strips both.
def dashboard_body(page: str) -> str:
    """The page minus every stamp `--check` must not read as drift."""
    def keep(line: str) -> bool:
        return not (line.startswith("<!-- generated by")
                    or line.startswith("> **Last updated")
                    or line.startswith('<div class="fresh">'))
    return "\n".join(l for l in page.splitlines() if keep(l))


def render_pages(c: dict) -> dict:
    return {"dashboard.md": render_dashboard(c),
            "dashboard.html": render_dashboard_html(c)}


# ------------------------------------------------------------------- plan ---
def detect_lane() -> str:
    """`local-dev` or `web-github` — where this session is running.

    The same probe the batch conductor uses: a remote session has no `gh`. No
    env var decides it; a session that could lie about where it is would plan
    laptop runs it cannot launch.
    """
    return LOCAL_LANE if shutil.which("gh") else "web-github"


def plan(c: dict, budget: int = DEFAULT_REVIEW_BUDGET,
         lane: str | None = None) -> dict:
    """Which ready phases fit the slot.

    The admission rule is the Cortex's own, not the Mind's: a phase is
    plannable when it is `ready`, has a registered witness and a budget, and
    its lane is this session's. No autonomy cap is consulted — science members
    are supervised by definition and the ruling is the human's.
    """
    session_lane = lane or detect_lane()
    members, rejected, pool = [], [], []
    for r in c["ready"]:
        if not (r["witness"] or "").strip():
            rejected.append((r["rel"], "no Witness: — nothing to score"))
        elif not (r["budget"] or "").strip():
            rejected.append((r["rel"], "no Budget:"))
        elif r["lane"] != session_lane:
            rejected.append((r["rel"],
                             f"lane {r['lane']}, session {session_lane}"))
        else:
            pool.append(r)
    # Cheapest first: this list is read when the human has a slot to fill.
    pool.sort(key=lambda r: (r["review_minutes"] if r["review_minutes"]
                             is not None else 999, r["rel"]))
    spent = 0
    for r in pool:
        cost = r["review_minutes"] or 0
        if spent + cost > budget:
            rejected.append((r["rel"], f"{cost} min would exceed the budget"))
            continue
        members.append(r)
        spent += cost
    return {
        "session_lane": session_lane,
        "review_budget": budget,
        "review_minutes_planned": spent,
        "members": members,
        "rejected": rejected,
        "ready_count": len(c["ready"]),
        "launch": [launch_payload(r, c["projects"]) for r in members],
    }


def emit_plan(d: dict) -> None:
    print("== CortexPlan ==")
    print(f"Session lane:      {d['session_lane']}")
    print(f"Review budget:     {d['review_budget']} min")
    print(f"Planned:           {d['review_minutes_planned']} review-minutes "
          f"over {len(d['members'])} member(s)")
    print()
    if d["session_lane"] != LOCAL_LANE:
        # The laptop-lane ruling: a science run is launched from the machine
        # that can reach the queue. A cloud session reports and plans nothing.
        print(f"  {d['ready_count']} phase(s) are ready — every Cortex phase "
              f"is `{LOCAL_LANE}`, so run")
        print("  `pyauto-brain cortex plan` from the laptop to plan them.")
        print()
        return
    if d["members"]:
        for r in d["members"]:
            print(f"  {r['review_minutes'] or 0:>3} min  "
                  f"{r['project']:<12} {r['rel']}")
            if not (r["witness"] or "").strip():
                print("           (no witness — not plannable)")
    else:
        print("  (no members — see the rejections below)")
    print()
    print(f"Not selected: {len(d['rejected'])}")
    counts: dict[str, int] = {}
    for _rel, why in d["rejected"]:
        key = why.split(":")[0].split(" would")[0]
        counts[key] = counts.get(key, 0) + 1
    for why, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {n:>4}  {why}")
    print()
    if d["members"]:
        print("To launch: run ONE of these, then record the job id —")
        for lines in d["launch"]:
            for line in lines:
                print(f"  {line}")
            print()
    print("This is a PROPOSAL. The submission is yours; the conductor never")
    print("dispatches, and the ruling on what comes back is yours too.")


# ----------------------------------------------------------------- census ---
def emit_census(c: dict) -> None:
    print("== Cortex census ==")
    print(f"Root:            {c['root']}")
    print(f"Phases:          {len(c['phases'])}   "
          + " · ".join(f"{k} {n}" for k, n in sorted(c["by_state"].items())))
    print(f"Board:           " + " · ".join(
        f"{title.lower()} {n}" for _k, title, n in section_counts(c)))
    print(f"Rulings:         {len(c['rulings'])}   "
          f"(heads {sum(1 for r in c['rulings'] if r['head'])})")
    print(f"Projects:        {len(c['projects'])}   "
          + " · ".join(sorted(c["projects"])))
    print(f"Batches:         {len(c['batches'])} record(s) · "
          f"{len(c['reviews'])} review(s)")
    print(f"Epics:           {len(c['epics'])}")
    if c["problems"]:
        print(f"Problems:        {len(c['problems'])} — run "
              "`python3 scripts/cortex.py check`")


# -------------------------------------------------------------------- cli ---
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cortex",
        description="The Cortex Agent — reason over PyAutoCortex: the board, "
                    "the gates, the slot. It never submits and never rules.")
    sub = ap.add_subparsers(dest="verb")

    def common(p):
        p.add_argument("--cortex", default="",
                       help="the PyAutoCortex checkout (default: $PYAUTO_CORTEX, "
                            "then beside this Brain checkout)")
        return p

    c = common(sub.add_parser("census", help="what the Cortex is holding"))
    c.add_argument("--json", dest="as_json", action="store_true")

    d = common(sub.add_parser("dashboard", help="render dashboard.md/.html"))
    d.add_argument("--check", action="store_true",
                   help="exit 1 if the committed pages are stale")
    d.add_argument("--apply", action="store_true", help="write both pages")

    p = common(sub.add_parser("plan", help="which ready phases fit a slot"))
    p.add_argument("--budget", type=int, default=DEFAULT_REVIEW_BUDGET,
                   help="review-minutes available in the slot")
    p.add_argument("--lane", default="",
                   help="override the detected session lane")

    g = common(sub.add_parser("gates", help="the gate refs, and grade them"))
    g.add_argument("--grade", action="store_true",
                   help="fetch every ref and give a verdict per phase")
    g.add_argument("--apply", action="store_true",
                   help="write the flips (implies --grade)")

    common(sub.add_parser("collect", help="score a pulled run (phase 2b)"))
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    verb = a.verb or "census"
    if verb == "census" and not hasattr(a, "cortex"):  # bare `cortex`
        a = ap.parse_args(["census"])

    root = resolve_root(getattr(a, "cortex", "") or None)
    try:
        mod = load_cortex(root)
    except CortexUnavailable as e:
        print(f"cortex: {e}", file=sys.stderr)
        return RC_USAGE

    if verb == "gates":
        # A thin wrapper: the grading, the clearing rule and the writes are
        # the Cortex script's, so the daily job can run them with no Brain
        # checkout at all. `--apply` is this surface's spelling of `--write`.
        lines, rc = mod.gates_report(root, grade=a.grade or a.apply,
                                     write=a.apply)
        print("\n".join(lines))
        return rc

    if verb == "collect":
        print("cortex collect lands in slice B of PyAutoMind#380 — until then "
              "score a pulled run by hand against the phase's `## Witness`.",
              file=sys.stderr)
        return RC_USAGE

    try:
        c = census(root)
    except mod.CortexError as e:
        print(f"cortex: {root}: {e}", file=sys.stderr)
        return RC_UNREADABLE
    except OSError as e:
        print(f"cortex: cannot read {root}: {e}", file=sys.stderr)
        return RC_UNREADABLE

    if verb == "census":
        print(json.dumps({k: v for k, v in c.items() if k != "phases"},
                         indent=2)) if a.as_json else emit_census(c)
        return RC_OK

    if verb == "plan":
        emit_plan(plan(c, budget=a.budget, lane=a.lane or None))
        return RC_OK

    if verb == "dashboard":
        pages = render_pages(c)
        if a.check:
            stale = []
            for name, want in pages.items():
                target = root / name
                on_disk = (target.read_text(encoding="utf-8")
                           if target.is_file() else "")
                if dashboard_body(on_disk) != dashboard_body(want):
                    stale.append(name)
            if not stale:
                print("dashboard.md + dashboard.html are current")
                return RC_OK
            print(f"{' + '.join(stale)} stale — regenerate with "
                  "`pyauto-brain cortex dashboard --apply`", file=sys.stderr)
            return RC_DRIFT
        if a.apply:
            for name, want in pages.items():
                (root / name).write_text(want, encoding="utf-8")
            print(f"Wrote: {' + '.join(pages)} "
                  f"({len(c['phases'])} phase(s), {len(c['rulings'])} ruling(s))")
            return RC_OK
        print(pages["dashboard.md"], end="")
        return RC_OK

    ap.print_help(sys.stderr)
    return RC_USAGE


if __name__ == "__main__":
    sys.exit(main())

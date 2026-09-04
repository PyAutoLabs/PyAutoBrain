#!/usr/bin/env python3
"""agents/conductors/cortex/_cortex.py — core for the Cortex Agent.

The Cortex Agent is the *learning function* of PyAutoBrain: the conductor that
reasons over PyAutoCortex, the organ where the organism learns what is true.
The Cortex holds the state — science phases, their pre-registered witnesses,
their runs and the rulings of record; this conductor holds the reasoning: it
renders the Cortex board, grades the gates, admits ready phases into a laptop
slot and scores what a pull brought back into a packet member. It **never
submits** and never edits a ruling: the run is the human's act, the verdict is
theirs, and the `Ruling` line this verb emits is left blank for them.

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

Verbs: `checkin [--dry-run|--apply] [--push|--no-push] [--project KEY]
[--skip-pull] [--refreshed ISO]` · `census [--json]` ·
`dashboard --check|--apply` · `gates` ·
`collect [--pull] [--refreshed ISO] [--apply] [--out F] [--phase REL]`.

`checkin` is **the door** — the one command behind "where is my science?": it
pulls every active project through that project's own sync CLI, scores every
`submitted | running` phase, moves what came back, re-renders the board,
optionally pushes the ledger, and prints a summary keyed **by project** with
the copy-ready prompt each phase's state already has. It composes the verbs
below and reasons nothing extra of its own.

`collect` is the scorer it composes: with no `--phase` it scopes to every phase
in `submitted | running`. It needs no batch record — the review-slot apparatus
was retired 2026-09-03.

Exit codes: 0 ok · 1 dashboard drift (the `dashboard_refresh.yml` contract),
and for `collect` a member the human must look at · 2 bad args / no Cortex
checkout · 3 the Cortex tree could not be read.
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
import tempfile
import zipfile
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
     "Gate cleared, witness registered — everything that could be submitted "
     "today."),
    ("gated", "Gated", "phases/",
     "Waiting on development work. Open the references; when they have all "
     "closed, `cortex.py move <phase> ready`."),
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
    "generated from `phases/`, `rulings/`, `epics.md` and `projects.yaml`, so "
    "it is only as current as they are. `dashboard_refresh.yml` re-renders it "
    "on every push to `main`."
)


def _mins(value: str) -> int | None:
    """`H+:MM` → minutes, or None."""
    m = re.fullmatch(r"(\d+):(\d{2})", (value or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _int(value: str) -> int | None:
    v = (value or "").strip()
    return int(v) if v.isdigit() else None


def _phase_row(mod, ph) -> dict:
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
        "witness": ph.get("Witness"),
        "budget": budget,
        "budget_minutes": _mins(budget),
        "runs": runs,
        "wall_minutes": max(walls) if walls else 0,
        "ruling": ph.get("Ruling"),
        "epic": ph.get("Epic"),
        "review_minutes": _int(ph.get("Review-minutes")),
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

    rows = [_phase_row(mod, ph) for ph in phases]
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

    home = _home(root)
    return {
        "root": str(root),
        "home": home,
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
    return ("python3 scripts/cortex.py gates   # then, once they have closed: "
            f"move {r['rel']} ready\n# gates: " + ", ".join(r["gates"]))


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
    """Budget vs elapsed — the live-progress line."""
    bits = []
    if r["budget_minutes"]:
        pct = round(100 * r["wall_minutes"] / r["budget_minutes"])
        bits.append(f"wall {r['wall_minutes'] // 60}:{r['wall_minutes'] % 60:02d}"
                    f" of {r['budget']} ({pct}%)")
    return " · ".join(bits)


def _gate_note(r: dict) -> str:
    return ", ".join(r["gates"]) or "no refs"


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
    print(f"Epics:           {len(c['epics'])}")
    if c["problems"]:
        print(f"Problems:        {len(c['problems'])} — run "
              "`python3 scripts/cortex.py check`")


# ---------------------------------------------------------------- collect ---
# What a pull brought back, scored against the phase's own pre-registered
# witness. Two facts shape every rule below.
#
# **The laptop is the whole world.** This verb reads only what the human's own
# sync CLI has already mirrored; it never reaches RAL. The single exception is
# `--pull`, which runs that CLI's own `pull` verb — the human's command, in the
# human's project, opt-in.
#
# **Two of the four `delivered:` legs are not observable here.**
# `search_internal/checkpoint.hdf5` is excluded from both projects' pulls, and
# one of the two project layouts writes no version stamp at all. A scorer that
# called those legs PASS would be inventing evidence and a scorer that called
# them FAIL would condemn every healthy run, so there is a third verdict:
# UNOBSERVABLE, which sends the member to the human as SUSPECT. The checkpoint
# leg becomes observable exactly when the project's own sync CLI writes the
# pull manifest (`.cortex/pull.json`), and not before.
PASS, FAIL, UNOBSERVABLE = "PASS", "FAIL", "UNOBSERVABLE"

#: the six legs, in the order the member block reads them — the four
#: `delivered:` legs the batch records were scored on plus the two the laptop
#: tree made necessary.
LEGS = ("err", "wall", "version", "checkpoint", "resume", "witness")
LEG_TITLES = {
    "err": "`.err` clean",
    "wall": "wall vs budget",
    "version": "version stamp",
    "checkpoint": "`checkpoint.hdf5` sane",
    "resume": "a fresh run, not a resume",
    "witness": "the witness landed",
}

#: `<mirror or local_path>/.cortex/pull.json`, written by each project's own
#: sync CLI (PyAutoCortex decision 51):
#: `{"schema": 1, "pulled_at": ISO,
#:   "checkpoints": {"<run dir rel to the pull root>": {"bytes": N, "mtime": ISO}},
#:   "runs": {"<jobid|jobid_task>": {"checkpoint_bytes": N, "checkpoint_mtime": ISO}}}`.
#: `checkpoints` is always filled — it is keyed by the only name both sides can
#: say — while `runs` is filled only where the CLI can link a job id to a run
#: directory. A manifest with no `schema` key is the phase-2 shape (`runs`
#: only) and still reads. Absent altogether — hence UNOBSERVABLE.
PULL_MANIFEST = (".cortex", "pull.json")

LOG_DEPTH = 4  # `**/output.<jobid>*.out` — deep enough for both layouts

# A benign `.err` is not an empty one: the baseline both projects produce is a
# warning line plus its indented source line. Anything else is read.
FATAL_ERR_RE = re.compile(r"Traceback|Error|Killed|OOM|out of memory")
BENIGN_ERR_RE = re.compile(r"\w*Warning\b")
# A resumed run is not a run of the model under test: it reports the previous
# fit's samples. Both spellings the stack emits.
RESUME_MARKER_RE = re.compile(r"Fit Already Completed"
                              r"|Resuming .*previous samples found")
FINISHED = "Finished."
STAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
TIME_TO_RUN_RE = re.compile(r"Time To Run\s*=\s*(\d+):(\d{2}):(\d{2})")
SUMMARY_NAME = "search.summary"


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _stamp_dt(value: str) -> _dt.datetime | None:
    m = STAMP_RE.search(value or "")
    if not m:
        return None
    try:
        return _dt.datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
    except ValueError:
        return None


def _since(ph) -> _dt.datetime:
    """The earliest date at which an artefact could belong to this campaign.

    The *first* submission, not the last: an array resubmitted on Tuesday does
    not make Monday's outputs stale, and a witness written by the run that
    preceded a failed resubmit is still this phase's witness. Freshness here
    means "not left over from before the phase started".
    """
    days = sorted(r.date for r in ph.runs if r.date)
    if not days:
        return _dt.datetime.min
    try:
        return _dt.datetime.fromisoformat(days[0])
    except ValueError:
        return _dt.datetime.min


def _mtime(path: Path) -> _dt.datetime:
    try:
        return _dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return _dt.datetime.min


def _wall(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def project_roots(row: dict) -> list[Path]:
    """The search roots for one project: the mirror the sync CLI fills, then
    the checkout. Both come from `projects.yaml`; no path is named here."""
    roots = []
    for key in ("mirror", "local_path"):
        value = (row.get(key) or "").strip()
        if value and value != "none":
            p = Path(value).expanduser()
            if p.is_dir() and p not in roots:
                roots.append(p)
    return roots


def _depth_glob(root: Path, pattern: str, depth: int = LOG_DEPTH) -> list[Path]:
    """`**/<pattern>` bounded to `depth` levels — a science mirror holds tens
    of thousands of files and an unbounded `rglob` walks all of them."""
    out: list[Path] = []
    for d in range(depth + 1):
        try:
            out += sorted(root.glob("/".join(["*"] * d + [pattern])))
        except OSError:
            continue
    return out


def find_logs(roots: list[Path], stems: list[str]) -> dict:
    """The SLURM logs of these job stems: `{"out": [...], "err": [...]}`.

    Both layouts seen on the laptop are covered by the same two globs —
    `logs/output/output.<jobid>.out` and
    `hpc/batch_cpu/output/output.<jobid>_<task>.out`.
    """
    found: dict[str, list[Path]] = {"out": [], "err": []}
    for root in roots:
        for stem in stems:
            for kind, pattern in (("out", f"output.{stem}*.out"),
                                  ("err", f"error.{stem}*.err")):
                for p in _depth_glob(root, pattern):
                    if p not in found[kind]:
                        found[kind].append(p)
    return found


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def where_paths(mod, ph, roots: list[Path]) -> list[Path]:
    """The phase's own `## Where to look` bullets, intersected with the roots.

    A phase names where its results are; that is the first place to look. A
    bullet pointing outside every root is not this project's tree (a RAL path,
    say) and is dropped rather than followed.
    """
    getter = getattr(mod, "_where_to_look", None)
    if getter is not None:
        bullets = getter(ph)
    else:  # a checkout whose script predates the helper
        span = mod.sections(ph.text).get("Where to look")
        bullets = ([ln for ln in ph.text.split("\n")[span[0]:span[1]]
                    if ln.startswith("- ") and ln.strip() != "-"]
                   if span else [])
    out = []
    for bullet in bullets:
        token = bullet[2:].strip().split()[0].strip("`,.") if bullet[2:].strip() else ""
        if not token:
            continue
        p = Path(token)
        if p.is_absolute() and any(_under(p, r) for r in roots) and p.exists():
            out.append(p)
    return out


def run_artifacts(roots: list[Path], where: list[Path],
                  since: _dt.datetime) -> tuple:
    """`(run_dir, zip_path)` — where this run's `search.summary` lives.

    The zip is authoritative when both exist: seven of the subhalo project's
    extracted run dirs are stale partial extractions, and reading the wall
    clock out of one of those reports a run that never finished as short.
    """
    bases = list(where) or [r / "output" for r in roots if (r / "output").is_dir()]
    seen: dict[Path, Path | None] = {}
    for base in bases:
        if (base / SUMMARY_NAME).is_file() or (base / ".completed").exists():
            seen.setdefault(base, None)
        try:
            for marker in sorted(base.rglob(".completed")):
                seen.setdefault(marker.parent, None)
            for z in sorted(base.rglob("*.zip")):
                seen[z.with_suffix("")] = z
        except OSError:
            continue
    if not seen:
        return None, None
    scored = [(max(_mtime(d), _mtime(z) if z else _dt.datetime.min), d, z)
              for d, z in seen.items()]
    fresh = [row for row in scored if row[0] >= since]
    best = max(fresh or scored, key=lambda row: (row[0], str(row[1])))
    return best[1], best[2]


def summary_minutes(run_dir: Path | None, zip_path: Path | None) -> tuple:
    """`(minutes, raw, source)` from `search.summary` — the zip first."""
    if zip_path is not None and zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if name.rsplit("/", 1)[-1] == SUMMARY_NAME:
                        text = zf.read(name).decode("utf-8", "replace")
                        got = _time_to_run(text)
                        if got:
                            return got[0], got[1], f"{zip_path.name} (zip)"
        except (OSError, zipfile.BadZipFile):
            pass
    if run_dir is not None and run_dir.is_dir():
        candidates = [run_dir / SUMMARY_NAME]
        if not candidates[0].is_file():
            try:
                candidates = sorted(run_dir.rglob(SUMMARY_NAME))[:1]
            except OSError:
                candidates = []
        for path in candidates:
            got = _time_to_run(_read(path))
            if got:
                return got[0], got[1], f"{run_dir.name}/{SUMMARY_NAME}"
    return None, None, ""


def _time_to_run(text: str) -> tuple | None:
    m = TIME_TO_RUN_RE.search(text or "")
    if not m:
        return None
    h, mi, s = (int(x) for x in m.groups())
    return h * 60 + mi, f"{h}:{mi:02d}:{s:02d}"


def witness_matches(roots: list[Path], pattern: str, since: _dt.datetime,
                    tokens: set | None = None) -> list[Path]:
    """Every file matching the project's `witness_file` glob, this phase's own
    first.

    `witness_file` is a *project-wide* glob and a project's phases share one
    output tree, so the glob alone would hand a phase its neighbour's numbers.
    A file whose path names this phase's run stem, or the directory its results
    were pulled into, is this phase's witness; everything else sorts behind it,
    newest first, rather than being hidden — a phase whose witness landed
    somewhere unexpected still has a witness.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return []
    hits: list[Path] = []
    for root in roots:
        try:
            hits += [p for p in root.glob(pattern) if p.is_file()]
        except (OSError, ValueError):
            continue
    fresh = [p for p in hits if _mtime(p) >= since]
    marks = {t for t in (tokens or set()) if t}
    return sorted(fresh, key=lambda p: (any(t in str(p) for t in marks),
                                        _mtime(p), str(p)), reverse=True)


def pull_manifest(roots: list[Path]) -> dict:
    """`<root>/.cortex/pull.json`, or `{}` — the only window onto RAL-only
    artefacts, and it exists only where the project's sync CLI writes it."""
    for root in roots:
        path = root.joinpath(*PULL_MANIFEST)
        if path.is_file():
            try:
                data = json.loads(_read(path))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


# --------------------------------------------------------------- the legs ---
def leg_err(errs: list[Path]) -> tuple:
    if not errs:
        return UNOBSERVABLE, "no `.err` file under the mirror"
    for path in errs:
        lines = [ln for ln in _read(path).split("\n") if ln.strip()]
        odd = [ln for ln in lines
               if not (ln[:1].isspace() or BENIGN_ERR_RE.search(ln))]
        if not odd:
            continue
        if any(FATAL_ERR_RE.search(ln) for ln in lines):
            first = next(ln for ln in lines if FATAL_ERR_RE.search(ln))
            return FAIL, f"{path.name}: {first.strip()[:110]}"
        return (UNOBSERVABLE,
                f"{path.name}: {len(odd)} line(s) that are neither warning nor "
                f"error — read it: {odd[0].strip()[:80]}")
    warned = sum(1 for p in errs
                 if BENIGN_ERR_RE.search(_read(p)))
    return PASS, (f"{len(errs)} file(s) hold only warnings"
                  if warned else f"{len(errs)} file(s), empty")


def leg_wall(outs: list[Path], run_dir, zip_path, budget_minutes,
             budget: str) -> tuple:
    minutes, raw, source = None, "", ""
    for path in outs:
        text = _read(path)
        if not text.rstrip().endswith(FINISHED):
            continue
        stamps = STAMP_RE.findall(text)
        if len(stamps) >= 2:
            a = _stamp_dt(f"{stamps[0][0]} {stamps[0][1]}")
            b = _stamp_dt(f"{stamps[-1][0]} {stamps[-1][1]}")
            if a and b and b >= a:
                minutes = int((b - a).total_seconds() // 60)
                raw, source = _wall(minutes), path.name
                break
    if minutes is None:
        minutes, raw, source = summary_minutes(run_dir, zip_path)
    if minutes is None:
        return (UNOBSERVABLE,
                "no `.out` ending `Finished.` and no `search.summary` — "
                "the run's wall clock is not on the laptop")
    if budget_minutes and minutes > budget_minutes:
        return FAIL, f"wall {raw} over the {budget} budget (from {source})"
    return PASS, (f"wall {raw}" + (f" of {budget}" if budget else "")
                  + f" (from {source})")


def leg_version(hits: list[Path]) -> tuple:
    jsons = [p for p in hits if p.suffix == ".json"]
    for path in jsons:
        try:
            data = json.loads(_read(path))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "version" in data:
            return PASS, f"{data['version']} — {path.name}"
    if not jsons:
        return (UNOBSERVABLE,
                "the witness is not JSON — this project writes no version "
                "stamp")
    return (UNOBSERVABLE,
            f"{len(jsons)} witness JSON(s), none with a top-level `version` key")


def _manifest_run_dir_key(roots: list[Path], run_dir) -> str:
    """The run directory as the puller named it: its path relative to the pull
    root it sits under. The empty string when it sits under none of them."""
    if run_dir is None:
        return ""
    for root in roots:
        if _under(run_dir, root):
            try:
                return run_dir.relative_to(root).as_posix()
            except ValueError:
                continue
    return ""


def leg_checkpoint(manifest: dict, roots: list[Path], run_dir, ph) -> tuple:
    """Three lookups, in order: the job id, its bare stem, then the run
    directory. The third is the one the profiling project can answer — its
    pull carries no job id at all, so `runs` is empty there and `checkpoints`
    is keyed by the run directory instead."""
    runs = manifest.get("runs") if isinstance(manifest.get("runs"), dict) else {}
    ckpts = (manifest.get("checkpoints")
             if isinstance(manifest.get("checkpoints"), dict) else {})
    rows: list[tuple] = []
    for r in ph.runs:
        row = runs.get(r.ident) or runs.get(r.stem)
        if isinstance(row, dict):
            rows.append((r.ident, int(row.get("checkpoint_bytes") or 0)))
    if not rows:
        key = _manifest_run_dir_key(roots, run_dir)
        row = ckpts.get(key) if key else None
        if isinstance(row, dict):
            rows.append((key, int(row.get("bytes") or 0)))
    if not rows:
        return (UNOBSERVABLE,
                "RAL only — `search_internal/checkpoint.hdf5` is not pulled "
                "and no `.cortex/pull.json` records it")
    empty = [label for label, size in rows if not size]
    if empty:
        return FAIL, f"empty checkpoint for {', '.join(empty)} — not delivered"
    total = sum(size for _label, size in rows)
    return PASS, f"{len(rows)} checkpoint(s), {total} bytes (pull manifest)"


def leg_resume(outs: list[Path]) -> tuple:
    if not outs:
        return UNOBSERVABLE, "no `.out` file under the mirror"
    for path in outs:
        m = RESUME_MARKER_RE.search(_read(path))
        if m:
            return FAIL, (f"{path.name}: `{m.group(0)}` — this is the previous "
                          "fit's samples, not a run of the model under test")
    return PASS, f"no resume marker in {len(outs)} `.out` file(s)"


def leg_witness(hits: list[Path], roots: list[Path], pattern: str) -> tuple:
    if not pattern.strip():
        return UNOBSERVABLE, "the project row names no `witness_file`"
    if not hits:
        return FAIL, f"nothing matching `{pattern}` newer than the submission"
    root = next((r for r in roots if _under(hits[0], r)), None)
    name = hits[0].relative_to(root).as_posix() if root else hits[0].name
    return PASS, f"{name}" + (f" (+{len(hits) - 1} more)" if len(hits) > 1 else "")


def health_of(legs: dict) -> str:
    verdicts = [legs[k][0] for k in LEGS]
    if FAIL in verdicts:
        return "FAILED"
    return "SUSPECT" if UNOBSERVABLE in verdicts else "HEALTHY"


def _readout(hits: list[Path]) -> list[tuple]:
    """The witness JSON's top-level scalars — the numbers the human reads."""
    for path in hits:
        if path.suffix != ".json":
            continue
        try:
            data = json.loads(_read(path))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        rows = [(k, v) for k, v in data.items()
                if isinstance(v, (str, int, float, bool)) or v is None]
        if rows:
            return rows
    return []


def score_phase(mod, ph, projects: dict) -> dict:
    """Every leg of one phase, plus what the packet block needs to print it."""
    key = ph.get("Project") or ph.project_dir
    row = projects.get(key, {})
    roots = project_roots(row)
    stems = sorted({r.stem for r in ph.runs})
    logs = find_logs(roots, stems)
    since = _since(ph)
    where = where_paths(mod, ph, roots)
    run_dir, zip_path = run_artifacts(roots, where, since)
    pattern = (row.get("witness_file") or "").strip()
    hits = witness_matches(roots, pattern, since,
                           tokens={r.stem for r in ph.runs}
                           | {p.name for p in where})
    budget = ph.get("Budget")
    legs = {
        "err": leg_err(logs["err"]),
        "wall": leg_wall(logs["out"], run_dir, zip_path, _mins(budget), budget),
        "version": leg_version(hits),
        "checkpoint": leg_checkpoint(pull_manifest(roots), roots, run_dir, ph),
        "resume": leg_resume(logs["out"]),
        "witness": leg_witness(hits, roots, pattern),
    }
    pulled_to = (str(run_dir) if run_dir is not None else
                 str(logs["out"][0].parent) if logs["out"] else
                 str(roots[0]) if roots else "")
    return {
        "slug": ph.slug,
        "rel": ph.rel,
        "phase": ph,
        "project": key,
        "state": ph.state,
        "live_run": any(r.state in mod.LIVE_RUN_STATES for r in ph.runs),
        "legs": legs,
        "health": health_of(legs),
        "roots": roots,
        "logs": logs,
        "run_dir": run_dir,
        "zip": zip_path,
        "witness_hits": hits,
        "readout": _readout(hits),
        "pulled_to": pulled_to,
    }


# ------------------------------------------------------ the packet member ---
def _section_text(mod, ph, name: str) -> str:
    span = mod.sections(ph.text).get(name)
    if span is None:
        return ""
    body = "\n".join(ph.text.split("\n")[span[0]:span[1]]).strip()
    return body


def member_block(mod, s: dict) -> list[str]:
    """One collected phase, as the report reads it."""
    ph = s["phase"]
    facets = [s["project"]]
    if ph.get("Phase"):
        facets.append(f"phase {ph.get('Phase')}")
    if ph.get("Budget"):
        facets.append(f"budget {ph.get('Budget')}")
    if ph.runs:
        facets.append("runs " + ", ".join(r.ident for r in ph.runs))
    L = [f"## {s['slug']} — {s['health']}", "",
         f"`{s['rel']}` — " + " · ".join(facets), "",
         "**Question**", "", _section_text(mod, ph, "Question") or "_(none)_",
         "", "**Witness**", ""]
    registered = ph.get("Witness")
    if registered:
        L += [f"Registered: {registered}", ""]
    L += [_section_text(mod, ph, "Witness") or "_(none)_", "",
          "**Health evidence**", ""]
    L += [f"- {LEG_TITLES[k]} — {s['legs'][k][0]} — {s['legs'][k][1]}"
          for k in LEGS]
    L += ["", "**Readout**", ""]
    if s["readout"]:
        L += ["| Key | Value |", "|---|---|"]
        L += [f"| `{_cell(k)}` | {_cell(v)} |" for k, v in s["readout"]]
    else:
        L += ["_(no JSON witness to read out — score the witness by eye)_"]
    # Left blank on purpose: the ruling is the human's sentence, and a draft
    # of it here is the conductor deciding.
    L += ["", "**Ruling**", "", "_(one line — yours to write)_", "",
          "**Your review**", ""]
    L += (["Leave to finish — a run of this phase is still live"]
          if s["live_run"] else ["Accept / Rerun / Drop / Leave to finish"])
    L += ["", "**Follow-ups**", ""]
    refs = mod.gate_refs(ph.get("Gates"))[0]
    L += ([f"- [{ref.split('#')[0]}] {ref}" for ref in refs] if refs
          else ["_(none yet — add them as you rule)_"])
    L += ["", "**Where to look yourself**", ""]
    for label, value in (("run dir", s["run_dir"]), ("zip", s["zip"])):
        if value is not None:
            L.append(f"- {label}: `{value}`")
    for kind in ("out", "err"):
        for path in s["logs"][kind][:2]:
            L.append(f"- `.{kind}`: `{path}`")
    for path in s["witness_hits"][:2]:
        L.append(f"- witness: `{path}`")
    if s["legs"]["checkpoint"][0] == UNOBSERVABLE:
        L.append("- `search_internal/checkpoint.hdf5`: **RAL only** — not "
                 "mirrored to the laptop")
    if len(L) and L[-1] == "":
        L.append("_(nothing found on the laptop)_")
    L += ["", f"**Est. review-minutes** — {ph.get('Review-minutes') or '?'}", ""]
    return L


def collect_report(mod, scope: str, scored: list, notes: list,
                   stamp: str = "") -> str:
    L = [f"# Cortex collect — {scope}", ""]
    if stamp:
        L += [f"Refreshed: {stamp}", ""]
    for s in scored:
        L += member_block(mod, s)
    if notes:
        L += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(L) + "\n"


def apply_ops(root: Path, mod, scored: list) -> list[str]:
    """Move every scored phase along the state table. Returns the notes.

    `submitted → pulled` is not an edge in the Cortex's transition table and a
    phase whose run line is still live has not finished, so both are left where
    they are with a note rather than forced. Nothing else is written: the batch
    record this once rewrote is closed history (retired 2026-09-03).
    """
    notes: list[str] = []
    by_rel = {ph.rel: ph for ph in mod.load_phases(root)[0]}
    for s in scored:
        ph = by_rel.get(s["rel"])
        if ph is None:
            notes.append(f"{s['slug']}: {s['rel']} is gone — not moved")
            continue
        state = ph.state
        try:
            if state == "running" and not any(r.state in mod.LIVE_RUN_STATES
                                              for r in ph.runs):
                mod.move_phase(root, ph.rel, "pulled",
                               pulled_to=s["pulled_to"] or None)
                state = "pulled"
            elif state == "running":
                notes.append(f"{s['slug']}: left running — a run line is still "
                             "submitted | running")
            elif state == "submitted":
                notes.append(f"{s['slug']}: left submitted — submitted → pulled "
                             "is not an edge; `move <phase> running` first")
            if state == "pulled":
                mod.move_phase(root, ph.rel, "awaiting-ruling")
                state = "awaiting-ruling"
        except mod.CortexError as e:
            notes.append(f"{s['slug']}: {e}")
    return notes


def run_pull(projects: dict, keys: list[str]) -> list[str]:
    """Run each project's own `<sync_cli> pull`. The command is printed before
    it runs: this is the one thing `collect` does that touches the cluster, and
    it is the human's own CLI doing it."""
    notes = []
    for key in keys:
        row = projects.get(key, {})
        local = (row.get("local_path") or "").strip()
        cli = (row.get("sync_cli") or "").strip()
        if not local or not cli or "pull" not in (row.get("sync_verbs") or []):
            notes.append(f"{key}: no `pull` verb in projects.yaml — not pulled")
            continue
        cmd = [str(Path(local) / cli), "pull"]
        print(f"$ cd {local} && {cli} pull")
        try:
            r = subprocess.run(cmd, cwd=local, capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as e:
            notes.append(f"{key}: pull could not run ({e}) — scored anyway")
            continue
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()
            notes.append(f"{key}: pull exited {r.returncode} — scored anyway"
                         + (f": {tail[-1][:160]}" if tail else ""))
    return notes


def cmd_collect(root: Path, mod, a) -> int:
    """The check-in. With no `--phase` the scope is every phase the Cortex
    believes is out there — `submitted | running` — because "what came back?"
    is a question about the runs, not about a slot somebody opened."""
    projects = mod.load_projects(root)[0]
    by_rel = {ph.rel: ph for ph in mod.load_phases(root)[0]}
    notes: list[str] = []
    phases = []
    if a.phase:
        for rel in a.phase:
            ph = by_rel.get(rel)
            if ph is None:
                notes.append(f"{rel}: no such phase — skipped")
            else:
                phases.append(ph)
    else:
        phases = [ph for ph in by_rel.values() if ph.state in LIVE_STATES]

    if a.pull:
        notes += run_pull(projects, sorted({ph.get("Project") or ph.project_dir
                                            for ph in phases}))
    stamp = a.refreshed.strip() or (_utc_now() if a.pull else "")

    scored = [score_phase(mod, ph, projects) for ph in phases]

    if a.apply:
        if not stamp:
            # `--apply` moves phases on the strength of what is on the laptop,
            # so the human has to say the laptop is current: either this run
            # pulled, or they pulled by hand and stamped it.
            print("cortex: --apply needs a refresh stamp — run it with --pull, "
                  "or pass --refreshed <ISO> when you pulled by hand",
                  file=sys.stderr)
            return RC_USAGE
        problems, applied, wrote = _apply_checked(root, mod, scored)
        notes += applied
        if problems:
            print("cortex: the tree does not check after the moves — "
                  + ("they were written; run `python3 scripts/cortex.py check`"
                     if wrote else "nothing was written") + ":",
                  file=sys.stderr)
            for problem in problems[:10]:
                print(f"  {problem}", file=sys.stderr)
            return RC_DRIFT

    delivered = sum(1 for s in scored if s["health"] == "HEALTHY")
    scope = " ".join(a.phase) if a.phase else "submitted | running"
    body = collect_report(mod, scope, scored, notes, stamp)
    print(f"collect [{scope}]: {len(scored)} phase(s), delivered "
          f"{delivered}/{len(scored)}")
    if a.out:
        Path(a.out).write_text(body, encoding="utf-8")
        print(f"Wrote: {a.out}")
    else:
        print(body, end="")
    return RC_OK if delivered == len(scored) else RC_DRIFT


def _apply_checked(root: Path, mod, scored: list) -> tuple:
    """`(problems, notes, wrote)` — rehearse the writes, then make them.

    `move_phase` writes phase by phase; a rejection halfway through would leave
    the tree in a state `check` fails on and no way back. So the whole apply is
    run against a throwaway copy first and only replayed on the real tree when
    `check_problems` comes back clean — and checked again afterwards, because
    the promise this verb makes is that it never leaves the Cortex in drift.
    """
    tmp = Path(tempfile.mkdtemp(prefix="cortex-collect-"))
    try:
        copy = tmp / root.name
        shutil.copytree(root, copy, ignore=shutil.ignore_patterns(".git"),
                        symlinks=True)
        apply_ops(copy, mod, scored)
        problems = mod.check_problems(copy)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        return problems, [], False
    notes = apply_ops(root, mod, scored)
    return mod.check_problems(root), notes, True


# --------------------------------------------------------------- check-in ---
# The one door. `collect` scores; `dashboard` renders; each project's own sync
# CLI pulls. `checkin` is the sequence a human actually wants when they ask
# "where is my science?" — sync every active project, score every live phase,
# move what finished, re-render the board, optionally push the ledger, and
# hand back the prompts. It composes the primitives above and adds none of its
# own reasoning; a phase edit is still `cortex.py move`'s and a verdict is
# still the human's.
#
# Three rules it does not bend:
#
# - **It reaches the cluster only through the projects' own CLIs.** No SSH of
#   its own, ever; `--dry-run` reaches nothing at all and prints the exact
#   command each project would run.
# - **One project's failure is that project's.** A pull that exits non-zero is
#   recorded against its project and the sweep continues — a check-in that
#   aborts on the first broken mirror tells you nothing about the other six.
# - **The push is a ledger push or it does not happen.** `claude/checkin-<date>`
#   cut from a fresh `origin/main`, explicit paths, no force, never `main`, and
#   refused outright if `ledger_merge.py classify` calls the diff code.
CHECKIN_BRANCH_PREFIX = "claude/checkin-"

#: The rule the `--push` default resolves by, stated wherever it is applied.
PUSH_RULE = ("`--push` needs `gh auth status` to succeed and the Cortex "
             "checkout to be clean on `main`")


def checkin_keys(projects: dict, phases: list, only: list) -> tuple:
    """`(keys, notes)` — the projects one check-in sweeps.

    Every `status: active` row, plus any project that owns a phase in
    `submitted | running`: a dormant project with a job still out there is
    still out there, and the run is what the check-in is about.
    """
    notes: list[str] = []
    keys = {key for key, row in projects.items()
            if (row.get("status") or "").strip() == "active"}
    for ph in phases:
        if ph.state in LIVE_STATES:
            keys.add(ph.get("Project") or ph.project_dir)
    for key in sorted(keys):
        if key not in projects:
            notes.append(f"{key}: a live phase names a project with no row in "
                         "projects.yaml — not pulled")
    keys &= set(projects)
    if only:
        for key in only:
            if key not in projects:
                notes.append(f"{key}: no such project in projects.yaml")
        keys &= set(only)
    return sorted(keys), notes


def pull_cmd(row: dict) -> tuple | None:
    """`(argv, cwd)` for this project's own `<sync_cli> pull`, or None when the
    row has no such verb. Every path comes from the row."""
    local = (row.get("local_path") or "").strip()
    cli = (row.get("sync_cli") or "").strip()
    if not local or not cli or "pull" not in (row.get("sync_verbs") or []):
        return None
    return [str(Path(local) / cli), "pull"], local


def pull_shell(row: dict) -> str:
    """The pull as a human would type it — what `--dry-run` prints."""
    cmd = pull_cmd(row)
    return (f"cd {cmd[1]} && {row.get('sync_cli')} pull" if cmd
            else "(no `pull` verb in projects.yaml)")


def run_pull_streamed(projects: dict, keys: list) -> dict:
    """`{key: (rc, note)}` — each project's own pull, **streamed**.

    Not captured: a pull runs for minutes and the human is watching this one
    command; buffering it would hold every project's output back to the end.
    `rc` is None when nothing ran.
    """
    results: dict[str, tuple] = {}
    for key in keys:
        row = projects.get(key, {})
        cmd = pull_cmd(row)
        if cmd is None:
            results[key] = (None, "no `pull` verb in projects.yaml — not pulled")
            continue
        argv, cwd = cmd
        print(f"\n$ {pull_shell(row)}", flush=True)
        try:
            rc = subprocess.run(argv, cwd=cwd).returncode
        except (OSError, subprocess.SubprocessError) as e:
            results[key] = (None, f"pull could not run ({e}) — scored anyway")
            continue
        results[key] = (rc, "" if rc == 0 else
                        f"pull exited {rc} — scored anyway, and the rest of "
                        "the sweep ran")
    return results


def pull_root(row: dict) -> Path | None:
    """Where this project's pull lands: the mirror it fills, else the
    checkout. The manifest is written at the top of that tree, which is the
    root `pull_manifest()` reads it back from."""
    for key in ("mirror", "local_path"):
        value = (row.get(key) or "").strip()
        if value and value != "none":
            path = Path(value).expanduser()
            if path.is_dir():
                return path
    return None


def write_pull_manifest(root_dir: Path, key: str, cmd: str, rc: int,
                        phases_live: list) -> Path | None:
    """Record this check-in's pull in `<pull root>/.cortex/pull.json`.

    **Merge, never clobber.** One project's own sync CLI already writes a
    richer manifest there (the `checkpoints` / `runs` tables the scorer's
    checkpoint leg reads); this adds the check-in's own keys and leaves every
    other key exactly as it found it. An unreadable file is replaced — it was
    telling the scorer nothing.
    """
    path = root_dir.joinpath(*PULL_MANIFEST)
    data: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(_read(path))
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            data = loaded
    data.update({"project": key, "pulled_at": _utc_now(), "cmd": cmd,
                 "rc": rc, "phases_live": list(phases_live)})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    except OSError:
        return None
    return path


# ------------------------------------------------------------- the push ---
def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def push_preflight(root: Path) -> tuple:
    """`(ok, reason)` — may this check-in push its own ledger diff?

    Read **before** anything is written, because "the checkout is clean" stops
    being true the moment the phases move. Two legs, both of them facts about
    this machine rather than a policy: a `gh` that is logged in (the cloud
    sessions have none, and that is the whole cloud/laptop split), and a
    Cortex checkout sitting clean on `main` (a dirty tree or a feature branch
    means the human is mid-something, and the check-in is not going to guess
    what).
    """
    if shutil.which("gh") is None:
        return False, "no `gh` on PATH — this is not a laptop session"
    if subprocess.run(["gh", "auth", "status"], capture_output=True,
                      text=True).returncode != 0:
        return False, "`gh auth status` fails — not authenticated"
    head = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode != 0:
        return False, "the Cortex checkout is not a git repo"
    branch = head.stdout.strip()
    if branch != "main":
        return False, f"the Cortex checkout is on `{branch}`, not `main`"
    dirty = _git(root, "status", "--porcelain")
    if dirty.returncode != 0 or dirty.stdout.strip():
        return False, "the Cortex checkout has uncommitted changes"
    return True, "`gh` is authenticated and the Cortex is clean on `main`"


def dirty_paths(root: Path) -> list[str]:
    """Every path the check-in's own writes left changed. Safe to read as
    *ours* only because the preflight demanded a clean tree first."""
    out = _git(root, "status", "--porcelain")
    paths = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:  # a rename: the destination is what we commit
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if path not in paths:
            paths.append(path)
    return sorted(paths)


def classify_paths(root: Path, paths: list) -> tuple:
    """`(rc, text)` from the Cortex's own `scripts/ledger_merge.py classify`.

    The gate the Cortex already owns, asked before pushing rather than after:
    0 = ledger (auto-merges), 1 = holds code (a human's call), 2 = the gate
    could not run. 1 and 2 are both refusals here, and they are not the same
    refusal.
    """
    script = root / "scripts" / "ledger_merge.py"
    if not script.is_file():
        return 2, "no scripts/ledger_merge.py in this checkout"
    r = subprocess.run([sys.executable, str(script), "classify", *paths],
                       cwd=str(root), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def push_ledger(root: Path, date: str, paths: list) -> tuple:
    """Commit the check-in's ledger diff on `claude/checkin-<date>` and push.

    Never `main`, never `--force`, never a path the classifier calls code.
    Returns `(ok, lines)` — the lines are the summary's push block.
    """
    L: list[str] = []
    if not paths:
        return True, ["push: nothing changed — no branch cut"]
    rc, text = classify_paths(root, paths)
    if rc != 0:
        L.append("push: REFUSED — " + ("the diff holds code, which is a "
                                       "human's call" if rc == 1 else
                                       "the classifier could not run"))
        L += [f"  {line}" for line in text.splitlines()[:8]]
        L.append("  nothing was pushed; the changes are in the checkout")
        return False, L
    branch = f"{CHECKIN_BRANCH_PREFIX}{date}"
    fetch = _git(root, "fetch", "origin")
    if fetch.returncode != 0:
        return False, ["push: REFUSED — `git fetch origin` failed",
                       f"  {fetch.stderr.strip()[:200]}"]
    exists = _git(root, "rev-parse", "--verify", "--quiet", branch).returncode == 0
    # A same-day re-check-in reuses its branch rather than resetting it: the
    # branch may already be pushed, and moving a pushed ref needs a force.
    co = (_git(root, "checkout", branch) if exists else
          _git(root, "checkout", "-b", branch, "origin/main"))
    if co.returncode != 0:
        return False, [f"push: REFUSED — could not cut `{branch}` from a fresh "
                       "origin/main", f"  {co.stderr.strip()[:200]}",
                       "  the changes are still in the checkout"]
    add = _git(root, "add", "--", *paths)
    if add.returncode != 0:
        return False, ["push: REFUSED — `git add` failed",
                       f"  {add.stderr.strip()[:200]}"]
    if _git(root, "diff", "--cached", "--quiet").returncode == 0:
        return True, [f"push: nothing staged on `{branch}` — already recorded"]
    msg = (f"cortex: check-in {date}\n\n"
           "Phase moves and the re-rendered board from "
           "`pyauto-brain cortex checkin --apply`.\n")
    commit = _git(root, "commit", "-m", msg)
    if commit.returncode != 0:
        return False, ["push: REFUSED — `git commit` failed",
                       f"  {commit.stderr.strip()[:200]}"]
    push = _git(root, "push", "-u", "origin", branch)
    if push.returncode != 0:
        return False, [f"push: FAILED — `git push -u origin {branch}`",
                       f"  {push.stderr.strip()[:200]}",
                       "  the commit is on the branch; push it by hand"]
    L.append(f"push: `{branch}` pushed ({len(paths)} path(s), ledger-only)")
    L.append("  `ledger_merge.yml` merges a ledger-only `claude/**` push into "
             "main and deletes the branch — no PR to open, nothing to merge "
             "by hand")
    return True, L


# ---------------------------------------------------- the by-project summary ---
def _payload_block(payload: str) -> list[str]:
    return ["", "```", *payload.split("\n"), "```", ""]


def project_digest(key: str, row: dict, c: dict, scored_by_rel: dict,
                   pull_line: str) -> list[str]:
    """One project's block of the check-in summary — where it lives, what came
    of its pull, and every phase of it a human could act on today, each with
    the prompt that already exists for that state.

    Phase 3 enriches this (the two missing prompts, the folders); it is keyed
    by project here because that is the axis the human checks in along — they
    ask about a project, never about a phase id.
    """
    rows = [r for r in c["phases"] if r["project"] == key]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    L = [f"### {key}", ""]
    where = [f"local `{row.get('local_path', '?')}`"]
    if (row.get("mirror") or "none") != "none":
        where.append(f"mirror `{row['mirror']}`")
    where.append(f"RAL `{row.get('ral_root', '?')}`")
    L += ["- " + " · ".join(where),
          f"- {pull_line}",
          "- phases: " + (" · ".join(f"{state} {n}" for state, n
                                     in sorted(counts.items()))
                          or "none")]

    def _phase_lines(title: str, phase_rows: list, payload) -> list[str]:
        if not phase_rows:
            return []
        out = ["", f"**{title}**", ""]
        for r in phase_rows:
            s = scored_by_rel.get(r["rel"])
            head = f"- `{r['rel']}` — {r['title']}"
            if s:
                head += f" — {s['health']}"
            out.append(head)
            note = _live_note(r)
            if note:
                out.append(f"  - {note}")
            if s:
                legs = ", ".join(f"{k} {s['legs'][k][0]}" for k in LEGS)
                out.append(f"  - legs: {legs}")
                for label, value in (("run dir", s["run_dir"]),
                                     ("zip", s["zip"])):
                    if value is not None:
                        out.append(f"  - {label}: `{value}`")
                for kind in ("out", "err"):
                    for path in s["logs"][kind][:1]:
                        out.append(f"  - `.{kind}`: `{path}`")
            out += _payload_block(payload(r))
        return out

    L += _phase_lines("Awaiting your ruling",
                      [r for r in c["awaiting"] if r["project"] == key],
                      _ruling_payload)
    L += _phase_lines("Still out there",
                      [r for r in c["live"] if r["project"] == key],
                      lambda r: _live_payload(r, c["projects"]))
    L += _phase_lines("Ready to submit",
                      [r for r in c["ready"] if r["project"] == key],
                      lambda r: _ready_payload(r, c["projects"]))
    L += _phase_lines("Gated",
                      [r for r in c["gated"] if r["project"] == key],
                      _gate_payload)
    L += [""]
    return L


def checkin_summary(c: dict, keys: list, scored: list, pulls: dict,
                    notes: list) -> str:
    """The whole by-project summary — the LAST thing the door prints, so a
    chat sees it above the fold and can paste from it."""
    scored_by_rel = {s["rel"]: s for s in scored}
    L = ["", "=" * 72, "", f"# Cortex check-in — {c['generated']}", "",
         f"{len(keys)} project(s) swept · {len(scored)} live phase(s) scored · "
         f"{len(c['awaiting'])} awaiting a ruling · {len(c['ready'])} ready",
         ""]
    for key in keys:
        row = c["projects"].get(key, {})
        rc, note = pulls.get(key, (None, "not pulled (--skip-pull)"))
        pull_line = ("pull: ok" if rc == 0 and not note else
                     f"pull: {note}" if note else "pull: not run")
        L += project_digest(key, row, c, scored_by_rel, pull_line)
    if notes:
        L += ["### Notes", ""] + [f"- {n}" for n in notes] + [""]
    return "\n".join(L)


# ----------------------------------------------------------- the door ---
def cmd_checkin(root: Path, mod, a) -> int:
    """`checkin` — sync, score, move, render, push, summarise by project."""
    if a.dry_run and a.apply:
        print("cortex: --dry-run and --apply are the two halves of this door "
              "— pass one", file=sys.stderr)
        return RC_USAGE
    projects = mod.load_projects(root)[0]
    phases_all = mod.load_phases(root)[0]
    keys, notes = checkin_keys(projects, phases_all, a.project)
    live = [ph for ph in phases_all if ph.state in LIVE_STATES
            and (ph.get("Project") or ph.project_dir) in keys]
    live_by_key: dict[str, list[str]] = {}
    for ph in live:
        live_by_key.setdefault(ph.get("Project") or ph.project_dir,
                               []).append(ph.rel)

    if not a.apply:  # the default: say what it would do, touch nothing
        print(f"cortex check-in (dry run) — {len(keys)} project(s), "
              f"{len(live)} live phase(s). Nothing is pulled, nothing is "
              "written, no cluster is reached.")
        for key in keys:
            row = projects.get(key, {})
            print(f"\n{key}  [{(row.get('status') or '?').strip()}]")
            print(f"  pull:   $ {pull_shell(row)}")
            print(f"  root:   {pull_root(row) or '(no readable pull root)'}")
            rels = live_by_key.get(key, [])
            print("  score:  " + (", ".join(rels) if rels
                                  else "(no submitted | running phase)"))
        for note in notes:
            print(f"\nnote: {note}")
        ok, why = push_preflight(root)
        print(f"\npush would be: {'yes' if ok else 'no'} — {why}")
        print(f"the rule: {PUSH_RULE}")
        return RC_OK

    # --- the push question is asked first: "clean on main" stops being true
    #     the moment the phases move.
    if a.push is False:
        push_ok, push_why = False, "--no-push"
    else:
        push_ok, push_why = push_preflight(root)
    if a.push is True and not push_ok:
        print(f"cortex: --push refused — {push_why}. The rule: {PUSH_RULE}.",
              file=sys.stderr)
    push_now = push_ok and a.push is not False
    print(f"push: {'yes' if push_now else 'no'} — {push_why}"
          + ("" if push_now else f" (the rule: {PUSH_RULE})"))

    # --- 1. sync ---------------------------------------------------------
    pulls: dict[str, tuple] = {}
    if not a.skip_pull:
        pulls = run_pull_streamed(projects, keys)
        for key, (rc, note) in pulls.items():
            if rc != 0:
                if note:
                    notes.append(f"{key}: {note}")
                continue
            row = projects.get(key, {})
            target = pull_root(row)
            if target is None:
                notes.append(f"{key}: pulled, but no readable pull root — no "
                             "manifest written")
                continue
            written = write_pull_manifest(target, key, pull_shell(row), rc,
                                          live_by_key.get(key, []))
            notes.append(f"{key}: pulled → {written}" if written else
                         f"{key}: pulled, but the manifest could not be written")
    stamp = a.refreshed.strip() or (_utc_now() if pulls else
                                    _newest_pull_stamp(projects, keys))
    if not stamp:
        print("cortex: --apply needs a refresh stamp — run it without "
              "--skip-pull, or pass --refreshed <ISO> when you pulled by hand",
              file=sys.stderr)
        return RC_USAGE

    # --- 2. score + move -------------------------------------------------
    scored = [score_phase(mod, ph, projects) for ph in live]
    problems, applied, wrote = _apply_checked(root, mod, scored)
    notes += applied
    if problems:
        print("cortex: the tree does not check after the moves — "
              + ("they were written; run `python3 scripts/cortex.py check`"
                 if wrote else "nothing was written") + ":", file=sys.stderr)
        for problem in problems[:10]:
            print(f"  {problem}", file=sys.stderr)
        return RC_DRIFT

    # --- 3. render -------------------------------------------------------
    c = census(root)
    pages = render_pages(c)
    for name, want in pages.items():
        (root / name).write_text(want, encoding="utf-8")
    print(f"Wrote: {' + '.join(pages)} ({len(c['phases'])} phase(s), "
          f"{len(c['rulings'])} ruling(s))")

    # --- 4. push ---------------------------------------------------------
    push_lines: list[str] = []
    rc_out = RC_OK
    if push_now:
        ok, push_lines = push_ledger(root, _dt.date.today().isoformat(),
                                     dirty_paths(root))
        if not ok:
            rc_out = RC_DRIFT
    if any(rc not in (0, None) for rc, _n in pulls.values()):
        rc_out = RC_DRIFT

    # --- 5. summarise, by project, last ----------------------------------
    print(checkin_summary(c, keys, scored, pulls, notes))
    for line in push_lines:
        print(line)
    print(f"\nRefreshed: {stamp}")
    return rc_out


def _newest_pull_stamp(projects: dict, keys: list) -> str:
    """The newest `pulled_at` any project's manifest carries — what
    `--skip-pull` scores against when the human pulled earlier themselves."""
    stamps = []
    for key in keys:
        root_dir = pull_root(projects.get(key, {}))
        if root_dir is None:
            continue
        data = pull_manifest([root_dir])
        value = str(data.get("pulled_at") or "").strip()
        if value:
            stamps.append(value)
    return max(stamps) if stamps else ""


# -------------------------------------------------------------------- cli ---
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cortex",
        description="The Cortex Agent — reason over PyAutoCortex: the board, "
                    "the gates, the check-in. It never submits and never "
                    "rules.")
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

    common(sub.add_parser("gates", help="every gated phase and its refs"))

    k = common(sub.add_parser(
        "collect", help="score what came back; default scope is every "
                        "submitted | running phase"))
    k.add_argument("--phase", action="append", default=[], metavar="REL",
                   help="score these phases instead of every submitted | "
                        "running one (repeatable)")
    k.add_argument("--pull", action="store_true",
                   help="run each project's own `<sync_cli> pull` first, then "
                        "stamp the refresh")
    k.add_argument("--refreshed", default="", metavar="ISO",
                   help="stamp the refresh at this time — for a pull you ran "
                        "by hand")
    k.add_argument("--apply", action="store_true",
                   help="move the scored phases to awaiting-ruling and write "
                        "the record (needs --pull or --refreshed)")
    k.add_argument("--out", default="", metavar="FILE",
                   help="write the packet markdown here instead of stdout")

    n = common(sub.add_parser(
        "checkin", help="the check-in door: pull every active project, score "
                        "every live phase, move what came back, re-render the "
                        "board and summarise it by project"))
    n.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="the default — say what would be pulled and scored, "
                        "and touch nothing")
    n.add_argument("--apply", action="store_true",
                   help="do it: pull, score, move, render (and push, per the "
                        "push rule)")
    n.add_argument("--push", dest="push", action="store_const", const=True,
                   default=None,
                   help="push the ledger diff on `claude/checkin-<date>` "
                        "(allowed only when `gh auth status` succeeds and the "
                        "Cortex is clean on main; that is also the default "
                        "when neither flag is given)")
    n.add_argument("--no-push", dest="push", action="store_const", const=False,
                   help="never push — the default in any session without a "
                        "logged-in `gh`")
    n.add_argument("--project", action="append", default=[], metavar="KEY",
                   help="sweep only these projects (repeatable)")
    n.add_argument("--skip-pull", dest="skip_pull", action="store_true",
                   help="score what is already on the laptop — an offline "
                        "re-score")
    n.add_argument("--refreshed", default="", metavar="ISO",
                   help="stamp the refresh at this time — for a pull you ran "
                        "by hand")
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
        # A thin wrapper over the Cortex script's own read-only listing: a
        # gated phase is moved on by a human typing `move <phase> ready`.
        lines, rc = mod.gates_report(root)
        print("\n".join(lines))
        return rc

    if verb == "checkin":
        # The door composes the verbs below; like `collect` it reads the tree
        # phase by phase rather than through `census`, because a tree that
        # does not check is exactly when a human checks in.
        try:
            return cmd_checkin(root, mod, a)
        except mod.CortexError as e:
            print(f"cortex: {root}: {e}", file=sys.stderr)
            return RC_UNREADABLE
        except OSError as e:
            print(f"cortex: cannot read {root}: {e}", file=sys.stderr)
            return RC_UNREADABLE

    if verb == "collect":
        # Scoring reads the tree phase by phase rather than through `census`:
        # a collect must work on a tree that does not fully check, because a
        # tree that does not check is exactly when the human needs the packet.
        try:
            return cmd_collect(root, mod, a)
        except mod.CortexError as e:
            print(f"cortex: {root}: {e}", file=sys.stderr)
            return RC_UNREADABLE
        except OSError as e:
            print(f"cortex: cannot read {root}: {e}", file=sys.stderr)
            return RC_UNREADABLE

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

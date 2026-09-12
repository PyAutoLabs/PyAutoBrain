#!/usr/bin/env python3
"""agents/conductors/cortex/_cortex.py — core for the Cortex Agent.

The Cortex Agent is the *learning function* of PyAutoBrain: the conductor
over PyAutoCortex, the organ where the organism keeps track of what is true.
The Cortex is **one ledger per science project** (`projects/<key>.md`): a
`## Now` the human rewrites, the `## Runs` on the cluster right now, and a
dated `## Log`, newest first. This conductor renders that ledger as the
board, pulls every active project through its own sync CLI, shows where each
run stands, and reads the ledger back by project. It **records cluster facts
and the human's words, never a verdict of its own**: it never scores a
result, never drafts a ruling, never writes a `result` or `lesson` entry —
those are the human's words, written on their ask through the Cortex's own
`scripts/cortex.py`. The same split as Heart ↔ vitals and Gut ↔ hygiene.

Three constraints shape this module:

- **Stdlib only (plus PyYAML through the Cortex script), and Mind-free.** The
  renderer runs bare inside the Cortex's own `dashboard_refresh.yml`, which
  checks out no PyAutoMind, so nothing from the Mind's conductors is imported.
- **The Cortex script is the API.** `<cortex_root>/scripts/cortex.py` exposes
  pure functions (`load_projects`, `load_ledgers`, `check_problems`,
  `issue_block`, `issue_url`) and is imported at runtime from the resolved
  root, so this conductor always reads the schema the checkout implements.
- **No path is named here.** Science projects live outside the workspace;
  the one place that carries such a path is the Cortex's own `projects.yaml`,
  and every path this module prints is read from a row of it at runtime.

Verbs: `checkin [--dry-run|--apply] [--push|--no-push] [--project KEY]
[--skip-pull]` (the door) · `census [--json]` · `dashboard --check|--apply` ·
`issue [--project KEY] [--apply]`.

Exit codes: 0 ok · 1 dashboard drift (the `dashboard_refresh.yml` contract),
a failed pull, or a tree that does not check · 2 bad args / no Cortex
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

#: How much of a run's `what` and a log entry's text a card shows.
RUN_CLIP, LOG_CLIP = 160, 240


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
    """The `scripts/cortex.py` that governs the tree at `root`: in the root,
    then its ancestors (a fixture tree lives inside its checkout), then the
    resolved checkout — the schema that reads a tree is the one beside it."""
    for candidate in (root, *root.resolve().parents):
        script = candidate / "scripts" / "cortex.py"
        if script.is_file():
            return script
    fallback = resolve_root() / "scripts" / "cortex.py"
    return fallback if fallback.is_file() else None


def load_cortex(root: Path):
    """Import the Cortex's own schema module for the tree at `root`, under a
    per-path module name so two checkouts can be read in one process."""
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

    Read from a file that travels with the repo (its own README/AGENTS links)
    so a laptop and the refresh workflow render byte-identical pages; the git
    remote is only the fallback. No org is named here.
    """
    for name in ("README.md", "AGENTS.md"):
        f = root / name
        if f.is_file():
            m = OWNER_IN_DOCS.search(_read(f))
            if m:
                return f"https://github.com/{m.group(1)}/{CORTEX_REPO}"
    return _home_from_git(root)


def _home_from_git(root: Path) -> str:
    """The fallback: the checkout's own `origin` (toplevel-guarded so a fixture
    inside another repo does not borrow its remote)."""
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


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


# --------------------------------------------------------------- check-in ---
#: The one-key file the check-in door writes and this page reads back. It
#: means *last check-in*, not last render: a doc-only push re-renders the
#: board and must not be able to fake freshness.
CHECKIN_FILE = "checkin.yaml"
CHECKIN_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z$")
CHECKIN_LABEL = "check in since last time"
CHECKIN_NEVER = "never checked in"

#: How old a check-in may be before the board calls it stale, in minutes. It
#: is interpolated into the page's script — never into the rendered stamp,
#: which is a fact and does not age between renders.
CHECKIN_FRESH_MINUTES = 180


def read_checkin(root: Path) -> tuple[str, list[str]]:
    """`(stamp, problems)` from `<root>/checkin.yaml`. Missing is not a
    problem (never checked in); a file with no readable `refreshed:` is."""
    path = root / CHECKIN_FILE
    if not path.is_file():
        return "", []
    m = re.search(r"^refreshed:\s*(\S+)\s*$", _read(path), re.M)
    value = (m.group(1) if m else "").strip().strip('"')
    if not CHECKIN_STAMP.match(value):
        return "", [f"{CHECKIN_FILE}: no readable `refreshed: <UTC ISO>` — "
                    "read as never checked in"]
    return value, []


def write_checkin(root: Path, stamp: str) -> Path:
    """Persist the refresh stamp before the pages are rendered: the board is
    meant to show the check-in that produced it, and `push_ledger` picks the
    file up in the same commit."""
    path = root / CHECKIN_FILE
    path.write_text(f"refreshed: {stamp}\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------- census ---
STATUS_RANK = {"active": 0, "planned": 1, "dormant": 2, "retired": 3}


def _ledger_dict(mod, led, row: dict) -> dict:
    issue = led.issue
    return {
        "key": led.key,
        "rel": led.rel,
        "summary": led.summary,
        "issue": issue,
        "issue_url": mod.issue_url(issue) if issue != "none" else "",
        "status": row.get("status", ""),
        "partition": row.get("partition", ""),
        "local_path": row.get("local_path", ""),
        "ral_root": row.get("ral_root", ""),
        "now": led.now,
        "runs": [{"ident": r.ident, "state": r.state, "partition": r.partition,
                  "date": r.date, "what": r.text()} for r in led.runs],
        "log": [{"date": e.date, "kind": e.kind, "text": e.text()}
                for e in led.log],
        "updated": led.updated(),
        "n_log": len(led.log),
    }


def census(root: Path) -> dict:
    """Everything the board and the check-in need, in one read: the rows of
    `projects.yaml`, one dict per ledger, the counts, the stamp, the
    problems `cortex.py check` would report."""
    mod = load_cortex(root)
    projects, _ = mod.load_projects(root)
    ledgers, _ = mod.load_ledgers(root)
    checkin, checkin_problems = read_checkin(root)
    problems = mod.check_problems(root) + checkin_problems
    rows = [_ledger_dict(mod, led, projects.get(led.key, {})) for led in ledgers]
    # projects.yaml order within a status, active first.
    order = {key: i for i, key in enumerate(projects)}
    rows.sort(key=lambda d: (STATUS_RANK.get(d["status"], 9),
                             order.get(d["key"], len(order)), d["key"]))
    counts = {
        "running": sum(1 for d in rows for r in d["runs"] if r["state"] == "running"),
        "open": sum(1 for d in rows for r in d["runs"] if r["state"] == "open"),
        "active": sum(1 for row in projects.values() if row.get("status") == "active"),
    }
    return {
        "root": str(root),
        "home": _home(root),
        "generated": _dt.date.today().isoformat(),
        "checkin": checkin,
        "problems": problems,
        "projects": projects,
        "ledgers": rows,
        "counts": counts,
    }


def ledger_of(c: dict, key: str) -> dict | None:
    for d in c["ledgers"]:
        if d["key"] == key:
            return d
    return None


def active_ledgers(c: dict) -> list[dict]:
    return [d for d in c["ledgers"] if d["status"] == "active"]


def no_ledger_rows(c: dict) -> list[tuple[str, dict]]:
    """Rows of `projects.yaml` with no `projects/<key>.md` at all."""
    have = {d["key"] for d in c["ledgers"]}
    return [(k, row) for k, row in c["projects"].items() if k not in have]


def emit_census(c: dict) -> None:
    n = c["counts"]
    print("== Cortex census ==")
    print(f"Root:            {c['root']}")
    print(f"Projects:        {len(c['projects'])} in projects.yaml · "
          f"{n['active']} active · {len(c['ledgers'])} with a ledger")
    print(f"Runs:            {n['running']} running · {n['open']} open")
    print(f"Last check-in:   {c['checkin'] or CHECKIN_NEVER}")
    for d in c["ledgers"]:
        runs = " · ".join(f"{r['ident']} {r['state']}" for r in d["runs"]) or "no runs"
        print(f"  {d['key']:<24} {d['status']:<8} {runs} · {d['n_log']} entries"
              f" · updated {d['updated'] or '-'}")
    if c["problems"]:
        print(f"Problems:        {len(c['problems'])} — run "
              "`python3 scripts/cortex.py check`")
        for p in c["problems"][:10]:
            print(f"  - {p}")


# ------------------------------------------------------------ the chips ---
def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def _attr(value: str) -> str:
    """Escape a string for a double-quoted HTML attribute."""
    return (str(value).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _esc(value: str) -> str:
    """Text content for the HTML page."""
    return _html.escape(str(value), quote=False)



def _task_row(summary: str, payload: str) -> str:
    """One 📋 row as a collapsed `<details>` whose summary IS the line and
    whose body is the fenced payload GitHub renders a copy button on."""
    return "\n".join([f"<details><summary>📋 {summary}</summary>", "", "```",
                      payload, "```", "", "</details>"])


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
    """The cross-board footer nav from `config/policy.yaml` `board: boards:`,
    skipping this page's own entry — a stdlib regex, as the renderer runs bare."""
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


def checkin_payload(c: dict) -> str:
    return (f"/cortex — check in on every active science project since the "
            f"last check-in ({c.get('checkin') or CHECKIN_NEVER}): pull each "
            "through its sync CLI, show me where each run stands, re-render "
            "and push the board, then read me the by-project summary. Record "
            "nothing about results — I will tell you what to log.")


def resume_payload(key: str, row: dict) -> str:
    """The one chip a project card carries: pick up where the human left off.
    Every path is the row's; the assistant is named, never read here."""
    ledger = f"{row.get('local_path', '')}/{row.get('ledger', '')}"
    text = (f"/cortex — resume {key}: read {CORTEX_REPO} projects/{key}.md "
            f"(Now, Runs, Log) and then {ledger}")
    assistant = (row.get("assistant") or "none").strip()
    if assistant != "none":
        text += f" and the assistant {assistant}'s AGENTS.md"
    return text + ("; tell me where I left off and what I said I would do "
                   "next. Submit nothing and log nothing until I say.")


# ------------------------------------------------------------- the pages ---
INTRO = ("One ledger per science project: what is on the cluster right now, "
         "what the human said they would do next, and the last few things they "
         "wrote down. Nothing here is inferred from a result — the board hands "
         "you the check-in and the resume prompt; what a run meant is yours to "
         "log.")


def _ledger_link(d: dict, blob: str) -> str:
    return f"{blob}{d['rel']}" if blob else d["rel"]


def _facts_md(d: dict, blob: str) -> str:
    issue = (f"[{d['issue']}]({d['issue_url']})" if d["issue_url"]
             else "no issue yet")
    return (f"{d['status']} · {d['partition']} · {issue} · "
            f"[{d['rel']}]({_ledger_link(d, blob)}) · "
            f"local `{_cell(d['local_path'])}` · RAL `{_cell(d['ral_root'])}`")


def _facts_html(d: dict, blob: str) -> str:
    issue = (f'<a href="{_attr(d["issue_url"])}">{_esc(d["issue"])}</a>'
             if d["issue_url"] else "no issue yet")
    return (f"{_esc(d['status'])} · {_esc(d['partition'])} · {issue} · "
            f'<a href="{_attr(_ledger_link(d, blob))}">{_esc(d["rel"])}</a> · '
            f'local <span class="pathchip">{_esc(d["local_path"])}</span> · '
            f'RAL <span class="pathchip">{_esc(d["ral_root"])}</span>')


def run_line(r: dict) -> str:
    return (f"{r['ident']} — {r['state']} — {r['partition']} — {r['date']} — "
            f"{_clip(r['what'], RUN_CLIP)}")


def _card_md(d: dict, row: dict, blob: str) -> list[str]:
    L = [f"### {d['key']} — {_cell(d['summary'])}", "", _facts_md(d, blob), "",
         "**Now**", "", d["now"] or "_(nothing yet)_", "", "**Runs**", ""]
    L += [f"- {_cell(run_line(r))}" for r in d["runs"]] or ["- _nothing on the cluster_"]
    L += ["", "**Last 5**", ""]
    L += [f"- {e['date']} — *{e['kind']}* — {_cell(_clip(e['text'], LOG_CLIP))}"
          for e in d["log"][:5]] or ["- _empty_"]
    L += ["", f"[full log]({_ledger_link(d, blob)})", ""]
    if d["status"] == "active":
        L += [_task_row(f"resume {d['key']}", resume_payload(d["key"], row)), ""]
    return L


def _card_html(d: dict, row: dict, blob: str) -> list[str]:
    H = ['<section class="project">',
         f"<h3>{_esc(d['key'])} — {_esc(d['summary'])}</h3>",
         f'<p class="muted">{_facts_html(d, blob)}</p>',
         "<p><b>Now</b></p>",
         "<p>" + ("<br>".join(_esc(x) for x in d["now"].split("\n"))
                  if d["now"] else '<span class="muted">(nothing yet)</span>')
         + "</p>",
         "<p><b>Runs</b></p>"]
    if d["runs"]:
        H += ["<ul>"] + [f"<li>{_esc(run_line(r))}</li>" for r in d["runs"]] + ["</ul>"]
    else:
        H.append('<p class="muted">nothing on the cluster</p>')
    H.append("<p><b>Last 5</b></p>")
    if d["log"]:
        H += ["<ul>"] + [f"<li>{_esc(e['date'])} — <i>{_esc(e['kind'])}</i> — "
                         f"{_esc(_clip(e['text'], LOG_CLIP))}</li>"
                         for e in d["log"][:5]] + ["</ul>"]
    else:
        H.append('<p class="muted">empty</p>')
    H.append(f'<p class="muted"><a href="{_attr(_ledger_link(d, blob))}">full log</a></p>')
    if d["status"] == "active":
        H.append(_html_task(f"resume {_esc(d['key'])}", resume_payload(d["key"], row)))
    H.append("</section>")
    return H


def render_dashboard(c: dict) -> str:
    """The Cortex board as `dashboard.md`."""
    home = c.get("home", "")
    blob = f"{home}/blob/main/" if home else ""
    n = c["counts"]
    L = ["# PyAutoCortex Dashboard", "",
         f"<!-- generated by `pyauto-brain cortex dashboard --apply` on "
         f"{c['generated']} — regenerate, do not hand-edit -->", ""]
    pages = _pages_url(home)
    if pages:
        L += [f"This is the markdown version of the "
              f"[PyAutoCortex Dashboard]({pages}), which puts the check-in "
              "and each project's resume prompt on your clipboard with a "
              "single tap of 📋.", ""]
    L += [INTRO, "", f"> **Last updated {c['generated']}.**", "",
          "| Where | Count |", "|-------|------:|",
          f"| [Running](#projects) | {n['running']} |",
          f"| [Open](#projects) | {n['open']} |",
          f"| [Projects](#projects) | {n['active']} |", ""]
    if c["problems"]:
        L += ["> ⚠️ **The tree does not check** — `python3 scripts/cortex.py "
              "check` reports:", ""]
        L += [f"> - `{_cell(p)}`" for p in c["problems"][:10]]
        L += [""]
    L += [_task_row(CHECKIN_LABEL, checkin_payload(c)), "",
          f"### Last check-in: {c.get('checkin') or CHECKIN_NEVER}", ""]

    L += ["## Summary", "", "| Project | Running | Open | Last update |",
          "|---|---:|---:|---|"]
    active = [k for k, row in c["projects"].items() if row.get("status") == "active"]
    for key in active:
        d = ledger_of(c, key)
        running = sum(1 for r in (d["runs"] if d else []) if r["state"] == "running")
        open_ = sum(1 for r in (d["runs"] if d else []) if r["state"] == "open")
        L.append(f"| {key} | {running} | {open_} | "
                 f"{(d['updated'] if d else '') or '-'} |")
    if not active:
        L.append("| _(no active project)_ | | | |")
    L.append("")

    L += ["## Projects", ""]
    live = [d for d in c["ledgers"] if d["status"] != "retired"]
    retired = [d for d in c["ledgers"] if d["status"] == "retired"]
    for d in live:
        L += _card_md(d, c["projects"].get(d["key"], {}), blob)
    if retired:
        L += [f"<details><summary>{len(retired)} retired</summary>", ""]
        L += [f"- [{d['key']}]({_ledger_link(d, blob)}) — {_cell(d['summary'])} — "
              f"{_cell(c['projects'].get(d['key'], {}).get('note') or '-')}"
              for d in retired]
        L += ["", "</details>", ""]
    bare = no_ledger_rows(c)
    if bare:
        L += ["#### No ledger", "", "| Project | Status | Note |", "|---|---|---|"]
        L += [f"| {k} | {_cell(row.get('status', ''))} | "
              f"{_cell(row.get('note') or '-')} |" for k, row in bare]
        L.append("")

    links = _board_links(home, THEME_ORGAN)
    if links:
        L += ["---", "", "Boards: " + " · ".join(f"[{name.title()}]({url})"
                                                 for name, url in links), ""]
    return "\n".join(L) + "\n"


_FRESH_CSS = (
    ".fresh{padding:.1rem .9rem;margin:1.2rem 0;background:var(--tint)}"
    ".fresh p{margin:.5rem 0}"
    "table.map{width:100%;border-collapse:collapse;font-size:.95em}"
    "table.map th{text-align:left;color:var(--muted);font-weight:600}"
    "table.map td,table.map th{border-bottom:1px solid var(--line);padding:.4rem .5rem .4rem 0;vertical-align:top}"
    ".checkin{display:flex;gap:.9rem;align-items:center;padding:.9rem 1.2rem;border:2px solid var(--line);border-radius:.6rem;margin:.2rem 0 1.4rem}"
    ".checkin .mark{font-size:2rem;line-height:1}"
    ".checkin .label{display:block;font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}"
    ".checkin time{font-size:1.6rem;font-weight:700;font-variant-numeric:tabular-nums;display:block}"
    ".checkin .note{font-size:.85rem;color:var(--muted)}"
    ".checkin.fresh-ok{border-color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,transparent)}"
    ".checkin.fresh-ok .mark{color:var(--ok)}"
    ".checkin.fresh-bad{border-color:var(--bad);background:color-mix(in srgb,var(--bad) 12%,transparent)}"
    ".checkin.fresh-bad .mark{color:var(--bad)}"
    ".project h3{font-size:1.35rem;font-weight:700;padding-bottom:.2rem;border-bottom:2px solid var(--accent);letter-spacing:.01em;margin-top:1.6rem}"
    ".pathchip{display:inline-block;background:var(--accent);color:#fff;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;padding:.12em .5em;border-radius:.3rem;overflow-wrap:anywhere}"
    "@media(prefers-color-scheme:dark){.pathchip{background:color-mix(in srgb,var(--accent) 55%,#000)}}"
    ".stale{color:var(--bad);font-weight:600}")

# The page is static, so a stamp is never stale *at render* — it is stale on
# the reader's clock, 3 h later, on a different day. So the age is computed
# on load, here, and nowhere else: the box is neutral until this runs.
_CHECKIN_JS = (
    "(function(){var e=document.getElementById('checkin'),"
    "b=document.getElementById('checkin-box'),"
    "m=document.getElementById('checkin-mark'),"
    "n=document.getElementById('checkin-note');if(!e||!b)return;"
    "var t=e.getAttribute('datetime'),d=t?new Date(t):null;"
    "if(!d||isNaN(d.getTime())||(Date.now()-d.getTime())/60000>"
    f"{CHECKIN_FRESH_MINUTES}){{"
    "b.classList.add('fresh-bad');e.classList.add('stale');"
    "if(m)m.textContent='✗';"
    "if(n)n.textContent=t?'stale, paste the check-in':'never checked in';"
    "}else{b.classList.add('fresh-ok');if(m)m.textContent='✓';"
    "var a=Math.round((Date.now()-d.getTime())/60000);"
    "if(n)n.textContent='fresh · '+(a<60?a+' min':Math.round(a/60)+' h')"
    "+' ago';}})();")


def render_dashboard_html(c: dict) -> str:
    """The one-tap-copy twin GitHub Pages serves — same content, real buttons."""
    home = c.get("home", "")
    blob = f"{home}/blob/main/" if home else ""
    n = c["counts"]
    H = [
        "<!doctype html>", '<html lang="en">', "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>PyAutoCortex Dashboard</title>",
        f"<!-- generated by `pyauto-brain cortex dashboard --apply` on "
        f"{c['generated']} — regenerate, do not hand-edit -->",
        f"<style>{_theme_css(THEME_ORGAN)}{_FRESH_CSS}</style>",
        "</head>", "<body>",
        hero(THEME_ORGAN, "Dashboard", _esc(INTRO)),
        stats((n["running"], "Running"), (n["open"], "Open"),
              (n["active"], "Projects")),
        # One line, deliberately: the `--check` normaliser drops it whole so
        # a date change is not drift.
        f'<div class="fresh"><p class="muted">Last updated '
        f'{c["generated"]}.</p></div>',
    ]
    if home:
        H.append(f'<p class="muted mdsrc"><a href="{_attr(blob + "dashboard.md")}">'
                 f'markdown version</a> · <a href="{_attr(blob + "README.md")}">'
                 "GitHub Page</a></p>")
    if c["problems"]:
        H += ['<p>⚠️ <b>The tree does not check</b> — '
              "<code>scripts/cortex.py check</code> reports:</p>", "<ul>"]
        H += [f"<li><code>{_esc(p)}</code></li>" for p in c["problems"][:10]]
        H += ["</ul>"]
    stamp = c.get("checkin") or ""
    H += [_html_task(_esc(CHECKIN_LABEL), checkin_payload(c)),
          f'<div class="checkin" id="checkin-box">'
          f'<span class="mark" id="checkin-mark"></span><div>'
          f'<span class="label">Last check-in</span>'
          f'<time id="checkin" datetime="{_attr(stamp)}">'
          f'{_esc(stamp or CHECKIN_NEVER)}</time>'
          f'<span class="note" id="checkin-note"></span></div></div>']

    H += ['<a id="summary"></a><h2>Summary</h2>', '<table class="map">',
          "<tr><th>Project</th><th>Running</th><th>Open</th>"
          "<th>Last update</th></tr>"]
    active = [k for k, row in c["projects"].items() if row.get("status") == "active"]
    for key in active:
        d = ledger_of(c, key)
        runs = d["runs"] if d else []
        H.append(f"<tr><td><b>{_esc(key)}</b></td>"
                 f"<td>{sum(1 for r in runs if r['state'] == 'running')}</td>"
                 f"<td>{sum(1 for r in runs if r['state'] == 'open')}</td>"
                 f"<td>{_esc((d['updated'] if d else '') or '-')}</td></tr>")
    if not active:
        H.append('<tr><td colspan="4" class="muted">(no active project)</td></tr>')
    H.append("</table>")

    H.append('<a id="projects"></a><h2>Projects</h2>')
    live = [d for d in c["ledgers"] if d["status"] != "retired"]
    retired = [d for d in c["ledgers"] if d["status"] == "retired"]
    for d in live:
        H += _card_html(d, c["projects"].get(d["key"], {}), blob)
    if retired:
        H += [f"<details><summary>{len(retired)} retired</summary><ul>"]
        H += [f'<li><a href="{_attr(_ledger_link(d, blob))}">{_esc(d["key"])}</a>'
              f" — {_esc(d['summary'])} — "
              f"{_esc(c['projects'].get(d['key'], {}).get('note') or '-')}</li>"
              for d in retired]
        H += ["</ul></details>"]
    bare = no_ledger_rows(c)
    if bare:
        H += ["<h4>No ledger</h4>", '<table class="map">',
              "<tr><th>Project</th><th>Status</th><th>Note</th></tr>"]
        H += [f"<tr><td>{_esc(k)}</td><td>{_esc(row.get('status', ''))}</td>"
              f"<td>{_esc(row.get('note') or '-')}</td></tr>" for k, row in bare]
        H.append("</table>")

    footer = boards_footer(dict(_board_links(home, THEME_ORGAN)), THEME_ORGAN)
    if footer:
        H.append(footer)
    H += [f"<script>{_THEME_JS}</script>",
          f"<script>{_CHECKIN_JS}</script>", "</body>", "</html>"]
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


def cmd_dashboard(root: Path, c: dict, a) -> int:
    pages = render_pages(c)
    if a.check:
        stale = []
        for name, want in pages.items():
            target = root / name
            on_disk = _read(target) if target.is_file() else ""
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
        print(f"Wrote: {' + '.join(pages)} ({len(c['ledgers'])} ledger(s), "
              f"{c['counts']['running']} running, {c['counts']['open']} open)")
        return RC_OK
    print(pages["dashboard.md"], end="")
    return RC_OK


# ------------------------------------------------------------- the pull ---
def _cli(row: dict, verb: str) -> tuple | None:
    """`(argv, cwd)` for this project's own `<sync_cli> <verb>`, or None when
    the row has no such verb. Every path comes from the row."""
    local = (row.get("local_path") or "").strip()
    cli = (row.get("sync_cli") or "").strip()
    if not local or not cli or verb not in (row.get("sync_verbs") or []):
        return None
    return [str(Path(local) / cli), verb], local


def pull_cmd(row: dict) -> tuple | None:
    return _cli(row, "pull")


def pull_shell(row: dict) -> str:
    """The pull as a human would type it — what `--dry-run` prints."""
    cmd = pull_cmd(row)
    if not cmd:
        return "(no `pull` verb in projects.yaml)"
    return f"cd {cmd[1]} && {row.get('sync_cli')} pull"


def run_pull_streamed(projects: dict, keys: list) -> dict:
    """`{key: (rc, note)}` — each project's own pull, **streamed** (a pull runs
    for minutes). A non-zero exit is recorded and the sweep continues."""
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
            results[key] = (None, f"pull could not run ({e}) — the sweep went on")
            continue
        results[key] = (rc, "" if rc == 0 else
                        f"pull exited {rc} — the rest of the sweep ran")
    return results


def run_jobs(row: dict) -> str | None:
    """The project's own `<sync_cli> jobs`, verbatim — stdout and stderr as
    they came, no parsing. None when the row has no `jobs` verb."""
    cmd = _cli(row, "jobs")
    if cmd is None:
        return None
    argv, cwd = cmd
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as e:
        return f"(jobs could not run: {e})"
    out = r.stdout + (r.stderr if r.stderr else "")
    if r.returncode != 0:
        out += f"\n(jobs exited {r.returncode})"
    return out.rstrip("\n") or "(jobs printed nothing)"


# ------------------------------------------------------------- the push ---
CHECKIN_BRANCH_PREFIX = "claude/checkin-"

#: The rule the `--push` default resolves by, stated wherever it is applied.
PUSH_RULE = ("`--push` needs `gh auth status` to succeed and the Cortex "
             "checkout to be clean on `main`")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def push_preflight(root: Path) -> tuple:
    """`(ok, reason)` — may this check-in push its own ledger diff? Read
    **before** anything is written. Two legs, both facts about this machine:
    a logged-in `gh` (the cloud/laptop split) and a clean checkout on `main`."""
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
    """`(rc, text)` from the Cortex's own `scripts/ledger_merge.py classify`:
    0 = ledger, 1 = holds code (a human's call), 2 = the gate could not run."""
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
           "The check-in stamp and the re-rendered board from "
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


# ------------------------------------------------------------- the door ---
def checkin_keys(projects: dict, ledgers: list, only: list) -> tuple:
    """`(keys, notes)` — the projects one check-in sweeps: every `status:
    active` row, plus any project whose ledger lists a run (a dormant project
    with a job still out there is still out there)."""
    notes: list[str] = []
    keys = {key for key, row in projects.items()
            if (row.get("status") or "").strip() == "active"}
    keys |= {led.key for led in ledgers if led.runs}
    for key in sorted(keys - set(projects)):
        notes.append(f"{key}: a ledger lists runs but projects.yaml has no "
                     "such row — not pulled")
    keys &= set(projects)
    if only:
        for key in only:
            if key not in projects:
                notes.append(f"{key}: no such project in projects.yaml")
        keys &= set(only)
    return [k for k in projects if k in keys], notes


def next_commands(key: str, d: dict | None) -> str:
    """The three `cortex.py` lines most likely typed next for this project.
    They are offered, never run: what a run meant is the human's to say."""
    jobid = d["runs"][0]["ident"] if d and d["runs"] else "<jobid>"
    return "\n".join([
        f"python3 scripts/cortex.py done {key} {jobid} [--wall H:MM]",
        f'python3 scripts/cortex.py log {key} "<what I learned>" --kind result|lesson',
        f'python3 scripts/cortex.py now {key} "<where I am>"'])


def project_digest(key: str, c: dict, pull: tuple | None, jobs: str | None,
                   skipped: bool) -> list[str]:
    d = ledger_of(c, key)
    row = c["projects"].get(key, {})
    L = [f"## {key} — {d['summary'] if d else '(no ledger)'}", ""]
    if skipped:
        L.append("pull: skipped (--skip-pull)")
    elif pull is None:
        L.append("pull: not run")
    else:
        rc, note = pull
        L.append("pull: ok" if rc == 0 else f"pull: {note or f'exited {rc}'}")
    if jobs is None:
        has = "jobs" in (row.get("sync_verbs") or [])
        L.append("jobs: " + ("no runs listed — not asked" if has else "no jobs verb"))
    else:
        L += ["jobs:", jobs]
    L.append("")
    if d is None:
        L += ["(no projects/<key>.md — `python3 scripts/cortex.py new "
              f"{key} --summary ...` opens one)", ""]
        return L
    L += ["Now:", d["now"] or "(nothing yet)", "", "Runs:"]
    L += [f"- {run_line(r)}" for r in d["runs"]] or ["- nothing on the cluster"]
    L += ["", "Last 5:"]
    L += [f"- {e['date']} — {e['kind']} — {_clip(e['text'], LOG_CLIP)}"
          for e in d["log"][:5]] or ["- empty"]
    L += ["", "```", next_commands(key, d), "```", ""]
    return L


def cmd_checkin(root: Path, mod, a) -> int:
    projects, _ = mod.load_projects(root)
    ledgers, _ = mod.load_ledgers(root)
    keys, notes = checkin_keys(projects, ledgers, a.project)
    runs_by_key = {led.key: len(led.runs) for led in ledgers}

    if not a.apply:
        print("== Cortex check-in — dry run (nothing is reached) ==")
        for key in keys:
            row = projects[key]
            print(f"\n{key} — {row.get('status')}")
            print(f"  $ {pull_shell(row)}")
            if runs_by_key.get(key) and "jobs" in (row.get("sync_verbs") or []):
                print(f"  $ cd {row.get('local_path')} && {row.get('sync_cli')} jobs")
        for n in notes:
            print(f"\nnote: {n}")
        print(f"\n{len(keys)} project(s) would be pulled. Run with --apply to "
              "check in.")
        return RC_OK

    # The push decision is read before anything is written.
    push_ok, push_why = push_preflight(root)
    push = push_ok if a.push is None else a.push
    push_note = ""
    if push and not push_ok:
        push, push_note = False, f"push: REFUSED — {push_why} ({PUSH_RULE})"
    elif not push:
        push_note = f"push: off — {push_why if a.push is None else '--no-push'}"

    pulls: dict[str, tuple] = {}
    if not a.skip_pull:
        pulls = run_pull_streamed(projects, keys)
    jobs_out: dict[str, str] = {}
    for key in keys:
        if not runs_by_key.get(key):
            continue
        out = run_jobs(projects[key])
        if out is None:
            continue
        jobs_out[key] = out
        print(f"\n$ cd {projects[key].get('local_path')} && "
              f"{projects[key].get('sync_cli')} jobs", flush=True)
        print(out, flush=True)

    stamp = _utc_now()
    write_checkin(root, stamp)
    c = census(root)
    for name, page in render_pages(c).items():
        (root / name).write_text(page, encoding="utf-8")

    push_lines = [push_note] if push_note else []
    if push:
        _ok, push_lines = push_ledger(root, stamp[:10], dirty_paths(root))

    failed = [k for k, (rc, _n) in pulls.items() if rc not in (0, None)]
    print(f"\n# The Cortex by project — check-in {stamp}\n")
    print(f"{len(keys)} project(s) · {c['counts']['running']} running · "
          f"{c['counts']['open']} open · pages re-rendered")
    for line in notes + push_lines:
        print(line)
    if c["problems"]:
        print(f"the tree does not check ({len(c['problems'])} problem(s)) — "
              "run `python3 scripts/cortex.py check`")
    print()
    for key in keys:
        print("\n".join(project_digest(key, c, pulls.get(key), jobs_out.get(key),
                                       a.skip_pull)))
    print("Record what the jobs output says with `python3 scripts/cortex.py "
          "running|done <key> <jobid>` in the Cortex checkout; a result or a "
          "lesson is written only in the human's words.")
    return RC_DRIFT if failed or c["problems"] else RC_OK


# ------------------------------------------------------------ the issue ---
def sync_issue_body(body: str, block: str, begin: str, end: str) -> str:
    """`body` with the fenced ledger block replaced, or the block prepended
    (plus a blank line) when the markers are absent. The begin marker is
    matched by its constant prefix so a stale key still gets replaced."""
    prefix = begin.split("{", 1)[0].split(" begin", 1)[0] + " begin"
    lines = body.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.startswith(prefix)), None)
    stop = next((i for i, ln in enumerate(lines) if ln.strip() == end), None)
    new = block.rstrip("\n").split("\n")
    if start is not None and stop is not None and stop >= start:
        return "\n".join(lines[:start] + new + lines[stop + 1:])
    return "\n".join(new + [""] + lines)


def cmd_issue(root: Path, mod, a) -> int:
    projects, _ = mod.load_projects(root)
    ledgers, _ = mod.load_ledgers(root)
    home = _home(root)
    rc = RC_OK
    shown = 0
    for led in ledgers:
        if a.project and led.key not in a.project:
            continue
        if led.issue == "none":
            continue
        shown += 1
        block = mod.issue_block(led, projects.get(led.key, {}), mod.LOG_WINDOW, home)
        url = mod.issue_url(led.issue)
        print(f"== {led.key} → {url}")
        print(block, end="")
        if not a.apply:
            continue
        if shutil.which("gh") is None:
            print(f"issue: no `gh` on PATH — would write the block above to {url}")
            rc = RC_DRIFT
            continue
        view = subprocess.run(["gh", "issue", "view", url, "--json", "body",
                               "-q", ".body"], capture_output=True, text=True)
        if view.returncode != 0:
            print(f"issue: `gh issue view {url}` failed: {view.stderr.strip()[:200]}")
            rc = RC_DRIFT
            continue
        begin = mod.ISSUE_BEGIN.format(key=led.key)
        new_body = sync_issue_body(view.stdout, block, begin, mod.ISSUE_END)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(new_body)
            tmp = fh.name
        try:
            edit = subprocess.run(["gh", "issue", "edit", url, "--body-file", tmp],
                                  capture_output=True, text=True)
        finally:
            os.unlink(tmp)
        if edit.returncode != 0:
            print(f"issue: `gh issue edit {url}` failed: {edit.stderr.strip()[:200]}")
            rc = RC_DRIFT
        else:
            print(f"issue: {url} updated")
    if not shown:
        print("no project carries an `Issue:` — nothing to sync")
    return rc


# -------------------------------------------------------------------- CLI ---
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cortex",
        description="The Cortex Agent — the per-project science ledger over "
                    "PyAutoCortex: the board, the check-in, the issue block. "
                    "It records cluster facts and the human's words, never a "
                    "verdict of its own; a run is submitted only on the "
                    "human's ask.")
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

    n = common(sub.add_parser(
        "checkin", help="the check-in door: pull every active project through "
                        "its own sync CLI, show where each run stands, "
                        "re-render the board and read it back by project"))
    n.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="the default — say what would be pulled and touch "
                        "nothing")
    n.add_argument("--apply", action="store_true",
                   help="do it: pull, jobs, stamp, render (and push, per the "
                        "push rule)")
    n.add_argument("--push", dest="push", action="store_const", const=True,
                   default=None,
                   help="push the ledger diff on `claude/checkin-<date>` "
                        "(allowed only when `gh auth status` succeeds and the "
                        "Cortex is clean on main; also the default when "
                        "neither flag is given)")
    n.add_argument("--no-push", dest="push", action="store_const", const=False,
                   help="never push — the default in any session without a "
                        "logged-in `gh`")
    n.add_argument("--project", action="append", default=[], metavar="KEY",
                   help="sweep only these projects (repeatable)")
    n.add_argument("--skip-pull", dest="skip_pull", action="store_true",
                   help="do not pull — stamp, render and read back what is "
                        "already on the laptop")

    i = common(sub.add_parser(
        "issue", help="the ledger block that sits at the top of each "
                      "project's issue; --apply writes it there with gh"))
    i.add_argument("--project", action="append", default=[], metavar="KEY")
    i.add_argument("--apply", action="store_true",
                   help="edit the issue body through `gh` (never creates one)")
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

    try:
        if verb == "checkin":
            return cmd_checkin(root, mod, a)
        if verb == "issue":
            return cmd_issue(root, mod, a)
        c = census(root)
    except mod.CortexError as e:
        print(f"cortex: {root}: {e}", file=sys.stderr)
        return RC_UNREADABLE
    except OSError as e:
        print(f"cortex: cannot read {root}: {e}", file=sys.stderr)
        return RC_UNREADABLE

    if verb == "census":
        if a.as_json:
            print(json.dumps(c, indent=2))
        else:
            emit_census(c)
        return RC_OK
    if verb == "dashboard":
        return cmd_dashboard(root, c, a)
    ap.print_help(sys.stderr)
    return RC_USAGE


if __name__ == "__main__":
    sys.exit(main())

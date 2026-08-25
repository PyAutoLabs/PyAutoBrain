#!/usr/bin/env python3
"""board/_board.py — the PyAutoBrain operational board (the morning door).

The sixth one-tap board: a generated page at the Brain's GitHub Pages URL
holding everything /wake_up used to assemble interactively — the overnight
scheduled-run sweep, the Heart's readiness headline, version-stamp consistency,
the community's waiting conversations, resume context from the Mind, and the
upkeep doors — each actionable row carrying a one-tap 📋 copy-for-Claude
payload. The morning routine becomes: run `bin/morning.sh` in a terminal
(the local sync/clean leg), open this board, tap what needs you.

Shape follows the sibling boards (Heart heart/dashboard.py, Hands
autohands/board.py): a THIN COLLECT (gh CLI + the sibling boards' published
badge.json, the cross-board headline contract) feeding PURE RENDERS
(md / html / json / badge). The board reasons about nothing new — every signal
already has an owner (compose, don't recompute) — and it never mutates
anything: read-only gh endpoints only, no posts, no labels, no writes outside
--apply's output directory.

Instance vocabulary (which workflows the overnight sweep reads, which stamps
the consistency check compares, which sibling boards exist) lives in
config/policy.yaml under `board:` — the declared config surface an adopting
fork replaces. The org/owner is derived from the Mind's body map
(PyAutoMind/repos.yaml), never hardcoded here.

Env (hermetic tests override all three):
  PYAUTO_ROOT       workspace root holding PyAutoMind/ (default: this
                    checkout's parent — the standard sibling layout)
  BOARD_GH          the gh binary (default `gh`)
  BOARD_PAGES_BASE  base URL of the sibling boards (default https://<org>.github.io)

Exit codes: 0 rendered · 4 inputs unresolvable (no policy / no body map).
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# The shared board theme — presentation only: the stylesheet, the hero
# and the small components every one-tap board draws itself with, so
# this page and the Mind dashboard are visibly the same family.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _theme import (  # noqa: E402
    JS as _THEME_JS, boards_footer, css as _theme_css, hero, pills, stats,
)

THEME_ORGAN = "brain"  # whose logo this page wears

BRAIN_HOME = Path(__file__).resolve().parents[1]
# Default workspace root = the checkout's parent (the standard sibling layout
# the sizing faculty also assumes) — no instance path named here.
PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", BRAIN_HOME.parent))
GH = os.environ.get("BOARD_GH", "gh")
POLICY_PATH = BRAIN_HOME / "config" / "policy.yaml"

# A successful scheduled run carrying a step with this name prefix stopped on
# purpose and made no change (the nightly driver's OUTCOME CONTRACT). Keep in
# sync with bin/overnight_status.sh and nightly-release.yml.
BLOCKED_STEP_PREFIX = "Blocked at a gate"

VERPAT = r"[0-9]{4}\.[0-9]+\.[0-9]+\.[0-9]+"

# The local morning leg — the one thing the board cannot do for you. Rendered
# as a copyable TERMINAL command (not a Claude payload) at the top of the page.
MORNING_CMD = "bash PyAutoBrain/bin/morning.sh"


def fail(code, msg):
    print(f"board: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- policy ----


def load_policy():
    """The `board:` block of config/policy.yaml (strict — the board's
    vocabulary is declared config, like the sizing faculty's)."""
    try:
        import yaml
    except ImportError:
        fail(4, "PyYAML is required (pip install pyyaml)")
    if not POLICY_PATH.is_file():
        fail(4, f"policy not found: {POLICY_PATH}")
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    board = policy.get("board")
    if not board:
        fail(4, f"no `board:` block in {POLICY_PATH}")
    return board


def repo_homes():
    """Every `github:` home in PyAutoMind/repos.yaml (regex, no yaml needed —
    same parse the community conductor uses). [] when the Mind is absent."""
    body_map = PYAUTO_ROOT / "PyAutoMind" / "repos.yaml"
    if not body_map.is_file():
        return []
    return re.findall(
        r"^\s+github:\s*(\S+)\s*$", body_map.read_text(encoding="utf-8"), re.M
    )


def derive_org(homes):
    """The organism's GitHub org = the most common owner in the body map;
    falls back to the Brain checkout's own remote when the Mind is absent."""
    owners = [h.split("/")[0] for h in homes if "/" in h]
    if owners:
        return max(set(owners), key=owners.count)
    try:
        r = subprocess.run(
            ["git", "-C", str(BRAIN_HOME), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        m = re.search(r"[:/]([^/:]+)/[^/]+?(?:\.git)?$", r.stdout.strip())
        if r.returncode == 0 and m:
            return m.group(1)
    except OSError:
        pass
    return None


# --------------------------------------------------------------- collect ----


def gh_json(args):
    """`gh api ...` -> parsed JSON; None on any failure (the surface degrades
    honestly rather than inventing content). Read-only endpoints only."""
    try:
        r = subprocess.run(
            [GH, "api", *args], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def age_h(iso):
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return round((datetime.now(timezone.utc) - then).total_seconds() / 3600)


def age_label(hours):
    if hours is None:
        return "?"
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def collect_overnight(jobs, org, degraded):
    """Latest run of each scheduled workflow (the what-ran-while-I-slept
    glance), with the blocked-at-a-gate refinement from overnight_status.sh."""
    rows = []
    for job in jobs:
        repo, _, wf = str(job).partition(":")
        if "/" not in repo:
            repo = f"{org}/{repo}"
        runs = gh_json([f"repos/{repo}/actions/workflows/{wf}/runs?per_page=1"])
        run = (runs or {}).get("workflow_runs") or [None]
        run = run[0]
        if run is None:
            if runs is None:
                degraded.append(f"overnight: could not read {repo}/{wf}")
            rows.append({"repo": repo, "workflow": wf, "conclusion": None,
                         "age_h": None, "url": None, "blocked": False})
            continue
        conclusion = run.get("conclusion") or run.get("status")
        blocked = False
        blocked_reason = None
        if conclusion == "success" and run.get("id"):
            jobs_json = gh_json([f"repos/{repo}/actions/runs/{run['id']}/jobs"])
            for j in (jobs_json or {}).get("jobs", []):
                for step in j.get("steps") or []:
                    if (step.get("conclusion") == "success"
                            and str(step.get("name", "")).startswith(BLOCKED_STEP_PREFIX)):
                        blocked = True
                        # The blocked step's ::warning annotation names why —
                        # surface it here so the morning glance needs no click.
                        anns = gh_json(
                            [f"repos/{repo}/check-runs/{j.get('id')}/annotations"])
                        for a in anns or []:
                            if "blocked" in str(a.get("title", "")).lower():
                                blocked_reason = str(a.get("message", ""))[:200]
                                break
        rows.append({
            "repo": repo,
            "workflow": wf,
            "conclusion": conclusion,
            "age_h": age_h(run.get("created_at")),
            "url": run.get("html_url"),
            "blocked": blocked,
            "blocked_reason": blocked_reason,
        })
    return rows


def _fetch_json(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError):
        return None


def fetch_badge(pages_base, repo):
    """A sibling board's published badge.json — the cross-board headline
    contract ({label, message, color}). None when unreachable."""
    return _fetch_json(f"{pages_base}/{repo}/badge.json")


HEART_BLOCKER_CAP = 5
PERF_FLAGGED_CAP = 5

# A conversation waiting on us this long stops being amber. The Ears own the
# triage; this is only the tone the morning glance gives the wait.
COMMUNITY_STALE_DAYS = 7


def fetch_heart_board(pages_base, repo, degraded):
    """The Heart board's published machine surface (board.json, schema v2) —
    ONE read, two consumers (the blockers and the performance block below).
    None when unreachable; the degraded row is recorded here, once."""
    board = _fetch_json(f"{pages_base}/{repo}/board.json")
    if board is None:
        degraded.append("readiness: Heart board.json unreachable "
                        "(blockers shown on the Heart board only)")
    return board


def extract_heart_blockers(board):
    """The structured blockers, each already carrying its own /bug prompt —
    rendered here verbatim, never re-derived. [] when the surface is
    unreachable or carries no blockers (a GREEN morning)."""
    blockers = (board or {}).get("blockers") or []
    return [{
        "text": str(b.get("text", ""))[:160],
        "severity": b.get("severity"),
        "repo": b.get("repo"),
        "repo_url": b.get("repo_url"),
        "run_url": b.get("run_url"),
        "prompt": b.get("prompt"),
        # An evidence gap also arrives with the command that re-runs its check
        # (Heart board.json v3); absent on other severities and on an older
        # Heart publish. Forwarded verbatim, like everything else here.
        "command": b.get("command"),
    } for b in blockers[:HEART_BLOCKER_CAP]]


def extract_heart_plan(board):
    """The Heart's whole-tier remedy — one payload that closes every current
    evidence gap ({count, command, prompt}). Rendered here verbatim; the Brain
    never derives a remedy of its own. None when nothing is stale, or when the
    surface predates the field."""
    plan = (board or {}).get("stale_plan")
    if not isinstance(plan, dict) or not plan.get("prompt"):
        return None
    return {"count": plan.get("count"),
            "command": plan.get("command"),
            "prompt": str(plan["prompt"])}


def fetch_heart_blockers(pages_base, repo, degraded):
    """Fetch-and-extract in one call (the blockers-only door)."""
    return extract_heart_blockers(fetch_heart_board(pages_base, repo, degraded))


def _as_list(value):
    return value if isinstance(value, list) else []


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def secs_label(seconds):
    """Seconds -> a compact duration (`9m12s`, `45s`); '' when unreadable."""
    s = _num(seconds)
    if s is None:
        return ""
    s = int(round(s))
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _perf_where(row):
    """The row's identity — `RepoA/Smoke Tests`, `RepoA/scripts/x.py` — from
    whichever of the producer's keys are present."""
    repo = str(row.get("repo") or "").strip()
    what = str(row.get("workflow") or row.get("entry") or "").strip()
    return "/".join(b for b in (repo, what) if b) or "?"


def extract_heart_performance(board, board_url=""):
    """The Heart board's additive `performance` block, compacted to the
    morning headline: the few worst flagged rows — hang/kill events first,
    then slowed gates, then SLOW no_run markers that were never measured —
    each carrying its OWN prompt, rendered verbatim like the blockers, plus
    the counts behind them. Each row keeps the bucket it came from as `kind`
    (event / slowed / never measured) — the classification this function
    already makes, surfaced so the render can tone it rather than re-read the
    sentence.

    None when the block is absent: an older Heart publish simply renders no
    section (an unreachable board.json is already a degraded row). Measurement
    lives in the Heart; this end only reads it, so every access is a .get with
    a default — a producer-side rename costs a field, never the render."""
    perf = _as_dict(board).get("performance")
    if not isinstance(perf, dict):
        return None
    gates = [g for g in _as_list(perf.get("gates")) if isinstance(g, dict)]
    events = [e for e in _as_list(perf.get("events")) if isinstance(e, dict)]
    no_run = _as_dict(perf.get("no_run"))
    rows = [r for r in _as_list(no_run.get("rows")) if isinstance(r, dict)]

    warn = [g for g in gates if str(g.get("state", "")).lower() == "warn"]
    warn.sort(key=lambda g: _num(g.get("median_s")) or 0.0, reverse=True)
    # A SLOW marker is not evidence of slowness: the ones with no measurement
    # behind them are the worst rows here, oldest first.
    unmeasured = [r for r in rows if not r.get("measured")
                  and str(r.get("marker", "")).upper() == "SLOW"]
    unmeasured.sort(key=lambda r: str(r.get("date") or ""))

    flagged = []
    for e in events:
        kind = str(e.get("kind") or "event").replace("_", " ")
        took = secs_label(e.get("duration_s"))
        flagged.append({
            "text": (f"{kind}: {_perf_where(e)}"
                     + (f" after {took}" if took else ""))[:160],
            "url": e.get("run_url"),
            "prompt": e.get("prompt"),
            "kind": "event",
        })
    for g in warn:
        bits = []
        for label, key in (("median", "median_s"), ("PR", "pr_median_s"),
                           ("max", "max_s")):
            value = secs_label(g.get(key))
            if value:
                bits.append(f"{label} {value}")
        if g.get("runs_counted"):
            bits.append(f"{g['runs_counted']} runs")
        if g.get("spark"):
            bits.append(str(g["spark"]))
        flagged.append({
            "text": (f"{_perf_where(g)} slowed"
                     + (f" — {' · '.join(bits)}" if bits else ""))[:160],
            "url": g.get("actions_url"),
            "prompt": g.get("prompt"),
            "kind": "slowed",
        })
    for r in unmeasured:
        since = f" since {r['date']}" if r.get("date") else ""
        flagged.append({
            "text": (f"{_perf_where(r)} {str(r.get('marker') or 'SLOW')}"
                     f"{since}, never measured")[:160],
            "url": r.get("url"),
            "prompt": r.get("prompt"),
            "kind": "never measured",
        })
    return {
        "flagged": flagged[:PERF_FLAGGED_CAP],
        "gates_total": len(gates),
        "gates_warn": len(warn),
        "events": len(events),
        "no_run_totals": _as_dict(no_run.get("totals")),
        "board_url": board_url,
    }


def collect_versions(stamps, org, reference_repo, degraded):
    """Version-stamp CONSISTENCY across the coupled set (the version_drift.sh
    invariant: same stamp as the siblings; the release tag is context only)."""
    rows = []
    for s in stamps:
        repo, _, path = str(s).partition(":")
        v = None
        local = PYAUTO_ROOT / repo / path
        if local.is_file():
            m = re.search(VERPAT, local.read_text(encoding="utf-8", errors="replace"))
            v = m.group(0) if m else None
        else:
            content = gh_json([f"repos/{org}/{repo}/contents/{path}"])
            if content and content.get("content"):
                try:
                    text = base64.b64decode(content["content"]).decode(
                        "utf-8", errors="replace")
                except (ValueError, TypeError):
                    text = ""
                m = re.search(VERPAT, text)
                v = m.group(0) if m else None
        rows.append({"repo": repo, "version": v})
    resolved = [r["version"] for r in rows if r["version"]]
    consensus = max(set(resolved), key=resolved.count) if resolved else None
    for r in rows:
        r["ok"] = r["version"] is None or consensus is None or r["version"] == consensus
    if not resolved:
        degraded.append("versions: no stamps resolved")
    reference = None
    if reference_repo:
        rel = gh_json([f"repos/{org}/{reference_repo}/releases/latest"])
        reference = (rel or {}).get("tag_name")
    return {
        "stamps": rows,
        "consensus": consensus,
        "reference": reference,
        "drift": sum(1 for r in rows if not r["ok"]),
    }


def collect_community(degraded):
    """The Ears' scan surface, reused wholesale (never re-derived): import the
    community conductor and call its build_scan()."""
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "community"))
    # The community module reads its env at import; mirror the board's gh
    # override so hermetic runs stay hermetic.
    os.environ.setdefault("COMMUNITY_GH", GH)
    try:
        import _community
        return _community.build_scan()
    except SystemExit as e:
        degraded.append(f"community: scan unavailable (exit {e.code})")
    except Exception as e:  # a degraded section, never a dead board
        degraded.append(f"community: scan failed ({type(e).__name__})")
    finally:
        sys.path.pop(0)
    return None


# The Mind's prompt header, as the intake conductor writes it: `Type:`,
# `Target:`, `Difficulty:`, `Autonomy:`, `Priority:`. Read, never derived —
# an unheaded prompt yields no facets and renders as a bare row.
_FACET_LINE = re.compile(
    r"(Type|Target|Difficulty|Autonomy|Priority):\s*(\S.*?)\s*$")
FACET_KEYS = ("type", "target", "difficulty", "autonomy", "priority")
# The header opens the file (a `# title` and a blank line may precede it), and
# the intake conductor writes its fields together. So: a block that starts
# late, or that is a single `Priority:` line, is prose — not a header.
FACET_HEADER_LINES = 8
FACET_MIN_FIELDS = 2


def prompt_facets(text):
    """The header facets of one Mind prompt — the header block, and only it.

    The board shows an in-flight task with the same pills the Mind dashboard
    gives it, so a task looks like itself on both pages.

    The block is the run of lines around the first field line: a `# title`
    above it, `Status:`/`Repos:`/`Milestone:` lines beside it, and the blank
    line that closes it. Reading stops there, so a `Priority:` written into
    the prose below is discussion, not the header the Mind maintains — and a
    lone field line, or one that starts well down the file, is prose too.
    An unheaded prompt yields nothing and renders as a bare row: no pill here
    is ever a guess.
    """
    found, started = {}, False
    for n, line in enumerate(text.splitlines()):
        m = _FACET_LINE.match(line)
        if m:
            if not started and n >= FACET_HEADER_LINES:
                break
            started = True
            found.setdefault(m.group(1).lower(), m.group(2))
        elif started and not line.strip():
            break
    if len(found) < FACET_MIN_FIELDS:
        found = {}
    # `target` keeps the header's own casing — it is a repo name, and the
    # Mind writes it as one. The rest are a closed vocabulary the pill tones
    # and the work-type glyphs are keyed on, so they normalise.
    return {k: (found.get(k, "") if k == "target"
                else found.get(k, "").lower()) for k in FACET_KEYS}


def collect_resume(org, degraded):
    """Resume context: the Mind's own generated counts (dashboard.md header —
    compose, don't recompute), the task files on deck (each with the header
    facets the Mind already gave it), the queue length, and open
    pending-release PRs."""
    mind = PYAUTO_ROOT / "PyAutoMind"
    counts = {}
    tasks = []
    queue_len = None
    if mind.is_dir():
        dash = mind / "dashboard.md"
        if dash.is_file():
            for label, n in re.findall(
                r"^\|\s*\[([^\]]+)\]\([^)]*\)[^|]*\|\s*(\d+)\s*\|",
                dash.read_text(encoding="utf-8"), re.M,
            ):
                counts[label] = int(n)
        active = mind / "active"
        if active.is_dir():
            for f in sorted(active.glob("*.md")):
                if f.name == "AGENTS.md":
                    continue
                body = f.read_text(encoding="utf-8")
                title = f.stem
                for line in body.splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                tasks.append({"path": f"active/{f.name}", "title": title,
                              "facets": prompt_facets(body)})
        queue = mind / "queue.md"
        if queue.is_file():
            queue_len = sum(
                1 for line in queue.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
                and (line.startswith("- ") or line.rstrip().endswith(".md"))
            )
    else:
        degraded.append("resume: PyAutoMind checkout not found (set PYAUTO_ROOT)")
    prs = gh_json(
        [f"search/issues?q=org:{org}+is:pr+is:open+label:pending-release"])
    pending = None
    if prs is not None:
        pending = [{
            "repo": "/".join(i.get("repository_url", "").split("/")[-2:]),
            "number": i.get("number"),
            "title": i.get("title", ""),
            "url": i.get("html_url"),
        } for i in prs.get("items", [])]
    else:
        degraded.append("resume: pending-release PR search failed")
    return {"counts": counts, "tasks": tasks, "queue_len": queue_len,
            "pending_prs": pending}


def collect_open_issues(org, degraded):
    """Total open issues across the org — the /issue_cleanup pointer count
    (the audit itself stays that skill's confirmation-gated job)."""
    res = gh_json([f"search/issues?q=org:{org}+is:issue+is:open&per_page=1"])
    if res is None:
        degraded.append("upkeep: open-issue count unavailable")
        return None
    return res.get("total_count")


# The board is cloud-first: with BOARD_HYGIENE_SCAN=1 (set by brain_board.yml,
# whose checkout step clones the body-map scan set) the collect runs the
# hygiene conductor's own fast pre-scan right here, so hygiene needs no
# machine at all. Opt-in by env because a terminal `pyauto-brain board`
# digest should stay instant.
HYGIENE_CMD = os.environ.get(
    "BOARD_HYGIENE_CMD",
    str(BRAIN_HOME / "agents" / "conductors" / "hygiene" / "hygiene.sh"))

# Rows in these states carry nothing actionable for the morning glance.
HYGIENE_QUIET_STATUSES = ("clean", "unscanned", "deferred", "advisory")


def collect_hygiene(degraded):
    """The hygiene conductor's --json pre-scan, run in THIS render (cloud or
    local — wherever the scan set is checked out). None when not enabled."""
    if os.environ.get("BOARD_HYGIENE_SCAN") != "1":
        return None
    try:
        r = subprocess.run(["bash", HYGIENE_CMD, "--json"],
                           capture_output=True, text=True, timeout=900)
        decision = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        decision = None
    if decision is None:
        degraded.append("hygiene: pre-scan failed — rows unavailable this render")
        return None
    return {
        "repos_present": decision.get("repos_present"),
        "repos_declared": decision.get("repos_declared"),
        "rows": [{
            "mode": row.get("mode"),
            "status": row.get("status"),
            "count": row.get("count"),
            "summary": str(row.get("summary", ""))[:200],
            "delegate": row.get("delegate"),
        } for row in decision.get("rows", [])],
    }


# Dev-box observations (state/devbox_board.json, pushed by `board publish` —
# usually via bin/morning.sh) are honest only with an age: fresh under 48h,
# shown stale up to 7d, then dropped with a re-run hint.
DEVBOX_FILE = Path(os.environ.get(
    "BOARD_DEVBOX_FILE", BRAIN_HOME / "state" / "devbox_board.json"))
DEVBOX_FRESH_H = 48
DEVBOX_EXPIRE_H = 24 * 7


def collect_devbox():
    """The committed dev-box distillation: hygiene worklist rows + worktree
    state — the two morning signals a cloud render cannot observe itself."""
    if not DEVBOX_FILE.is_file():
        return None
    try:
        payload = json.loads(DEVBOX_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    hours = age_h(payload.get("ts"))
    if hours is None or hours > DEVBOX_EXPIRE_H:
        return None
    payload["age_h"] = hours
    payload["stale"] = hours > DEVBOX_FRESH_H
    return payload


AUTONOMY_ROW_CAP = 5


def _judgement_chip(value, cap=28):
    """The log's two judgement cells, as a chip-sized label.

    The log writes them as `<verdict> (<why>)` — "safe (feature medium cap;
    same resumed acknowledged launch ...)" — because it is a record, read as a
    table. A pill is not a table cell: it cannot wrap, so the whole sentence
    became one chip a thousand pixels wide and the board scrolled sideways on
    a phone. The verdict is the part that belongs on a chip; the why stays in
    the log, which is where the row's link sends you.

    It also restores the colour: `_LEVEL_TONES`/`_OUTCOME_TONES` key off the
    bare verdict, so every one of these rows was silently rendering neutral.
    """
    head = value.split(" (", 1)[0].strip()
    return head if len(head) <= cap else head[:cap - 1].rstrip() + "\u2026"


def collect_autonomy():
    """The tail of the Mind's autonomy calibration log — what ran unattended
    lately and how it ended (read verbatim; the log stays the record)."""
    log = PYAUTO_ROOT / "PyAutoMind" / "autonomy_log.md"
    if not log.is_file():
        return []
    rows = re.findall(
        r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|"
        r"[^|]*\|\s*([^|]+?)\s*\|",
        log.read_text(encoding="utf-8"), re.M)
    return [{"date": d, "task": t[:70],
             "level": _judgement_chip(lvl), "outcome": _judgement_chip(o)}
            for d, t, lvl, o in rows[-AUTONOMY_ROW_CAP:]]


HISTORY_CAP = 30


def updated_history(prev_board, need_you, today):
    """Self-carrying trend: yesterday's published board.json hands its history
    forward; today's count is appended (one entry per date, newest last)."""
    history = list((prev_board or {}).get("history") or [])
    history = [h for h in history
               if isinstance(h, dict) and h.get("date") != today]
    history.append({"date": today, "need_you": need_you})
    return history[-HISTORY_CAP:]


def sparkline(history):
    """The last fortnight of 'N need you' as unicode blocks ('' if <2 days)."""
    values = [int(h.get("need_you", 0)) for h in history][-14:]
    if len(values) < 2:
        return ""
    peak = max(max(values), 1)
    blocks = "▁▂▃▄▅▆▇█"
    return "".join(blocks[min((v * (len(blocks) - 1) + peak - 1) // peak,
                              len(blocks) - 1)] for v in values)


def collect_doors():
    """EVERY door, from the two single sources: the dispatcher registry
    (conductors + faculties — all the agents) and skills/*/SKILL.md (the
    non-agent doors: compositions, dev-flow entries, ship/cleanup workflows).
    Never a second hand-written roster."""
    script = (
        f'source "{BRAIN_HOME}/bin/pyauto-brain"; '
        'for v in "${CONDUCTOR_ORDER[@]}"; do printf "conductor\\t%s\\t%s\\n" "$v" "${AGENT_DESC[$v]}"; done; '
        'for v in "${FACULTY_ORDER[@]}"; do printf "faculty\\t%s\\t%s\\n" "$v" "${AGENT_DESC[$v]}"; done'
    )
    try:
        r = subprocess.run(["bash", "-c", script],
                           capture_output=True, text=True, timeout=30)
    except OSError:
        return []
    doors = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            doors.append({"tier": parts[0], "verb": parts[1], "desc": parts[2]})
    agent_verbs = {d["verb"] for d in doors}
    # board (this page) and wake_up (superseded BY this page) stay off the
    # roster on purpose.
    skip = agent_verbs | {"board", "wake_up"}
    for skill in sorted((BRAIN_HOME / "skills").glob("*/SKILL.md")):
        verb = skill.parent.name
        if verb in skip:
            continue
        m = re.search(r"^description:\s*(.+)$", skill.read_text(encoding="utf-8"),
                      re.M)
        desc = m.group(1).strip() if m else ""
        # First sentence only — the SKILL.md carries the full contract.
        desc = re.split(r"(?<=[.!?]) ", desc, maxsplit=1)[0][:140]
        doors.append({"tier": "skill", "verb": verb, "desc": desc})
    return doors


def collect():
    board_cfg = load_policy()
    homes = repo_homes()
    org = derive_org(homes)
    if org is None:
        fail(4, "cannot derive the GitHub org (no body map, no git remote)")
    pages_base = os.environ.get(
        "BOARD_PAGES_BASE", f"https://{org.lower()}.github.io")
    degraded = []
    board_family = board_cfg.get("boards") or {}
    heart_repo = board_cfg.get("heart_board", "PyAutoHeart")
    overnight = collect_overnight(board_cfg.get("overnight_jobs", []), org, degraded)
    heart = fetch_badge(pages_base, heart_repo)
    if heart is None:
        degraded.append("readiness: Heart board badge unreachable")
    # One read of the Heart's machine surface, two consumers: the blockers
    # and the test-performance block.
    heart_board = fetch_heart_board(pages_base, heart_repo, degraded)
    heart_blockers = extract_heart_blockers(heart_board)
    heart_plan = extract_heart_plan(heart_board)
    performance = extract_heart_performance(
        heart_board, f"{pages_base}/{heart_repo}/")
    hands = fetch_badge(pages_base, board_family.get("hands", "PyAutoHands"))
    versions = collect_versions(
        board_cfg.get("version_stamps", []), org,
        board_cfg.get("reference_release_repo"), degraded)
    community = collect_community(degraded)
    resume = collect_resume(org, degraded)
    open_issues = collect_open_issues(org, degraded)
    boards = {name: f"{pages_base}/{repo}/"
              for name, repo in board_family.items()}
    now = datetime.now(timezone.utc)
    data = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "org": org,
        "overnight": overnight,
        "heart": heart,
        "heart_blockers": heart_blockers,
        "heart_plan": heart_plan,
        "performance": performance,
        "hands": hands,
        "versions": versions,
        "community": community,
        "resume": resume,
        "open_issues": open_issues,
        "hygiene": collect_hygiene(degraded),
        "devbox": collect_devbox(),
        "autonomy": collect_autonomy(),
        "doors": collect_doors(),
        "boards": boards,
        "degraded": degraded,
    }
    # The trend hands itself forward through the published board.json.
    prev = _fetch_json(f"{pages_base}/{board_family.get('brain', 'PyAutoBrain')}/board.json")
    blocking, attention = verdict(data)
    data["history"] = updated_history(
        prev, len(blocking) + len(attention), now.strftime("%Y-%m-%d"))
    return data


# --------------------------------------------------------------- verdict ----


def verdict(data):
    """(blocking, attention) — the two tiers of 'needs you'. Blocking = a red
    overnight job or a RED Heart; attention = gates blocked on purpose,
    version drift, humans waiting on a reply, a non-GREEN Heart."""
    blocking, attention = [], []
    for r in data["overnight"]:
        if r["conclusion"] not in (None, "success"):
            blocking.append(f"overnight: {r['repo']}/{r['workflow']} {r['conclusion']}")
        elif r["blocked"]:
            attention.append(f"overnight: {r['repo']}/{r['workflow']} blocked at a gate")
    heart_msg = (data["heart"] or {}).get("message", "")
    if heart_msg.startswith("RED"):
        blocking.append(f"Heart verdict {heart_msg}")
    elif heart_msg and not heart_msg.startswith("GREEN"):
        attention.append(f"Heart verdict {heart_msg}")
    # Timing rows are advisory, never gating — but a run that hung or was
    # killed is a morning fact, so it joins the attention tier.
    events = (data.get("performance") or {}).get("events") or 0
    if events:
        attention.append(f"{events} CI hang event(s) flagged on the "
                         "test-performance surface")
    if data["versions"]["drift"]:
        attention.append(f"{data['versions']['drift']} version stamp(s) off consensus")
    waiting = ((data["community"] or {}).get("counts") or {}).get("awaiting_response", 0)
    if waiting:
        attention.append(f"{waiting} community conversation(s) awaiting a reply")
    return blocking, attention


def headline(data):
    blocking, attention = verdict(data)
    n = len(blocking) + len(attention)
    return "clear to work" if n == 0 else f"{n} need you"


def badge_color(data):
    blocking, attention = verdict(data)
    if blocking:
        return "red"
    if attention:
        return "orange"
    return "brightgreen"


# --------------------------------------------------------------- renders ----


def render_badge(data):
    """The cross-board headline contract the umbrella router consumes."""
    return json.dumps({
        "schemaVersion": 1,
        "label": "brain",
        "message": headline(data),
        "color": badge_color(data),
    }, indent=2) + "\n"


def _overnight_line(r):
    if r["conclusion"] is None:
        return f"– {r['repo']}/{r['workflow']} — no runs"
    if r["blocked"]:
        return (f"⏸ {r['repo']}/{r['workflow']} — blocked at a gate, no change "
                f"made ({age_label(r['age_h'])})")
    icon = "✓" if r["conclusion"] == "success" else "✗"
    return f"{icon} {r['repo']}/{r['workflow']} — {r['conclusion']} ({age_label(r['age_h'])})"


def render_md(data):
    """The terminal/GitHub digest — the same prioritized card /wake_up used
    to emit, generated instead of assembled."""
    blocking, attention = verdict(data)
    spark = sparkline(data.get("history") or [])
    L = [
        "# PyAutoBrain Board",
        "",
        f"<!-- generated by `pyauto-brain board` on {data['generated']} — "
        "regenerate, do not hand-edit -->",
        "",
        f"**{headline(data)}**"
        + (f" — {len(blocking)} blocking, {len(attention)} for attention"
           if blocking or attention else "")
        + (f" · trend `{spark}`" if spark else ""),
        "",
        f"Morning sync (local, terminal): `{MORNING_CMD}`",
        "",
    ]
    if blocking:
        L.append("## 🚨 Blocking")
        L += [f"- {b}" for b in blocking] + [""]
    L.append("## 🌙 Overnight")
    for r in data["overnight"]:
        line = f"- {_overnight_line(r)}"
        if r["url"]:
            line += f" — [run]({r['url']})"
        L.append(line)
        if r.get("blocked_reason"):
            L.append(f"  - {r['blocked_reason']}")
    L.append("")
    L.append("## ❤️ Readiness & release")
    if data["heart"]:
        L.append(f"- Heart verdict: **{data['heart'].get('message', '?')}** — "
                 f"[board]({data['boards'].get('heart', '')}) · re-run via `/health`")
    else:
        L.append("- Heart board unreachable — consult `/health` directly")
    plan = data.get("heart_plan")
    if plan:
        # The gaps are worth one line, not N: the Heart already wrote the plan
        # that closes all of them, and `fix stale` prints it in a terminal.
        clear = f"`{plan['command']}`" if plan.get("command") else "`pyauto-heart fix stale`"
        L.append(f"- Evidence gaps: {plan.get('count', '?')} — clear them all: {clear}")
    for b in data.get("heart_blockers") or []:
        sev = f"[{b['severity']}] " if b.get("severity") else ""
        line = f"  - {sev}{b['text']}"
        if b.get("run_url"):
            line += f" — [run]({b['run_url']})"
        L.append(line)
        if b.get("command"):
            L.append(f"    - `{b['command']}`")
        if b.get("prompt"):
            L.append(f"    - `{b['prompt']}`")
    if data.get("hands"):
        L.append(f"- Shipped: **{data['hands'].get('message', '?')}** — "
                 f"[Hands board]({data['boards'].get('hands', '')})")
    L.append("")
    perf = data.get("performance")
    if perf is not None:
        L.append("## ⏱ Test performance")
        if perf.get("flagged"):
            for f in perf["flagged"]:
                line = f"- {f['text']}"
                if f.get("url"):
                    line += f" — [run]({f['url']})"
                L.append(line)
                if f.get("prompt"):
                    L.append(f"  - `{f['prompt']}`")
        else:
            L.append(f"- ✓ {perf.get('gates_total', 0)} gates timed · nothing "
                     f"flagged — [full timings]({perf.get('board_url', '')})")
        L.append("")
    v = data["versions"]
    L.append("## 🏷️ Version consistency")
    if v["consensus"]:
        if v["drift"] == 0:
            L.append(f"- consistent at `{v['consensus']}` across the coupled set")
        else:
            for r in v["stamps"]:
                if not r["ok"]:
                    L.append(f"- ✗ {r['repo']} `{r['version']}` ≠ consensus "
                             f"`{v['consensus']}`")
        if v["reference"] and v["reference"] != v["consensus"]:
            L.append(f"  (latest release tag {v['reference']} — the frozen "
                     "source stamp trailing it is expected)")
    else:
        L.append("- no stamps resolved")
    L.append("")
    L.append("## 💬 Community")
    c = data["community"]
    if c:
        counts = c["counts"]
        L.append(f"- {counts['open_external']} external issue(s), "
                 f"{counts['open_external_prs']} external PR(s) open — "
                 f"**{counts['awaiting_response']} awaiting our reply** "
                 "(respond via `/community`; never auto-reply)")
        awaiting_keys = {(e["repo"], e["number"]) for e in c["awaiting_response"]}
        for e in c["awaiting_response"]:
            days = (f"{e['waiting_days']:.0f}d"
                    if e.get("waiting_days") is not None else "?")
            L.append(f"  - `/community triage {e['repo']}#{e['number']}` "
                     f"[{days} waiting] @{e['author']}: {e['title'][:70]}")
        for e in c["open_external_issues"] + c["open_external_prs"]:
            if (e["repo"], e["number"]) in awaiting_keys:
                continue
            note = ("ours to watch" if e.get("awaiting_response") is False
                    else "unchecked")
            L.append(f"  - `/community triage {e['repo']}#{e['number']}` "
                     f"[{note}] @{e['author']}: {e['title'][:70]}")
        for e in c["awaiting_review"]:
            L.append(f"  - `/community triage {e['repo']}#{e['number']}` "
                     f"[review requested] @{e['author']}: {e['title'][:70]}")
    else:
        L.append("- scan unavailable — run `/community` for the live surface")
    L.append("")
    L.append("## 🔄 Resume")
    counts = data["resume"]["counts"]
    if counts:
        L.append("- " + " · ".join(f"{k} {n}" for k, n in counts.items())
                 + f" — [Mind board]({data['boards'].get('mind', '')})")
    for t in data["resume"]["tasks"]:
        L.append(f"  - `/start_dev {t['path']}` — {t['title'][:70]}")
    pending = data["resume"]["pending_prs"]
    if pending:
        L.append(f"- {len(pending)} pending-release PR(s):")
        for p in pending:
            L.append(f"  - {p['repo']}#{p['number']} {p['title'][:60]} — {p['url']}")
    elif pending is not None:
        L.append("- no pending-release PRs open")
    L.append("")
    L.append("## 🧹 Upkeep")
    if data["open_issues"] is not None:
        L.append(f"- {data['open_issues']} open issue(s) org-wide — reconcile "
                 "via `/issue_cleanup` (closing stays confirmation-gated)")
    L.append("- `/hygiene` — code-quality debt sweep")
    L.append("- `/repo_cleanup` — stale branches / stashes / dirty checkouts (local)")
    L.append("")
    hygiene = data.get("hygiene")
    if hygiene:
        L.append(f"## 🧼 Hygiene (scanned this render — "
                 f"{hygiene.get('repos_present')}/{hygiene.get('repos_declared')} "
                 "repos present)")
        flagged = [r for r in hygiene["rows"]
                   if r.get("status") not in HYGIENE_QUIET_STATUSES]
        if flagged:
            for row in flagged:
                summary = str(row.get("summary", ""))[:140]
                L.append(f"- {row.get('mode')}: {summary} → `{row.get('delegate')}`")
        else:
            L.append("- nothing flagged")
        L.append("")
    devbox = data.get("devbox")
    if devbox:
        stale = " — STALE, re-run `bash PyAutoBrain/bin/morning.sh`" \
            if devbox.get("stale") else ""
        L.append(f"## 🖥️ Dev box (observed {age_label(devbox['age_h'])} "
                 f"ago via morning.sh{stale})")
        # The cloud scan supersedes the dev box's hygiene rows; only the
        # worktree state (unknowable from the cloud) still needs this vantage.
        if not hygiene:
            for row in devbox.get("hygiene", {}).get("rows", []):
                if row.get("status") in HYGIENE_QUIET_STATUSES:
                    continue
                summary = str(row.get("summary", ""))[:140]
                L.append(f"- {row.get('mode')}: {summary} → `{row.get('delegate')}`")
        for wt in devbox.get("worktrees", []):
            bits = [wt.get("branch") or "?"]
            if wt.get("ahead"):
                bits.append(f"{wt['ahead']} unpushed")
            if wt.get("dirty"):
                bits.append("dirty")
            if wt.get("stashes"):
                bits.append(f"{wt['stashes']} stash(es)")
            L.append(f"- worktree {wt.get('repo')}: {' · '.join(bits)}")
        L.append("")
    if data.get("autonomy"):
        L.append("## 🤖 Autonomous runs (latest — the calibration log's tail)")
        for a in data["autonomy"]:
            L.append(f"- {a['date']} — {a['task']} — {a['outcome']}")
        L.append("")
    if data["degraded"]:
        L.append("## Degraded")
        L += [f"- {d}" for d in data["degraded"]]
        L.append("")
    L.append("Boards: " + " · ".join(
        f"[{name}]({url})" for name, url in data["boards"].items()
        if name != "brain"))
    L.append("")
    return "\n".join(L)


def _attr(s):
    return html.escape(str(s), quote=True)


def _row(text_html, payload, term=False):
    """One actionable row: a copy button (📋 Claude payload, ⌨ terminal
    command) then the text."""
    icon, cls, label = ("⌨", "copy term", "Copy the terminal command") \
        if term else ("📋", "copy", "Copy the Claude command")
    return (f'<div class="task"><button class="{cls}" data-cmd="{_attr(payload)}" '
            f'aria-label="{label}">{icon}</button><p>{text_html}</p></div>')


def _plain(text_html):
    return f'<div class="task"><p>{text_html}</p></div>'


def section_counts(data):
    """`(number, label)` pairs for the header strip — one per section that can
    ask something of a human, in the order those sections appear.

    A source that could not be read contributes `–`, never a zero: the strip
    is read before the rows and must not promise a quiet morning the board
    cannot see.
    """
    # Red as `verdict()` counts it: a gate that stopped on purpose is amber
    # there, so it is not red here either.
    red = sum(1 for r in data["overnight"]
              if r["conclusion"] not in (None, "success") and not r["blocked"])
    blockers = len(data.get("heart_blockers") or []) if data["heart"] else "–"
    community = data["community"]
    awaiting = (community["counts"]["awaiting_response"]
                if community else "–")
    issues = data["open_issues"] if data["open_issues"] is not None else "–"
    return [(red, "Overnight red"), (blockers, "Blockers"),
            (awaiting, "Awaiting"), (len(data["resume"]["tasks"]), "In flight"),
            (issues, "Open issues")]


def _verdict_tone(message):
    """A sibling board's headline, toned. GREEN goes, RED stops, anything
    else — including a word this end has never seen — asks for a look."""
    return "g" if message.startswith("GREEN") else (
        "r" if message.startswith("RED") else "y")


def _hygiene_row(row):
    """One hygiene finding: the summary reads, the mode and status pill."""
    summary = html.escape(str(row.get("summary", ""))[:140])
    return summary + pills((str(row.get("mode") or "?"), ""),
                           (str(row.get("status") or ""), "y"))


# The autonomy log's two judgement columns. Colour marks the exception: the
# level a task ran at only matters when it was unusually free or unusually
# gated, and `merged-unchanged` is what four in five rows say — tinting the
# ordinary outcome would paint the whole log and tell no one anything.
_LEVEL_TONES = {"safe": "g", "human-required": "r"}
_OUTCOME_TONES = {"amended": "y", "rejected": "r", "reverted": "r"}


# The html twin. Self-contained by the same contract as the Mind dashboard —
# no external assets, inline style and script only, one copy button per
# actionable row — and dressed by the shared board theme, so this page and
# that one are visibly the same family (board/_theme.py).
def render_html(data):
    blocking, attention = verdict(data)
    esc = html.escape
    H = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>PyAutoBrain Board</title>",
        f"<!-- generated by `pyauto-brain board` on {data['generated']} — "
        "regenerate, do not hand-edit -->",
        f"<style>{_theme_css(THEME_ORGAN)}</style>",
        "</head>",
        "<body>",
        hero(THEME_ORGAN, "Board",
             "The organism's morning door — what ran overnight, who is "
             "waiting, and what needs you. Tap 📋 to put a command on your "
             "clipboard for a Claude Code chat; ⌨ rows are terminal "
             "commands."),
    ]
    verdict_cls = "bad" if blocking else ("warn" if attention else "ok")
    spark = sparkline(data.get("history") or [])
    spark_html = (f'<span class="muted" title="need-you count, last '
                  f'{min(len(data.get("history") or []), 14)} days"> · trend '
                  f'{esc(spark)}</span>') if spark else ""
    # The verdict is the one thing a human reads before anything else, so it
    # gets a banner rather than a coloured word in a paragraph.
    H.append(f'<p class="verdict {verdict_cls}"><b>{esc(headline(data))}</b>'
             f'<span class="muted">generated {esc(data["generated"])}</span>'
             f'{spark_html}</p>')
    # The five numbers a human wants before reading a row — one per section
    # that can ask something of them, so the strip doubles as a contents
    # page. `–` where a source was unreachable: an absent count is never a
    # zero here, the same contract the rows keep.
    H.append(stats(*section_counts(data)))
    H.append("<h2>⌨ Morning sync (local)</h2>")
    H.append(_row(
        "Sync every repo to main + clean generated cruft — run in a terminal "
        "at the workspace root, not in a Claude chat.",
        MORNING_CMD, term=True))

    H.append("<h2>🌙 Overnight</h2>")
    for r in data["overnight"]:
        # The workflow is the row's subject; its repo and its conclusion are
        # facets, so they read as pills — the repo in the organ accent
        # (identity) and the conclusion in its verdict tone.
        link = f' — <a href="{_attr(r["url"])}">run ↗</a>' if r["url"] else ""
        age = (f' <span class="muted">({age_label(r["age_h"])})</span>'
               if r["conclusion"] is not None else "")
        subject = f'<b>{esc(r["workflow"])}</b>{age}{link}'
        failed = r["conclusion"] not in (None, "success")
        if r["conclusion"] is None:
            state, tone, reason = "no runs", "n", ""
        elif r["blocked"]:
            state, tone = "blocked at a gate", "y"
            reason = ('<br><span class="muted">no change made — '
                      f'{esc(r["blocked_reason"])}</span>'
                      if r.get("blocked_reason") else
                      '<br><span class="muted">no change made</span>')
        elif not failed:
            state, tone, reason = "success", "g", ""
        else:
            state, tone, reason = r["conclusion"], "r", ""
        # pills() escapes its own values; only the hand-built html above is
        # escaped here.
        text = subject + reason + pills((r["repo"], ""), (state, tone))
        if failed and not r["blocked"]:
            H.append(_row(text, f"/bug overnight: {r['repo']}/{r['workflow']} "
                                f"concluded {r['conclusion']} — "
                                f"{r['url'] or 'no run url'}"))
        else:
            H.append(_plain(text))

    H.append("<h2>❤️ Readiness &amp; release</h2>")
    heart_url = data["boards"].get("heart", "")
    if data["heart"]:
        msg = data["heart"].get("message", "?")
        H.append(_row(
            f'Heart verdict — <a href="{_attr(heart_url)}">Heart board ↗</a>'
            + pills((msg, _verdict_tone(msg))), "/health"))
    else:
        H.append(_row("Heart board unreachable — consult the clinician "
                      "directly." + pills(("unreachable", "y")), "/health"))
    plan = data.get("heart_plan")
    if plan:
        # One tap for the whole stale tier, above the gaps it closes: the
        # Claude prompt always, the shell chain when the Heart could offer one.
        H.append(_row(f'Clear all {plan.get("count", "?")} evidence gaps — one prompt'
                      + pills(("stale", "y")), plan["prompt"]))
        if plan.get("command"):
            H.append(_row("… or the command chain that re-runs every check",
                          plan["command"], term=True))
    for b in data.get("heart_blockers") or []:
        sev = b.get("severity")
        links = "".join(
            f' <a href="{_attr(url)}">{label} ↗</a>'
            for label, url in (("repo", b.get("repo_url")),
                               ("run", b.get("run_url"))) if url)
        text = (f'{esc(b["text"])}{links}'
                + pills((sev, "r" if sev == "red" else "y")))
        if b.get("prompt"):
            H.append(_row(text, b["prompt"]))
        else:
            H.append(_plain(text))
    if data.get("hands"):
        hands_url = data["boards"].get("hands", "")
        shipped = data["hands"].get("message", "?")
        H.append(_plain(
            f'Shipped — <a href="{_attr(hands_url)}">Hands board ↗</a>'
            + pills((shipped, _verdict_tone(shipped)))))

    # The Heart's test-performance block, rendered as it arrived — the rows
    # carry their own prompts, this end never re-derives one.
    perf = data.get("performance")
    if perf is not None:
        H.append("<h2>⏱ Test performance</h2>")
        if perf.get("flagged"):
            for f in perf["flagged"]:
                link = (f' <a href="{_attr(f["url"])}">run ↗</a>'
                        if f.get("url") else "")
                # The sentence is the Heart's, verbatim; the pill is the
                # bucket it arrived in, so severity is scannable.
                kind = f.get("kind") or ""
                text = (f'{esc(f["text"])}{link}'
                        + pills((kind, "r" if kind == "event" else "y")))
                if f.get("prompt"):
                    H.append(_row(text, f["prompt"]))
                else:
                    H.append(_plain(text))
        else:
            timings_url = perf.get("board_url") or heart_url
            H.append(_plain(
                f'{perf.get("gates_total", 0)} gates timed — '
                f'<a href="{_attr(timings_url)}">full timings ↗</a>'
                + pills(("nothing flagged", "g"))))

    v = data["versions"]
    H.append("<h2>🏷️ Version consistency</h2>")
    if v["consensus"] and v["drift"] == 0:
        H.append(_plain(
            f'The coupled set agrees at <code>{esc(v["consensus"])}</code>'
            + pills(("consistent", "g"))))
    elif v["consensus"]:
        for r in v["stamps"]:
            if not r["ok"]:
                H.append(_row(
                    f'<code>{esc(r["version"] or "?")}</code> ≠ consensus '
                    f'<code>{esc(v["consensus"])}</code>'
                    + pills((r["repo"], ""), ("drift", "r")),
                    f"/bug version drift: {r['repo']} stamp {r['version']} is "
                    f"out of step with the coupled-set consensus {v['consensus']}"))
    else:
        H.append(_plain('<span class="muted">no stamps resolved</span>'))
    if v["reference"] and v["consensus"] and v["reference"] != v["consensus"]:
        H.append(f'<p class="muted">Latest release tag {esc(v["reference"])} — '
                 "the frozen source stamp trailing it is expected.</p>")

    H.append("<h2>💬 Community</h2>")
    c = data["community"]
    if c:
        counts = c["counts"]
        H.append(_row(
            'Replies stay human-gated in <code>/community</code>.'
            + pills((f'{counts["open_external"]} issue(s)', ""),
                    (f'{counts["open_external_prs"]} PR(s)', "n"),
                    (f'{counts["awaiting_response"]} awaiting our reply',
                     "y" if counts["awaiting_response"] else "g")),
            "/community"))

        def community_row(e, note, tone):
            """Every conversation gets its own one-tap triage chip.

            The conversation's kind leads the pills in the accent — it is what
            this row *is* — and the note takes the tone of how long someone
            has been waiting on us.
            """
            url = e.get("url") or ""
            title = esc(e.get("title", "")[:80])
            kind = "PR" if e.get("type") == "pr" else "issue"
            link = f'<a href="{_attr(url)}">{esc(e["repo"])}#{e["number"]}</a>' \
                if url else f'{esc(e["repo"])}#{e["number"]}'
            return _row(
                f'{link} @{esc(e["author"])}: {title}'
                + pills((kind, ""), (note, tone)),
                f"/community triage {e['repo']}#{e['number']}")

        awaiting_keys = {(e["repo"], e["number"]) for e in c["awaiting_response"]}
        for e in c["awaiting_response"]:
            waited = e.get("waiting_days")
            days = f"{waited:.0f}d waiting" if waited is not None else "waiting"
            H.append(community_row(
                e, days, "r" if (waited or 0) >= COMMUNITY_STALE_DAYS else "y"))
        for e in c["open_external_issues"] + c["open_external_prs"]:
            if (e["repo"], e["number"]) in awaiting_keys:
                continue
            note = ("ours to watch" if e.get("awaiting_response") is False
                    else "unchecked")
            H.append(community_row(e, note, "n"))
        for e in c["awaiting_review"]:
            H.append(community_row(e, "review requested", "y"))
    else:
        H.append(_row("Scan unavailable — run the Ears directly.", "/community"))

    H.append("<h2>🔄 Resume</h2>")
    counts = data["resume"]["counts"]
    mind_url = data["boards"].get("mind", "")
    if counts:
        H.append(_plain(
            f'Pick from the <a href="{_attr(mind_url)}">Mind board ↗</a>'
            + pills(*[(f"{k} {n}", "" if i == 0 else "n")
                      for i, (k, n) in enumerate(counts.items())])))
    for t in data["resume"]["tasks"]:
        # An in-flight task wears the header facets the Mind gave it, so it
        # looks like itself on both pages — same pills, same order.
        facets = t.get("facets") or {}
        H.append(_row(
            f'{esc(t["title"][:80])} <code>{esc(t["path"])}</code>'
            + pills(facets.get("target"), facets.get("difficulty"),
                    facets.get("autonomy"), facets.get("priority"),
                    work_type=facets.get("type")),
            f"/start_dev {t['path']}"))
    pending = data["resume"]["pending_prs"]
    if pending:
        for p in pending:
            H.append(_row(
                f'<a href="{_attr(p["url"])}">{esc(p["repo"])}#{p["number"]}'
                f'</a> — {esc(p["title"][:70])}'
                + pills(("pending-release", "y")),
                f"/prm {p['url']}"))
    elif pending is not None:
        H.append(_plain('<span class="muted">no pending-release PRs open</span>'))

    H.append("<h2>🧹 Upkeep</h2>")
    # Standing invitations rather than state, so the one pill each carries is
    # the door it routes to — what the 📋 puts on the clipboard, visible
    # without tapping it.
    issue_note = (f"{data['open_issues']} open issue(s) org-wide — "
                  if data["open_issues"] is not None else "")
    for text, door in (
        (f"{issue_note}reconcile the trackers (closing stays "
         "confirmation-gated).", "/issue_cleanup"),
        ("Code-quality debt sweep — slow tests, CLI noise, dep-cap drift "
         "(the Hygiene section below is its scan).", "/hygiene"),
        ("Stale branches, stashes, dirty checkouts (runs locally).",
         "/repo_cleanup"),
    ):
        H.append(_row(text + pills((door, "")), door))

    hygiene = data.get("hygiene")
    if hygiene:
        H.append(f'<h2>🧼 Hygiene <span class="muted">(scanned this render — '
                 f'{hygiene.get("repos_present")}/{hygiene.get("repos_declared")} '
                 "repos present)</span></h2>")
        flagged = [r for r in hygiene["rows"]
                   if r.get("status") not in HYGIENE_QUIET_STATUSES]
        if flagged:
            for row in flagged:
                H.append(_row(_hygiene_row(row),
                              str(row.get("delegate") or "/hygiene")))
        else:
            H.append(_plain("Every mode came back clean"
                            + pills(("nothing flagged", "g"))))

    devbox = data.get("devbox")
    if devbox:
        stale = (' — <span class="warn">STALE</span>'
                 if devbox.get("stale") else "")
        H.append(f'<h2>🖥️ Dev box <span class="muted">(observed '
                 f'{age_label(devbox["age_h"])} ago via morning.sh{stale})</span></h2>')
        if devbox.get("stale"):
            H.append(_row("Refresh the dev-box observation — run in a "
                          "terminal at the workspace root.", MORNING_CMD,
                          term=True))
        # Cloud hygiene supersedes the dev box's hygiene rows; the worktree
        # state below is the one thing only this vantage can see.
        if not hygiene:
            for row in devbox.get("hygiene", {}).get("rows", []):
                if row.get("status") in HYGIENE_QUIET_STATUSES:
                    continue
                H.append(_row(_hygiene_row(row),
                              str(row.get("delegate") or "/hygiene")))
        for wt in devbox.get("worktrees", []):
            # Unpushed work and a dirty tree are the things that lose work;
            # a stash is a note to self. Tone them accordingly.
            facets = [(str(wt.get("repo")), ""),
                      (str(wt.get("branch") or "?"), "n")]
            if wt.get("ahead"):
                facets.append((f'{wt["ahead"]} unpushed', "y"))
            if wt.get("dirty"):
                facets.append(("dirty", "y"))
            if wt.get("stashes"):
                facets.append((f'{wt["stashes"]} stash(es)', "n"))
            H.append(_plain("worktree" + pills(*facets)))

    if data.get("autonomy"):
        H.append('<h2>🤖 Autonomous runs <span class="muted">(the calibration '
                 "log's tail)</span></h2>")
        for a in data["autonomy"]:
            H.append(_plain(
                f'<span class="muted">{esc(a["date"])}</span> '
                f'{esc(a["task"])}'
                + pills((a["level"], _LEVEL_TONES.get(a["level"], "n")),
                        (a["outcome"], _OUTCOME_TONES.get(a["outcome"], "n")))))

    doors = data["doors"]
    if doors:
        H.append("<h2>🚪 All doors</h2>")
        H.append("<details><summary>every agent and workflow door</summary>")
        for d in doors:
            if d["tier"] == "skill":
                continue
            # The tier is the one thing that changes what a door does to the
            # world: a conductor acts, a faculty only opines. Accent the
            # actors; leave the read-only ones quiet.
            H.append(_row(
                f'<b>/{esc(d["verb"])}</b> — {esc(d["desc"])}'
                + pills((d["tier"], "" if d["tier"] == "conductor" else "n")),
                f"/{d['verb']}"))
        skills = [d for d in doors if d["tier"] == "skill"]
        if skills:
            H.append('<p class="muted">Workflow doors — compositions and '
                     'dev-flow entries, no agent of their own:</p>')
            for d in skills:
                H.append(_row(f'<b>/{esc(d["verb"])}</b> — {esc(d["desc"])}'
                              + pills(("workflow", "n")), f"/{d['verb']}"))
        H.append("</details>")

    if data["degraded"]:
        H.append("<h2>Degraded</h2>")
        for d in data["degraded"]:
            H.append(_plain(f'<span class="warn">{esc(d)}</span>'))

    footer = boards_footer(data["boards"], THEME_ORGAN)
    if footer:
        H.append(footer)
    H += [f"<script>{_THEME_JS}</script>", "</body>", "</html>"]
    return "\n".join(H) + "\n"


def render_json(data):
    return json.dumps(data, indent=2) + "\n"


# ------------------------------------------------------------------- cli ----


def main():
    parser = argparse.ArgumentParser(prog="board", description=__doc__)
    parser.add_argument("--md", action="store_true", help="markdown digest (default)")
    parser.add_argument("--html", action="store_true", help="the one-tap html page")
    parser.add_argument("--json", action="store_true", help="the raw surface")
    parser.add_argument("--badge", action="store_true",
                        help="badge.json (the cross-board headline contract)")
    parser.add_argument("--apply", action="store_true",
                        help="write index.html + badge.json + board.json + "
                             "board.md into --out")
    parser.add_argument("--out", default="_site", help="--apply output dir")
    args = parser.parse_args()

    data = collect()
    if args.apply:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text(render_html(data), encoding="utf-8")
        (out / "badge.json").write_text(render_badge(data), encoding="utf-8")
        (out / "board.json").write_text(render_json(data), encoding="utf-8")
        (out / "board.md").write_text(render_md(data), encoding="utf-8")
        print(f"board: wrote {out}/index.html + badge.json + board.json + board.md")
        return
    if args.html:
        print(render_html(data), end="")
    elif args.json:
        print(render_json(data), end="")
    elif args.badge:
        print(render_badge(data), end="")
    else:
        print(render_md(data))


if __name__ == "__main__":
    main()

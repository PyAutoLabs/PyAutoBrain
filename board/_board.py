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
        if conclusion == "success" and run.get("id"):
            jobs_json = gh_json([f"repos/{repo}/actions/runs/{run['id']}/jobs"])
            for j in (jobs_json or {}).get("jobs", []):
                for step in j.get("steps") or []:
                    if (step.get("conclusion") == "success"
                            and str(step.get("name", "")).startswith(BLOCKED_STEP_PREFIX)):
                        blocked = True
        rows.append({
            "repo": repo,
            "workflow": wf,
            "conclusion": conclusion,
            "age_h": age_h(run.get("created_at")),
            "url": run.get("html_url"),
            "blocked": blocked,
        })
    return rows


def fetch_badge(pages_base, repo):
    """A sibling board's published badge.json — the cross-board headline
    contract ({label, message, color}). None when unreachable."""
    url = f"{pages_base}/{repo}/badge.json"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError):
        return None


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


def collect_resume(org, degraded):
    """Resume context: the Mind's own generated counts (dashboard.md header —
    compose, don't recompute), the task files on deck, the queue length, and
    open pending-release PRs."""
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
                title = f.stem
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                tasks.append({"path": f"active/{f.name}", "title": title})
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


def collect_doors():
    """The conductor/faculty roster, read from the dispatcher registry itself
    (bin/pyauto-brain is the single source; never a second copy here)."""
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
    overnight = collect_overnight(board_cfg.get("overnight_jobs", []), org, degraded)
    heart = fetch_badge(pages_base, board_cfg.get("heart_board", "PyAutoHeart"))
    if heart is None:
        degraded.append("readiness: Heart board badge unreachable")
    versions = collect_versions(
        board_cfg.get("version_stamps", []), org,
        board_cfg.get("reference_release_repo"), degraded)
    community = collect_community(degraded)
    resume = collect_resume(org, degraded)
    open_issues = collect_open_issues(org, degraded)
    boards = {name: f"{pages_base}/{repo}/"
              for name, repo in (board_cfg.get("boards") or {}).items()}
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "org": org,
        "overnight": overnight,
        "heart": heart,
        "versions": versions,
        "community": community,
        "resume": resume,
        "open_issues": open_issues,
        "doors": collect_doors(),
        "boards": boards,
        "degraded": degraded,
    }


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
    L = [
        "# PyAutoBrain Board",
        "",
        f"<!-- generated by `pyauto-brain board` on {data['generated']} — "
        "regenerate, do not hand-edit -->",
        "",
        f"**{headline(data)}**"
        + (f" — {len(blocking)} blocking, {len(attention)} for attention"
           if blocking or attention else ""),
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
    L.append("")
    L.append("## ❤️ Readiness")
    if data["heart"]:
        L.append(f"- Heart verdict: **{data['heart'].get('message', '?')}** — "
                 f"[board]({data['boards'].get('heart', '')}) · re-run via `/health`")
    else:
        L.append("- Heart board unreachable — consult `/health` directly")
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
        for e in c["awaiting_response"]:
            days = (f"{e['waiting_days']:.0f}d"
                    if e.get("waiting_days") is not None else "?")
            L.append(f"  - {e['repo']}#{e['number']} [{days} waiting] "
                     f"@{e['author']}: {e['title'][:70]}")
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
    L.append("- `/hygiene` — code-quality debt sweep (local)")
    L.append("- `/repo_cleanup` — stale branches / stashes / dirty checkouts (local)")
    L.append("")
    if data["degraded"]:
        L.append("## Degraded")
        L += [f"- {d}" for d in data["degraded"]]
        L.append("")
    L.append(f"Boards: " + " · ".join(
        f"[{name}]({url})" for name, url in data["boards"].items()))
    L.append("")
    return "\n".join(L)


# The html twin — same CSS/JS contract as the Mind dashboard: self-contained
# (no external assets; inline script + href anchors only), one copy button per
# actionable row.
_HTML_CSS = """\
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2328;--muted:#59636e;
 --line:#d1d9e0;--btn:#f6f8fa;--ok:#1a7f37;--warn:#9a6700;--bad:#d1242f;
 --accent:#0969da}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#f0f6fc;
 --muted:#9198a1;--line:#3d444d;--btn:#151b23;--ok:#3fb950;--warn:#d29922;
 --bad:#f85149;--accent:#4493f8}}
*{box-sizing:border-box}
body{margin:0 auto;max-width:44rem;padding:1rem 1rem 4rem;background:var(--bg);
 color:var(--fg);font:16px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",
 Helvetica,Arial,sans-serif}
h1{font-size:1.35rem;margin:.4rem 0}
h2{font-size:1.15rem;margin-top:2rem;border-bottom:1px solid var(--line);
 padding-bottom:.3rem}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.muted{color:var(--muted)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em;
 background:var(--btn);padding:.1em .3em;border-radius:4px}
.task{display:flex;gap:.6rem;align-items:flex-start;padding:.45rem 0;
 border-bottom:1px solid var(--line)}
.task p{margin:.25rem 0 0;flex:1;overflow-wrap:anywhere}
button.copy{flex:0 0 auto;width:2.6rem;height:2.6rem;font-size:1.1rem;
 border:1px solid var(--line);border-radius:8px;background:var(--btn);
 cursor:pointer;color:var(--fg)}
button.copy.ok{color:var(--ok);border-color:var(--ok)}
button.copy.term{font-size:.95rem}
details{margin:.5rem 0}
summary{cursor:pointer;font-weight:600;padding:.4rem 0}
"""

_HTML_JS = """\
async function copyCmd(b){
  const cmd=b.dataset.cmd;
  try{await navigator.clipboard.writeText(cmd);}
  catch(e){const t=document.createElement("textarea");t.value=cmd;
    document.body.appendChild(t);t.select();document.execCommand("copy");
    t.remove();}
  const old=b.textContent;
  b.textContent="\\u2713";b.classList.add("ok");
  setTimeout(()=>{b.textContent=old;b.classList.remove("ok");},1200);}
document.addEventListener("click",e=>{
  const b=e.target.closest("button.copy");if(b)copyCmd(b);});
"""


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
        f"<style>{_HTML_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>🧠 PyAutoBrain Board</h1>",
        "<p>The organism's morning door — what ran overnight, who is waiting, "
        "and what needs you. Tap 📋 to put a command on your clipboard for a "
        "Claude Code chat; ⌨ rows are terminal commands.</p>",
    ]
    verdict_cls = "bad" if blocking else ("warn" if attention else "ok")
    H.append(f'<p><b class="{verdict_cls}">{esc(headline(data))}</b>'
             f'<span class="muted"> — generated {esc(data["generated"])}</span></p>')
    H.append("<h2>⌨ Morning sync (local)</h2>")
    H.append(_row(
        "Sync every repo to main + clean generated cruft — run in a terminal "
        "at the workspace root, not in a Claude chat.",
        MORNING_CMD, term=True))

    H.append("<h2>🌙 Overnight</h2>")
    for r in data["overnight"]:
        name = f"{esc(r['repo'])}/{esc(r['workflow'])}"
        link = f' — <a href="{_attr(r["url"])}">run ↗</a>' if r["url"] else ""
        if r["conclusion"] is None:
            H.append(_plain(f'<span class="muted">–</span> {name} — no runs'))
        elif r["blocked"]:
            H.append(_plain(
                f'<span class="warn">⏸</span> {name} — blocked at a gate, no '
                f'change made ({age_label(r["age_h"])}){link}'))
        elif r["conclusion"] == "success":
            H.append(_plain(f'<span class="ok">✓</span> {name} — success '
                            f'({age_label(r["age_h"])}){link}'))
        else:
            H.append(_row(
                f'<span class="bad">✗</span> {name} — {esc(r["conclusion"])} '
                f'({age_label(r["age_h"])}){link}',
                f"/bug overnight: {r['repo']}/{r['workflow']} concluded "
                f"{r['conclusion']} — {r['url'] or 'no run url'}"))

    H.append("<h2>❤️ Readiness</h2>")
    heart_url = data["boards"].get("heart", "")
    if data["heart"]:
        msg = data["heart"].get("message", "?")
        cls = "ok" if msg.startswith("GREEN") else (
            "bad" if msg.startswith("RED") else "warn")
        H.append(_row(
            f'Heart verdict: <b class="{cls}">{esc(msg)}</b> — '
            f'<a href="{_attr(heart_url)}">Heart board ↗</a>', "/health"))
    else:
        H.append(_row("Heart board unreachable — consult the clinician "
                      "directly.", "/health"))

    v = data["versions"]
    H.append("<h2>🏷️ Version consistency</h2>")
    if v["consensus"] and v["drift"] == 0:
        H.append(_plain(f'<span class="ok">✓</span> consistent at '
                        f'<code>{esc(v["consensus"])}</code> across the coupled set'))
    elif v["consensus"]:
        for r in v["stamps"]:
            if not r["ok"]:
                H.append(_row(
                    f'<span class="bad">✗</span> {esc(r["repo"])} '
                    f'<code>{esc(r["version"] or "?")}</code> ≠ consensus '
                    f'<code>{esc(v["consensus"])}</code>',
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
            f'{counts["open_external"]} external issue(s), '
            f'{counts["open_external_prs"]} external PR(s) open — '
            f'<b>{counts["awaiting_response"]} awaiting our reply</b>. '
            'Replies stay human-gated in <code>/community</code>.',
            "/community"))
        for e in c["awaiting_response"]:
            days = (f"{e['waiting_days']:.0f}d"
                    if e.get("waiting_days") is not None else "?")
            url = e.get("url") or ""
            title = esc(e.get("title", "")[:80])
            link = f'<a href="{_attr(url)}">{esc(e["repo"])}#{e["number"]}</a>' \
                if url else f'{esc(e["repo"])}#{e["number"]}'
            H.append(_row(
                f'{link} <span class="muted">[{days} waiting]</span> '
                f'@{esc(e["author"])}: {title}',
                f"/community triage {e['repo']}#{e['number']}"))
    else:
        H.append(_row("Scan unavailable — run the Ears directly.", "/community"))

    H.append("<h2>🔄 Resume</h2>")
    counts = data["resume"]["counts"]
    mind_url = data["boards"].get("mind", "")
    if counts:
        joined = " · ".join(f"{esc(k)} {n}" for k, n in counts.items())
        H.append(_plain(f'{joined} — pick from the '
                        f'<a href="{_attr(mind_url)}">Mind board ↗</a>'))
    for t in data["resume"]["tasks"]:
        H.append(_row(f'<code>{esc(t["path"])}</code> — {esc(t["title"][:80])}',
                      f"/start_dev {t['path']}"))
    pending = data["resume"]["pending_prs"]
    if pending:
        for p in pending:
            H.append(_row(
                f'pending-release <a href="{_attr(p["url"])}">'
                f'{esc(p["repo"])}#{p["number"]}</a> — {esc(p["title"][:70])}',
                f"/prm {p['url']}"))
    elif pending is not None:
        H.append(_plain('<span class="muted">no pending-release PRs open</span>'))

    H.append("<h2>🧹 Upkeep</h2>")
    issue_note = (f"{data['open_issues']} open issue(s) org-wide — "
                  if data["open_issues"] is not None else "")
    H.append(_row(f"{issue_note}reconcile the trackers (closing stays "
                  "confirmation-gated).", "/issue_cleanup"))
    H.append(_row("Code-quality debt sweep — slow tests, CLI noise, dep-cap "
                  "drift (runs locally).", "/hygiene"))
    H.append(_row("Stale branches, stashes, dirty checkouts (runs locally).",
                  "/repo_cleanup"))

    doors = data["doors"]
    if doors:
        H.append("<h2>🚪 All doors</h2>")
        H.append("<details><summary>every conductor and faculty</summary>")
        for d in doors:
            tier = '<span class="muted"> (faculty)</span>' \
                if d["tier"] == "faculty" else ""
            H.append(_row(f'<b>/{esc(d["verb"])}</b>{tier} — {esc(d["desc"])}',
                          f"/{d['verb']}"))
        H.append("</details>")

    if data["degraded"]:
        H.append("<h2>Degraded</h2>")
        for d in data["degraded"]:
            H.append(_plain(f'<span class="warn">{esc(d)}</span>'))

    nav = " · ".join(f'<a href="{_attr(url)}">{esc(name)}</a>'
                     for name, url in data["boards"].items())
    H.append(f'<p class="muted">Boards: {nav}</p>')
    H += [f"<script>{_HTML_JS}</script>", "</body>", "</html>"]
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

"""The shift-end cloud workspace sweep (M3.7e, PyAutoBrain#692; ruling S4).

AUTONOMY.md "Shift speed — 2026-11-19" (S4 and the red handling) and "The
watcher's network surface" (amendment 2026-11-19, M3.7e). The watcher:

- dispatches the sweep workflow once at shift close, when the shift merged
  at least one library or workspace PR (`dispatch`), with no inputs — never
  `force`, never the pinned (bisect) entry;
- reads the workflow's latest runs on `main` once a tick (`observe`): one
  `gh run list`, then each run's two artifacts (`workspace-smoke-shas`, and
  `workspace-validation-report` for a run that did not succeed) downloaded
  once per run id, at most `DOWNLOAD_TRIES` tries ever, cached in
  `<home>/sweep/` and shared by every shift;
- blocks unattended merges on the repos of a red run's failing workspaces
  (`block`) until a later run on `main` is green or the human posts
  `/clear-sweep` (`clear`);
- files one bug draft per red run through the one Mind writer (`file_draft`),
  naming the failing scripts and the suspect PRs (one `compare` read per
  affected repo per red run, cached).

Every call runs under the human's own `gh` login (decision b): `run_gh` passes
no App token. Which repo and workflow come from `config/policy.yaml`
`shift_watcher:` (`sweep_repo`, `sweep_workflow`, `sweep_siblings`); the
install chains from Heart's `config/repos.yaml` `smoke:` block and the
workspace map of its validation workflow, read from the local Heart checkout.
Nothing here names an instance repo.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: The artifacts the sweep uploads (PyAutoHeart workspace-smoke.yml, M3.7d).
SHAS_ARTIFACT = "workspace-smoke-shas"
SHAS_FILE = "shas.json"
REPORT_ARTIFACT = "workspace-validation-report"
REPORT_FILE = "report.json"
#: Tries per artifact per run id, ever (the first included).
DOWNLOAD_TRIES = 3
#: Runs listed a tick: the latest completed one and any still running.
RUN_LIST_LIMIT = 10
#: Conclusions that make a run red. A gate run that skipped the sweep ends
#: `success` and is green.
RED = ("failure", "cancelled", "timed_out", "startup_failure")
SWEEP_DIR = "sweep"
STATE_FILE = "state.json"
CLEARED_FILE = "cleared.json"
DRAFTED_DIR = "drafted"
#: `<slot>/sweep.dispatched`: claimed exclusively before the one dispatch.
DISPATCH_MARKER = "sweep.dispatched"
#: `<lease dir>/<task>.sweep-red`: a running close-out checks it before merging.
SWEEP_RED_SUFFIX = ".sweep-red"
RED_WHY = "workspace sweep red: {url}"
#: A dispatched run is matched by `createdAt` at most this long before the
#: recorded dispatch time (the two clocks differ).
DISPATCH_SLACK_S = 120
ALL_LIBRARIES = "every library repo"
_MERGE_RE = re.compile(r"^Merge pull request #(\d+)\b")
_SQUASH_RE = re.compile(r"\(#(\d+)\)\s*$")
_WS_MAP_RE = re.compile(r"declare -A WS=\((.*?)\)\n", re.S)
_WS_PAIR_RE = re.compile(r"\[(\w+)\]=([\w.-]+)")


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")[:200]


# --- configuration (declared surfaces only) ---------------------------------------------

def config(policy_path: Path) -> dict:
    """`shift_watcher:` `sweep_repo` (`<owner>/<repo>`), `sweep_workflow` and
    `sweep_siblings` from the Brain's policy file. No repo: the sweep is off."""
    try:
        import yaml
        cfg = (yaml.safe_load(Path(policy_path).read_text(encoding="utf-8")) or {})
        sw = cfg.get("shift_watcher") or {}
    except Exception:  # noqa: BLE001 — an unreadable policy turns the sweep off
        sw = {}
    repo = str(sw.get("sweep_repo") or "").strip()
    workflow = str(sw.get("sweep_workflow") or "").strip()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not workflow:
        return {}
    sib = sw.get("sweep_siblings") or {}
    return {"repo": repo, "workflow": workflow,
            "siblings": {str(k): str(v) for k, v in sib.items()} if isinstance(sib, dict) else {}}


def heart_root() -> Path | None:
    """The Heart checkout: `$PYAUTO_HEART`, else the shared repo resolver."""
    env = os.environ.get("PYAUTO_HEART")
    if env:
        return Path(env)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from _pyauto_root import pyauto_root  # noqa: E402
        from _repo_paths import repo_path  # noqa: E402
        return repo_path(pyauto_root(), "PyAutoHeart")
    except Exception:  # noqa: BLE001 — no Heart: every name is unknown
        return None


def heart_map(root: Path | None = None) -> dict:
    """{"chains": {workspace: [repo, …]}, "dirs": {workspace: repo},
    "projects": {cloud project: repo}} from the Heart checkout: `smoke:` in
    `config/repos.yaml` and the `declare -A WS=(…)` map of
    `.github/workflows/workspace-validation.yml`. Local reads; a file that
    cannot be read gives empty maps (every name unknown)."""
    root = root if root is not None else heart_root()
    out = {"chains": {}, "dirs": {}, "projects": {}}
    if root is None:
        return out
    try:
        import yaml
        cfg = yaml.safe_load((Path(root) / "config" / "repos.yaml").read_text()) or {}
        for name, ws in ((cfg.get("smoke") or {}).get("workspaces") or {}).items():
            if isinstance(ws, dict):
                out["chains"][str(name)] = [str(r) for r in ws.get("chain") or []]
                if ws.get("directory"):
                    out["dirs"][str(name)] = str(ws["directory"])
    except Exception:  # noqa: BLE001
        pass
    try:
        text = (Path(root) / ".github" / "workflows" / "workspace-validation.yml").read_text()
        m = _WS_MAP_RE.search(text)
        if m:
            out["projects"] = dict(_WS_PAIR_RE.findall(m.group(1)))
    except OSError:
        pass
    return out


# --- the one runner: the human's own gh login (decision b) -------------------------------

def run_gh(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run one `gh` call under the human's own login: no `GH_TOKEN` from the
    watcher's App is passed (AUTONOMY.md amendment 2026-11-19, M3.7e). The
    test suite replaces this function (tests/conftest.py)."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _call(argv: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        res = run_gh(argv, timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "gh timed out"
    except OSError as e:
        return 127, "", f"gh could not run: {e}"
    return res.returncode, res.stdout or "", res.stderr or ""


def dispatch(cfg: dict) -> dict:
    """The one `gh workflow run` at shift close, with no inputs: the workflow's
    own SHA gate decides whether to sweep. Never retried by the caller."""
    rc, out, err = _call(["gh", "workflow", "run", cfg["workflow"], "-R", cfg["repo"]])
    if rc == 0:
        return {"ok": True}
    return {"ok": False, "error": _first_line(err or out) or f"exit {rc}"}


def list_runs(cfg: dict) -> tuple[list[dict] | None, str]:
    """The workflow's latest runs on `main`, newest first; (None, why) when
    GitHub could not say."""
    rc, out, err = _call(["gh", "run", "list", "-R", cfg["repo"], "--workflow", cfg["workflow"],
                          "--branch", "main", "--limit", str(RUN_LIST_LIMIT), "--json",
                          "databaseId,status,conclusion,url,createdAt,event"], timeout=60)
    if rc != 0:
        return None, _first_line(err or out) or f"exit {rc}"
    try:
        data = json.loads(out or "")
    except ValueError:
        return None, "gh run list: not JSON"
    if not isinstance(data, list):
        return None, "gh run list: not a list"
    runs = []
    for r in data:
        if not isinstance(r, dict) or r.get("databaseId") in (None, ""):
            continue
        runs.append({"id": str(r["databaseId"]), "status": str(r.get("status") or ""),
                     "conclusion": str(r.get("conclusion") or ""), "url": str(r.get("url") or ""),
                     "createdAt": str(r.get("createdAt") or ""), "event": str(r.get("event") or "")})
    runs.sort(key=lambda r: (r["createdAt"], int(r["id"]) if r["id"].isdigit() else 0),
              reverse=True)
    return runs, ""


def _download(cfg: dict, run_id: str, artifact: str, name: str) -> dict | None:
    """One `gh run download` of one artifact; its JSON file, else None. The
    artifact is data: only `json.loads` reads it."""
    with tempfile.TemporaryDirectory(prefix="pyauto-sweep-") as d:
        rc, _out, _err = _call(["gh", "run", "download", str(run_id), "-R", cfg["repo"],
                                "-n", artifact, "-D", d], timeout=120)
        if rc != 0:
            return None
        try:
            data = json.loads((Path(d) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def compare_prs(cfg: dict, repo: str, base: str, head: str) -> list[int] | None:
    """The PR numbers merged in `base...head` of `<owner>/<repo>` (the sweep
    repo's owner): "Merge pull request #N" first lines and squash "(#N)"
    suffixes. None when GitHub could not say."""
    owner = cfg["repo"].split("/", 1)[0]
    rc, out, _err = _call(["gh", "api", f"repos/{owner}/{repo}/compare/{base}...{head}",
                           "--jq", "[.commits[].commit.message]"], timeout=60)
    if rc != 0:
        return None
    try:
        msgs = json.loads(out or "")
    except ValueError:
        return None
    if not isinstance(msgs, list):
        return None
    prs: list[int] = []
    for msg in msgs:
        first = str(msg or "").split("\n", 1)[0].strip()
        m = _MERGE_RE.match(first) or _SQUASH_RE.search(first)
        if m and int(m.group(1)) not in prs:
            prs.append(int(m.group(1)))
    return prs


# --- state under <home>/sweep -----------------------------------------------------------

def sweep_dir(home: Path) -> Path:
    return Path(home) / SWEEP_DIR


def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def load_state(home: Path) -> dict:
    return _read(sweep_dir(home) / STATE_FILE)


def run_record(home: Path, run_id: str) -> dict:
    return _read(sweep_dir(home) / "runs" / f"{run_id}.json")


def _report_of(data: dict) -> dict:
    """The failing scripts and projects of a `report.json` (PyAutoHands'
    aggregate, read the way Heart's test_run leg reads it: `failures` entries
    with `project`, `directory`, `file`, `status`; `per_project` counts)."""
    failing, projects = [], []
    for e in data.get("failures") or []:
        if not isinstance(e, dict):
            continue
        path = str(e.get("file") or "")
        directory = str(e.get("directory") or "").strip("/")
        name = path.rsplit("/", 1)[-1]
        proj = str(e.get("project") or "")
        failing.append({"project": proj, "status": str(e.get("status") or ""),
                        "script": f"{directory}/{name}" if directory else path.lstrip("/")})
        if proj and proj not in projects:
            projects.append(proj)
    per = data.get("per_project") or {}
    if isinstance(per, dict):
        for proj, s in per.items():
            if isinstance(s, dict) and (int(s.get("failed") or 0) or int(s.get("timeout") or 0)) \
                    and proj not in projects:
                projects.append(str(proj))
    return {"failing": failing, "projects": projects, "ready": data.get("ready")}


def _fetch(home: Path, cfg: dict, run: dict, red: bool) -> dict:
    """The run's artifacts, each downloaded once per run id (at most
    DOWNLOAD_TRIES tries ever), kept in `<home>/sweep/runs/<id>.json`."""
    path = sweep_dir(home) / "runs" / f"{run['id']}.json"
    rec = _read(path) or {"id": run["id"]}
    rec.update(url=run["url"], conclusion=run["conclusion"], createdAt=run["createdAt"])
    wants = [("shas", SHAS_ARTIFACT, SHAS_FILE)]
    if red:
        wants.append(("report", REPORT_ARTIFACT, REPORT_FILE))
    for key, artifact, name in wants:
        tries = int(rec.get(f"{key}_tries") or 0)
        if rec.get(key) is not None or tries >= DOWNLOAD_TRIES:
            continue
        rec[f"{key}_tries"] = tries + 1
        data = _download(cfg, run["id"], artifact, name)
        if data is not None:
            rec[key] = data if key == "shas" else _report_of(data)
    _write(path, rec)
    return rec


def settled(rec: dict, red: bool) -> bool:
    """Whether every artifact of a run is read, or its tries are spent."""
    keys = ("shas", "report") if red else ("shas",)
    return all(rec.get(k) is not None or int(rec.get(f"{k}_tries") or 0) >= DOWNLOAD_TRIES
               for k in keys)


def is_red(run: dict | None) -> bool:
    return bool(run) and run.get("status") == "completed" and run.get("conclusion") in RED


def observe(home: Path, cfg: dict, now: _dt.datetime) -> dict:
    """The tick's one read of the sweep (once a tick: `read_at`). Returns the
    state; a failed list keeps the last known runs, with the error noted."""
    state = load_state(home)
    if not cfg or state.get("read_at") == _iso(now):
        return state
    state["read_at"] = _iso(now)
    runs, why = list_runs(cfg)
    if runs is None:
        state.update(ok=False, error=why)
        _write(sweep_dir(home) / STATE_FILE, state)
        return state
    state.update(ok=True, error="", runs=runs)
    done = [r for r in runs if r["status"] == "completed"]
    state["latest"] = done[0] if done else state.get("latest")
    state["running"] = [r for r in runs if r["status"] != "completed"]
    greens = [r for r in done if r["conclusion"] == "success"]
    old = state.get("last_green") or {}
    if greens and greens[0]["createdAt"] >= str(old.get("createdAt") or ""):
        state["last_green"] = greens[0]
    latest = state.get("latest")
    if latest:
        _fetch(home, cfg, latest, is_red(latest))
    green = state.get("last_green")
    if green and (not latest or green["id"] != latest["id"]):
        _fetch(home, cfg, green, False)
    _write(sweep_dir(home) / STATE_FILE, state)
    return state


# --- the block ---------------------------------------------------------------------------

def cleared(home: Path) -> dict:
    return _read(sweep_dir(home) / CLEARED_FILE)


def red_run(home: Path, state: dict | None = None) -> dict | None:
    """The latest completed run, when it is red and not cleared."""
    latest = (state if state is not None else load_state(home)).get("latest")
    if not is_red(latest) or latest["id"] in cleared(home):
        return None
    return latest


def _repos_for(project: str, hmap: dict, cfg: dict) -> list[str] | None:
    """The install chain plus the workspace repo of one failing cloud project,
    or None when the name cannot be mapped."""
    chains, dirs = hmap.get("chains") or {}, hmap.get("dirs") or {}
    own = (hmap.get("projects") or {}).get(project) or dirs.get(project)
    if project in chains:
        return list(chains[project]) + ([own] if own else [])
    sib = (cfg.get("siblings") or {}).get(project)
    if sib and sib in chains and own:
        return list(chains[sib]) + [own]
    return None


def block(home: Path, cfg: dict, hmap: dict, key, state: dict | None = None) -> dict | None:
    """The red block, or None: {run_id, url, repos (as Heart writes them),
    keys (canonical keys, `key`), all_libraries, projects}. A failing project
    that cannot be mapped, or a report that cannot be read, blocks every
    library repo (fail closed)."""
    run = red_run(home, state)
    if run is None:
        return None
    rec = run_record(home, run["id"])
    report = rec.get("report")
    projects = list((report or {}).get("projects") or [])
    repos: list[str] = []
    unknown = not projects
    for p in projects:
        got = _repos_for(p, hmap, cfg)
        if got is None:
            unknown = True
            continue
        repos += [r for r in got if r not in repos]
    return {"run_id": run["id"], "url": run["url"], "repos": repos,
            "keys": sorted({key(r) for r in repos}), "all_libraries": unknown,
            "projects": projects, "why": RED_WHY.format(url=run["url"])}


def blocks(blk: dict | None, repo: str, key, is_library) -> bool:
    """Whether a PR on `repo` (its GitHub name) is blocked by `blk`."""
    if not blk or not repo:
        return False
    if blk.get("all_libraries") and is_library(repo):
        return True
    return key(repo) in set(blk.get("keys") or [])


def clear(home: Path, who: str, at: str, state: dict | None = None) -> str:
    """`/clear-sweep`: clear the block for the latest red run id only."""
    state = state if state is not None else load_state(home)
    run = red_run(home, state)
    if run is None:
        latest = state.get("latest")
        if is_red(latest):
            return (f"nothing to clear: the red sweep {latest['url']} is already cleared")
        return "nothing to clear: no red workspace sweep blocks merges"
    data = cleared(home)
    data[run["id"]] = {"url": run["url"], "by": who, "at": at}
    _write(sweep_dir(home) / CLEARED_FILE, data)
    return (f"cleared: workspace sweep red {run['url']} no longer blocks unattended merges; "
            "a newer red sweep blocks again")


# --- the bug draft -----------------------------------------------------------------------

def _order(hmap: dict) -> dict[str, int]:
    """Upstream first: each repo's earliest place in any install chain."""
    out: dict[str, int] = {}
    for chain in (hmap.get("chains") or {}).values():
        for i, r in enumerate(chain):
            out[r] = min(out.get(r, i), i)
    return out


def suspects(home: Path, cfg: dict, blk: dict, base: dict, head: dict) -> dict:
    """{repo: [PR numbers] | None} for each affected repo whose SHA moved from
    the last green run to the red one: one compare read per repo per red run,
    cached (None: unreadable)."""
    path = sweep_dir(home) / "compare" / f"{blk['run_id']}.json"
    cache = _read(path)
    moved = sorted(r for r in head if base.get(r) and head.get(r) and base[r] != head[r])
    wanted = set(blk.get("repos") or [])
    affected = [r for r in moved if blk.get("all_libraries") or r in wanted]
    for r in affected:
        if r in cache:
            continue
        cache[r] = compare_prs(cfg, r, base[r], head[r])
        _write(path, cache)
    return {r: cache.get(r) for r in affected}


def draft_text(cfg: dict, blk: dict, rec: dict, green: dict | None, prs: dict | None,
               target: str, repos: list[str], day: str) -> str:
    owner = cfg["repo"].split("/", 1)[0]
    report = rec.get("report")
    lines = [f"# Workspace sweep red on main: run {blk['run_id']}", "",
             "Type: bug", f"Target: {target}", "Repos:"]
    lines += [f"- {r}" for r in repos]
    lines += ["Difficulty: medium", "Autonomy: supervised", "Priority: high",
              "Status: draft", f"Filed: {day}",
              "Consequence: judge",
              "", "## Finding", "",
              f"The cloud workspace sweep (`{cfg['workflow']}` on `{cfg['repo']}`) concluded "
              f"`{rec.get('conclusion') or '?'}` on `main`: {blk['url']}", ""]
    if report is None:
        lines += ["Failing workspaces and scripts: unknown — the run's "
                  f"`{REPORT_ARTIFACT}` artifact could not be read.", ""]
    else:
        lines += ["Failing workspaces: " + (", ".join(f"`{p}`" for p in blk["projects"])
                                            or "none named in the report"), "",
                  "Failing scripts:"]
        lines += [f"- `{f['project']}`: `{f['script']}` ({f['status'] or '?'})"
                  for f in report.get("failing") or []] or ["- none named in the report"]
        lines += [""]
    lines += ["Unattended merges are blocked on: "
              + (ALL_LIBRARIES if blk["all_libraries"] else ", ".join(blk["repos"]))
              + ". A later green sweep on `main` clears the block, or `/clear-sweep` "
                "on a shift issue.", "", "## Suspect PRs", ""]
    if not green:
        lines += ["No green sweep on `main` is known to compare against: no suspects named."]
    elif prs is None:
        lines += ["The last green sweep's or this run's tested SHAs could not be read: "
                  "no suspects named."]
    else:
        lines += [f"Merged between the last green sweep ({green.get('url', '?')}) and this run:", ""]
        for repo, nums in prs.items():
            if nums is None:
                lines.append(f"- `{repo}`: compare unreadable — check its merges by hand")
            elif nums:
                lines.append(f"- `{repo}`: " + ", ".join(
                    f"[#{n}](https://github.com/{owner}/{repo}/pull/{n})" for n in nums))
            else:
                lines.append(f"- `{repo}`: moved, but no PR merge found in the compare")
        if not prs:
            lines.append("- no affected repo moved between the two runs")
    lines += ["", "## What to do", "",
              "Reverts are draft PRs opened for the human; nothing is reverted unattended. "
              "Bisect from a chat session: dispatch `workspace-smoke-pinned.yml` with its "
              "`commit_shas` input set to the SHAs to test (the red run's are in its "
              f"`{SHAS_ARTIFACT}` artifact).", ""]
    return "\n".join(lines)


def draft_path(blk: dict, prs: dict | None, hmap: dict, cfg: dict, key, is_library) -> str:
    """`draft/bug/<most-upstream suspect library repo's key>/…`; no suspect
    library: the sweep repo's key."""
    order = _order(hmap)
    sus = [r for r, nums in (prs or {}).items() if nums and is_library(r)]
    sus.sort(key=lambda r: order.get(r, 999))
    target = key(sus[0]) if sus else key(cfg["repo"].split("/", 1)[1])
    return f"draft/bug/{target}/workspace_sweep_red_{blk['run_id']}.md"


def file_draft(home: Path, cfg: dict, hmap: dict, blk: dict | None, ledger_dir: Path,
               now: _dt.datetime, key, is_library, queue_op) -> str | None:
    """One bug draft per red run id, ever: once its artifacts are settled,
    the compares are read (cached), the marker `<home>/sweep/drafted/<id>` is
    claimed exclusively, then one `write` op is queued for the one Mind
    writer. Returns the draft path when this call filed it."""
    if not blk:
        return None
    rec = run_record(home, blk["run_id"])
    if not settled(rec, True):
        return None
    marker = sweep_dir(home) / DRAFTED_DIR / str(blk["run_id"])
    if marker.exists():
        return None
    state = load_state(home)
    green = state.get("last_green")
    if green and green.get("id") == blk["run_id"]:
        green = None
    base = (run_record(home, green["id"]).get("shas") or {}).get("commit_shas") if green else None
    head = (rec.get("shas") or {}).get("commit_shas")
    prs = suspects(home, cfg, blk, base, head) \
        if isinstance(base, dict) and isinstance(head, dict) else None
    path = draft_path(blk, prs, hmap, cfg, key, is_library)
    sus = [r for r, nums in (prs or {}).items() if nums]
    repos = sus or [cfg["repo"].split("/", 1)[1]]
    text = draft_text(cfg, blk, rec, green, prs, path.split("/")[2], repos,
                      now.strftime("%Y-%m-%d"))
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w") as fh:
        fh.write(path + "\n")
    queue_op(ledger_dir, {"op": "write", "path": path, "text": text})
    return path


def drafted(home: Path, run_id: str) -> str:
    try:
        return (sweep_dir(home) / DRAFTED_DIR / str(run_id)).read_text().strip()
    except OSError:
        return ""


# --- what the digest reads ---------------------------------------------------------------

def own_run(state: dict, dispatched_at: str) -> dict | None:
    """The run the shift's own dispatch started: event `workflow_dispatch`,
    created at or after the dispatch (less DISPATCH_SLACK_S), the earliest."""
    at = _parse(dispatched_at)
    if at is None:
        return None
    floor = at - _dt.timedelta(seconds=DISPATCH_SLACK_S)
    mine = [r for r in state.get("runs") or []
            if r.get("event") == "workflow_dispatch" and (_parse(r.get("createdAt", "")) or at) >= floor]
    return min(mine, key=lambda r: r["createdAt"]) if mine else None


def snapshot(home: Path, cfg: dict, state: dict, blk: dict | None, key=None,
             is_library=None) -> dict:
    """What the digest says about the sweep, kept in `counters["sweep"]`."""
    out = {"read": {"ok": bool(state.get("ok")), "at": state.get("read_at", ""),
                    "error": state.get("error", "")},
           "repo": cfg.get("repo", ""), "runs": state.get("runs") or []}
    green = state.get("last_green")
    if green:
        shas = run_record(home, green["id"]).get("shas") or {}
        commit = shas.get("commit_shas") if isinstance(shas.get("commit_shas"), dict) else {}
        out["green"] = {"id": green["id"], "url": green["url"], "createdAt": green["createdAt"],
                        "full_sweep_run_id": str(shas.get("full_sweep_run_id") or ""),
                        "verified": {r: str(s)[:12] for r, s in sorted(commit.items())
                                     if is_library is None or is_library(r)}}
    latest = state.get("latest")
    if latest:
        out["latest"] = latest
        if is_red(latest) and latest["id"] in cleared(home):
            out["cleared"] = {"run_id": latest["id"], **cleared(home)[latest["id"]]}
    if blk:
        out["block"] = {**blk, "draft": drafted(home, blk["run_id"])}
    return out

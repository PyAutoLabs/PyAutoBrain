"""Maintenance finding adapters — Phase 14.1 (PyAutoBrain#731). Read-only.

One `Finding` shape over three sources of "something on main needs fixing":

- the no-run census (Heart's `no_run_census.json`, or the board's
  `performance.no_run`): a parked or slow workspace script;
- the Heart monitoring inventory (the board's `monitoring.findings`);
- the Heart release verdict, through `_green.classify` (one filing path —
  `_green` is reused, never changed).

Each finding carries a STABLE key, so two reads of the same board — or two
boards whose only difference is a smoke run id — give the same keys. That key
is what slice 14.2 will write into a prompt and dedupe against.

`batch maintain --dry-run` prints them. Nothing here writes: no prompt, no
state file, no Mind. It runs at brief and collect time only; the watcher's
tick never reads Heart and never calls this.

The adapters are pure functions of already-loaded data; the loaders read
local files first, else the published board, and say how old what they read is.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import _green

SOURCES = ("census", "monitoring", "release")
#: Local Heart evidence, the same default Heart and the profiling conductor use.
HEART_STATE_DIR = Path(os.environ.get("HEART_STATE_DIR", Path.home() / ".pyauto-heart"))
CENSUS_NAME = "no_run_census.json"
BOARD_TIMEOUT = 90  # seconds: board.json is several MB
MAX_AGE_HOURS = _green.MAX_AGE_HOURS

#: Monitoring families this lane never files. `worktree_drift` and `repo_state`
#: are local checkout state (human decision 4: Gut and /repo_cleanup own it);
#: `release` is the verdict the release adapter already reads (decision 3: one
#: filing path); `open_prs` are a human's /prm.
EXCLUDED_FAMILIES = frozenset({"worktree_drift", "repo_state", "release", "open_prs"})
#: Statuses that are a defect on main. `grey`/`stale` mean the evidence is
#: missing or old — a collector refresh, not a fix — so they are left out.
FILED_STATUSES = ("red", "yellow")
#: Families whose finding concerns a workflow file, a dependency cap or a
#: public name — always judge tier.
JUDGE_FAMILIES = frozenset({"required_workflow_drift", "version_skew", "version_skew_pypi",
                            "manifest_drift", "url_check"})

CENSUS_WITNESS = ("the entry is gone from the repo's no_run.yaml and the script passes "
                  "under the smoke cap")
MONITORING_WITNESS = "the key is absent, or green, on a fresh Heart board read"
RELEASE_WITNESS = "a fresh Heart verdict (under 6 h old) no longer lists the reason"

_CI = _green._CI
#: Organ CI-red lines `_green` matches with no rule (`ci-red-legacy` allows no
#: `/` in the workflow): `<Organ>/workflows/<name>: failure`.
ORGAN_CI_RX = re.compile(rf"^(?P<repo>[\w.-]+)/workflows/(?P<wf>.+?): {_CI}$")


@dataclasses.dataclass
class Finding:
    key: str
    source: str
    repo: str
    paths: list
    summary: str
    witness: str
    tier_floor: str
    lane: str
    evidence: dict

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def organ_repos() -> set:
    """The body map's `organ` repos (identity lives in one place)."""
    try:
        from _sizing import _body_map_categories
        return {n for n, c in _body_map_categories().items() if c == "organ"}
    except Exception:  # noqa: BLE001 — no body map: nothing counts as an organ
        return set()


def _ci_key(repo: str, wf: str = "") -> str:
    return f"ci:{repo}:{wf}" if wf else f"ci:{repo}"


# --- adapters (pure) ----------------------------------------------------------

def census_findings(census: dict) -> list[Finding]:
    """No-run census rows → findings keyed `no_run:<repo>/<entry>`.
    `permanent` rows are by design and never become findings."""
    out = []
    for row in (census or {}).get("rows") or []:
        if not isinstance(row, dict) or row.get("marker") not in ("SLOW", "NEEDS_FIX"):
            continue
        repo, entry = str(row.get("repo") or ""), str(row.get("entry") or "")
        if not repo or not entry:
            continue
        out.append(Finding(
            key=f"no_run:{repo}/{entry}", source="census", repo=repo,
            paths=[entry, "no_run.yaml"],
            summary=f"{row['marker']} since {row.get('date') or '?'}: "
                    f"{str(row.get('reason') or '').strip()}",
            witness=CENSUS_WITNESS, tier_floor="glance", lane="local-dev",
            evidence=dict(row)))
    return out


def monitoring_key(f: dict) -> str:
    """A monitoring finding's id with its run discriminator dropped.

    Heart builds `family:subject:discriminator` (heart/monitoring.py), where the
    discriminator is a `run_id` or `run_url` that changes every run — smoke
    timings above all. Census rows map to the census adapter's key and CI rows
    to `_green`'s `ci:` keys, so the same defect has one key whichever source
    reports it."""
    fid, fam, subj = str(f.get("id") or ""), str(f.get("family") or ""), str(f.get("subject") or "")
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    head = f"{fam}:{subj}"
    if fid.startswith(head + ":"):
        rest = fid[len(head) + 1:]
        drop = {str(ev.get(k)) for k in ("run_id", "run_url") if ev.get(k)}
        if not rest or rest in drop or rest.isdigit() or "://" in rest:
            fid = head
    if fam == "no_run_census" and fid == head:
        return f"no_run:{subj}"
    if fam == "ci_status" and fid == head:
        repo, _, wf = subj.partition("/workflows/")
        return _ci_key(repo, wf)
    return fid


def _repo_of(f: dict) -> str:
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    if ev.get("repo"):
        return str(ev["repo"])
    return re.split(r"[/:]", str(f.get("subject") or ""), maxsplit=1)[0]


def _tier(family: str, repo: str, subject: str, status: str, organs: set) -> str:
    """Conservative: glance only for an organ's own workflow red; judge for a
    workflow file, a dependency cap or a public name, and whenever unsure."""
    if family in JUDGE_FAMILIES:
        return "judge"
    if family == "ci_status" and status == "red" and repo in organs:
        return "glance"
    if family == "no_run_census":
        return "glance"
    return "judge"


def monitoring_findings(board: dict, organs=frozenset()) -> list[Finding]:
    """The board's `monitoring.findings` → findings, worktree drift and the
    other excluded families left out, roll-ups dropped."""
    rows = [f for f in ((board or {}).get("monitoring") or {}).get("findings") or []
            if isinstance(f, dict) and f.get("family") not in EXCLUDED_FAMILIES
            and f.get("status") in FILED_STATUSES]
    # Roll-ups: a family `:coverage` row, and a repo-level CI row when a
    # workflow-level row of the same repo is listed.
    wf_repos = {str(f.get("subject")).split("/workflows/")[0] for f in rows
                if f.get("family") == "ci_status" and "/workflows/" in str(f.get("subject"))}
    out = []
    for f in rows:
        fam, subj, fid = f["family"], str(f.get("subject") or ""), str(f.get("id") or "")
        if fid.endswith(":coverage") or monitoring_key(f).endswith(":coverage"):
            continue
        if fam == "ci_status" and subj in wf_repos:
            continue
        repo = _repo_of(f)
        ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
        path = subj[len(repo) + 1:] if subj.startswith(repo + "/") else ""
        out.append(Finding(
            key=monitoring_key(f), source="monitoring", repo=repo,
            paths=[path] if path else [],
            summary=f"[{f['status']}] {fam}: {subj} — {str(f.get('summary') or '').strip()}"[:240],
            witness=MONITORING_WITNESS,
            tier_floor=_tier(fam, repo, subj, f["status"], set(organs)),
            lane="any" if fam == "ci_status" else "local-dev",
            evidence={"id": fid, "family": fam, "status": f["status"],
                      "observed_at": f.get("observed_at"), "source": f.get("source"),
                      "detail": ev}))
    return out


def release_findings(heart: dict, organs=frozenset()) -> list[Finding]:
    """Heart's release verdict through `_green.classify`: its fixable-dev
    findings (the same filter `_green.run` files from), plus the organ
    CI-red lines no `_green` rule matches."""
    out = []
    for reason in (heart or {}).get("reasons") or []:
        if reason.get("severity") == "stale":
            continue
        m = ORGAN_CI_RX.match(str(reason.get("text") or ""))
        classified = _green.classify(reason)
        if m and all(c["rule"] == "unmatched" for c in classified):
            repo = reason.get("repo") or m["repo"]
            classified = [dict(reason, rule="organ-ci-red", cls="fixable-dev",
                               key=_ci_key(m["repo"], m["wf"].strip()), lane="any",
                               repo=repo, action="fix the red workflow on main")]
        for c in classified:
            if c["cls"] != "fixable-dev" or not c.get("key"):
                continue
            repo = c.get("repo") or ""
            organ_ci = c["key"].startswith("ci:") and repo in set(organs)
            out.append(Finding(
                key=c["key"], source="release", repo=repo,
                paths=[c["script"]] if c.get("script") else [],
                summary=f"[{c['severity']}] {c['text']}"[:240], witness=RELEASE_WITNESS,
                tier_floor="glance" if organ_ci else "judge",
                lane=c.get("lane") or "local-dev",
                evidence={"rule": c["rule"], "severity": c["severity"], "text": c["text"],
                          "action": c.get("action", "")}))
    return out


def dedupe(findings) -> list[Finding]:
    """One finding per key; the earlier source wins (callers pass census
    first — its record is the richest)."""
    seen, out = set(), []
    for f in findings:
        if f.key in seen:
            continue
        seen.add(f.key)
        out.append(f)
    return out


def collect(census=None, board=None, heart=None, sources=SOURCES,
            organs=frozenset()) -> list[Finding]:
    found = []
    if "census" in sources and census is not None:
        found += census_findings(census)
    if "monitoring" in sources and board is not None:
        found += monitoring_findings(board, organs)
    if "release" in sources and heart is not None:
        found += release_findings(heart, organs)
    return dedupe(found)


# --- loaders (read-only) ------------------------------------------------------

def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return None, f"{path} unreadable ({str(exc)[:80]})"


def board_url():
    """(url, why): the published board.json beside the Heart feed's state.json."""
    url, why = _green._hf().feed_url()
    return (url.rsplit("/", 1)[0] + "/board.json", "") if url else (None, why)


def fetch_board(url: str, timeout=BOARD_TIMEOUT):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
        obj = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return None, f"board.json unreachable ({str(exc)[:80]})"
    return (obj, "") if isinstance(obj, dict) else (None, "board.json is not an object")


def load_board(board_json: str = "", now=None) -> dict:
    """{data, source, why, age_hours} — a saved board, else the published one."""
    if board_json:
        data, why = _read_json(Path(board_json))
        source = f"file {board_json}"
    else:
        url, why = board_url()
        data, why = fetch_board(url) if url else (None, why)
        source = "published board"
    if not isinstance(data, dict):
        return {"data": None, "source": "none", "why": why, "age_hours": None}
    return {"data": data, "source": source, "why": "",
            "age_hours": _green._hf().age_hours(data.get("ts"), now)}


def load_census(census_json: str = "", board: dict | None = None, now=None) -> dict:
    """{data, source, why, age_hours} — Heart's local census (all rows) first;
    the board's `performance.no_run` (capped at 10 rows) when the local file is
    absent, or older than the board."""
    hf = _green._hf()
    path = Path(census_json) if census_json else HEART_STATE_DIR / CENSUS_NAME
    data, why = _read_json(path)
    age = hf.age_hours(data.get("ts"), now) if isinstance(data, dict) else None
    bage = hf.age_hours((board or {}).get("ts"), now)
    published = ((board or {}).get("performance") or {}).get("no_run")
    if not census_json and isinstance(published, dict) and (
            not isinstance(data, dict)
            or (bage is not None and (age is None or bage < age))):
        return {"data": published, "source": "published board performance.no_run",
                "why": why, "age_hours": bage}
    if not isinstance(data, dict):
        return {"data": None, "source": "none", "why": why, "age_hours": None}
    return {"data": data, "source": f"local {path.name}", "why": "", "age_hours": age}


# --- CLI ----------------------------------------------------------------------

def _age(h):
    if h is None:
        return "age unknown"
    stale = " — STALE, re-check" if h > MAX_AGE_HOURS else ""
    return f"{h:.1f} h old{stale}"


def render(findings, reads) -> str:
    L = ["batch maintain --dry-run — maintenance findings (read-only; writing is slice 14.2)", ""]
    for name, r in reads.items():
        L.append(f"  {name:<10} {r['source']}"
                 + (f" ({_age(r.get('age_hours'))})" if r.get("source") != "none" else
                    f" — {r.get('why')}"))
    L += ["", f"{len(findings)} finding(s)", ""]
    rows = [("KEY", "SOURCE", "REPO", "TIER", "SUMMARY")] + [
        (f.key, f.source, f.repo, f.tier_floor, f.summary) for f in findings]
    w = [min(max(len(r[i]) for r in rows), cap) for i, cap in enumerate((70, 10, 26, 6))]
    for r in rows:
        cells = [r[i][:w[i]].ljust(w[i]) for i in range(4)]
        L.append("  ".join(cells) + "  " + r[4][:110])
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="batch maintain",
        description="List maintenance findings from the no-run census, Heart's "
                    "monitoring inventory and its release verdict (read-only).")
    ap.add_argument("--dry-run", action="store_true",
                    help="required: list findings, write nothing")
    ap.add_argument("--sources", default=",".join(SOURCES),
                    help=f"comma-separated subset of {','.join(SOURCES)}")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--board-json", default="", metavar="FILE",
                    help="read this saved Heart board.json instead of the published one")
    ap.add_argument("--census-json", default="", metavar="FILE",
                    help="read this saved no_run_census.json instead of Heart's local one")
    ap.add_argument("--heart-json", default="", metavar="FILE",
                    help="read this saved `readiness --json` / state.json instead of Heart")
    ap.add_argument("--at", default="", help="judge ages as of this ISO time (a replay)")
    a = ap.parse_args(argv)
    if not a.dry_run:
        print("batch maintain: only --dry-run exists — writing is slice 14.2",
              file=sys.stderr)
        return 2
    sources = [s.strip() for s in a.sources.split(",") if s.strip()]
    bad = [s for s in sources if s not in SOURCES]
    if bad or not sources:
        print(f"batch maintain: --sources {a.sources!r} — a subset of {','.join(SOURCES)}",
              file=sys.stderr)
        return 2
    now = None
    if a.at:
        now = _dt.datetime.fromisoformat(a.at.replace("Z", "+00:00"))
        now = now if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    reads = {}
    board = None
    if "monitoring" in sources or ("census" in sources and not a.census_json):
        reads["board"] = load_board(a.board_json, now)
        board = reads["board"]["data"]
    census = heart = None
    if "census" in sources:
        reads["census"] = load_census(a.census_json, board, now)
        census = reads["census"]["data"]
    if "release" in sources:
        h = _green.read_heart(a.heart_json, now=now)
        reads["release"] = {"source": h.get("source", "none"), "why": h.get("why", ""),
                            "age_hours": h.get("age_hours")}
        heart = h if h.get("source") != "none" else None
    found = collect(census=census, board=board if "monitoring" in sources else None,
                    heart=heart, sources=sources, organs=organ_repos())
    if a.as_json:
        print(json.dumps({"dry_run": True, "sources": sources,
                          "reads": {k: {kk: v for kk, v in r.items() if kk != "data"}
                                    for k, r in reads.items()},
                          "count": len(found),
                          "findings": [f.as_dict() for f in found]}, indent=2, default=str))
    else:
        sys.stdout.write(render(found, reads))
    return 0

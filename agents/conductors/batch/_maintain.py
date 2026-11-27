"""Maintenance finding adapters — Phase 14.1 (PyAutoBrain#731). Read-only.

One `Finding` shape over three sources of "something on main needs fixing":

- the no-run census (Heart's `no_run_census.json`, the board's
  `performance.no_run`, and the board's `no_run_census` monitoring rows — all
  one source, one key shape): a parked or slow workspace script;
- the Heart monitoring inventory (the board's `monitoring.findings`);
- the Heart release verdict, through `_green.classify` (one filing path —
  `_green` is reused, never changed).

Each finding carries a STABLE key, so two reads of the same board — or two
boards whose only difference is a run id — give the same keys, and the same
defect has one key whichever source reports it. That key is what slice 14.2
will write into a prompt and dedupe against.

`batch maintain --dry-run` prints them. It is run by hand (and later by the
14.2/14.3 filing steps); the watcher's tick never reads Heart and never calls
this. Nothing here writes: no prompt, no state file, no Mind.

A read that failed never looks like all-clear: every requested source reports
`ok`, `stale` and `partial`, and the CLI exits 3 when any requested source was
not read. 14.2 must never file from, or clear keys for, an unread or stale
source, and never clear keys from a partial one.

The adapters are pure functions of already-loaded data; the loaders read
local files first, else the published board, and say how old what they read is.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import gzip
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import _green

SOURCES = ("census", "monitoring", "release")
#: Local Heart evidence, the same default Heart and the profiling conductor use.
HEART_STATE_DIR = Path(os.environ.get("HEART_STATE_DIR", Path.home() / ".pyauto-heart"))
CENSUS_NAME = "no_run_census.json"
BOARD_TIMEOUT = 90  # seconds: board.json is several MB
MAX_AGE_HOURS = _green.MAX_AGE_HOURS
RC_UNREAD = 3

#: Timing families: slice 14.5 (Heart-flagged rows only), not this slice.
TIMING_FAMILIES = frozenset({"smoke_timings", "unit_test_timing", "ci_timing",
                             "script_timing", "import_time", "workspace_testmode_timing"})
#: Monitoring families this adapter never lists. `worktree_drift` and
#: `repo_state` are local checkout state (human decision 4: Gut and
#: /repo_cleanup own it); `release` is the verdict the release adapter reads
#: (decision 3: one filing path); `open_prs` are a human's /prm; the census
#: rows go through the census adapter (one key shape).
EXCLUDED_FAMILIES = frozenset({"worktree_drift", "repo_state", "release", "open_prs",
                               "no_run_census"}) | TIMING_FAMILIES
#: Statuses that are a defect on main. `grey`/`stale` mean the evidence is
#: missing or old — a collector refresh, not a fix — so they are left out.
FILED_STATUSES = ("red", "yellow")
#: A release-execution workflow is never a glance fix.
RELEASE_WORKFLOW_RX = re.compile(r"release", re.I)
#: Words in a census reason that force judge whatever the evidence says.
KILLED_RX = re.compile(r"\bOOM\b|SIGKILL|\bkilled\b|timed?[\s-]*out|times out", re.I)
PY_SUFFIX_RX = re.compile(r"/\d+\.\d+$")

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
    stale: bool = False

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def glance_organs() -> set:
    """Organs whose own workflow red may be a glance fix: the body map's
    `organ` repos, minus those shipping a package (`package:`), the Brain
    itself (`organ: Brain`) and the readiness oracle this lane reads (the
    policy's `board: heart_board`, the same declared surface `heart_feed.py`
    reads) — a change there reaches users, this lane or its evidence."""
    try:
        from _sizing import _body_map_specs
        oracle = _green._hf().heart_board_repo()
        return {n for n, s in _body_map_specs().items()
                if s.get("category") == "organ" and not s.get("package")
                and s.get("organ") != "Brain" and n != oracle}
    except Exception:  # noqa: BLE001 — no body map: nothing is glance
        return set()


def _ci_key(repo: str, wf: str = "") -> str:
    repo, wf = str(repo).strip(), str(wf or "").strip()
    return f"ci:{repo}:{wf}" if wf else f"ci:{repo}"


def _norm_ci(key: str) -> str:
    """Every `ci:` key through `_ci_key` (whitespace stripped)."""
    if not key.startswith("ci:"):
        return key
    repo, _, wf = key[3:].partition(":")
    return _ci_key(repo, wf)


# --- adapters (pure) ----------------------------------------------------------

def _census_tier(row: dict) -> str:
    """Glance only for a real marker removal, proven by STRUCTURED evidence:
    a SLOW row with `passed: true` and a numeric `seconds`/`measured_s` within
    a numeric `cap_s`. Free text is never parsed for seconds; NEEDS_FIX is
    never glance; a reason naming a kill or a timeout forces judge."""
    if row.get("marker") != "SLOW" or KILLED_RX.search(str(row.get("reason") or "")):
        return "judge"
    secs = row.get("seconds", row.get("measured_s"))
    cap = row.get("cap_s")
    num = (int, float)
    if row.get("passed") is True and isinstance(secs, num) and isinstance(cap, num) \
            and not isinstance(secs, bool) and not isinstance(cap, bool) and secs <= cap:
        return "glance"
    return "judge"


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
            witness=CENSUS_WITNESS, tier_floor=_census_tier(row), lane="local-dev",
            evidence=dict(row)))
    return out


def board_census_rows(board: dict) -> list[dict]:
    """The board's census rows: `performance.no_run.rows` (capped) plus every
    `no_run_census` monitoring finding's evidence (uncapped)."""
    rows = [dict(r) for r in (((board or {}).get("performance") or {}).get("no_run") or {})
            .get("rows") or [] if isinstance(r, dict)]
    for f in ((board or {}).get("monitoring") or {}).get("findings") or []:
        if isinstance(f, dict) and f.get("family") == "no_run_census" \
                and f.get("status") in FILED_STATUSES and isinstance(f.get("evidence"), dict):
            row = dict(f["evidence"])
            if not row.get("repo"):
                subj = str(f.get("subject") or "")
                ent = str(row.get("entry") or "")
                row["repo"] = subj[:-len(ent) - 1] if ent and subj.endswith("/" + ent) \
                    else subj.split("/", 1)[0]
            rows.append(row)
    return rows


def monitoring_key(f: dict) -> str:
    """A monitoring finding's id with its run discriminator dropped.

    Heart builds `family:subject:discriminator` (heart/monitoring.py), where the
    discriminator is a `run_id` or `run_url` that changes every run. Timing
    subjects lose a trailing `/<py-version>`. CI rows map to `_green`'s `ci:`
    keys (an un-namespaced `<repo>:ci` too), census rows to `no_run:`."""
    fid, fam, subj = str(f.get("id") or ""), str(f.get("family") or ""), str(f.get("subject") or "")
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    head = f"{fam}:{subj}"
    if fid.startswith(head + ":"):
        rest = fid[len(head) + 1:]
        drop = {str(ev.get(k)) for k in ("run_id", "run_url") if ev.get(k)}
        if not rest or rest in drop or rest.isdigit() or "://" in rest:
            fid = head
    if fam in TIMING_FAMILIES and fid == head:
        return f"{fam}:{PY_SUFFIX_RX.sub('', subj)}"
    if fam == "no_run_census" and fid == head:
        return f"no_run:{subj}"
    if fam == "ci_status" and fid == f"{subj}:ci":
        return _ci_key(subj)
    if fam == "ci_status" and fid == head:
        repo, _, wf = subj.partition("/workflows/")
        return _ci_key(repo, wf)
    return fid


def _repo_of(f: dict) -> str:
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    if ev.get("repo"):
        return str(ev["repo"])
    return re.split(r"[/:]", str(f.get("subject") or ""), maxsplit=1)[0]


def _organ_ci_tier(repo: str, wf: str, on_head, organs) -> str:
    """Glance only for an organ's own workflow red that is on its head commit
    and is not a release-execution workflow; judge otherwise."""
    if repo in set(organs) and on_head is True and not RELEASE_WORKFLOW_RX.search(wf or ""):
        return "glance"
    return "judge"


def monitoring_findings(board: dict, organs=frozenset()) -> list[Finding]:
    """The board's `monitoring.findings` → findings: excluded families, grey
    and stale rows, and roll-ups left out. `organs` are the glance-eligible
    organs (`glance_organs`)."""
    rows = [f for f in ((board or {}).get("monitoring") or {}).get("findings") or []
            if isinstance(f, dict) and f.get("family") not in EXCLUDED_FAMILIES
            and f.get("status") in FILED_STATUSES]
    out = []
    for f in rows:
        fam, subj, fid = f["family"], str(f.get("subject") or ""), str(f.get("id") or "")
        key = monitoring_key(f)
        if fid.endswith(":coverage") or key.endswith(":coverage"):
            continue
        repo = _repo_of(f)
        ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
        path = subj[len(repo) + 1:] if subj.startswith(repo + "/") else ""
        if fam == "ci_status":
            wf = subj.partition("/workflows/")[2]
            tier = _organ_ci_tier(repo, wf, ev.get("on_head"), organs) if wf else "judge"
        else:
            tier = "judge"
        out.append(Finding(
            key=key, source="monitoring", repo=repo,
            paths=[path] if path else [],
            summary=f"[{f['status']}] {fam}: {subj} — {str(f.get('summary') or '').strip()}"[:240],
            witness=MONITORING_WITNESS, tier_floor=tier,
            lane="any" if fam == "ci_status" else "local-dev",
            evidence={"id": fid, "family": fam, "status": f["status"],
                      "observed_at": f.get("observed_at"), "source": f.get("source"),
                      "fresh": f.get("fresh"), "detail": ev},
            stale=f.get("fresh") is False))
    return out


def release_findings(heart: dict, organs=frozenset()) -> list[Finding]:
    """Heart's release verdict through `_green.classify`: its fixable-dev
    findings (the same filter `_green.run` files from), plus the organ
    CI-red lines no `_green` rule matches. The verdict carries no `on_head`
    evidence, so an organ CI red from here is judge (the monitoring row, read
    first, carries it)."""
    out = []
    for reason in (heart or {}).get("reasons") or []:
        if reason.get("severity") == "stale":
            continue
        m = ORGAN_CI_RX.match(str(reason.get("text") or ""))
        classified = _green.classify(reason)
        if m and all(c["rule"] == "unmatched" for c in classified):
            repo = reason.get("repo") or m["repo"]
            classified = [dict(reason, rule="organ-ci-red", cls="fixable-dev",
                               key=_ci_key(m["repo"], m["wf"]), lane="any",
                               repo=repo, action="fix the red workflow on main")]
        for c in classified:
            if c["cls"] != "fixable-dev" or not c.get("key"):
                continue
            repo = c.get("repo") or ""
            key = _norm_ci(c["key"])
            wf = key[3:].partition(":")[2] if key.startswith("ci:") else ""
            tier = (_organ_ci_tier(repo, wf, None, organs) if key.startswith("ci:")
                    else "judge")
            out.append(Finding(
                key=key, source="release", repo=repo,
                paths=[c["script"]] if c.get("script") else [],
                summary=f"[{c['severity']}] {c['text']}"[:240], witness=RELEASE_WITNESS,
                tier_floor=tier, lane=c.get("lane") or "local-dev",
                evidence={"rule": c["rule"], "severity": c["severity"], "text": c["text"],
                          "action": c.get("action", "")}))
    return out


def dedupe(findings) -> list[Finding]:
    """One finding per key; the earlier source wins (census, then monitoring,
    then release). A repo-level `ci:<repo>` gives way to any `ci:<repo>:*`."""
    seen, out = set(), []
    for f in findings:
        if f.key in seen:
            continue
        seen.add(f.key)
        out.append(f)
    wf_repos = {f.key.split(":")[1] for f in out
                if f.key.startswith("ci:") and f.key.count(":") >= 2}
    return [f for f in out if not (f.key.startswith("ci:") and f.key.count(":") == 1
                                   and f.key[3:] in wf_repos)]


def collect(census=None, board=None, heart=None, sources=SOURCES,
            organs=frozenset(), stale_sources=()) -> list[Finding]:
    """All requested sources, deduped. A finding from a source in
    `stale_sources` (over the 6 h rule, or a grey/stale verdict) is flagged
    `stale`, as is a monitoring row Heart itself marks `fresh: false`."""
    found = []
    if "census" in sources:
        # One whole source (the loader picks it): the census document given,
        # else the board's census rows. Never a merge of the two.
        rows = (census or {}).get("rows") if census is not None else \
            board_census_rows(board) if board is not None else []
        found += census_findings({"rows": rows or []})
    if "monitoring" in sources and board is not None:
        found += monitoring_findings(board, organs)
    if "release" in sources and heart is not None:
        found += release_findings(heart, organs)
    out = dedupe(found)
    for f in out:
        if f.source in stale_sources:
            f.stale = True
    return out


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
    except (urllib.error.URLError, http.client.HTTPException, EOFError, zlib.error,
            gzip.BadGzipFile, ValueError, OSError) as exc:
        return None, f"board.json unreachable ({exc.__class__.__name__}: {str(exc)[:80]})"
    return (obj, "") if isinstance(obj, dict) else (None, "board.json is not an object")


def _read(data, source, why, age, status=None, partial=False) -> dict:
    ok = isinstance(data, dict) and status != "grey"
    stale = (not ok) or age is None or age > MAX_AGE_HOURS or status == "stale"
    return {"data": data if isinstance(data, dict) else None,
            "source": source if isinstance(data, dict) else "none",
            "why": why, "age_hours": age, "ok": ok, "stale": stale, "partial": partial,
            **({"status": status} if status is not None else {})}


def load_board(board_json: str = "", now=None) -> dict:
    """{data, source, why, age_hours, ok, stale} — a saved board, else the
    published one."""
    if board_json:
        data, why = _read_json(Path(board_json))
        source = f"file {board_json}"
    else:
        url, why = board_url()
        data, why = fetch_board(url) if url else (None, why)
        source = "published board"
    age = _green._hf().age_hours(data.get("ts"), now) if isinstance(data, dict) else None
    return _read(data, source, why, age)


def load_census(census_json: str = "", board_read: dict | None = None, now=None) -> dict:
    """ONE whole census source, the fresher of two: Heart's local
    `no_run_census.json`, or the board's census rows (its `no_run_census`
    monitoring rows are the complete set; `performance.no_run` is a capped
    subset of them). Never a merge: a stale local file must not resurrect
    entries the board has since dropped. The read's age is that source's.

    With the board unreadable and only the local file read, the read is
    `partial` and its `why` carries the board's failure; 14.2 must not clear
    keys from a stale or partial read."""
    path = Path(census_json) if census_json else HEART_STATE_DIR / CENSUS_NAME
    local, lwhy = _read_json(path)
    local = local if isinstance(local, dict) else None
    lage = _green._hf().age_hours(local.get("ts"), now) if local else None
    br = board_read or {}
    board = br.get("data") if br.get("ok") else None
    bage = br.get("age_hours")
    if board is not None and (local is None or (bage is not None
                                                and (lage is None or bage < lage))):
        return _read({"ts": board.get("ts"), "rows": board_census_rows(board)},
                     "board census rows", "", bage)
    if local is not None:
        partial = board is None
        why = (f"board census rows not read ({br.get('why') or 'board unread'})"
               if partial else "")
        return _read(local, f"local {path.name}", why, lage, partial=partial)
    return _read(None, "none", "; ".join(x for x in (lwhy, br.get("why")) if x), None)


def load_release(heart_json: str = "", now=None) -> dict:
    h = _green.read_heart(heart_json, now=now)
    data = h if h.get("source") != "none" else None
    return _read(data, h.get("source", "none"), h.get("why") or "", h.get("age_hours"),
                 status=str(h.get("status") or "grey").lower())


# --- CLI ----------------------------------------------------------------------

def _read_line(name, r) -> str:
    if not r["ok"]:
        return (f"  {name:<10} UNREAD — {r.get('why') or r.get('status') or 'no data'}"
                f" (findings from it are not all-clear)")
    age = "age unknown" if r.get("age_hours") is None else f"{r['age_hours']:.1f} h old"
    status = f", verdict {r['status']}" if r.get("status") else ""
    flag = " — STALE: listed, never filed or cleared" if r["stale"] else ""
    if r.get("partial"):
        flag += f" — PARTIAL ({r.get('why')}): never clear keys from it"
    return f"  {name:<10} {r['source']} ({age}{status}){flag}"


def render(findings, reads) -> str:
    L = ["batch maintain --dry-run — maintenance findings (read-only; writing is slice 14.2)", ""]
    L += [_read_line(name, r) for name, r in reads.items()]
    L += ["", f"{len(findings)} finding(s)", ""]
    rows = [("KEY", "SOURCE", "REPO", "TIER", "SUMMARY")] + [
        (f.key, f.source, f.repo, f.tier_floor + ("*" if f.stale else ""), f.summary)
        for f in findings]
    w = [min(max(len(r[i]) for r in rows), cap) for i, cap in enumerate((70, 10, 26, 7))]
    for r in rows:
        cells = [r[i][:w[i]].ljust(w[i]) for i in range(4)]
        L.append("  ".join(cells) + "  " + r[4][:110])
    if any(f.stale for f in findings):
        L += ["", "* stale: from a stale read or a row Heart marks not fresh"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="batch maintain",
        description="List maintenance findings from the no-run census, Heart's "
                    "monitoring inventory and its release verdict (read-only). "
                    "Exit 3 when a requested source could not be read.")
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
    board_read = None
    if "monitoring" in sources or "census" in sources:
        board_read = load_board(a.board_json, now)
    if "census" in sources:
        reads["census"] = load_census(a.census_json, board_read, now)
    if "monitoring" in sources:
        reads["monitoring"] = board_read
    if "release" in sources:
        reads["release"] = load_release(a.heart_json, now)
    stale = {s for s, r in reads.items() if r["stale"]}
    found = collect(census=(reads.get("census") or {}).get("data"),
                    board=(board_read or {}).get("data"),
                    heart=(reads.get("release") or {}).get("data"),
                    sources=sources, organs=glance_organs(), stale_sources=stale)
    unread = [s for s, r in reads.items() if not r["ok"]]
    if a.as_json:
        print(json.dumps({"dry_run": True, "sources": sources, "unread": unread,
                          "reads": {k: {kk: v for kk, v in r.items() if kk != "data"}
                                    for k, r in reads.items()},
                          "count": len(found),
                          "findings": [f.as_dict() for f in found]}, indent=2, default=str))
    else:
        sys.stdout.write(render(found, reads))
    if unread:
        print(f"batch maintain: source(s) not read: {', '.join(unread)} — "
              "the list is incomplete, not all-clear", file=sys.stderr)
        return RC_UNREAD
    return 0

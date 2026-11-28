"""Maintenance finding adapters — Phase 14.1 (PyAutoBrain#731), with the
hygiene and timing sources of Phase 14.5 (PyAutoBrain#739). Read-only.

One `Finding` shape over five sources of "something on main needs fixing":

- the no-run census (Heart's `no_run_census.json`, the board's
  `performance.no_run`, and the board's `no_run_census` monitoring rows — all
  one source, one key shape): a parked or slow workspace script;
- the Heart monitoring inventory (the board's `monitoring.findings`);
- the Heart release verdict, through `_green.classify` (one filing path —
  `_green` is reused, never changed);
- the hygiene ledger (`board/_hygiene_ledger.py`, 14.0): the latest day's
  per-finding keys, gated PER MODE — each mode is its own source
  (`hygiene:<mode>`), so a partial mode is never filed or cleared while a
  complete one is;
- slowed CI timings: only the gate, script and unit-test rows Heart itself
  flags (warn/slowed/red), never `hygiene ci`'s raw ranking.

Each finding carries a STABLE key, so two reads of the same board — or two
boards whose only difference is a run id — give the same keys, and the same
defect has one key whichever source reports it. That key is what slice 14.2
will write into a prompt and dedupe against.

`batch maintain --dry-run` prints them; `batch maintain --file --mind <path>`
hands them to the 14.2 writer (`_maintain_write.file_findings`), which files
sized draft prompts into that Mind (a linked worktree or a non-git directory,
never the shared checkout) and keeps `maintain.json`. It is run by hand (and
later by the 14.3 filing step); the watcher's tick never reads Heart and never
calls this. The adapters and loaders here write nothing.

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

SOURCES = ("census", "monitoring", "release", "hygiene", "timing")
#: Local Heart evidence, the same default Heart and the profiling conductor use.
HEART_STATE_DIR = Path(os.environ.get("HEART_STATE_DIR", Path.home() / ".pyauto-heart"))
CENSUS_NAME = "no_run_census.json"
BOARD_TIMEOUT = 90  # seconds: board.json is several MB
MAX_AGE_HOURS = _green.MAX_AGE_HOURS
RC_UNREAD = 3

#: Timing families. Since 14.5 they are no longer excluded from maintenance:
#: the TIMING source reads the three per-row families (`ci_timing`,
#: `smoke_timings`, `unit_test_timing`) with its own key shape, Heart-flagged
#: rows only; the monitoring adapter leaves every timing family to it (one key
#: per defect). `script_timing`, `import_time` and
#: `workspace_testmode_timing` are coverage/devbox roll-ups with no per-row key.
TIMING_FAMILIES = frozenset({"smoke_timings", "unit_test_timing", "ci_timing",
                             "script_timing", "import_time", "workspace_testmode_timing"})
TIMING_ROW_FAMILIES = ("ci_timing", "smoke_timings", "unit_test_timing")
#: Monitoring families this adapter never lists. `worktree_drift` and
#: `repo_state` are local checkout state (human decision 4: Gut and
#: /repo_cleanup own it); `release` is the verdict the release adapter reads
#: (decision 3: one filing path); `open_prs` are a human's /prm; the census
#: rows go through the census adapter (one key shape). The timing families go
#: through the timing adapter (`TIMING_FAMILIES`, skipped by the monitoring
#: adapter, not excluded from maintenance).
EXCLUDED_FAMILIES = frozenset({"worktree_drift", "repo_state", "release", "open_prs",
                               "no_run_census"})
#: Statuses that are a defect on main. `grey`/`stale` mean the evidence is
#: missing or old — a collector refresh, not a fix — so they are left out.
FILED_STATUSES = ("red", "yellow")
#: A release-execution workflow is never a glance fix.
#: Broad on purpose: only ever LOWERS an organ CI red to judge (the glance gate).
RELEASE_WORKFLOW_RX = re.compile(r"release", re.I)
#: Narrow: a release-EXECUTION workflow, human-only (its witness needs a
#: release run) — the name, trimmed and minus a `.yml`, starts or ends with
#: the word "release": "PyAuto Release", "Nightly Release", "Release",
#: "release.yml". "Pre-release checks" and "release-notes lint" are not.
RELEASE_EXEC_RX = re.compile(r"^release(?:\s|$)|(?:^|\s)release$", re.I)
#: Heart's unit-test timing roll-up line; with it present, a bare per-test
#: status line (`<path>::<test>[/<py>]: red|warn`) is a timing row, not a failure.
TIMING_ROLLUP_RX = re.compile(r"^\s*Unit-test timing:", re.I)
TEST_STATUS_LINE_RX = re.compile(r"^(?P<id>.+::.+?)(?:/\d+\.\d+)?: (?:red|warn|yellow)$")
#: The published feed cuts a long line with "…", which can drop the status: a
#: test id cut before any `: ` (so no failure text is visible).
TEST_CUT_LINE_RX = re.compile(r"^(?P<id>[^:]+::(?:(?!: ).)+?)…$")
#: Words in a census reason that force judge whatever the evidence says.
KILLED_RX = re.compile(r"\bOOM\b|SIGKILL|\bkilled\b|timed?[\s-]*out|times out", re.I)
PY_SUFFIX_RX = re.compile(r"/\d+\.\d+$")

CENSUS_WITNESS = ("the entry is gone from the repo's no_run.yaml and the script passes "
                  "under the smoke cap")
MONITORING_WITNESS = "the key is absent, or green, on a fresh Heart board read"
RELEASE_WITNESS = "a fresh Heart verdict (under 6 h old) no longer lists the reason"
HYGIENE_WITNESS = "the key is absent from a fresh hygiene ledger day whose mode is complete"
#: A slow witness (it needs post-merge runs), so the tier is judge.
TIMING_WITNESS = ("post-merge runs on main are below Heart's flagged threshold: the row "
                  "is no longer warn/slowed/red on a fresh Heart board read")
TIMING_ACTION = ("investigate whether the slowdown is real (runner noise, a cache miss, a "
                 "new or larger input) before changing anything; then speed it up, or "
                 "re-baseline it when the new time is the right one. Nothing is failing: "
                 "this is never \"fix the failing test\"")

#: The hygiene ledger's keyed modes (`_hygiene_ledger.KEYED_MODES`) by tier:
#: refs/docstrings/escapes are text or documentation fixes in the one file the
#: key names (glance); optdeps/extras change dependencies (judge).
HYGIENE_GLANCE_MODES = ("refs", "docstrings", "escapes")
HYGIENE_JUDGE_MODES = ("optdeps", "extras")
HYGIENE_ACTION = {
    "refs": "fix the dead reference (or name the undocumented folder) in this file",
    "docstrings": "merge or remove the adjacent docstrings in this file",
    "escapes": "fix the LaTeX the string escapes eat in this file (a raw string or "
               "doubled backslashes). Glance only while every changed string is a "
               "docstring or a comment; changing any other string literal (a plot label, "
               "a format string, a regex) changes runtime output and raises the tier to "
               "judge",
    "optdeps": "add the house `find_spec` skip guard to this smoke-listed script "
               "(the `/refactor` route); never drop the script from the smoke list",
    "extras": "add the missing install to the workspace-validation smoke leg (the "
              "`/bug` route); fix the install set, never the scripts",
}
#: The hygiene ledger is written once a day (the Brain Board's cron): a line
#: dated today or yesterday (UTC) is current; older, or none, is UNREAD — the
#: 6 h rule of a live board does not fit a daily ledger.
HYGIENE_MAX_AGE_HOURS = 48
#: Heart's per-row timing states that flag a row (performance rows).
TIMING_FLAGGED_STATES = frozenset({"warn", "slowed", "red", "yellow"})
#: A slowdown state proper; a red gate counts only with duration evidence and
#: no failing conclusion (`_gate_slowdown`).
SLOWDOWN_STATES = frozenset({"warn", "slowed"})
#: A Heart-flagged timing row is a FAILURE, never a slowdown, when Heart's
#: monitoring walker reached it under one of these keys (heart/monitoring.py
#: marks them red), or it carries a failing exit, `ok: false`, a timeout/hang
#: kind, a failing conclusion or status, or says it timed out.
FAILURE_PATH_RX = re.compile(r"(?:^|[/:])(failures|failing_scripts|events)/")
TIMEOUT_KINDS = frozenset({"suspect_cancelled", "timed_out", "timeout", "hang", "kill_timer"})
FAIL_CONCLUSIONS = frozenset({"failure", "timed_out", "cancelled", "startup_failure",
                              "action_required"})
FAIL_STATUSES = frozenset({"failed", "failure", "error", "timed_out", "timeout"})
TIMED_OUT_RX = re.compile(r"timed?[\s-]*out|times out", re.I)
SMOKE_WITNESS = "the script passes under the smoke cap on a fresh run"
SMOKE_ACTION = ("fix the failing or timed-out smoke script (reproduce first: run it under "
                "the smoke cap on main and read its own error before changing anything)")

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
        if not oracle:  # the oracle cannot be named, so it cannot be excluded: nothing is glance
            return set()
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
            and f.get("family") not in TIMING_FAMILIES
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


def timing_context(heart: dict, board: dict | None = None) -> tuple[bool, frozenset]:
    """(roll-up?, test ids): whether the verdict carries a `Unit-test timing:`
    roll-up line, and the board's `unit_test_timing` subjects (py suffix off)."""
    rollup = any(TIMING_ROLLUP_RX.match(str(r.get("text") or ""))
                 for r in (heart or {}).get("reasons") or [])
    subjects = frozenset(
        PY_SUFFIX_RX.sub("", str(f.get("subject") or ""))
        for f in ((board or {}).get("monitoring") or {}).get("findings") or []
        if isinstance(f, dict) and f.get("family") == "unit_test_timing")
    return rollup, subjects


def is_timing(c: dict, ctx) -> bool:
    """A `unit-test` reason that is a timing row: it says "timing"; or it is a
    bare `<path>::<test>: red|warn` status line (no failure text) and the
    verdict carries the timing roll-up, or the board lists it as timing."""
    if c.get("rule") != "unit-test":
        return False
    text = str(c.get("text") or "").strip()
    if re.search(r"timing", text, re.I):
        return True
    rollup, subjects = ctx or (False, frozenset())
    m = TEST_STATUS_LINE_RX.match(text)
    if m:
        # the board's timing subjects decide when read, so a real failing test
        # beside an unrelated timing regression is never hidden; else the roll-up
        return (m["id"] in subjects) if subjects else rollup
    cut = TEST_CUT_LINE_RX.match(text)
    if cut:  # a cut id: the board's timing subjects decide when read, else the roll-up
        if subjects:
            return any(s.startswith(cut["id"]) for s in subjects)
        return rollup
    return False


def release_exec(wf: str) -> bool:
    name = re.sub(r"\.ya?ml$", "", (wf or "").strip(), flags=re.I).strip()
    return bool(name) and RELEASE_EXEC_RX.search(name) is not None


def release_findings(heart: dict, organs=frozenset(), board=None) -> list[Finding]:
    """Heart's release verdict through `_green.classify`: its fixable-dev
    findings (the same filter `_green.run` files from), plus the organ
    CI-red lines no `_green` rule matches. The verdict carries no `on_head`
    evidence, so an organ CI red from here is judge (the monitoring row, read
    first, carries it). A unit-test timing row (`is_timing`, with the board's
    timing subjects when given) is marked so the writer skips it."""
    out = []
    ctx = timing_context(heart, board)
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
        out += [release_finding(c, organs, timing=is_timing(c, ctx)) for c in classified
                if c["cls"] == "fixable-dev" and c.get("key")]
    return out


def release_finding(c: dict, organs=frozenset(), timing: bool = False) -> Finding:
    """One `_green.classify` fixable-dev finding as a `Finding` (the release
    adapter's shape; `_green`'s file mode hands the writer these)."""
    repo = c.get("repo") or ""
    key = _norm_ci(c["key"])
    wf = key[3:].partition(":")[2] if key.startswith("ci:") else ""
    tier = (_organ_ci_tier(repo, wf, None, organs) if key.startswith("ci:")
            else "judge")
    return Finding(
        key=key, source="release", repo=repo,
        paths=[c["script"]] if c.get("script") else [],
        summary=f"[{c['severity']}] {c['text']}"[:240], witness=RELEASE_WITNESS,
        tier_floor=tier, lane=c.get("lane") or "local-dev",
        evidence={"rule": c["rule"], "severity": c["severity"], "text": c["text"],
                  "action": c.get("action", ""), **({"timing": True} if timing else {})})


# --- hygiene (14.5) -----------------------------------------------------------

def _ledger():
    """board/_hygiene_ledger.py (14.0), imported lazily — read-only use."""
    if "_hygiene_ledger" not in sys.modules:
        d = str(Path(__file__).resolve().parents[3] / "board")
        if d not in sys.path:
            sys.path.append(d)
    import _hygiene_ledger  # noqa: E402
    return _hygiene_ledger


def hygiene_source(mode: str) -> str:
    """The per-mode source name: `hygiene:<mode>`. Each mode is gated (filed,
    cleared) on its own completeness."""
    return f"hygiene:{mode}"


def base_source(source: str) -> str:
    """`hygiene:refs` → `hygiene`; any other source unchanged."""
    return str(source or "").partition(":")[0]


def hygiene_modes(line: dict) -> list[str]:
    """The keyed modes the ledger line reports at all (a status, a count or
    keys), in the ledger's order."""
    seen = set(line.get("status") or {}) | set(line.get("rows") or {}) \
        | set(line.get("findings") or {}) | set(line.get("unkeyed") or [])
    return [m for m in _ledger().KEYED_MODES if m in seen]


def mode_gaps(line: dict, mode: str) -> str:
    """Why `mode` is not a complete scan in `line`, or "" when it is
    (`_hygiene_ledger.mode_complete` is the test; this names the gap)."""
    if _ledger().mode_complete(line, mode):
        return ""
    why = []
    status = (line.get("status") or {}).get(mode)
    if status in _ledger().INCOMPLETE_STATUSES:
        why.append(f"status {status}")
    if mode in (line.get("unkeyed") or []) or mode not in (line.get("findings") or {}):
        why.append("unkeyed")
    if (line.get("not_scanned") or {}).get(mode):
        why.append("not_scanned " + ", ".join(line["not_scanned"][mode]))
    if (line.get("absent_repos") or {}).get(mode):
        why.append("absent_repos " + ", ".join(sorted(line["absent_repos"][mode])))
    return "; ".join(why) or "incomplete"


def _split_key(key: str) -> tuple[str, str, str, str]:
    mode, repo, file, ref = (key.split(":", 3) + ["", "", "", ""])[:4]
    return mode, repo, file, ref


def _hygiene_summary(mode: str, repo: str, file: str, ref: str, ev: dict) -> str:
    where = "/".join(x for x in (repo, file) if x)
    if mode == "refs":
        return f"dead or undocumented reference `{ref}` in {where}"
    if mode == "docstrings":
        return f"adjacent docstrings in {where}"
    if mode == "escapes":
        return f"LaTeX eaten by string escapes in {where}"
    if mode == "optdeps":
        return f"smoke-listed {where} uses optional dependency `{ref}` without a skip guard"
    if mode == "extras":
        by = ", ".join(str(r) for r in ev.get("declared_by") or ev.get("repos") or []) or "?"
        return f"optional dependency `{ref}` (declared by {by}) never installed by the smoke leg"
    return f"{mode}: {where} {ref}".strip()


def hygiene_findings(line: dict) -> dict[str, list[Finding]]:
    """{`hygiene:<mode>`: [Finding]} for every keyed mode the ledger line
    reports — an empty list for a mode with no findings (so a complete, clean
    mode clears its keys). Keys exactly as the ledger defines them
    (`_hygiene_ledger.finding_key`). A finding of an incomplete mode is
    flagged `stale`: listed, never filed; the per-mode read says why."""
    out: dict[str, list[Finding]] = {}
    for mode in hygiene_modes(line or {}):
        gap = mode_gaps(line, mode)
        tier = "glance" if mode in HYGIENE_GLANCE_MODES else "judge"
        rows = []
        for key in (line.get("findings") or {}).get(mode) or []:
            m, repo, file, ref = _split_key(str(key))
            if m != mode:
                continue
            extra = dict((line.get("evidence") or {}).get(key) or {})
            rows.append(Finding(
                key=str(key), source=hygiene_source(mode), repo=repo,
                paths=[file] if file else [],
                summary=_hygiene_summary(mode, repo, file, ref, extra)[:240],
                witness=HYGIENE_WITNESS, tier_floor=tier, lane="local-dev",
                evidence={"mode": mode, "date": line.get("date"), "sha": line.get("sha"),
                          "mode_status": (line.get("status") or {}).get(mode),
                          "mode_count": (line.get("rows") or {}).get(mode),
                          "reference": ref, "action": HYGIENE_ACTION.get(mode, ""),
                          **({"ledger_evidence": extra} if extra else {}),
                          **({"incomplete": gap} if gap else {})},
                stale=bool(gap)))
        out[hygiene_source(mode)] = rows
    return out


# --- slowed CI timings (14.5) ---------------------------------------------------

def timing_key(kind: str, repo: str, name: str) -> str:
    """`timing:<gate|script|unit>:<repo>:<workflow|entry|nodeid>`, the
    python-version suffix stripped (`/3.12`)."""
    return f"timing:{kind}:{str(repo).strip()}:{PY_SUFFIX_RX.sub('', str(name).strip())}"


def _flagged(row: dict) -> bool:
    return str(row.get("state") or "").lower() in TIMING_FLAGGED_STATES


def failure_reason(row: dict, path: str = "", summary: str = "") -> str:
    """Why a Heart-flagged timing row is a failure (a red smoke script, a
    timed-out run, a failing gate), or "" when it can be a slowdown."""
    m = FAILURE_PATH_RX.search(str(path or ""))
    if m:
        return f"reported under `{m.group(1)}`"
    ec = row.get("exit_code")
    if isinstance(ec, int) and not isinstance(ec, bool) and ec != 0:
        return f"exit code {ec}"
    if row.get("ok") is False:
        return "ok: false"
    if str(row.get("kind") or "").lower() in TIMEOUT_KINDS:
        return f"kind {row['kind']}"
    if str(row.get("conclusion") or "").lower() in FAIL_CONCLUSIONS:
        return f"conclusion {row['conclusion']}"
    if str(row.get("status") or "").lower() in FAIL_STATUSES:
        return f"status {row['status']}"
    text = " ".join(str(row.get(k) or "") for k in ("reason", "detail", "summary")) \
        + " " + str(summary or "")
    if TIMED_OUT_RX.search(text):
        return "timed out"
    return ""


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _gate_slowdown(row: dict) -> bool:
    """A gate row is a slowdown only on `state` warn/slowed, or a red/yellow
    with duration evidence (a ratio or a delta) and no failing conclusion —
    never a red driven by conclusions: `ci_status` covers failing gates."""
    st = str(row.get("state") or "").lower()
    if st in SLOWDOWN_STATES:
        return True
    return (st in ("", "red", "yellow") and not row.get("conclusion")
            and (_num(row.get("ratio")) or _num(row.get("delta_s"))))


def smoke_key(repo: str, entry: str) -> str:
    """`smoke:<repo>:<entry>` — a failing or timed-out smoke script (python
    suffix stripped), never a `timing:` key."""
    return f"smoke:{str(repo).strip()}:{PY_SUFFIX_RX.sub('', str(entry).strip())}"


def _perf_rows(board: dict):
    """(kind, repo, name, row) for each Heart-flagged performance row."""
    perf = (board or {}).get("performance") or {}
    for g in perf.get("gates") or []:
        if isinstance(g, dict) and _flagged(g):
            yield "gate", g.get("repo"), g.get("workflow"), g
    scripts = perf.get("scripts") if isinstance(perf.get("scripts"), dict) else {}
    for slowed, rows in ((True, scripts.get("slowed")), (False, scripts.get("rows"))):
        for r in rows or []:
            if isinstance(r, dict) and (_flagged(r) or (slowed and str(
                    r.get("state") or "").lower() not in ("ok", "green"))):
                yield "script", r.get("repo"), r.get("entry"), r
    unit = perf.get("unit") if isinstance(perf.get("unit"), dict) else {}
    for slowed, rows in ((True, unit.get("slowed_tests")), (False, unit.get("tests"))):
        for r in rows or []:
            if isinstance(r, dict) and (_flagged(r) or (slowed and str(
                    r.get("state") or "").lower() not in ("ok", "green"))):
                yield "unit", r.get("repo"), r.get("nodeid"), r


def _mon_timing(f: dict):
    """(kind, repo, name) of a per-row timing monitoring finding, or None
    (a roll-up, `:coverage` or a subject it cannot split)."""
    fam = f.get("family")
    key = monitoring_key(f)
    if fam not in TIMING_ROW_FAMILIES or key.endswith(":coverage"):
        return None
    subj = key[len(fam) + 1:]
    ev = f.get("evidence") if isinstance(f.get("evidence"), dict) else {}
    if fam == "ci_timing":
        kind, name = "gate", ev.get("workflow")
    elif fam == "smoke_timings":
        kind, name = "script", ev.get("entry")
    else:
        kind, name = "unit", ev.get("test") or ev.get("nodeid")
    repo = ev.get("repo")
    if not (repo and name):
        if "/" not in subj:
            return None
        repo, name = subj.split("/", 1)
    if kind == "unit" and "::" not in str(name):
        return None
    return kind, repo, name


_TIMING_NOUN = {"gate": "CI gate", "script": "smoke script", "unit": "unit test"}


def _timing_summary(kind, repo, name, row) -> str:
    sec = row.get("median_s", row.get("seconds", row.get("latest_seconds")))
    base = row.get("baseline_s", row.get("prev_s", row.get("baseline_seconds")))
    ratio = row.get("ratio")
    nums = ""
    if isinstance(sec, (int, float)):
        nums = f": {sec:g}s"
        if isinstance(base, (int, float)):
            nums += f" vs {base:g}s baseline"
        if isinstance(ratio, (int, float)):
            nums += f" (x{ratio:g})"
    state = row.get("state") or row.get("status") or "flagged"
    return f"[{state}] slowed {_TIMING_NOUN[kind]} {repo}: {name}{nums}"


def timing_findings(board: dict) -> list[Finding]:
    """Heart-flagged slowed timings → findings keyed `timing:<kind>:<repo>:<name>`:
    `performance.gates`/`scripts`/`unit` rows whose `state` is warn, slowed or
    red (plus the `slowed` lists), and the red/yellow `ci_timing`,
    `smoke_timings` and `unit_test_timing` monitoring rows. One finding per
    key, however many rows (run ids, python versions) report it. Judge
    always (a slow witness). Stale when Heart marks every monitoring row for
    the key not fresh, or stale, and none flags it fresh.

    A flagged row that is a FAILURE (`failure_reason`) is never a slowdown: a
    smoke script becomes `smoke:<repo>:<entry>` (fix it, reproduce first;
    witness: passes under the smoke cap), and a failing gate is dropped (the
    monitoring `ci_status` rows file it). A gate is a slowdown only on
    `_gate_slowdown`."""
    found: dict[str, Finding] = {}
    fresh_flag, stale_flag = set(), set()

    def classify(kind, repo, name, row, path="", summary=""):
        """(key, kind, failure) or None when the row is not this source's."""
        if not repo or not name:
            return None
        why = failure_reason(row, path, summary)
        if kind == "gate":
            return None if why or not _gate_slowdown(row) else \
                (timing_key(kind, repo, name), kind, "")
        if kind == "script" and why:
            return smoke_key(repo, name), "smoke", why
        return timing_key(kind, repo, name), kind, ""

    def add(cls, repo, name, row, origin):
        key, kind, why = cls
        compact = {k: v for k, v in row.items()
                   if k not in ("spark", "baseline_run_ids", "action")}
        f = found.get(key)
        if f is None:
            name = PY_SUFFIX_RX.sub("", str(name).strip())
            path = name.split("::", 1)[0] if kind == "unit" else \
                name if kind in ("script", "smoke") else ""
            if kind == "smoke":
                state = row.get("state") or row.get("status") or "red"
                summary = (f"[{state}] failing or timed-out smoke script {repo}: {name} "
                           f"— {why}")
                witness, action = SMOKE_WITNESS, SMOKE_ACTION
            else:
                summary = _timing_summary(kind, repo, name, row)
                witness, action = TIMING_WITNESS, TIMING_ACTION
            f = found[key] = Finding(
                key=key, source="timing", repo=str(repo).strip(),
                paths=[path] if path else [], summary=summary[:240],
                witness=witness, tier_floor="judge",
                lane="any" if kind == "gate" else "local-dev",
                evidence={"kind": kind, "name": name, "action": action,
                          "status": "red" if kind == "smoke" else "yellow", "rows": [],
                          **({"failure": why} if why else {})})
        if kind != "smoke" and "baseline" not in f.summary:  # the richest row names it
            better = _timing_summary(kind, f.repo, f.evidence["name"], row)[:240]
            if "baseline" in better:
                f.summary = better
        st = str(row.get("status") or row.get("state") or "").lower()
        if st == "red":
            f.evidence["status"] = "red"
        f.evidence["rows"].append({"from": origin, **compact})

    for kind, repo, name, row in _perf_rows(board):
        cls = classify(kind, repo, name, row)
        if cls:
            add(cls, repo, name, row, "performance")
    for m in ((board or {}).get("monitoring") or {}).get("findings") or []:
        if not isinstance(m, dict):
            continue
        parsed = _mon_timing(m)
        if parsed is None:
            continue
        ev = m.get("evidence") if isinstance(m.get("evidence"), dict) else {}
        row = {"status": m.get("status"), "id": m.get("id"),
               "observed_at": m.get("observed_at"), **ev}
        if parsed[0] == "gate" and "state" not in ev:
            row["state"] = ""   # a monitoring status alone is not a slowdown state
        cls = classify(*parsed, row, path=str(m.get("source") or ""),
                       summary=str(m.get("summary") or ""))
        if cls is None:
            continue
        key = cls[0]
        if m.get("fresh") is False or m.get("status") in ("stale", "grey"):
            stale_flag.add(key)
        if m.get("status") not in FILED_STATUSES:
            continue
        if m.get("fresh") is not False:
            fresh_flag.add(key)
        add(cls, parsed[1], parsed[2], row, "monitoring")
    for key, f in found.items():
        f.stale = key in stale_flag and key not in fresh_flag
        f.evidence["rows"] = f.evidence["rows"][:6]
    return list(found.values())


def release_timing_key(f: Finding, timing_keys) -> str:
    """The `timing:unit:` key a release-verdict unit-test timing line is about,
    when the timing source lists it, else "" — so one slow test is one key."""
    ev = f.evidence or {}
    if ev.get("rule") != "unit-test":
        return ""
    text = str(ev.get("text") or "").strip()
    m = TEST_STATUS_LINE_RX.match(text)
    cut = None if m else TEST_CUT_LINE_RX.match(text)
    full = (m or cut)["id"] if (m or cut) else ""
    if "/" not in full:
        return ""
    repo, nodeid = full.split("/", 1)
    want = timing_key("unit", repo, nodeid)
    if m:
        return want if want in timing_keys else ""
    return next((k for k in sorted(timing_keys) if k.startswith(want)), "")


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


def collect_raw(census=None, board=None, heart=None, sources=SOURCES,
                organs=frozenset(), hygiene=None) -> dict:
    """{source: [Finding]} before the cross-source dedupe — what each source
    itself lists. The writer clears a key only when no freshly read source
    lists it, whichever source won the dedupe. The hygiene source lists
    per mode (`hygiene:<mode>`), from the ledger line `hygiene`.

    A release-verdict unit-test timing line about a test the timing source
    lists is dropped from the release list: one slow test is one key (the
    timing one, filed with timing's action text, not "fix the test")."""
    out = {}
    if "census" in sources:
        # One whole source (the loader picks it): the census document given,
        # else the board's census rows. Never a merge of the two.
        rows = (census or {}).get("rows") if census is not None else \
            board_census_rows(board) if board is not None else []
        out["census"] = census_findings({"rows": rows or []})
    if "monitoring" in sources and board is not None:
        out["monitoring"] = monitoring_findings(board, organs)
    if "timing" in sources and board is not None:
        out["timing"] = timing_findings(board)
    if "release" in sources and heart is not None:
        rel = release_findings(heart, organs, board)
        tkeys = {f.key for f in out.get("timing") or []}
        out["release"] = [f for f in rel if not (
            (f.evidence or {}).get("timing") or human_only_reason(f))
            or not release_timing_key(f, tkeys)]
    if "hygiene" in sources and hygiene is not None:
        out.update(hygiene_findings(hygiene))
    return out


def ordered(raw: dict) -> list[Finding]:
    """`raw`'s findings in source order (`SOURCES`; a hygiene mode at
    `hygiene`'s place), each source's own order kept."""
    rank = {s: i for i, s in enumerate(SOURCES)}
    names = sorted(raw, key=lambda n: (rank.get(base_source(n), 99), n))
    return [f for n in names for f in raw[n]]


def collect(census=None, board=None, heart=None, sources=SOURCES,
            organs=frozenset(), stale_sources=(), raw=None, hygiene=None) -> list[Finding]:
    """All requested sources, deduped. A finding from a source in
    `stale_sources` (over the 6 h rule, or a grey/stale verdict) is flagged
    `stale`, as is a monitoring row Heart itself marks `fresh: false`, a
    timing row Heart marks stale and a hygiene finding of an incomplete mode."""
    raw = raw if raw is not None else collect_raw(census, board, heart, sources, organs,
                                                  hygiene)
    out = dedupe(ordered(raw))
    for f in out:
        if f.source in stale_sources:
            f.stale = True
    return out


def human_only_reason(f: Finding) -> str:
    """Why a listed finding is the human's, never a filed fix, or "": a
    release-execution workflow (its witness needs a release run) or a
    release-verdict unit-test timing line (14.2). Since 14.5 the timing source
    files Heart-flagged timings itself, and a release line about a test it
    lists is dropped there (`collect_raw`), so this keeps only the lines it
    does not list."""
    if f.key.startswith("ci:"):
        wf = f.key[3:].partition(":")[2]
        if release_exec(wf):
            return ("human-only: a release-execution workflow — its witness needs a "
                    "release run")
    ev = f.evidence or {}
    if ev.get("rule") == "unit-test" and (
            ev.get("timing") or re.search(r"timing", str(ev.get("text") or ""), re.I)):
        return ("human-only: a unit-test timing line in the release verdict — not a "
                "failing test; the timing source files Heart-flagged slow tests")
    return ""


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
    # A negative age (`--at` before the evidence) is unknown, so stale.
    stale = ((not ok) or partial or age is None or age < 0 or age > MAX_AGE_HOURS
             or status == "stale")
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


#: Set (to 1) by the Brain board's job (`brain_board.yml`): the release source
#: reads Heart's published feed only, never a local `pyauto-heart readiness`.
FEED_ONLY_ENV = "BOARD_HEART_FEED_ONLY"


def load_release(heart_json: str = "", now=None) -> dict:
    h = _green.read_heart(heart_json, now=now,
                          local=os.environ.get(FEED_ONLY_ENV) != "1")
    data = h if h.get("source") != "none" else None
    return _read(data, h.get("source", "none"), h.get("why") or "", h.get("age_hours"),
                 status=str(h.get("status") or "grey").lower())


def ledger_url():
    """(url, why): the published `hygiene_ledger.jsonl` beside the Brain
    board's board.json — the same declared surface the board publishes to
    (the policy's `board: boards: brain`, on the Pages base the Heart feed
    URL derives from the body map, or `BOARD_PAGES_BASE`)."""
    url, why = _green._hf().feed_url()
    if not url:
        return None, why
    base = url.rsplit("/", 2)[0]
    try:
        brain = (_green._hf()._board().load_policy().get("boards") or {}).get("brain")
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — a missing policy is unread
        return None, f"cannot read the board policy ({str(exc)[:80]})"
    if not brain:
        return None, "no `board: boards: brain` in config/policy.yaml"
    return f"{base}/{brain}/{_ledger().LEDGER_NAME}", ""


def fetch_text(url: str, timeout=BOARD_TIMEOUT):
    """(text, why) — GET with the Pages CDN cache bypassed; a 404 is "not
    published" (unread, never "no findings")."""
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache",
                                               "Pragma": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, f"no hygiene ledger published at {url} (404)"
        return None, f"hygiene ledger unreachable (HTTP {exc.code})"
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        return None, f"hygiene ledger unreachable ({exc.__class__.__name__}: {str(exc)[:80]})"


def latest_line(text: str):
    """(line, why): the latest day's line of a ledger body — JSONL, or one
    JSON object (a saved line). A malformed line makes the whole read
    unread: a truncated or HTML body must never read as fewer findings."""
    if text is None:
        return None, "no ledger"
    lines, nonblank = _ledger()._parse(text)
    if nonblank and len(lines) != nonblank:
        try:
            one = json.loads(text)
        except ValueError:
            one = None
        if isinstance(one, dict) and isinstance(one.get("date"), str):
            return one, ""
        return None, f"ledger has {nonblank - len(lines)} malformed of {nonblank} line(s)"
    if not lines:
        return None, "ledger is empty"
    return max(lines, key=lambda e: e["date"]), ""


def _ledger_age(date: str, now=None):
    """Hours since the start of the line's UTC day; None when unparseable."""
    try:
        day = _dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return ((now or _dt.datetime.now(_dt.timezone.utc)) - day).total_seconds() / 3600


def load_hygiene(hygiene_json: str = "", now=None) -> dict:
    """The hygiene source's read: {data (the latest line), source, why,
    age_hours, ok, stale, partial}. Unread (ok False, exit 3) when the ledger
    is unpublished, unreadable, empty, or its latest day is over
    `HYGIENE_MAX_AGE_HOURS` (or in the future). A current ledger is never
    `stale` as a whole: completeness is per mode (`mode_reads`)."""
    if hygiene_json:
        path = Path(hygiene_json)
        try:
            text, why = path.read_text(encoding="utf-8"), ""
        except OSError as exc:
            text, why = None, f"{path} unreadable ({str(exc)[:80]})"
        source = f"file {hygiene_json}"
    else:
        url, why = ledger_url()
        text, why = fetch_text(url) if url else (None, why)
        source = "published hygiene ledger"
    line, lwhy = latest_line(text) if text is not None else (None, why)
    if line is None:
        return {"data": None, "source": "none" if text is None else source,
                "why": lwhy or why, "age_hours": None, "ok": False, "stale": True,
                "partial": False}
    age = _ledger_age(line.get("date"), now)
    if age is None or age < 0 or age > HYGIENE_MAX_AGE_HOURS:
        when = "undated" if age is None else ("in the future" if age < 0
                                              else f"{age:.0f} h old")
        return {"data": None, "source": source, "age_hours": age, "ok": False,
                "stale": True, "partial": False,
                "why": f"latest ledger day {line.get('date')} is {when} — over the "
                       f"{HYGIENE_MAX_AGE_HOURS} h rule for a daily ledger"}
    return {"data": line, "source": f"{source}, day {line.get('date')}", "why": "",
            "age_hours": age, "ok": True, "stale": False, "partial": False}


def mode_reads(hread: dict) -> dict:
    """One read per keyed mode of a read ledger line (`hygiene:<mode>`): `ok`
    and fresh as the ledger, `partial` (never filed, never cleared) when the
    mode is not complete — status partial/errored, `unkeyed`, `not_scanned`
    or `absent_repos`."""
    line = (hread or {}).get("data")
    if not (hread or {}).get("ok") or not isinstance(line, dict):
        return {}
    out = {}
    for mode in hygiene_modes(line):
        gap = mode_gaps(line, mode)
        out[hygiene_source(mode)] = {
            "data": None, "source": hread["source"], "why": gap,
            "age_hours": hread.get("age_hours"), "ok": True, "stale": bool(gap),
            "partial": bool(gap)}
    return out


def read_sources(sources=SOURCES, board_json: str = "", census_json: str = "",
                 heart_json: str = "", now=None,
                 hygiene_json: str = "") -> tuple[dict, dict, list[Finding]]:
    """(reads, raw, findings) for `sources`: each source's read ({ok, stale,
    partial, …}; the hygiene source also one read per mode, `hygiene:<mode>`),
    what each listed before the dedupe (`collect_raw`), and the deduped
    findings. Read-only; `batch maintain` and the maintenance brief
    (`batch brief --new --maintenance`, Phase 14.3) share it."""
    reads = {}
    board_read = None
    if {"monitoring", "census", "timing"} & set(sources):
        board_read = load_board(board_json, now)
    if "census" in sources:
        reads["census"] = load_census(census_json, board_read, now)
    if "monitoring" in sources:
        reads["monitoring"] = board_read
    if "release" in sources:
        reads["release"] = load_release(heart_json, now)
    if "timing" in sources:
        reads["timing"] = board_read
    hread = None
    if "hygiene" in sources:
        hread = load_hygiene(hygiene_json, now)
        reads["hygiene"] = hread
        reads.update(mode_reads(hread))
    stale = {s for s, r in reads.items() if r["stale"]}
    raw = collect_raw(census=(reads.get("census") or {}).get("data"),
                      board=(board_read or {}).get("data"),
                      heart=(reads.get("release") or {}).get("data"),
                      sources=sources, organs=glance_organs(),
                      hygiene=(hread or {}).get("data") if (hread or {}).get("ok") else None)
    return reads, raw, collect(sources=sources, stale_sources=stale, raw=raw)


# --- CLI ----------------------------------------------------------------------

def _read_line(name, r) -> str:
    if not r["ok"]:
        return (f"  {name:<18} UNREAD — {r.get('why') or r.get('status') or 'no data'}"
                f" (findings from it are not all-clear)")
    age = "age unknown" if r.get("age_hours") is None else f"{r['age_hours']:.1f} h old"
    status = f", verdict {r['status']}" if r.get("status") else ""
    flag = " — STALE: listed, never filed or cleared" if r["stale"] else ""
    if r.get("partial"):
        flag += f" — PARTIAL ({r.get('why')}): never clear keys from it"
    return f"  {name:<18} {r['source']} ({age}{status}){flag}"


def render(findings, reads) -> str:
    L = ["batch maintain — maintenance findings", ""]
    L += [_read_line(name, r) for name, r in reads.items()]
    L += ["", f"{len(findings)} finding(s)", ""]
    rows = [("KEY", "SOURCE", "REPO", "TIER", "SUMMARY")] + [
        (f.key, f.source, f.repo, f.tier_floor + ("*" if f.stale else ""), f.summary)
        for f in findings]
    w = [min(max(len(r[i]) for r in rows), cap) for i, cap in enumerate((70, 18, 26, 7))]
    for r in rows:
        cells = [r[i][:w[i]].ljust(w[i]) for i in range(4)]
        L.append("  ".join(cells) + "  " + r[4][:110])
    if any(f.stale for f in findings):
        L += ["", "* stale: from a stale read, a row Heart marks not fresh or stale, or "
                  "an incomplete hygiene mode — listed, never filed"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="batch maintain",
        description="List maintenance findings from the no-run census, Heart's "
                    "monitoring inventory, its release verdict, the hygiene ledger "
                    "and Heart-flagged slowed CI timings (--dry-run), or "
                    "file them as draft prompts into a Mind (--file --mind). "
                    "Exit 3 when a requested source could not be read.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="list findings, write nothing")
    mode.add_argument("--file", action="store_true",
                      help="file each finding as a draft prompt into --mind (Phase 14.2)")
    ap.add_argument("--mind", default="", metavar="DIR",
                    help="--file: the Mind to write into — a linked worktree on "
                         "origin/main or a non-git directory, never the shared checkout")
    ap.add_argument("--cap", type=int, default=3,
                    help="--file: at most this many new prompts per run (default 3)")
    ap.add_argument("--home", default="", metavar="DIR",
                    help="--file: the directory holding maintain.json (default: the "
                         "orchestrator home, beside heart_green.json)")
    ap.add_argument("--sources", default=",".join(SOURCES),
                    help=f"comma-separated subset of {','.join(SOURCES)}")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--board-json", default="", metavar="FILE",
                    help="read this saved Heart board.json instead of the published one")
    ap.add_argument("--census-json", default="", metavar="FILE",
                    help="read this saved no_run_census.json instead of Heart's local one")
    ap.add_argument("--heart-json", default="", metavar="FILE",
                    help="read this saved `readiness --json` / state.json instead of Heart")
    ap.add_argument("--hygiene-json", default="", metavar="FILE",
                    help="read this saved hygiene ledger (JSONL, or one day's line) "
                         "instead of the published one")
    ap.add_argument("--at", default="", help="judge ages as of this ISO time (a replay)")
    a = ap.parse_args(argv)
    if not (a.dry_run or a.file):
        print("batch maintain: pass --dry-run (list) or --file --mind <dir> (write, Phase 14.2)",
              file=sys.stderr)
        return 2
    if a.file and not a.mind:
        print("batch maintain --file: --mind <dir> is required — a linked worktree "
              "on origin/main (`git -C <mind> worktree add --detach <dir> origin/main`) "
              "or a non-git directory; the shared checkout is never written",
              file=sys.stderr)
        return 2
    if a.cap < 0:
        print("batch maintain: --cap must be >= 0", file=sys.stderr)
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
    hold = ""
    if a.file:
        import _maintain_write  # noqa: E402 — the 14.2 writer
        hold = _maintain_write.write_hold(Path(a.mind))
        if hold:  # refuse before any read: nothing is written, the state included
            print(f"batch maintain --file: refused — {hold}", file=sys.stderr)
            return 2
    reads, raw, found = read_sources(sources, a.board_json, a.census_json,
                                     a.heart_json, now, a.hygiene_json)
    unread = [s for s, r in reads.items() if not r["ok"]]
    wres = None
    if a.file:
        home = Path(a.home) if a.home else _orchestrator_home()
        wres = _maintain_write.file_findings(
            found, reads, Path(a.mind), cap=a.cap,
            state_path=home / _maintain_write.STATE_NAME, now=now,
            present=_maintain_write.present_keys(raw, reads))
    if a.as_json:
        print(json.dumps({"dry_run": bool(a.dry_run), "sources": sources, "unread": unread,
                          "reads": {k: {kk: v for kk, v in r.items() if kk != "data"}
                                    for k, r in reads.items()},
                          "count": len(found),
                          "findings": [f.as_dict() for f in found],
                          **({"write": wres} if wres is not None else {})},
                         indent=2, default=str))
    else:
        sys.stdout.write(render(found, reads))
        if wres is not None:
            sys.stdout.write(_maintain_write.render(wres))
    if unread:
        print(f"batch maintain: source(s) not read: {', '.join(unread)} — "
              "the list is incomplete, not all-clear", file=sys.stderr)
        return RC_UNREAD
    return 0


def _orchestrator_home() -> Path:
    import _orchestrator  # noqa: E402 — deferred: only the state path
    return Path(_orchestrator.orchestrator_home())

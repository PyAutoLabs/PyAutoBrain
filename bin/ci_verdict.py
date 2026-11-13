#!/usr/bin/env python3
"""bin/ci_verdict.py — one CI verdict for one pull request (PyAutoBrain#628).

    pyauto-brain ci-verdict <owner/repo>#<n> [--json]

WHY. The CI judgement for a merge lived in three places that disagreed: `/prm`
prose, the shift watcher's `pr_health` (`batch/_digest.py`) and the close-out
template. Six lessons (review finding FB-4) are about misreading a PR's CI:
one run of four read as the whole, skipped legs read as green, a conflicting
PR or an outage showing "no checks", and an empty head sha that matched every
run in the repo. This is the one executable judgement every merge path uses.

WHAT IT READS (read-only `gh api`, REST only):
  * the PR — head sha (`.head.sha`; an empty sha is refused, never queried),
    state, `mergeable` / `mergeable_state` (re-read once while GitHub is still
    computing it);
  * every check-run on the head sha (paginated), every commit status, and
    every workflow run for the sha with every job of every run.

THE RULES (`judge`). Reasons accumulate; any RED reason makes the verdict RED,
else any PENDING reason makes it PENDING, else it is GREEN.
  * RED — a check failed, was cancelled or timed out (or has a conclusion this
    reader does not know: fail closed); the PR is conflicting, behind, a draft
    or closed unmerged; once every check has completed: there are zero checks,
    or only skipped ones, or the PR is blocked or in a mergeable state that is
    not `clean`. An unreadable reply or an empty head sha is RED too.
  * PENDING — a check or workflow run has not completed, or GitHub has not
    computed mergeability (`unknown`, or `unstable` while every check reads
    green).
  * GREEN — at least one completed check, every completed check `success`
    (or skipped/neutral, which are listed by name), and `mergeable_state`
    `clean`. A merged PR's mergeability is not judged (GitHub stops computing
    it), and the summary says so.

The watcher's network surface is `gh pr checks` only (AUTONOMY.md "The
watcher's network surface — 2026-11-03"), so `pr_health` keeps that read and
hands its rows to `judge` with mergeability not read (`from_pr_checks`).

Exit status: 0 GREEN, 1 RED, 2 PENDING, 64 usage. `--json` prints one object.
`gh` is behind the `run` seam (a `subprocess.run`-shaped callable) so the
tests are offline.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

GREEN, PENDING, RED = "GREEN", "PENDING", "RED"
EXIT = {GREEN: 0, RED: 1, PENDING: 2}
EXIT_USAGE = 64

#: Completed conclusions that are green.
SUCCESS = frozenset({"success"})
#: Completed conclusions that never ran or say nothing: allowed, but named, and
#: never evidence on their own (PyAutoHeart#343).
SKIPPED = frozenset({"skipped", "neutral"})
#: Completed conclusions that are red, by reason code.
FAILED = {"failure": "check-failed", "error": "check-failed",
          "startup_failure": "check-failed", "action_required": "check-failed",
          "stale": "check-failed", "cancelled": "check-cancelled",
          "timed_out": "check-timed-out"}
#: Mergeable states that are red whatever the checks say.
MERGE_RED_ALWAYS = {"dirty": "conflicting", "behind": "behind", "draft": "draft"}

_REF_RE = re.compile(
    r"^(?:https?://github\.com/)?([\w.-]+/[\w.-]+)(?:#|/pull/|/pulls/)(\d+)/?$")


class UsageError(ValueError):
    pass


def parse_ref(ref: str) -> tuple[str, int]:
    """`owner/repo#n`, `owner/repo/pull/n` or the PR URL → (owner/repo, n)."""
    m = _REF_RE.match((ref or "").strip())
    if not m:
        raise UsageError(f"not a PR reference: {ref!r} (want owner/repo#N or a PR URL)")
    return m.group(1), int(m.group(2))


# --- the judgement ----------------------------------------------------------------

def _row(name, status, conclusion, kind="check") -> dict:
    status = str(status or "").lower()
    return {"name": str(name or "?"), "kind": kind,
            "status": "completed" if status == "completed" else (status or "pending"),
            "conclusion": str(conclusion or "").lower() or None}


def judge(checks: list, *, mergeable_state: str | None = None,
          mergeable: bool | None = None, pr_state: str = "open",
          merged: bool = False, read_mergeable: bool = True) -> dict:
    """The verdict for one PR head: GREEN, PENDING or RED, with reasons.

    `checks` are rows `{name, kind, status, conclusion}` (`status`
    `completed` or not). `read_mergeable=False` judges the checks alone (the
    watcher's `gh pr checks` read carries no mergeability)."""
    reasons: list[dict] = []

    def add(level, code, detail):
        reasons.append({"level": level, "code": code, "detail": detail})

    done = [c for c in checks if c["status"] == "completed"]
    pending = [c for c in checks if c["status"] != "completed"]
    success = [c for c in done if c["conclusion"] in SUCCESS]
    skipped = [c for c in done if c["conclusion"] in SKIPPED]
    red = [c for c in done if c["conclusion"] in FAILED]
    odd = [c for c in done if c not in success + skipped + red]

    for code in sorted({FAILED[c["conclusion"]] for c in red}):
        names = [f"{c['name']} ({c['conclusion']})" for c in red
                 if FAILED[c["conclusion"]] == code]
        add(RED, code, ", ".join(names))
    if odd:
        add(RED, "check-unrecognised", "conclusion this reader does not know: "
            + ", ".join(f"{c['name']} ({c['conclusion'] or 'none'})" for c in odd))
    if pending:
        add(PENDING, "checks-pending", f"{len(pending)} of {len(checks)} not completed: "
            + ", ".join(f"{c['name']} ({c['status']})" for c in pending))
    elif not checks:
        add(RED, "no-checks", "no check on the head sha — no CI ran (no workflow, a "
            "path filter, an outage, or a conflicting PR GitHub cannot build)")
    elif not success and not red and not odd:
        add(RED, "skipped-only", "every check was skipped — nothing ran: "
            + ", ".join(c["name"] for c in skipped))

    state = str(mergeable_state or "").lower() or "unknown"
    note = None
    if pr_state == "closed" and not merged:
        add(RED, "closed", "the PR is closed without merging")
    elif merged:
        note = "PR already merged: mergeability not judged"
    elif read_mergeable:
        if mergeable is False and state != "dirty":
            add(RED, "conflicting", f"mergeable=false (mergeable_state {state})")
        if state in MERGE_RED_ALWAYS:
            add(RED, MERGE_RED_ALWAYS[state], f"mergeable_state {state}")
        elif state == "unknown" or (mergeable is None and state != "clean"):
            add(PENDING, "mergeable-unknown",
                f"GitHub has not computed mergeability (mergeable_state {state})")
        elif state == "clean":
            pass
        elif pending:
            pass  # blocked/unstable while checks run is GitHub waiting on them
        elif state == "unstable":
            add(PENDING, "mergeable-unstable", "mergeable_state unstable while every "
                "check read here has completed — re-read before merging")
        elif state == "blocked":
            add(RED, "blocked", "mergeable_state blocked (protection rule or review)")
        else:
            add(RED, "not-clean", f"mergeable_state {state} is not clean")
    else:
        note = "mergeability not read"

    levels = {r["level"] for r in reasons}
    verdict = RED if RED in levels else PENDING if PENDING in levels else GREEN
    return {
        "verdict": verdict,
        "reasons": reasons,
        "counts": {"checks": len(checks), "completed": len(done), "success": len(success),
                   "skipped": len(skipped), "red": len(red) + len(odd),
                   "pending": len(pending)},
        "skipped": [c["name"] for c in skipped],
        "mergeable_state": state if read_mergeable and not merged else None,
        "note": note,
    }


# --- the watcher's read: `gh pr checks --json name,bucket,state` -----------------

_BUCKET = {"pass": ("completed", "success"), "fail": ("completed", "failure"),
           "cancel": ("completed", "cancelled"), "skipping": ("completed", "skipped"),
           "pending": ("pending", None)}


def from_pr_checks(rows: list) -> list:
    """`gh pr checks --json` rows → judge rows. A bucket this reader does not
    know stays a completed row with that conclusion, so `judge` fails closed."""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        bucket = str(r.get("bucket") or "").lower()
        status, conclusion = _BUCKET.get(bucket, ("completed", bucket or "unknown"))
        out.append(_row(r.get("name"), status, conclusion, kind="pr-checks"))
    return out


# --- the full read: REST, behind the `run` seam ------------------------------------

class GhError(RuntimeError):
    pass


def _gh(run, *args) -> list:
    """`gh api <args>` → every JSON value it printed (`--paginate --jq '.x[]'`
    prints one per line). A non-zero exit or unparseable output raises."""
    argv = ["gh", "api", *args]
    try:
        res = run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise GhError(f"`{' '.join(argv)}` could not run: {e}") from e
    if res.returncode != 0:
        tail = ((res.stderr or res.stdout or "").strip().splitlines() or ["no output"])[-1]
        raise GhError(f"`{' '.join(argv[:4])}` exited {res.returncode}: {tail[:200]}")
    text, values, dec, i = res.stdout or "", [], json.JSONDecoder(), 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return values
        try:
            value, i = dec.raw_decode(text, i)
        except ValueError as e:
            raise GhError(f"`{' '.join(argv[:4])}` printed non-JSON output") from e
        values.append(value)


PR_JQ = ("{sha: .head.sha, state: .state, merged: .merged, mergeable: .mergeable, "
         "mergeable_state: .mergeable_state, draft: .draft, url: .html_url}")


def read_pr(repo: str, number: int, run, sleep=time.sleep) -> dict:
    got = _gh(run, f"repos/{repo}/pulls/{number}", "--jq", PR_JQ)
    pr = got[0] if got and isinstance(got[0], dict) else {}
    if pr.get("state") == "open" and pr.get("mergeable") is None:
        sleep(3)   # GitHub computes mergeability lazily: ask once more
        again = _gh(run, f"repos/{repo}/pulls/{number}", "--jq", PR_JQ)
        if again and isinstance(again[0], dict) and again[0].get("sha") == pr.get("sha"):
            pr = again[0]
    return pr


def collect(repo: str, sha: str, run) -> list:
    """Every check-run, commit status, workflow run and job for one sha, as
    judge rows. A job is the check-run with the same id, named with its
    workflow and event; a run is a row only where its jobs do not already say
    it (queued with no jobs yet, or failed before any job started)."""
    if not sha:
        raise GhError("empty head sha")
    base = f"repos/{repo}"
    checks = _gh(run, "--paginate", f"{base}/commits/{sha}/check-runs?per_page=100",
                 "--jq", ".check_runs[]")
    statuses = _gh(run, "--paginate", f"{base}/commits/{sha}/status?per_page=100",
                   "--jq", ".statuses[]")
    runs = _gh(run, "--paginate", f"{base}/actions/runs?head_sha={sha}&per_page=100",
               "--jq", ".workflow_runs[]")
    rows, seen = [], set()
    for wr in runs:
        if wr.get("head_sha") not in (None, sha):
            continue   # never judge another commit's run
        jobs = _gh(run, "--paginate", f"{base}/actions/runs/{wr['id']}/jobs?per_page=100",
                   "--jq", ".jobs[]")
        label = f"{wr.get('name') or 'workflow'} [{wr.get('event') or '?'}]"
        for j in jobs:
            seen.add(j.get("id"))
            rows.append(_row(f"{label} / {j.get('name')}", j.get("status"),
                             j.get("conclusion"), kind="job"))
        run_done = str(wr.get("status") or "").lower() == "completed"
        run_concl = str(wr.get("conclusion") or "").lower()
        jobs_open = any(str(j.get("status") or "").lower() != "completed" for j in jobs)
        jobs_red = any(str(j.get("conclusion") or "").lower() in FAILED for j in jobs)
        if (not run_done and not jobs_open) or \
           (run_done and run_concl in FAILED and not jobs_red):
            rows.append(_row(label, wr.get("status"), wr.get("conclusion"), kind="run"))
    for c in checks:
        if c.get("id") in seen:
            continue
        app = (c.get("app") or {}).get("slug") if isinstance(c.get("app"), dict) else None
        rows.append(_row(f"{c.get('name')}" + (f" ({app})" if app else ""),
                         c.get("status"), c.get("conclusion"), kind="check-run"))
    for s in statuses:
        st = str(s.get("state") or "").lower()
        rows.append(_row(f"{s.get('context')} (status)",
                         "pending" if st == "pending" else "completed",
                         None if st == "pending" else st, kind="status"))
    return rows


def verdict_for(ref: str, run=None, sleep=time.sleep) -> dict:
    """The whole read and judgement for one PR reference."""
    run = run or subprocess.run
    repo, number = parse_ref(ref)
    out = {"pr": f"{repo}#{number}", "sha": None}
    try:
        pr = read_pr(repo, number, run, sleep=sleep)
        sha = str(pr.get("sha") or "").strip()
        out.update(sha=sha or None, pr_state=pr.get("state"), merged=bool(pr.get("merged")),
                   url=pr.get("url"))
        if not sha:
            return {**out, **_refused("empty-sha", "the PR read gave an empty head sha — "
                                      "refused (an empty sha matches every run in the repo)")}
        rows = collect(repo, sha, run)
    except GhError as e:
        return {**out, **_refused("unreadable", str(e))}
    state = "draft" if pr.get("draft") and pr.get("state") == "open" else pr.get("mergeable_state")
    out.update(judge(rows, mergeable_state=state, mergeable=pr.get("mergeable"),
                     pr_state=str(pr.get("state") or "open"), merged=bool(pr.get("merged"))))
    out["checks"] = rows
    return out


def _refused(code: str, detail: str) -> dict:
    return {"verdict": RED, "reasons": [{"level": RED, "code": code, "detail": detail}],
            "counts": {}, "skipped": [], "mergeable_state": None, "note": None,
            "checks": []}


def summary(v: dict) -> str:
    sha = (v.get("sha") or "")[:10] or "no sha"
    lines = [f"{v['pr']} @ {sha} — {v['verdict']}"]
    c = v.get("counts") or {}
    if c:
        lines.append(f"  checks: {c['checks']} ({c['success']} success, {c['skipped']} "
                     f"skipped, {c['red']} red, {c['pending']} pending)")
    if v.get("skipped"):
        lines.append("  skipped: " + ", ".join(v["skipped"]))
    merge = v.get("note") or f"mergeable_state {v.get('mergeable_state')}"
    lines.append(f"  merge: {merge}")
    for r in v.get("reasons") or []:
        lines.append(f"  {r['level']} {r['code']}: {r['detail']}")
    return "\n".join(lines)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"ci-verdict: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv=None, run=None, sleep=time.sleep) -> int:
    p = _Parser(prog="pyauto-brain ci-verdict",
                description="Judge one PR's CI: GREEN, PENDING or RED, with reasons. "
                            "Exit 0 GREEN, 1 RED, 2 PENDING.")
    p.add_argument("pr", help="owner/repo#N, owner/repo/pull/N or the PR URL")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    a = p.parse_args(argv)
    try:
        v = verdict_for(a.pr, run=run, sleep=sleep)
    except UsageError as e:
        print(f"ci-verdict: {e}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(v, indent=2) if a.json else summary(v))
    return EXIT[v["verdict"]]


if __name__ == "__main__":
    sys.exit(main())

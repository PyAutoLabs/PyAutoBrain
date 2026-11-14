"""The shift digest (phase 3d) — what the human reads at `review-at:`.

The format is `PyAutoMind/batches/AGENTS.md` "Digest" and "Proof packet". The
digest is built from what the watcher itself recorded during the shift — the
brief, `counters.json` (dispatch picks and their reasons, outcomes, crashes,
tokens) and the proof packets the workers wrote — plus one read-only
`gh pr checks` per PR, the only GitHub read the watcher's network surface
allows (AUTONOMY.md "The watcher's network surface — 2026-11-03"). It never
reads a session's own account of itself beyond the `.done` and proof files the
worker contract asks for, and it invents nothing: a task with no proof packet
gets a stub that says so.

`validate` is the digest half of `batch brief --check`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import _brief  # noqa: E402

# The one CI judgement (PyAutoBrain#628) lives in bin/, beside its CLI.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bin"))
import ci_verdict  # noqa: E402

DIGEST_HEADING = "## Digest"
SECTIONS = ("### Brief work", "### Backlog picks", "### Proof packets", "### Counters")
#: Every counter, always printed — a zero is a fact, an absent line is a finding.
COUNTERS = ("merges", "glance-auto-merges", "reverts", "pushes", "drafts-filed",
            "packets-sent", "workers-crashed", "tokens", "review-minutes-planned")
#: Counters only phase 4 (unattended merges) and phase 5 (RAL packets) move;
#: they read from `counters.json` and are 0 until then (human, 2026-11-04).
LATER_COUNTERS = {"glance-auto-merges": "glance_auto_merges", "reverts": "reverts",
                  "pushes": "pushes", "drafts-filed": "drafts_filed",
                  "packets-sent": "packets_sent"}
PROOFS_DIR = "proofs"
NO_PICKS = "- none"
#: What a shadow shift's line and packet section say instead of work (phase 4a).
PROPOSED = "proposed (shadow)"
NO_PACKETS_SHADOW = "- none — shadow shift: nothing was dispatched"
#: A shadow digest's counters, in one line: every one is 0 by construction.
SHADOW_COUNTERS = "- all counters 0 — shadow shift, nothing dispatched"
#: A pick line names its task in backticks after its title (`label`).
_SLUG_RE = re.compile(r"\(`([^`]+)`")
_ISSUE_RE = re.compile(r"^(https://github\.com/[^/]+/[^/]+)/issues/\d+")
#: An issue URL on a `.done` line, wherever it is hosted.
_ISSUE_URL_RE = re.compile(r"/issues/\d+")

#: The pilot ledger (phase 4a). A subfolder, because every `batches/*.md` is
#: read as a batch record (lifecycle.py, `_batch.records`, the calibration rule).
PILOT_PATH = "batches/pilot/pilot.md"
PILOT_COLUMNS = ("slot", "mode", "review-minutes-planned", "review-minutes-actual",
                 "merges", "glance-auto-merges", "reverts", "overrules", "pushes",
                 "drafts-filed", "tokens", "workers-crashed")
#: Cells only the human can fill, at check-in.
PILOT_HUMAN = ("review-minutes-actual", "overrules")
#: In a shadow shift the orchestrator merges nothing, so `merges` is the human's
#: own in the window — the baseline the live shifts are measured against
#: (epic: "the human works as today, minutes are logged"), counted at check-in.
PILOT_HUMAN_SHADOW = ("merges",)
PILOT_HEADER = ("| " + " | ".join(PILOT_COLUMNS) + " |\n"
                + "|" + "|".join("---" for _ in PILOT_COLUMNS) + "|\n")

_BULLET_RE = re.compile(r"^- (\S+)")


# --- outcomes ------------------------------------------------------------------

def parse_done(text: str) -> dict:
    """A worker's `.done` file: one PR or issue URL per line, `merged <url>` for
    a PR it merged in-turn under its tier, `obsolete <why>` when its premise
    check stopped it. An issue URL (a worker that parked on its issue with a
    question) goes in `issues`, never in `prs`: `prs` is what CI, a close-out
    and the merge count read (PyAutoBrain#610)."""
    prs, merged, issues, obsolete = [], [], [], None
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == "obsolete":
            # The worker's premise check found the task obsolete on main and
            # it stopped (worker_template.md); the rest is its evidence.
            obsolete = line.strip()[len("obsolete"):].strip(" :—-")
        elif words[0] == "merged" and len(words) > 1:
            merged.append(words[1])
            prs.append(words[1])
        elif words[0].startswith("http"):
            (issues if _ISSUE_URL_RE.search(words[0]) else prs).append(words[0])
    out = {"prs": prs, "merged": merged, "issues": issues}
    if obsolete is not None:
        out["obsolete"] = obsolete
    return out


def urls_of(outcome: dict | None) -> list[str]:
    """Every URL a `.done` named: its PRs, then the issues it parked on."""
    outcome = outcome or {}
    return list(outcome.get("prs") or []) + list(outcome.get("issues") or [])


def pr_health(url: str, run=None) -> str:
    """One read-only `gh pr checks --json`, judged by `bin/ci_verdict.py`
    (PyAutoBrain#628) — the one CI judgement `/prm` and the close-out run too.

    The watcher's network surface is `gh pr checks` only (AUTONOMY.md "The
    watcher's network surface"), so this keeps that read and hands its rows to
    `ci_verdict.judge` with mergeability not read; the close-out session runs
    the full `pyauto-brain ci-verdict`, which reads it. The words map from the
    verdict: GREEN is HEALTHY (at least one completed check, every completed
    check green — PyAutoHeart#343); a failed, cancelled or timed-out check is
    FAILED (`gh pr checks`' exit code counts a cancelled check as skipped, so
    the exit code alone is not the verdict); a bucket the judge does not know
    is UNKNOWN (fail closed); a pending check is RUNNING; no checks, or only
    skipped ones, is NO-CHECKS, which the close-out refuses — that PR is the
    human's merge."""
    if "/pull/" not in url:
        return "PARKED-ON-ISSUE"
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "checks", url, "--json", "name,bucket,state"],
                  capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    if "no checks" in ((res.stderr or "") + (res.stdout or "")).lower():
        return health_word(ci_verdict.judge([], read_mergeable=False))
    try:
        checks = json.loads(res.stdout or "")
    except ValueError:
        checks = None
    if not isinstance(checks, list):
        return "UNKNOWN"   # gh could not say (auth, network): never a pass
    return health_word(ci_verdict.judge(ci_verdict.from_pr_checks(checks),
                                        read_mergeable=False))


def health_word(verdict: dict) -> str:
    """A `ci_verdict.judge` result in the watcher's words."""
    codes = {r["code"] for r in verdict["reasons"]}
    if codes & {"check-failed", "check-cancelled", "check-timed-out"}:
        return "FAILED"
    if "check-unrecognised" in codes:
        return "UNKNOWN"
    if verdict["verdict"] == ci_verdict.PENDING:
        return "RUNNING"
    if codes & {"no-checks", "skipped-only"}:
        return "NO-CHECKS"
    return "HEALTHY" if verdict["verdict"] == ci_verdict.GREEN else "UNKNOWN"


# --- build ---------------------------------------------------------------------

def task_state(task: str, counters: dict, health, *, live: bool = False,
               lease: dict | None = None, agents=None) -> tuple[str, bool]:
    """(what a task is doing, whether its tier follows) — the one wording the
    digest and `batch watch` share, so the live view and the digest never
    disagree. Only the live view passes `live=True` (with the task's `lease`
    and the `agents` view): at `review-at:` the watcher has already reaped
    every lease, and the digest's wording stays exactly as it was. A task the
    human dropped by `/drop` (PyAutoBrain#622) says so first."""
    state, tiered = _task_state(task, counters, health, live=live, lease=lease,
                                agents=agents)
    if task not in (counters.get("dropped") or {}):
        return state, tiered
    if live and lease is not None:
        return f"dropped, still running — {state}", tiered
    if state == "not started":
        return "dropped by /drop — not started", False
    return f"dropped by /drop — {state}", tiered


def _task_state(task: str, counters: dict, health, *, live: bool = False,
                lease: dict | None = None, agents=None) -> tuple[str, bool]:
    out = counters.get("outcomes", {}).get(task)
    if counters.get("picks", {}).get(task, {}).get("proposed"):
        return PROPOSED, True
    if task in counters.get("parked", []):
        return "parked: awaiting-input (blocked on a person)", False
    if task in counters.get("abandoned", []):
        return "abandoned: crashed twice, not re-dispatched", False
    if out is None:
        if live and lease is not None:
            return _lease_state(lease, agents), True
        if live and task in counters.get("pending_redispatch", []):
            return "crashed — awaiting re-dispatch", True
        return "not started", False
    urls = urls_of(out)
    if not urls and "obsolete" in out:
        return ("obsolete (premise check): "
                + (out["obsolete"] or "see its proof packet")), False
    if not urls:
        return "finished, no PR or issue named in its .done", False
    parts = []
    closeouts = counters.get("closeouts", {})
    for url in urls:
        co = closeouts.get(url, {})
        if url in out.get("issues", []):
            state = "PARKED-ON-ISSUE"
        elif url in out["merged"]:
            state = ("merged unattended (close-out, " + co.get("model", "?") + ")"
                     if co.get("state") == "merged" else "merged")
        elif co.get("state") == "refused":
            state = f"awaiting /prm — close-out refused: {co.get('why', '?')}"
        elif co.get("state") == "running":
            state = "close-out running"
        else:
            state = health(url)
        parts.append(f"{url} — {state}")
    return "; ".join(parts), True


#: `claude agents` states for a session that has ended without succeeding. A
#: real worker in one of these with no `.done` is a crash at once — it can never
#: write one late, so it gets no grace (PyAutoBrain#592: three `failed` workers
#: held their leases for 40 minutes, read as alive). An unknown word is still
#: read as alive; add it here once seen. `_orchestrator` reaps by this set.
ENDED_STATES = frozenset({"failed", "error", "errored", "killed", "stopped",
                          "crashed", "cancelled", "canceled", "exited"})


def _lease_state(lease: dict, agents) -> str:
    """A held lease, as the live view words it (the digest never sees one)."""
    since = lease.get("started") or lease.get("heartbeat") or "?"
    if lease.get("stalled_since"):
        return f"blocked on a person since {lease['stalled_since']}"
    agent = lease.get("agent_id")
    if not agent:
        return f"running (pid {lease.get('pid', '?')}, since {since})"
    state = agents.state(agent) if agents is not None else None
    if state in ENDED_STATES:
        return f"ended ({state}, agent {agent}) — the next tick reaps it as a crash"
    if state == "blocked":
        return f"blocked on a person (agent {agent})"
    if state is None:
        return f"running? (agent {agent} not listed — inside the grace for a late .done)"
    return f"running (agent {agent}, {state}, since {since})"


def mind_blob_base(issue_url: str) -> str:
    """`https://github.com/<owner>/<mind>/blob/main/` from the brief's `issue:`
    (a Mind issue), so a pick links its prompt; "" when it cannot tell."""
    m = _ISSUE_RE.match(issue_url or "")
    return f"{m.group(1)}/blob/main/" if m else ""


def label(task: str, pick: dict | None, base: str = "") -> str:
    """How a pick is named to a human: its title, linked to its prompt, the
    task slug in backticks, then size and repos. A pick recorded before titles
    were (or with none) falls back to the bare slug."""
    pick = pick or {}
    title = pick.get("title")
    if not title:
        return task
    prompt = pick.get("prompt") or ""
    head = f"[{title}]({base}{prompt})" if base and prompt else f"**{title}**"
    details = " · ".join(x for x in (pick.get("size"), ", ".join(pick.get("repos") or [])) if x)
    return f"{head} (`{task}`" + (f"; {details}" if details else "") + ")"


def _line(task: str, counters: dict, tier: str, health, base: str = "") -> str:
    state, tiered = task_state(task, counters, health)
    name = label(task, counters.get("picks", {}).get(task), base)
    return f"- {name} — {state}" + (f" — {tier}" if tiered else "")


def _packet(task: str, slot: Path, counters: dict) -> str:
    proof = slot / PROOFS_DIR / f"{task}.md"
    if proof.is_file():
        return proof.read_text(encoding="utf-8").strip()
    prs = urls_of(counters.get("outcomes", {}).get(task)) or ["no PR"]
    return (f"#### {task} — {prs[0]}\n"
            "- claim: not supplied — the worker wrote no proof packet\n"
            "- not checked: everything; read the PR itself\n"
            "- revert: see the PR")


def build(brief: dict, slot: Path, counters: dict, *, tiers: dict | None = None,
          health=None, issue: str = "") -> str:
    """The `## Digest` block for one shift, as Markdown."""
    tiers = tiers or {}
    health = health or pr_health
    picks = counters.get("picks", {})
    named = [Path(p).stem for p in _brief.tasks_of(brief)]
    backlog = [t for t in picks if t not in named]

    lines = [DIGEST_HEADING, "", "### Brief work"]
    base = mind_blob_base(issue)
    lines += [_line(t, counters, tiers.get(t, picks.get(t, {}).get("tier", "?")), health, base)
              for t in named] or [NO_PICKS]
    lines += ["", "### Backlog picks"]
    lines += [_line(t, counters, tiers.get(t, picks[t].get("tier", "?")), health, base)
              + f" — why: {picks[t].get('why') or 'NOT RECORDED'}" for t in backlog] or [NO_PICKS]
    lines += backlog_gate_lines(counters)

    started = [t for t in named + backlog
               if t in counters.get("outcomes", {}) or t in counters.get("parked", [])
               or t in counters.get("abandoned", [])]
    lines += ["", "### Proof packets"]
    lines += ["\n\n".join(_packet(t, slot, counters) for t in started)
              or (NO_PACKETS_SHADOW if _brief.is_shadow(brief) else NO_PICKS)]

    values = counter_values(brief, counters)
    lines += ["", "### Counters"]
    if _brief.is_shadow(brief):
        lines.append(f"{SHADOW_COUNTERS} · review-minutes-planned: {values['review-minutes-planned']}")
    else:
        lines += [f"- {k}: {values[k]}" for k in COUNTERS]
        lines += ["", WORKERS_HEADING] + (worker_lines(counters, base) or [NO_PICKS])
        lines += ["", REFUSALS_HEADING] + (refusal_lines(counters) or [NO_PICKS])
    lines += identity_lines(counters)
    return "\n".join(lines) + "\n"


def identity_lines(counters: dict) -> list[str]:
    """PyAutoBrain#630: the watcher's App identity failed, so its GitHub writes
    were held — never made under the human's own gh auth instead."""
    auth = counters.get("github_auth") or {}
    if not auth.get("error"):
        return []
    return ["", f"- warning: GitHub writes held — the watcher's App token could not be "
                f"had on {auth.get('ticks', 1)} tick(s), {auth.get('first', '?')} to "
                f"{auth.get('last', '?')}: {auth['error']}"]


def backlog_gate_lines(counters: dict) -> list[str]:
    """What the M2.3 gates kept out of the backlog dip (AUTONOMY.md "M2
    rulings — 2026-11-12"), as of the watcher's last tick. Not bullets: a
    `- ` line in this section is read as a pick and must carry a `why:`."""
    gates = counters.get("backlog_gates") or {}
    out = []
    if gates.get("queue_stop"):
        out.append("Backlog dip stopped: queue.md is empty, so the shift took the "
                   "brief's named tasks only.")
    absent = gates.get("lane_absent") or []
    if absent:
        out.append(f"Lane absent: {len(absent)} draft(s) excluded — no valid `Lane:`, "
                   "and an unattended pick fails closed: "
                   + ", ".join(f"`{Path(a).stem}`" for a in absent))
    return [""] + out if out else []


# --- per-worker exits, GitHub merges, tokens (PyAutoBrain#610) -----------------

WORKERS_HEADING = "### Workers"
#: A worker's exit path is these words joined by `/` — `spawned/crashed`,
#: `spawned/parked/late/finished`. `launch-failed` stands alone: no session
#: started. `ended` is a parked worker that ended without a `.done`.
EXIT_WORDS = ("spawned", "finished", "crashed", "parked", "late", "ended",
              "launch-failed")
CRASH_WORDS = ("crashed", "launch-failed")


def worker_lines(counters: dict, base: str = "") -> list[str]:
    """One line per worker the shift started (or failed to start)."""
    picks = counters.get("picks", {})
    out = []
    for w in counters.get("workers", []):
        line = f"- {label(w['task'], picks.get(w['task']), base)} ({w.get('key') or '?'}): " \
               + "/".join(w.get("exits") or ["spawned"])
        if w.get("stalled_s"):
            line += f" — blocked {round(w['stalled_s'] / 60)} min"
        for m in w.get("mentions", []):
            line += f" — mentioned ({m.get('state', '?')})"
        out.append(line)
    poster, mentioned = counters.get("poster_login") or "", counters.get("mention_login") or ""
    if poster and poster.lower() == mentioned.lower():
        out.append(f"- warning: mention will not notify: posted as the mentioned account "
                   f"({poster}) — set the watcher's App (PYAUTO_SHIFT_APP_*) or "
                   "PYAUTO_SHIFT_GH_TOKEN")
    pushes = counters.get("pushes", 0)
    if pushes > 1:
        out.append(f"- finding: {pushes} pushes this shift — the push test budgets "
                   "about one (AUTONOMY.md)")
    return out


REFUSALS_HEADING = "### Refusals"


def refusal_lines(counters: dict) -> list[str]:
    """Every spawn the watcher refused, with its reason: one line per task and
    reason, with how many ticks refused it and when first (#610 review)."""
    seen: dict[tuple[str, str], list] = {}
    for r in counters.get("refusals", []):
        k = (r.get("task", "?"), r.get("why", "?"))
        seen.setdefault(k, [0, r.get("at", "?")])[0] += 1
    return [f"- {task} — {why} — {n}× from {at}" for (task, why), (n, at) in seen.items()]


def workers_crashed(counters: dict) -> int:
    """Workers whose exit path holds a crash (or whose launch failed); a slot
    recorded before per-worker exits falls back to its crash tally."""
    workers = counters.get("workers") or []
    if not workers:
        return counters.get("crashes", 0)
    return sum(1 for w in workers if any(x in CRASH_WORDS for x in w.get("exits") or []))


def merged_prs(counters: dict) -> list[dict]:
    """The shift's PRs that are merged, with GitHub's `mergedBy` and the merge
    actor. GitHub decides where it was read at `review-at:` (`github`, with
    `in_window`: merged at or before `review-at:`); a PR it could not say
    about falls back to what the watcher recorded (`.done` / close-out)."""
    gh_all = counters.get("github", {})
    closeouts = counters.get("closeouts", {})
    out = []
    for task, o in counters.get("outcomes", {}).items():
        for url in o.get("prs") or []:
            gh = gh_all.get(url)
            recorded = url in (o.get("merged") or [])
            if not (gh.get("in_window") if gh is not None else recorded):
                continue
            co = closeouts.get(url, {})
            actor = ("unattended-watcher" if co.get("state") == "merged"
                     else "in-turn-autonomous" if recorded else "unknown")
            by = (gh or {}).get("mergedBy") or (co.get("github") or {}).get("mergedBy") or ""
            out.append({"url": url, "task": task, "mergedBy": by, "actor": actor})
    return out


def token_parts(counters: dict) -> dict:
    """The shift's tokens by component and by session kind. `measured` is what
    was read; `total` is that sum only when every session was measured, else
    None (written `null` / `unmeasured`, never 0), with the sessions named in
    `unmeasured` — never read, or `UNREADABLE_READS` failed reads in a row."""
    parts = {"total": 0, "measured": 0, "input": 0, "output": 0, "cache_creation": 0,
             "cache_read": 0, "subagents": 0, "workers": 0, "closeouts": 0,
             "unmeasured": []}
    for key, u in sorted((counters.get("usage") or {}).items()):
        if u.get("total") is None or u.get("unmeasured"):
            parts["unmeasured"].append(key)
        if u.get("total") is None:
            continue
        parts["measured"] += int(u["total"])
        for k in ("input", "output", "cache_creation", "cache_read", "subagents"):
            parts[k] += int(u.get(k) or 0)
        parts["closeouts" if u.get("kind") == "closeout" else "workers"] += int(u["total"])
    if not counters.get("usage"):
        parts["measured"] = parts["workers"] = int(counters.get("tokens", 0) or 0)
    parts["total"] = None if parts["unmeasured"] else parts["measured"]
    return parts


def counter_values(brief: dict, counters: dict) -> dict:
    """Every digest counter's value, from the brief and `counters.json`."""
    budget = brief.get("token-budget", {}).get("value", "?")
    parts = token_parts(counters)
    tokens = f"{parts['measured']} of {budget}"
    extra = ([f"cache-read {parts['cache_read']}"] if parts["cache_read"] else []) \
        + ([f"{len(parts['unmeasured'])} session(s) unmeasured"] if parts["unmeasured"] else [])
    values = {"merges": len(merged_prs(counters)), "workers-crashed": workers_crashed(counters),
              "tokens": tokens + (f" ({'; '.join(extra)})" if extra else ""),
              "review-minutes-planned": brief.get("review-minutes", {}).get("value", "?")}
    for key, field in LATER_COUNTERS.items():
        values[key] = counters.get(field, 0)
    return values


#: The machine-readable pilot ledger: one JSON line per shift, keyed by `slot`
#: and amended in place (`amended: true`) by a late arrival — never a second
#: line. `pilot.md` is its render (`pilot_md_row`).
PILOT_JSONL = "batches/pilot/pilot.jsonl"


def pilot_record(slot_name: str, brief: dict, counters: dict, *, amended: bool = False) -> dict:
    """The shift's one `pilot.jsonl` row. Shadow merges are the human's (None)."""
    shadow = _brief.is_shadow(brief)
    v = counter_values(brief, counters)
    stall = sum(float(w.get("stalled_s") or 0) for w in counters.get("workers", []))
    cells = {k: v[k] for k in COUNTERS if k not in ("tokens", "review-minutes-planned")}
    if shadow:
        cells["merges"] = None
    return {
        "slot": slot_name, "mode": "shadow" if shadow else "live",
        "review-minutes-planned": v["review-minutes-planned"],
        "counters": cells,
        "tokens": token_parts(counters),
        "merged": [] if shadow else merged_prs(counters),
        "workers": [{"task": w["task"], "key": w.get("key"),
                     "exits": "/".join(w.get("exits") or ["spawned"]),
                     "stall_minutes": round(float(w.get("stalled_s") or 0) / 60)}
                    for w in counters.get("workers", [])],
        "stall_minutes": round(stall / 60),
        "amended": amended,
    }


def pilot_md_row(record: dict) -> str:
    """`pilot.md`'s row for one `pilot.jsonl` record; the human's cells are `?`."""
    cells = {**record["counters"], "slot": record["slot"], "mode": record["mode"],
             "review-minutes-planned": record["review-minutes-planned"],
             "tokens": record["tokens"]["total"]}
    if cells["tokens"] is None:
        cells["tokens"] = "unmeasured"
    human = PILOT_HUMAN + (PILOT_HUMAN_SHADOW if record["mode"] == "shadow" else ())
    return "| " + " | ".join("?" if c in human or cells.get(c) is None else str(cells[c])
                             for c in PILOT_COLUMNS) + " |\n"


def pilot_row(slot_name: str, brief: dict, counters: dict) -> str:
    """One `batches/pilot/pilot.md` row; the human's cells land as `?`."""
    return pilot_md_row(pilot_record(slot_name, brief, counters))


# --- validate ------------------------------------------------------------------

def _sections(text: str) -> dict[str, list[str]]:
    body = text[text.index(DIGEST_HEADING) + len(DIGEST_HEADING):]
    nxt = body.find("\n## ")
    body = body if nxt < 0 else body[:nxt]
    out: dict[str, list[str]] = {}
    current = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = line.strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def _slug(line: str) -> str:
    """The task a digest bullet is about: the backticked slug a titled pick
    carries, else the bullet's first word (a pick recorded without a title)."""
    m = _BULLET_RE.match(line)
    if not m:
        return ""
    s = _SLUG_RE.search(line.split(" — ", 1)[0])
    return s.group(1) if s else m.group(1)


def validate(text: str) -> list[str]:
    """Errors in a record's `## Digest`; empty when there is none, or it is whole."""
    if DIGEST_HEADING not in text:
        return []
    errs = []
    secs = _sections(text)
    for s in SECTIONS:
        if s not in secs:
            errs.append(f"digest: {s[4:]} section missing")
    for line in secs.get("### Backlog picks", []):
        slug = _slug(line)
        if slug and line.strip() != NO_PICKS:
            why = line.split(" — why: ", 1)
            if len(why) < 2 or not why[1].strip() or why[1].strip() == "NOT RECORDED":
                errs.append(f"digest: backlog pick {slug} has no `why:` — "
                            "every pick names the brief rule it was picked under")
    seen = {}
    for line in secs.get("### Counters", []):
        m = re.match(r"^- ([a-z-]+):\s*(\S.*)?$", line)
        if m:
            seen[m.group(1)] = (m.group(2) or "").strip()
    shadow = any(line.startswith(SHADOW_COUNTERS) for line in secs.get("### Counters", []))
    for key in (() if shadow else COUNTERS):
        if not seen.get(key):
            errs.append(f"digest: counter {key} missing")
    packets = "\n".join(secs.get("### Proof packets", []))
    for sec in ("### Brief work", "### Backlog picks"):
        for line in secs.get(sec, []):
            slug = _slug(line)
            if slug and line.strip() != NO_PICKS and "not started" not in line \
                    and PROPOSED not in line \
                    and f"#### {slug}" not in packets:
                errs.append(f"digest: {slug} has no proof packet")
    return errs

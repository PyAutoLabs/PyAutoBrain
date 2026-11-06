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

import re
import subprocess
from pathlib import Path

import _brief  # noqa: E402

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
    a PR it merged in-turn under its tier."""
    prs, merged = [], []
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if words[0] == "merged" and len(words) > 1:
            merged.append(words[1])
            prs.append(words[1])
        elif words[0].startswith("http"):
            prs.append(words[0])
    return {"prs": prs, "merged": merged}


def pr_health(url: str, run=None) -> str:
    """One read-only `gh pr checks`. Its exit code is the verdict: 0 passed,
    8 pending; anything else failed — or names why it could not say."""
    if "/pull/" not in url:
        return "PARKED-ON-ISSUE"
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "checks", url], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    if res.returncode == 0:
        return "HEALTHY"
    if res.returncode == 8:
        return "RUNNING"
    if "no checks" in (res.stderr or res.stdout or "").lower():
        return "NO-CHECKS"
    return "FAILED"


# --- build ---------------------------------------------------------------------

def task_state(task: str, counters: dict, health, *, live: bool = False,
               lease: dict | None = None, agents=None) -> tuple[str, bool]:
    """(what a task is doing, whether its tier follows) — the one wording the
    digest and `batch watch` share, so the live view and the digest never
    disagree. Only the live view passes `live=True` (with the task's `lease`
    and the `agents` view): at `review-at:` the watcher has already reaped
    every lease, and the digest's wording stays exactly as it was."""
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
    if not out["prs"]:
        return "finished, no PR or issue named in its .done", False
    parts = []
    closeouts = counters.get("closeouts", {})
    for url in out["prs"]:
        co = closeouts.get(url, {})
        if url in out["merged"]:
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
    prs = counters.get("outcomes", {}).get(task, {}).get("prs") or ["no PR"]
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
    return "\n".join(lines) + "\n"


def counter_values(brief: dict, counters: dict) -> dict:
    """Every digest counter's value, from the brief and `counters.json`."""
    budget = brief.get("token-budget", {}).get("value", "?")
    merged = sum(len(o["merged"]) for o in counters.get("outcomes", {}).values())
    values = {"merges": merged, "workers-crashed": counters.get("crashes", 0),
              "tokens": f"{counters.get('tokens', 0)} of {budget}",
              "review-minutes-planned": brief.get("review-minutes", {}).get("value", "?")}
    for key, field in LATER_COUNTERS.items():
        values[key] = counters.get(field, 0)
    return values


def pilot_row(slot_name: str, brief: dict, counters: dict) -> str:
    """One `batches/pilot/pilot.md` row; the human's cells land as `?`."""
    v = counter_values(brief, counters)
    cells = {**v, "slot": slot_name, "tokens": counters.get("tokens", 0),
             "mode": "shadow" if _brief.is_shadow(brief) else "live"}
    human = PILOT_HUMAN + (PILOT_HUMAN_SHADOW if cells["mode"] == "shadow" else ())
    return "| " + " | ".join("?" if c in human else str(cells[c])
                             for c in PILOT_COLUMNS) + " |\n"


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

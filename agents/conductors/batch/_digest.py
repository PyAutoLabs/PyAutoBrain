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

def _line(task: str, counters: dict, tier: str, health) -> str:
    out = counters.get("outcomes", {}).get(task)
    if task in counters.get("parked", []):
        return f"- {task} — parked: awaiting-input (blocked on a person)"
    if task in counters.get("abandoned", []):
        return f"- {task} — abandoned: crashed twice, not re-dispatched"
    if out is None:
        return f"- {task} — not started"
    if not out["prs"]:
        return f"- {task} — finished, no PR or issue named in its .done"
    parts = []
    for url in out["prs"]:
        state = "merged" if url in out["merged"] else health(url)
        parts.append(f"{url} — {state}")
    return f"- {task} — " + "; ".join(parts) + f" — {tier}"


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
          health=None) -> str:
    """The `## Digest` block for one shift, as Markdown."""
    tiers = tiers or {}
    health = health or pr_health
    picks = counters.get("picks", {})
    named = [Path(p).stem for p in _brief.tasks_of(brief)]
    backlog = [t for t in picks if t not in named]

    lines = [DIGEST_HEADING, "", "### Brief work"]
    lines += [_line(t, counters, tiers.get(t, picks.get(t, {}).get("tier", "?")), health)
              for t in named] or [NO_PICKS]
    lines += ["", "### Backlog picks"]
    lines += [_line(t, counters, tiers.get(t, picks[t].get("tier", "?")), health)
              + f" — why: {picks[t].get('why') or 'NOT RECORDED'}" for t in backlog] or [NO_PICKS]

    started = [t for t in named + backlog
               if t in counters.get("outcomes", {}) or t in counters.get("parked", [])
               or t in counters.get("abandoned", [])]
    lines += ["", "### Proof packets"]
    lines += ["\n\n".join(_packet(t, slot, counters) for t in started) or NO_PICKS]

    budget = brief.get("token-budget", {}).get("value", "?")
    merged = sum(len(o["merged"]) for o in counters.get("outcomes", {}).values())
    values = {"merges": merged, "workers-crashed": counters.get("crashes", 0),
              "tokens": f"{counters.get('tokens', 0)} of {budget}",
              "review-minutes-planned": brief.get("review-minutes", {}).get("value", "?")}
    for key, field in LATER_COUNTERS.items():
        values[key] = counters.get(field, 0)
    lines += ["", "### Counters"] + [f"- {k}: {values[k]}" for k in COUNTERS]
    return "\n".join(lines) + "\n"


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
        m = _BULLET_RE.match(line)
        if m and line.strip() != NO_PICKS:
            why = line.split(" — why: ", 1)
            if len(why) < 2 or not why[1].strip() or why[1].strip() == "NOT RECORDED":
                errs.append(f"digest: backlog pick {m.group(1)} has no `why:` — "
                            "every pick names the brief rule it was picked under")
    seen = {}
    for line in secs.get("### Counters", []):
        m = re.match(r"^- ([a-z-]+):\s*(\S.*)?$", line)
        if m:
            seen[m.group(1)] = (m.group(2) or "").strip()
    for key in COUNTERS:
        if not seen.get(key):
            errs.append(f"digest: counter {key} missing")
    packets = "\n".join(secs.get("### Proof packets", []))
    for sec in ("### Brief work", "### Backlog picks"):
        for line in secs.get(sec, []):
            m = _BULLET_RE.match(line)
            if m and line.strip() != NO_PICKS and "not started" not in line \
                    and f"#### {m.group(1)}" not in packets:
                errs.append(f"digest: {m.group(1)} has no proof packet")
    return errs

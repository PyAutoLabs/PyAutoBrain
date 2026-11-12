"""`batch watch` — a live terminal view of a running shift (PyAutoBrain#575).

The shift watcher (`_orchestrator`) keeps a shift's state in its slot directory
— `counters.json`, the lease files, `tick.log` — and says nothing until the
digest at `review-at:`. This verb draws that state while the shift runs: time
left, each task's state and pick reason, PR / CI health, the budgets, and the
last few ticks.

It is strictly **read-only**: it writes nothing to the slot, to Mind or to
GitHub, takes no lock and leaves no comment, so it is safe beside the ticking
timer. Its only reads beyond local files are the two the watcher itself is
allowed (AUTONOMY.md "The watcher's network surface — 2026-11-03"): one
`claude agents --json` per refresh, only on a live shift holding real worker
leases, and `gh pr checks` for PRs not yet merged, cached for the interval.

Task wording comes from `_digest.task_state`, the digest's own, so the live
view and the digest never disagree.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import time
from pathlib import Path

import _brief  # noqa: E402 — the batch conductor puts this directory on sys.path
import _digest  # noqa: E402
import _orchestrator  # noqa: E402

#: The refresh interval floor, in seconds: `gh pr checks` is not hammered.
MIN_INTERVAL_S = 30
TICK_LINES = 5
NO_TICK = "no tick yet — the watcher has not run for this brief"


class CachedHealth:
    """`_digest.pr_health`, remembered per PR for `ttl_s` seconds."""

    def __init__(self, ttl_s: float, health=None, clock=time.monotonic):
        self._ttl, self._health, self._clock = ttl_s, health or _digest.pr_health, clock
        self._seen: dict[str, tuple[float, str]] = {}

    def __call__(self, url: str) -> str:
        hit = self._seen.get(url)
        if hit and self._clock() - hit[0] < self._ttl:
            return hit[1]
        verdict = self._health(url)
        self._seen[url] = (self._clock(), verdict)
        return verdict


def _value(block: dict | None, key: str, default="?"):
    return (block or {}).get(key, {}).get("value", default)


def _ticks(slot: Path, n: int) -> list[dict]:
    try:
        lines = (slot / _orchestrator.LOG_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"action": "unreadable", "raw": line[:80]})
    return out


def _time_left(now: _dt.datetime, review_at: _dt.datetime | None) -> str:
    if review_at is None:
        return "no review-at"
    secs = int((review_at - now).total_seconds())
    if secs <= 0:
        return "closed — review-at has passed"
    h, m = divmod(secs // 60, 60)
    return (f"{h}h {m:02d}m" if h else f"{m}m") + " left"


def _opens_in(now: _dt.datetime, start: _dt.datetime) -> str:
    """Before `dispatched:` the watcher does nothing (PyAutoBrain#589)."""
    left = _time_left(now, start)
    return "not yet open — opens in " + left.replace(" left", "")


def snapshot(brief_path: Path, slot: Path, now: _dt.datetime, *, agents=None,
             health=None, tick_lines: int = TICK_LINES) -> dict:
    """Everything one refresh draws, as a dict. Reads only."""
    rec = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))
    top, brief = rec["top"], rec["brief"] or {}
    shadow = _brief.is_shadow(brief)
    try:
        review_at = _brief._iso(_value(top, "review-at", ""))
    except (ValueError, TypeError):
        review_at = None
    try:
        start = _brief._iso(_value(top, "dispatched", ""))
    except (ValueError, TypeError):
        start = None

    started = slot.is_dir()
    counters = _orchestrator.read_counters(slot) if started else {}
    held = _orchestrator.leases(slot) if started else {}
    picks = counters.get("picks", {})
    named = [Path(p).stem for p in _brief.tasks_of(brief)]
    tasks = list(dict.fromkeys(named + list(picks) + list(held)))

    if agents is None and not shadow and any(l.get("agent_id") for l in held.values()):
        agents = _orchestrator.AgentsView()  # one `claude agents --json` per refresh
    health = health or _digest.pr_health

    rows = []
    for task in tasks:
        state, _ = _digest.task_state(task, counters, health, live=True,
                                      lease=held.get(task), agents=agents)
        rows.append({"task": task, "state": state,
                     "label": _digest.label(task, picks.get(task)),
                     "tier": picks.get(task, {}).get("tier", "?"),
                     "why": "named in the brief" if task in named
                            else picks.get(task, {}).get("why") or "NOT RECORDED",
                     "redispatched": counters.get("redispatched", {}).get(task, 0)})

    values = _digest.counter_values(brief, counters)
    merges = values["merges"]
    return {
        "slot": slot.name,
        "brief": str(brief_path),
        "mode": "SHADOW" if shadow else "LIVE",
        "now": _orchestrator._iso(now),
        "dispatched": _value(top, "dispatched"),
        "review_at": _value(top, "review-at"),
        "time_left": (_opens_in(now, start) if start is not None and now < start
                      else _time_left(now, review_at)),
        "stop": (slot / _orchestrator.STOP_FILE).exists(),
        "digest_posted": (slot / _orchestrator.DIGEST_MARKER).exists(),
        "started": started,
        "tasks": rows,
        "budgets": {
            "workers": f"{sum(l.get('state') != 'parked' for l in held.values())} live of {_brief.cap_of(brief, 'max-workers')}",
            "sessions": f"{counters.get('sessions', 0)} of {_brief.cap_of(brief, 'max-sessions')}",
            "tokens": values["tokens"],
            "merges": f"{merges} of {_value(brief, 'merge-cap')}"
                      f" ({values['glance-auto-merges']} unattended)",
            "crashes": values["workers-crashed"],
        },
        "ticks": _ticks(slot, tick_lines) if started else [],
    }


def _tick_line(t: dict) -> str:
    at = (t.get("at") or "?")[11:16] + "Z" if t.get("at") else "?"
    if t.get("reason"):
        return f"  {at} {t.get('action', '?')} — {t['reason']}"
    counts = ", ".join(f"{k} {len(t[k])}" for k in ("proposed", "spawned", "reaped", "refused")
                       if isinstance(t.get(k), list))
    return f"  {at} {t.get('action', '?')}" + (f" — {counts}" if counts else "")


def render(snap: dict) -> str:
    flags = [snap["mode"], snap["time_left"]]
    if snap["stop"]:
        flags.append("STOP present — the watcher does nothing")
    if snap["digest_posted"]:
        flags.append("digest posted")
    lines = [f"Shift {snap['slot']} — " + " · ".join(flags),
             f"  {snap['dispatched']} → {snap['review_at']}   (as of {snap['now']})",
             f"  brief: {snap['brief']}", ""]
    if not snap["started"]:
        return "\n".join(lines + [NO_TICK]) + "\n"
    lines.append("Tasks")
    lines += [f"- {r['label']} — {r['state']} — {r['tier']} — why: {r['why']}"
              + (f" — re-dispatched {r['redispatched']}×" if r["redispatched"] else "")
              for r in snap["tasks"]] or ["- none yet"]
    b = snap["budgets"]
    lines += ["", "Budgets",
              f"- workers: {b['workers']}", f"- sessions: {b['sessions']}",
              f"- tokens: {b['tokens']}",
              f"- merges: {b['merges']}", f"- workers crashed: {b['crashes']}",
              "", "Last ticks"]
    lines += [_tick_line(t) for t in snap["ticks"]] or ["  none"]
    return "\n".join(lines) + "\n"


def watch(brief_path: Path, slot: Path, *, interval: float = MIN_INTERVAL_S,
          once: bool = False, out=None, sleep=time.sleep, clock=None,
          agents=None, health=None) -> int:
    """Draw the shift; with `once`, one snapshot and return. Ctrl-C ends it."""
    out = out or sys.stdout
    clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
    interval = max(float(interval), MIN_INTERVAL_S)
    health = health or CachedHealth(interval)
    try:
        while True:
            text = render(snapshot(brief_path, slot, clock(), agents=agents, health=health))
            if once:
                out.write(text)
                return 0
            out.write("\033[H\033[2J" + text + f"\n(refresh every {int(interval)} s — Ctrl-C to stop)\n")
            out.flush()
            sleep(interval)
    except KeyboardInterrupt:
        out.write("\n")
        return 0

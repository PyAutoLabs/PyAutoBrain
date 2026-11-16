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

`--stream` (`stream`, PyAutoBrain#644) prints the shift's event stream instead
— the watcher's `events.jsonl`, one plain line per event — and exits when the
shift ends. It reads local files only: no `claude agents`, no `gh`.

The same snapshot is the shift's live status comment on its issue
(`render_status`, written by the watcher, PyAutoBrain#622) and the dashboard's
`- live:` record line (`live_line`); this verb itself still writes nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import time
from pathlib import Path

import _brief  # noqa: E402 — the batch conductor puts this directory on sys.path
import _digest  # noqa: E402
import _events  # noqa: E402
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
             health=None, tick_lines: int = TICK_LINES, mind=None, issue: str = "") -> dict:
    """Everything one refresh draws, as a dict. Reads only. With the
    watcher's Mind checkout (`mind`) and the shift issue, a task with no PR
    yet links to the work issue its claim names — a local git read
    (`_digest.MindLinks`), no network (PyAutoBrain#634)."""
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
    # The caps and tasks this shift now runs under (`/cap`, `/add`, #644).
    brief = _brief.effective(brief, counters)
    added = counters.get("added") or {}
    held = _orchestrator.leases(slot) if started else {}
    picks = counters.get("picks", {})
    named = [Path(p).stem for p in _brief.tasks_of(brief)]
    tasks = list(dict.fromkeys(named + list(picks) + list(held)))

    if agents is None and not shadow and any(l.get("agent_id") for l in held.values()):
        agents = _orchestrator.AgentsView()  # one `claude agents --json` per refresh
    health = health or _digest.pr_health

    links = _digest.MindLinks(mind, issue) if mind else None
    rows = []
    for task in tasks:
        state, tiered = _digest.task_state(task, counters, health, live=True,
                                           lease=held.get(task), agents=agents)
        tier = picks.get(task, {}).get("tier", "?")
        why = ("added by /add" if task in added else "named in the brief" if task in named
               else picks.get(task, {}).get("why") or "NOT RECORDED")
        again = counters.get("redispatched", {}).get(task, 0)
        # The status comment's two-line entry (#634): no Mind prompt link —
        # a sha-pinned link would change on every Mind commit and force an
        # edit each time; the digest carries it.
        entry = _digest.entry_lines(
            task, picks.get(task), state, tiered, tier,
            _digest.work_link(task, counters, links),
            why=why if task in added else "" if task in named else why,
            extra=[f"re-dispatched {again}×"] if again else [])
        rows.append({"task": task, "state": state,
                     "label": _digest.label(task, picks.get(task)),
                     "tier": tier, "why": why, "redispatched": again,
                     "entry": entry})

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
        # Steering (PyAutoBrain#622): a pause, the dropped tasks, every command
        # enacted with its acknowledgement, and where the status comment is.
        "paused": counters.get("paused") or None,
        "dropped": sorted(counters.get("dropped") or {}),
        "commands": list(counters.get("commands") or []),
        "commands_unread": counters.get("commands_unread") or "",
        "refusals": _digest.refusal_lines(counters) if started else [],
        "status_url": _orchestrator.status_url(slot) if started else "",
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


def _flags(snap: dict) -> list[str]:
    flags = [snap["mode"], snap["time_left"]]
    if snap["stop"]:
        flags.append("STOP present — the watcher does nothing")
    if snap.get("paused"):
        flags.append(f"PAUSED by {snap['paused'].get('by', '?')} — /resume to continue")
    if snap["digest_posted"]:
        flags.append("digest posted")
    return flags


def _steering_lines(snap: dict) -> list[str]:
    """Refusals and commands, as bullets; only the sections that have any."""
    lines = []
    if snap.get("refusals"):
        lines += ["", "Refusals"] + snap["refusals"]
    if snap.get("commands"):
        lines += ["", "Commands"] + [f"- `{c['command']}` by {c['by']} at {c['at']} — {c['ack']}"
                                     for c in snap["commands"]]
    return lines


def render(snap: dict) -> str:
    flags = _flags(snap)
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
              f"- merges: {b['merges']}", f"- workers crashed: {b['crashes']}"]
    lines += _steering_lines(snap)
    if snap.get("status_url"):
        lines += ["", f"Status comment: {snap['status_url']}"]
    lines += ["", "Last ticks"]
    lines += [_tick_line(t) for t in snap["ticks"]] or ["  none"]
    return "\n".join(lines) + "\n"


# --- the live status comment and the dashboard line (PyAutoBrain#622) -----------

COMMAND_HELP = ("Steer it with a comment from the human's login, its first line one of: "
                "`/pause`, `/resume`, `/drop <task>`, `/stop`, `/add <prompt>`, "
                "`/cap merges|workers|sessions|tokens <n>`, `/kill <task>`.")


def render_status(snap: dict) -> str:
    """The shift's live status comment: the `render` snapshot as Markdown,
    without the tick log. It never names a login with `@` — an edit must not
    notify (AUTONOMY.md push test)."""
    lines = [f"**Shift `{snap['slot']}` — " + " · ".join(_flags(snap)) + "**",
             f"{snap['dispatched']} → {snap['review_at']} (as of {snap['now']}; "
             "this comment is edited in place, never re-posted)", "", "**Tasks**"]
    lines += [line for r in snap["tasks"] for line in r["entry"]] or ["- none yet"]
    b = snap["budgets"]
    lines += ["", "**Budgets**", f"- workers: {b['workers']}", f"- sessions: {b['sessions']}",
              f"- tokens: {b['tokens']}", f"- merges: {b['merges']}",
              f"- workers crashed: {b['crashes']}"]
    for line in _steering_lines(snap):
        lines.append(f"**{line}**" if line in ("Refusals", "Commands") else line)
    if snap.get("commands_unread"):
        lines += ["", f"_Commands could not be read at {snap['commands_unread']}; "
                      "the next tick reads again._"]
    if snap.get("commands_on", True) and not snap["digest_posted"]:
        lines += ["", COMMAND_HELP]
    elif not snap.get("commands_on", True) and not snap["digest_posted"]:
        lines += ["", "_Steering is off: no human login is set (`PYAUTO_SHIFT_MENTION` "
                      "or `shift_watcher: mention_login:`)._"]
    return "\n".join(lines).replace("@", "@\u200b") + "\n"


def status_key(snap: dict) -> str:
    """What makes a status edit due at once: the snapshot without its clock,
    its token figure and its tick log — those refresh every
    `_orchestrator.STATUS_REFRESH_S` instead."""
    keep = {k: v for k, v in snap.items()
            if k not in ("now", "time_left", "ticks", "budgets", "status_url")}
    keep["budgets"] = {k: v for k, v in snap["budgets"].items() if k != "tokens"}
    keep["refusals"] = [r.rsplit(" — ", 1)[0] for r in snap.get("refusals") or []]
    keep["commands_unread"] = bool(snap.get("commands_unread"))
    return json.dumps(keep, sort_keys=True, default=str)


def live_line(snap: dict) -> tuple[str, str]:
    """The dashboard's one-line copy of the status (the brief record's
    `- live:` key), and the part of it whose change rewrites it."""
    states = [r["state"] for r in snap["tasks"]]
    counts = {
        "running": sum(s.startswith(("running", "dropped, still running")) for s in states),
        "blocked or parked": sum(s.startswith(("blocked", "parked")) for s in states),
        "finished": sum("github.com" in s or s.startswith(("finished", "obsolete"))
                        for s in states),
        "dropped": len(snap.get("dropped") or []),
        "refusal reasons": len(snap.get("refusals") or []),
    }
    head = [snap["mode"]] + (["STOPPED"] if snap["stop"] else []) \
        + (["PAUSED"] if snap.get("paused") else []) \
        + [", ".join(f"{n} {k}" for k, n in counts.items() if n) or "nothing started"]
    key = " · ".join(head) + (f" — status: {snap['status_url']}" if snap.get("status_url") else "")
    line = (" · ".join(head) + f" · tokens {snap['budgets']['tokens']}"
            + f" · review-at {snap['review_at']} (as of {snap['now']})"
            + (f" — status: {snap['status_url']}" if snap.get("status_url") else ""))
    return " ".join(line.split()), key


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


# --- `batch watch --stream`: the shift's event stream (PyAutoBrain#644) -----------

#: The env file the watcher's systemd unit reads; the stream reads the same
#: brief and home from it, so the two agree on the slot.
ENV_FILE = Path.home() / ".config" / "pyauto" / "orchestrator.env"
#: Seconds between two reads of `events.jsonl` (a local stat and read).
STREAM_POLL_S = 5
#: The stream may attach this long before `dispatched:` …
ATTACH_BEFORE_S = 30 * 60
#: … and runs until this long after `review-at:` (the late-sweep window,
#: human ruling H2).
LATE_WINDOW_S = 45 * 60
#: Events printed on attach without `--from`.
CATCH_UP = 5
#: Exit codes: done (shift over, STOP, window), refused, segment over.
RC_DONE, RC_REFUSED, RC_SEGMENT = 0, 2, 3


def env_file(path: Path | None = None) -> dict[str, str]:
    """`KEY=VALUE` lines of the orchestrator env file; {} when absent."""
    out = {}
    try:
        text = Path(path or ENV_FILE).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _window(record: Path) -> tuple:
    rec = _brief.parse(Path(record).read_text(encoding="utf-8"))
    top = rec["top"]
    start = _brief._iso(_value(top, "dispatched", ""))
    end = _brief._iso(_value(top, "review-at", ""))
    return start, end


def attachable(record: Path, slot: Path, now: _dt.datetime,
               from_seq: int | None = None) -> tuple[bool, str]:
    """(may the stream run now?, why not). Window: `dispatched:` − 30 min to
    `review-at:` + 45 min; never with `STOP` present, nor after `shift-end` —
    unless `from_seq` is before it: a cockpit re-attaching with `--from`
    still gets the lines it missed, the digest and `shift-end`, then exits."""
    try:
        start, end = _window(record)
    except (OSError, _brief.BriefError) as e:
        return False, f"unreadable record {record} ({e})"
    if start is None or end is None:
        return False, f"{Path(record).name} has no dispatched:/review-at: to watch between"
    if now < start - _dt.timedelta(seconds=ATTACH_BEFORE_S):
        opens = start - _dt.timedelta(seconds=ATTACH_BEFORE_S)
        return False, f"shift {slot.name} not open yet: attach from {opens:%H:%M}Z"
    if now > end + _dt.timedelta(seconds=LATE_WINDOW_S):
        return False, f"shift {slot.name} watch window is over (review-at + 45 min)"
    if (slot / _orchestrator.STOP_FILE).exists():
        return False, f"STOP present in {slot}: the watcher does nothing"
    end_seq = next((e["seq"] for e in _events.read_events(slot)
                    if e.get("kind") == "shift-end"), None)
    if end_seq is not None and (from_seq is None or from_seq >= end_seq):
        return False, f"shift {slot.name} is over (shift-end written)"
    return True, ""


def attach_summary(record: Path, slot: Path) -> str:
    """One line from `counters.json` and the leases: live workers, merges of
    the cap, tokens of the budget, paused. Local files only — no `claude
    agents`, no `gh` (a test holds it to that)."""
    if not (slot / _orchestrator.COUNTERS_FILE).exists():
        return "no tick yet — the watcher has not run for this brief"
    counters = _orchestrator.read_counters(slot)
    brief = _brief.parse(Path(record).read_text(encoding="utf-8"))["brief"] or {}
    brief = _brief.effective(brief, counters)
    held = _orchestrator.leases(slot)
    live = sum(1 for l in held.values() if l.get("state") != "parked")
    values = _digest.counter_values(brief, counters)
    parts = [f"{live} worker{'s' if live != 1 else ''} live of "
             f"{_brief.cap_of(brief, 'max-workers')}",
             f"{values['merges']} merged of merge-cap {_value(brief, 'merge-cap')}",
             f"tokens {values['tokens']}"]
    if counters.get("paused"):
        parts.append(f"PAUSED by {counters['paused'].get('by', '?')}")
    return ", ".join(parts)


def _render_event(e: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(e, sort_keys=True, ensure_ascii=False)
    return f"{_events._hhmm(e.get('at') or '')} " + ("NEEDS YOU: " if e.get("needs_you") else "") \
        + str(e.get("line") or "")


class _Tail:
    """`events.jsonl`, read from a byte offset: complete lines only, so a
    line still being written is read on the next poll."""

    def __init__(self, path: Path):
        self.path, self.offset = Path(path), 0

    def read(self) -> list[dict]:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                data = fh.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []
        self.offset += end + 1
        out = []
        for raw in data[:end].split(b"\n"):
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if isinstance(e, dict) and isinstance(e.get("seq"), int):
                out.append(e)
        return out


def stream(record: Path, slot: Path, *, from_seq: int | None = None,
           for_min: float | None = None, as_json: bool = False, check: bool = False,
           out=None, err=None, clock=None, sleep=time.sleep,
           poll_s: float = STREAM_POLL_S) -> int:
    """`batch watch --stream`: the shift's events as they land, one line each.

    Refuses (exit 2, one line on stderr) outside the watch window, with `STOP`
    present, or once `shift-end` is written; `check` stops there (exit 0:
    attachable now). Then `attached <slot>: <summary>`, the last
    `CATCH_UP` events (or every one after `from_seq`), and each new one as
    `HH:MMZ <line>` (`NEEDS YOU: ` first when it needs the human; the raw
    object with `as_json`). Exit 0 on `shift-end` (or `/stop`'s `stopped`), on
    a hand-written `STOP`, or when the window closes; exit 3 after `for_min`
    minutes, with `segment-end next=--from <seq>` — the one exit after which
    the cockpit attaches again."""
    out, err = out or sys.stdout, err or sys.stderr
    clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
    record, slot = Path(record), Path(slot)
    began = clock()
    ok, why = attachable(record, slot, began, from_seq)
    if not ok:
        err.write(f"batch watch --stream: {why}\n")
        return RC_REFUSED
    if check:
        out.write(f"attachable: {slot.name} ({slot})\n")
        return RC_DONE
    _start, end = _window(record)
    closes = end + _dt.timedelta(seconds=LATE_WINDOW_S)
    tail = _Tail(slot / _events.EVENTS_FILE)
    first = tail.read()
    last = max((e["seq"] for e in first), default=0)
    shown = [e for e in first if e["seq"] > from_seq] if from_seq is not None \
        else first[-CATCH_UP:]
    if from_seq is not None:
        last = max(last, from_seq)
    lines = [f"attached {slot.name}: {attach_summary(record, slot)}"]
    lines += [_render_event(e, as_json) for e in shown]
    out.write("\n".join(lines) + "\n")
    out.flush()
    if any(e.get("kind") in _events.FINAL_KINDS for e in shown):
        return RC_DONE
    stop_seen = any(e.get("kind") == "stopped" for e in first)
    while True:
        new = tail.read()
        if new:
            last = max(last, max(e["seq"] for e in new))
            out.write("\n".join(_render_event(e, as_json) for e in new) + "\n")
            out.flush()
            if any(e.get("kind") in _events.FINAL_KINDS for e in new):
                return RC_DONE
        now = clock()
        if (slot / _orchestrator.STOP_FILE).exists() and not stop_seen:
            out.write(f"{now:%H:%M}Z STOP file present: the watcher does nothing. "
                      "Watch ended.\n")
            out.flush()
            return RC_DONE
        if now > closes:
            out.write(f"{now:%H:%M}Z Watch window over (review-at + 45 min). "
                      "Run /prm or read the digest.\n")
            out.flush()
            return RC_DONE
        if for_min is not None and (now - began).total_seconds() >= for_min * 60:
            out.write(f"segment-end next=--from {last}\n")
            out.flush()
            return RC_SEGMENT
        sleep(poll_s)

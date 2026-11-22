"""The shift's event stream: one append-only `events.jsonl` per slot, beside
`counters.json` and `tick.log`.

The watcher calls `record_tick` inside its tick lock, once per tick that did
work, with the tick's result. It renders each new event as one plain sentence
(`line`) and appends one JSON object per event. `batch watch --stream`
(`_watch.stream`) prints the file; the cockpit chat watches that.

No new reads and no LLM: the deriver reads the tick's `result`,
`counters.json`, the slot's own files and `events.state.json`. It makes no
subprocess call and no network call (a test holds it to that).

Dedup lives in the file itself: every event has a `key`, and an event whose
key is already in `events.jsonl` is never written again. The next `seq` is the
file's last plus one. A crash between the append and the state write can
therefore neither repeat an event nor reuse a `seq`; losing
`events.state.json` costs at most one repeated `ci` line (its key still
dedups it). All the lines of one tick go out in one `write()`, each line at
most `RECORD_MAX` bytes, and a reader ignores a last line with no newline.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path

import _digest  # noqa: E402 — the batch conductor puts this directory on sys.path
import _login  # noqa: E402 — its wording only; the probe runs in the tick, not here

EVENTS_FILE = "events.jsonl"
STATE_FILE = "events.state.json"
SCHEMA = 1
#: The printed sentence, at most this many characters.
LINE_MAX = 300
#: One JSON line, at most this many bytes (one local append, never torn).
RECORD_MAX = 1024
#: A dedup key, at most this many characters: stored and compared truncated
#: alike, so a long key can never repeat on every tick.
KEY_MAX = 200
#: CI verdicts that make a `ci` line; RUNNING never does, UNKNOWN is skipped
#: ("gh could not say" — the tick asks again).
CI_EMIT = ("HEALTHY", "FAILED", "NO-CHECKS")
#: Ticks in a row with the commands read failing before `steer-unread`.
UNREAD_TICKS = 3
#: Every kind `record_tick` may write (DESIGN §1.4).
KINDS = ("shift-open", "spawned", "redispatched", "crashed", "pr-opened", "finished",
         "question", "parked", "ci", "closeout-started", "merged", "merged-outside",
         "refused", "cap", "steer", "steer-unread", "impaired", "late", "digest",
         "stopped", "shift-end", "login-expired", "waiting")
#: The kinds after which the stream has nothing more to follow.
FINAL_KINDS = ("shift-end", "stopped")

_GH_RE = re.compile(r"^https://github\.com/[^/\s]+/([^/\s]+)/(?:pull|issues)/(\d+)")
_LATE_TAIL_RE = re.compile(r"\s*\(after review-at, [^)]*\)\s*$")
#: Close-out refusals whose reason is the shift's, not the PR's: one `cap`
#: line per class, then silence (DESIGN §1.4, `cap`).
_CLOSEOUT_CAP_RE = re.compile(r"^(merge-cap \d+ reached|token spend reached)")


# --- reading -----------------------------------------------------------------------

def read_events(slot: Path) -> list[dict]:
    """Every complete event in the slot's file, in order. A last line with no
    newline (a write in progress) and a line that is not JSON are skipped."""
    try:
        data = (Path(slot) / EVENTS_FILE).read_bytes()
    except OSError:
        return []
    out = []
    for raw in data.split(b"\n")[:-1]:   # the part after the last newline is not a line yet
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("seq"), int):
            out.append(e)
    return out


def _read_state(slot: Path) -> dict:
    try:
        s = json.loads((Path(slot) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    if not isinstance(s, dict):
        s = {}
    s.setdefault("ci", {})
    s.setdefault("unread_run", 0)
    return s


def _write_state(slot: Path, state: dict) -> None:
    tmp = Path(slot) / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, Path(slot) / STATE_FILE)


def _read_counters(slot: Path) -> dict:
    try:
        c = json.loads((Path(slot) / "counters.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    return c if isinstance(c, dict) else {}


# --- wording -----------------------------------------------------------------------

def ref(url: str) -> str:
    """`Repo#n` for a GitHub PR or issue URL; the URL itself otherwise."""
    m = _GH_RE.match(url or "")
    return f"{m.group(1)}#{m.group(2)}" if m else (url or "?")


def _hhmm(iso: str) -> str:
    return iso[11:16] + "Z" if iso and len(iso) >= 16 else (iso or "?")


def _clean(text: str) -> str:
    """One line, no `@` that could notify (written `@​`, as the status
    comment does), at most `LINE_MAX` characters."""
    text = " ".join(str(text).split()).replace("@", "@​")
    return text if len(text) <= LINE_MAX else text[:LINE_MAX - 1] + "…"


def _label(task: str, pick: dict | None) -> str:
    title = (pick or {}).get("title")
    return f"{title} ({task})" if title else task


# --- the deriver -------------------------------------------------------------------

class _Batch:
    """One tick's new events, deduplicated against the file and each other."""

    def __init__(self, slot: Path, now: _dt.datetime, existing: list[dict]):
        self.slot, self.now = Path(slot), now
        self.keys = {e.get("key") for e in existing}
        self.seq = max((e["seq"] for e in existing), default=0)
        self.events: list[dict] = []
        self.existing = existing

    def has(self, key: str) -> bool:
        return key in self.keys

    def add(self, kind: str, key: str, line: str, *, needs_you: bool = False, **extra) -> None:
        key = key[:KEY_MAX]
        if key in self.keys:
            return
        self.keys.add(key)
        self.seq += 1
        e = {"v": SCHEMA, "seq": self.seq,
             "at": self.now.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "slot": self.slot.name, "kind": kind, "key": key,
             "line": _clean(line), "needs_you": bool(needs_you)}
        for k, v in extra.items():
            if v not in (None, "", [], {}):
                e[k] = v if not isinstance(v, str) else v[:300]
        self.events.append(e)

    def runs(self, task: str) -> int:
        """How many workers this shift started for `task`, as the file knows."""
        return sum(1 for k in self.keys if k == f"spawned:{task}"
                   or (k or "").startswith(f"redispatched:{task}"))

    def count(self, prefix: str) -> int:
        return sum(1 for k in self.keys if (k or "").startswith(prefix))


def _inboxed(counters: dict, task: str, issue: str | None = None) -> bool:
    """Whether this tick's reap filed `task`'s question (on `issue`) in the
    questions inbox (`counters["inbox"]`)."""
    return any(q.get("task") == task and (issue is None or q.get("issue") == issue)
               for q in counters.get("inbox") or [])


def _outcome(event: dict, counters: dict) -> dict:
    """A `done` reap's outcome: the event's own fields, else the task's
    outcome in `counters` (a replayed `tick.log` event without them)."""
    fields = ("prs", "merged", "questions", "obsolete", "verdicts", "issues")
    if any(k in event for k in fields):
        return {k: event[k] for k in fields if k in event}
    return dict((counters.get("outcomes") or {}).get(event.get("task"), {}) or {})


def _reaped(b: _Batch, result: dict, counters: dict) -> None:
    picks = counters.get("picks") or {}
    dropped = counters.get("dropped") or {}
    for e in result.get("reaped") or []:
        task, ev = e.get("task"), e.get("event")
        if not task:
            continue
        run = max(b.runs(task), 1)
        if ev == "dead":
            by_kill = bool(e.get("killed"))
            what = "stopped by /kill" if by_kill else "died"
            if task in dropped:
                tail = "It is not restarted: you dropped it."
            elif str(e.get("redispatch", "")).startswith("allowed"):
                tail = "It restarts once."
            else:
                tail = "Retry spent: left for your /prm."
            b.add("crashed", f"crashed:{task}:{run}", f"Worker on {task} {what}. {tail}",
                  task=task)
        elif ev == "parked":
            since = str(e.get("why") or "").replace("blocked since ", "")
            filed = _inboxed(counters, task)
            b.add("parked", f"parked:{task}:{run}",
                  f"{task} is stuck at a prompt (since {_hhmm(since)})."
                  + (" Added to your inbox." if filed else ""), task=task,
                  inbox=filed or None)
        elif ev == "done":
            o = _outcome(e, counters)
            merged = list(o.get("merged") or [])
            tier = (picks.get(task) or {}).get("tier") or "?"
            for pr in o.get("prs") or []:
                if pr in merged or "/pull/" not in pr:
                    continue
                how = ("glance: close-out when CI is green" if tier == "glance"
                       else f"{tier}: your /prm")
                b.add("pr-opened", f"pr-opened:{pr}", f"{task} opened {ref(pr)} ({how}).",
                      task=task, pr=pr)
            for pr in merged:
                b.add("merged", f"merged-in-turn:{pr}",
                      f"{task} merged {ref(pr)} in-turn (notify).", task=task, pr=pr)
            questions = [] if "obsolete" in o else list(o.get("questions") or [])
            for q in questions:
                # "Added to your inbox" only when the watcher filed it: a merged
                # task's question, or one it could not file, is not.
                filed = _inboxed(counters, task, q)
                b.add("question", f"question:{task}:{q}",
                      f"{task} parked with a question on {ref(q)}."
                      + (" Added to your inbox." if filed else ""), task=task, url=q,
                      inbox=filed or None)
            if "obsolete" in o or o.get("verdicts") or not (o.get("prs") or questions):
                if "obsolete" in o:
                    state = "obsolete (premise check)"
                elif o.get("verdicts"):
                    state = "verdict posted"
                else:
                    state = "finished, no PR or issue named in its .done"
                b.add("finished", f"finished:{task}:{run}",
                      f"{task} finished: {_digest.plain_outcome(state)}.", task=task,
                      url=(o.get("verdicts") or [""])[0])


def _steer(b: _Batch, result: dict, counters: dict) -> None:
    for c in result.get("commands") or []:
        cmd = "/" + str(c.get("command") or "?") + (f" {c['arg']}" if c.get("arg") else "")
        by = c.get("by") or next((x.get("by") for x in counters.get("commands") or []
                                  if x.get("command") == cmd and x.get("ack") == c.get("ack")),
                                 "") or "the human"
        ack = str(c.get("ack") or "")
        key = f"steer:{c['id']}" if c.get("id") else f"steer:{b.now.isoformat()}:{cmd}"
        b.add("steer", key, f"{cmd} from {by}: {ack}",
              needs_you=ack.startswith(("ignored", "refused")), url=c.get("url"))


def _spawned(b: _Batch, result: dict, counters: dict) -> None:
    picks = counters.get("picks") or {}
    added = counters.get("added") or {}
    for s in result.get("spawned") or []:
        task = s.get("task")
        if not task:
            continue
        runs = b.runs(task)
        if runs:
            key = f"redispatched:{task}" + (f":{runs + 1}" if runs > 1 else "")
            b.add("redispatched", key, f"Restarted {task} (its one retry).", task=task)
            continue
        pick = picks.get(task) or {}
        why = "added by /add" if task in added else (pick.get("why") or "named in the brief")
        b.add("spawned", f"spawned:{task}",
              f"Started {_label(task, pick)} ({pick.get('tier') or '?'}; {why}).", task=task)


def _refused(b: _Batch, result: dict) -> None:
    wide: dict[str, list[str]] = {}
    for r in result.get("refused") or []:
        cls = _digest.refusal_class(r.get("why", ""))
        if _digest.SHIFT_WIDE_RE.match(cls):
            wide.setdefault(cls, []).append(r.get("task") or "?")
            continue
        task = r.get("task") or "?"
        b.add("refused", f"refused:{task}:{cls}", f"{task} not started: {cls}.",
              task=task, cls=cls)
    for cls, tasks in wide.items():
        n = len(tasks)
        b.add("cap", f"cap:{cls}", f"{cls}: {n} task{'s' if n != 1 else ''} wait.", cls=cls)


def _ci(b: _Batch, result: dict, state: dict) -> None:
    """A `ci` line when a PR's verdict changes to HEALTHY, FAILED or
    NO-CHECKS — again after any change, e.g. green, then a new push RUNNING,
    then red or green once more. The key carries how many `ci` lines the PR
    already has, so each transition is its own key; with the state file
    lost, the last verdict comes from the file's own `ci` lines (at most one
    repeated line)."""
    for pr, verdict in sorted((result.get("health") or {}).items()):
        if verdict == "UNKNOWN":
            continue
        mine = [e for e in b.existing + b.events if e.get("kind") == "ci" and e.get("pr") == pr]
        last = state["ci"].get(pr, mine[-1].get("verdict") if mine else None)
        state["ci"][pr] = verdict
        if verdict not in CI_EMIT or verdict == last:
            continue
        line = {"HEALTHY": f"CI green on {ref(pr)}.",
                "FAILED": f"CI red on {ref(pr)}: never merged unattended.",
                "NO-CHECKS": f"No CI checks on {ref(pr)}: left for your /prm."}[verdict]
        b.add("ci", f"ci:{pr}:{len(mine) + 1}:{verdict}", line, pr=pr, verdict=verdict)


def _closeouts(b: _Batch, result: dict, counters: dict, info: dict) -> None:
    co_all = counters.get("closeouts") or {}
    dropped = counters.get("dropped") or {}
    events = result.get("closeouts") or {}
    outside = set(events.get("merged_outside") or [])
    cap = info.get("merge_cap", "?")
    for pr in events.get("merged") or []:
        co = co_all.get(pr) or {}
        k = b.count("merged:") + 1
        b.add("merged", f"merged:{pr}",
              f"Merged {ref(pr)} unattended ({k} of merge-cap {cap}).",
              task=co.get("task"), pr=pr)
    for pr in sorted(outside):
        co = co_all.get(pr) or {}
        login = ((co.get("github") or {}).get("mergedBy")) or "?"
        b.add("merged-outside", f"merged-outside:{pr}",
              f"{ref(pr)} was merged outside the close-out (by {login}).",
              needs_you=co.get("task") in dropped, task=co.get("task"), pr=pr)
    _ci(b, result, b.state)
    for pr in events.get("refused") or []:
        if pr in outside:
            continue
        co = co_all.get(pr) or {}
        cls = _digest.refusal_class(co.get("why") or "refused")
        wide = _CLOSEOUT_CAP_RE.match(cls)
        if wide:
            b.add("cap", f"cap:{wide.group(1)}",
                  f"{cls.removesuffix(' this shift')}: later green PRs wait for /prm.",
                  cls=cls)
            continue
        # Merge order: later PRs of the shift wait behind it.
        later = sum(1 for w in (counters.get("merge_waits") or {}).values()
                    if pr in (w.get("behind") or []))
        tail = f"; {later} later PR(s) wait behind it" if later else ""
        b.add("refused", f"refused:{pr}",
              f"Not merging {ref(pr)}: {cls}. Left for your /prm{tail}.",
              task=co.get("task"), pr=pr, cls=cls)
    for pr in events.get("waiting") or []:
        w = (counters.get("merge_waits") or {}).get(pr) or {}
        behind = w.get("behind") or []
        b.add("waiting", f"waiting:{pr}:{','.join(behind)}",
              f"{ref(pr)} waits behind {', '.join(map(ref, behind)) or '?'}: "
              f"merge {ref(behind[0]) if behind else '?'} first.",
              task=w.get("task"), pr=pr)
    for pr in events.get("started") or []:
        co = co_all.get(pr) or {}
        if co.get("kind") == "update":
            line = (f"Branch update started on {ref(pr)} (after "
                    f"{', '.join(map(ref, co.get('after') or [])) or '?'} merged).")
        else:
            line = f"Close-out started on {ref(pr)}."
        b.add("closeout-started", f"closeout-started:{pr}:{co.get('started', '')}", line,
              task=co.get("task"), pr=pr)


def _impaired(b: _Batch, result: dict) -> None:
    auth = result.get("github_auth") or {}
    if auth.get("error"):
        b.add("impaired", "impaired:github-auth",
              f"Watcher can't post to GitHub ({str(auth['error'])[:160]}). Writes held.",
              needs_you=True)
    for ledger in (result.get("ledger"), (result.get("status") or {}).get("ledger")):
        if not isinstance(ledger, dict):
            continue
        if ledger.get("error"):
            why = str(ledger["error"])[:160]
            b.add("impaired", f"impaired:ledger-error:{why[:80]}",
                  f"Mind write failed: {why}.", needs_you=True)
        # A mechanical set-aside (already true on main) is a digest line only;
        # a worker's human set-asides are one NEEDS YOU per task.
        by_task: dict = {}
        per_op = []
        for x in ledger.get("set_aside") or []:
            if isinstance(x, dict) and x.get("needs") == "mechanical":
                continue
            if isinstance(x, dict) and isinstance(x.get("task"), str) and x["task"]:
                by_task.setdefault(x["task"], []).append(x)
            else:
                per_op.append(("set aside", x))
        for task, xs in sorted(by_task.items()):
            paths = ", ".join(sorted({str(x.get("path") or x.get("op") or "?") for x in xs}))
            n = len(xs)
            tail = ("; its completion record is held — not shipped to Mind"
                    if any(x.get("kind") == "withheld" for x in xs) else
                    "; its completion record is already on main — check it"
                    if any(x.get("record") == "on-main" for x in xs) else "")
            b.add("impaired", f"impaired:ledger:task:{task}",
                  f"Mind write set aside for `{task}`: {n} op{'s' if n != 1 else ''} "
                  f"({paths}){tail}.", needs_you=True, task=task)
        per_op += [("held", x) for x in ledger.get("held") or []]
        for word, x in per_op:
            op = x.get("op") if isinstance(x, dict) else str(x)
            why = (x.get("why") if isinstance(x, dict) else "") or "?"
            where = x.get("file") if isinstance(x, dict) else ""
            b.add("impaired", f"impaired:ledger:{word}:{where or op}:{str(why)[:60]}",
                  f"Mind write {word}: {op}, {why}.", needs_you=True)


def _login_expired(b: _Batch, result: dict) -> None:
    """The CLI login has expired: its own needs-you event, once per episode
    (keyed by when the tick first saw it) — never read as a worker blocked
    on a person."""
    login = result.get("login") or {}
    if login.get("state") != "expired":
        return
    since = login.get("since") or login.get("at") or b.now.isoformat()
    b.add("login-expired", f"login-expired:{since}",
          (login.get("detail", "Codex login required") if login.get("backend") == "codex"
           else _login.EXPIRED_LINE) + ". No worker starts until it passes.", needs_you=True)


def _late(b: _Batch, result: dict) -> None:
    for line in result.get("late") or []:
        text = _LATE_TAIL_RE.sub("", str(line).removeprefix("- late: ").strip())
        b.add("late", f"late:{text[:200]}", f"Late arrival: {text} after review-at.")


def _digest_event(b: _Batch, result: dict, counters: dict) -> None:
    post = result.get("post") or {}
    parked = [t for t, o in (counters.get("outcomes") or {}).items()
              if isinstance(o, dict) and o.get("questions") and "obsolete" not in o
              and not o.get("merged")]
    parked += [t for t in counters.get("parked") or [] if t not in parked]
    filed = len(counters.get("inbox") or [])
    tail = (f" {filed} question{'s' if filed != 1 else ''} added to your inbox."
            if filed else
            f" {len(parked)} task{'s' if len(parked) != 1 else ''} parked on a question."
            if parked else "")
    # The shift ended before review-at: the line says so.
    closed = "Shift closed early." if counters.get("closed_early") else "Shift closed."
    if post.get("url"):
        b.add("digest", "digest", f"{closed} Digest: {post['url']}.{tail}", url=post["url"])
    else:
        why = post.get("error") or "not posted"
        b.add("digest", "digest", f"{closed} Digest written to the record; its post: "
                                  f"{why}.{tail}")


def record_tick(slot: Path, now: _dt.datetime, result: dict, counters: dict | None = None,
                *, info: dict | None = None, quiet: bool | None = None) -> list[dict]:
    """Append this tick's new events to `<slot>/events.jsonl`; returns them.

    `result` is what the tick returned (and logs). `counters` defaults to the
    slot's `counters.json` (a replay passes its own). `info` carries what the
    record says about the shift (`review_at`, `named`, `merge_cap`,
    `token_budget`), for the `shift-open` and `merged` lines. `quiet` is
    whether nothing is left for the late sweep (no lease, no queued op, no
    close-out out, nothing unreported, no post due): on a digest or late-sweep
    tick it writes `shift-end`. Called by the watcher inside its tick lock."""
    slot = Path(slot)
    info = info or {}
    counters = counters if counters is not None else _read_counters(slot)
    existing = read_events(slot)
    b = _Batch(slot, now, existing)
    b.state = _read_state(slot)
    action = result.get("action")

    if action in ("ticked", "shadow") and not existing:
        n = info.get("named")
        parts = [f"Shift {slot.name} open until {_hhmm(info.get('review_at') or '')}"]
        bits = ([f"{n} named task{'s' if n != 1 else ''}"] if n is not None else []) \
            + [f"merge-cap {info.get('merge_cap', '?')}"] \
            + ([f"{info['token_budget']} token budget"] if info.get("token_budget") else [])
        b.add("shift-open", "shift-open", parts[0] + ": " + ", ".join(bits) + ".")
    _reaped(b, result, counters)
    _steer(b, result, counters)
    _closeouts(b, result, counters, info)
    _spawned(b, result, counters)
    _refused(b, result)
    _impaired(b, result)
    _login_expired(b, result)
    _late(b, result)
    if action in ("ticked", "shadow", "stopped"):
        if counters.get("commands_unread"):
            if not b.state["unread_run"]:
                b.state["unread_since"] = counters["commands_unread"]
            b.state["unread_run"] += 1
            if b.state["unread_run"] >= UNREAD_TICKS:
                since = b.state.get("unread_since") or counters["commands_unread"]
                b.add("steer-unread", f"steer-unread:{since}",
                      f"Can't read your commands on the shift issue since {_hhmm(since)}. "
                      "Steering is on hold.", needs_you=True)
        else:
            b.state["unread_run"] = 0
            b.state.pop("unread_since", None)
    if action == "digest" and result.get("post") is not None \
            and (result.get("post") or {}).get("error") != "already posted this shift":
        _digest_event(b, result, counters)
    if action == "stopped" and "/stop" in str(result.get("reason") or ""):
        b.add("stopped", "stopped", "Stopped by /stop. The watcher does nothing more. "
                                    "Workers still out are not killed.")
    if action in ("digest", "late") and quiet and b.has("digest"):
        b.add("shift-end", "shift-end", f"Shift {slot.name} over. Nothing is still running.")

    if b.events:
        _append(slot, b.events)
    _write_state(slot, b.state)
    return b.events


def _encode(e: dict) -> bytes:
    raw = json.dumps(e, sort_keys=True, ensure_ascii=False).encode("utf-8")
    while len(raw) > RECORD_MAX - 1:
        for k in ("url", "pr"):
            if k in e and len(e[k]) > 120:
                e[k] = e[k][:120]
        e["line"] = e["line"][:max(len(e["line"]) - 60, 40)]
        raw = json.dumps(e, sort_keys=True, ensure_ascii=False).encode("utf-8")
        if len(e["line"]) <= 40:
            break
    return raw + b"\n"


def _append(slot: Path, events: list[dict]) -> None:
    """One `write()` for the tick's lines. A torn last line from a crash is
    closed off first, so the new lines never join it."""
    path = Path(slot) / EVENTS_FILE
    data = b"".join(_encode(e) for e in events)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size:
        with open(path, "rb") as fh:
            fh.seek(size - 1)
            if fh.read(1) != b"\n":
                data = b"\n" + data
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)

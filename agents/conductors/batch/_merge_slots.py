"""One merge-slot counter per shift.

Inside a shift every merge counts against the brief's `merge-cap:`: a worker's
in-turn `notify` merge and the watcher's close-outs alike. A worker runs
`pyauto-brain merge-slot take <pr>` (`bin/merge_slot.py`) as its own bare call
before its bare `gh pr merge`; so does a merge close-out session, immediately
before its merge. The watcher takes a slot only before it spawns a
branch-update session; before a merge close-out it only reads whether one is
free (`room`). All write the same file.

The file is `merge_slots.json` in the shift's slot directory, read and written
under an exclusive `fcntl.flock` on `merge_slots.lock` beside it, and written
through a temporary file and `os.replace`, so two takes can never both see the
last free slot. The watcher publishes the cap (and whether the shift is paused)
every tick. It fails closed: no published cap, or a paused shift, refuses.

Slots are keyed by the PR's canonical URL (`pr_key`): a bare number, or any
other string, is never a key, so PR #12 of two repos never shares a slot. A
take is idempotent per PR and task: a PR that already holds a slot is told yes
again only for the same task — the worker that took it, or the close-out
session for the task the watcher took it for (its own `/prm` take). Anyone
else is refused. A release frees a slot only for the caller that took it.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path

SLOTS_FILE = "merge_slots.json"
LOCK_FILE = "merge_slots.lock"
#: Who the watcher is, as a slot holder.
WATCHER = "watcher"
#: Who every worker and close-out session is, as a slot holder (one class:
#: `bin/merge_slot.py` takes as this).
SESSION = "worker"


#: A GitHub PR URL, with anything after the number (`/files`, `/`, `#…`, `?…`).
_PR_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)"
                        r"(?:[/?#].*)?$")


def pr_key(url: str) -> str | None:
    """The canonical `https://github.com/<owner>/<repo>/pull/<n>` for a PR URL
    (owner and repo case-folded, as GitHub resolves them), else None."""
    m = _PR_URL_RE.match((url or "").strip())
    if not m:
        return None
    return f"https://github.com/{m.group(1).lower()}/{m.group(2).lower()}/pull/{int(m.group(3))}"


class MergeSlotError(RuntimeError):
    """The slot file cannot be read or written: the caller cannot tell."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty() -> dict:
    return {"cap": None, "paused": False, "published": "", "slots": {},
            "refusals": [], "released": []}


@contextlib.contextmanager
def _locked(slot: Path):
    """The slot file's contents under the exclusive lock; a changed dict is
    written back atomically on exit."""
    slot = Path(slot)
    if not slot.is_dir():
        raise MergeSlotError(f"no shift slot directory at {slot}")
    with open(slot / LOCK_FILE, "a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            data = _read(slot)
            before = json.dumps(data, sort_keys=True)
            yield data
            if json.dumps(data, sort_keys=True) != before:
                _write(slot, data)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read(slot: Path) -> dict:
    path = Path(slot) / SLOTS_FILE
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise MergeSlotError(f"unreadable {path}: {e}") from e
    if not isinstance(data, dict):
        raise MergeSlotError(f"unreadable {path}: not a JSON object")
    out = _empty()
    out.update(data)
    return out


def _write(slot: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".merge_slots.", dir=str(slot))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, Path(slot) / SLOTS_FILE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def publish(slot: Path, cap: int, paused: bool) -> None:
    """The watcher's word on this tick's cap and pause, for every take."""
    with _locked(slot) as data:
        data["cap"], data["paused"] = int(cap), bool(paused)
        if not data.get("published"):
            data["published"] = _now()


def _judge(data: dict, key: str, task: str, pending: int = 0) -> tuple[bool | None, str]:
    """(True, why) when `key` already holds a slot for `task`; (None, "") when
    a slot is free for it; (False, why) when it is refused. `pending` counts
    slots promised but not yet taken (`room`)."""
    held = data["slots"].get(key)
    cap, used = data.get("cap"), len(data["slots"])
    if held and task and held.get("task") == task:
        return True, (f"{key} already holds a merge slot for task {task} "
                      f"(taken by {held.get('by', '?')})")
    if held:
        return False, (f"{key} holds a merge slot for task {held.get('task') or '?'}, "
                       f"not {task or '(no task)'} — left for your /prm")
    if cap is None:
        return False, "no merge-cap published by the watcher — left for your /prm"
    if data.get("paused"):
        return False, "the shift is paused — left for your /prm"
    if used + pending >= int(cap):
        return False, f"merge-cap {cap} reached this shift — left for your /prm"
    return None, ""


def take(slot: Path, pr: str, by: str, task: str = "") -> tuple[bool, str]:
    """(taken, why). Idempotent per PR and task; every refusal is recorded."""
    key = pr_key(pr)
    if key is None:
        return False, (f"{pr!r} is not a https://github.com/<owner>/<repo>/pull/<n> URL "
                       "— left for your /prm")
    with _locked(slot) as data:
        ok, why = _judge(data, key, task)
        if ok:
            return True, why
        if ok is None:
            used, cap = len(data["slots"]), data.get("cap")
            data["slots"][key] = {"by": by, "task": task, "at": _now()}
            return True, f"merge slot {used + 1} of merge-cap {cap} taken for {key}"
        data["refusals"].append({"pr": key, "by": by, "task": task, "why": why, "at": _now()})
        return False, why


def room(slot: Path, pr: str, task: str, pending: int = 0) -> tuple[bool, str]:
    """(free, why) — whether `take(pr, task)` would succeed now, read only:
    nothing is taken and no refusal recorded. The watcher reads this before a
    merge close-out; the session takes its slot itself, immediately before
    the merge. `pending` is the slots already promised to close-outs still
    running without one, so the cap is never oversold."""
    key = pr_key(pr)
    if key is None:
        return False, (f"{pr!r} is not a https://github.com/<owner>/<repo>/pull/<n> URL "
                       "— left for your /prm")
    ok, why = _judge(state(slot), key, task, pending)
    return ok is not False, why


def release(slot: Path, pr: str, by: str, why: str = "", *, task: str | None = None) -> bool:
    """Free `pr`'s slot, only when `by` took it — and, when `task` is given
    (every worker or close-out session holds as one class), only for that
    task. True when one was freed."""
    key = pr_key(pr)
    if key is None:
        return False
    with _locked(slot) as data:
        held = data["slots"].get(key)
        if not held or held.get("by") != by:
            return False
        if task is not None and held.get("task") != task:
            return False
        del data["slots"][key]
        data["released"].append({"pr": key, "by": by, "task": held.get("task", ""),
                                 "why": why, "at": _now()})
        return True


def state(slot: Path) -> dict:
    """The whole file, read under the lock (the CLI's `status`)."""
    with _locked(slot) as data:
        return json.loads(json.dumps(data))


def used(slot: Path) -> int:
    """Slots held now — every merge taken this shift, in-turn or close-out.
    0 when there is no slot file yet."""
    if not (Path(slot) / SLOTS_FILE).exists():
        return 0
    return len(state(slot)["slots"])


def holders(slot: Path) -> dict:
    """{canonical PR URL: {by, task}} for every slot held now; {} with no file."""
    if not (Path(slot) / SLOTS_FILE).exists():
        return {}
    return {k: {"by": v.get("by", ""), "task": v.get("task", "")}
            for k, v in state(slot)["slots"].items()}


def why_unmerged(slot: Path, pr: str) -> str:
    """The last refusal or release recorded for `pr`, else ""."""
    if not (Path(slot) / SLOTS_FILE).exists():
        return ""
    pr = pr_key(pr) or pr
    data = state(slot)
    seen = [("refused", r) for r in data["refusals"] if r.get("pr") == pr] \
        + [("released", r) for r in data["released"] if r.get("pr") == pr]
    if not seen:
        return ""
    kind, last = max(seen, key=lambda kr: kr[1].get("at") or "")
    if kind == "released":
        return f"slot released by {last.get('by', '?')}: {last.get('why') or 'no reason given'}"
    return last.get("why") or ""

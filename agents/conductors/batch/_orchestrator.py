"""The shift watcher's core — one deterministic tick, no LLM in it.

Doctrine: `PyAutoMind/policy/shift_watcher.md` (the one exemption to "sessions
end at their deliverable") and `AUTONOMY.md` "Shift briefs and unattended
`glance`" plus "The watcher's network surface". A tick, in this order:

1. `STOP` in the slot directory → do nothing, before reading anything else;
2. no open brief (`batch brief --check` fails, or `review-at:` has passed) →
   do nothing;
3. take the tick lock (exclusive create) — an overlapping tick backs off;
4. reap leases — a finished worker is released, a dead one is counted and its
   task may be dispatched again **once** per shift;
5. ask the planner what the brief admits (`plan(..., brief=...)`);
6. for each candidate: the caps, then an exclusive-create lease, then spawn.

Phase 3a runs fake workers only (`PYAUTO_ORCHESTRATOR_FAKE=1`); real
`claude --bg` workers are phase 3b, the Mind writer 3c, the digest 3d.
Nothing here commits, merges, posts or arms a timer: the systemd timer that
calls `bin/orchestrator_watch.py` is installed by the human.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import _brief  # noqa: E402 — the batch conductor puts this directory on sys.path

STOP_FILE = "STOP"
LOCK_FILE = "tick.lock"
COUNTERS_FILE = "counters.json"
LOG_FILE = "tick.log"
#: A tick lock older than this belongs to a tick that died; it is broken.
LOCK_TTL_S = 600
#: A worker whose process is gone keeps its lease this long before it is
#: declared dead — room for a worker that writes its `.done` marker late.
LEASE_GRACE_S = 120
#: A task's lease may be re-dispatched after a crash this many times a shift.
REDISPATCH_LIMIT = 1

FAKE_ENV = "PYAUTO_ORCHESTRATOR_FAKE"
HOME_ENV = "PYAUTO_ORCHESTRATOR_HOME"


class OrchestratorError(RuntimeError):
    pass


# --- where state lives ---------------------------------------------------------

def orchestrator_home() -> Path:
    """`$PYAUTO_ORCHESTRATOR_HOME`, else `.orchestrator` under the worktree root.

    No path is written here: the worktree root comes from the shared resolver,
    so an adopting fork changes its environment, not this file.
    """
    env = os.environ.get(HOME_ENV)
    if env:
        return Path(env)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from _pyauto_root import pyauto_wt_root  # noqa: E402
    return pyauto_wt_root() / ".orchestrator"


def slot_dir(brief_path: Path, home: Path | None = None) -> Path:
    """One directory per shift, named after the brief record."""
    return (home or orchestrator_home()) / Path(brief_path).stem


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- counters and the log --------------------------------------------------------

def read_counters(slot: Path) -> dict:
    try:
        c = json.loads((slot / COUNTERS_FILE).read_text())
    except (OSError, ValueError):
        c = {}
    c.setdefault("sessions", 0)
    c.setdefault("crashes", 0)
    c.setdefault("redispatched", {})
    c.setdefault("done", [])
    c.setdefault("abandoned", [])
    c.setdefault("refusals", [])
    c.setdefault("pending_redispatch", [])
    return c


def _write_counters(slot: Path, c: dict) -> None:
    tmp = slot / (COUNTERS_FILE + ".tmp")
    tmp.write_text(json.dumps(c, indent=2, sort_keys=True))
    os.replace(tmp, slot / COUNTERS_FILE)


def _log(slot: Path, now: _dt.datetime, result: dict) -> None:
    with open(slot / LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": _iso(now), **result}, sort_keys=True) + "\n")


# --- processes ------------------------------------------------------------------

def _alive(pid: int) -> bool:
    """Whether a worker process is still running (a zombie is not)."""
    try:
        done, _status = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            return False
    except ChildProcessError:
        pass  # not our child: another tick spawned it
    except OSError:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


# The stub a fake worker runs: sleep, then write the done marker — or exit 1
# without it, which is what a crash looks like to the watcher.
_FAKE_WORKER = (
    "import sys, time, pathlib\n"
    "lease_dir, task, mode, secs = sys.argv[1:5]\n"
    "time.sleep(float(secs))\n"
    "if mode == 'crash':\n"
    "    sys.exit(1)\n"
    "pathlib.Path(lease_dir, task + '.done').write_text('done')\n"
)


class FakeSpawner:
    """Stub workers for a dry shift (`PYAUTO_ORCHESTRATOR_FAKE=1`)."""

    def __init__(self, seconds: float = 0.5, crash: set[str] | None = None):
        self.seconds = seconds
        self.crash = set(crash or ())

    def spawn(self, task: str, prompt_path: str, lease_dir: Path) -> dict:
        mode = "crash" if task in self.crash else "ok"
        proc = subprocess.Popen(
            [sys.executable, "-c", _FAKE_WORKER, str(lease_dir), task, mode,
             str(self.seconds)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        return {"pid": proc.pid, "session_id": f"fake-{proc.pid}", "worktree": None}


class RealSpawner:
    """`claude --bg` workers from the session template — phase 3b."""

    def spawn(self, task: str, prompt_path: str, lease_dir: Path) -> dict:
        raise OrchestratorError("real dispatch arrives in phase 3b; set "
                                f"{FAKE_ENV}=1 for a dry shift")


def default_spawner():
    return FakeSpawner() if os.environ.get(FAKE_ENV) == "1" else RealSpawner()


# --- locks and leases ------------------------------------------------------------

def _create_exclusive(path: Path, payload: dict) -> bool:
    """Write `payload` to `path` only if nobody has; True when this call won."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh, sort_keys=True)
    return True


def _take_lock(slot: Path, now: _dt.datetime) -> bool:
    lock = slot / LOCK_FILE
    me = {"pid": os.getpid(), "at": now.timestamp()}
    if _create_exclusive(lock, me):
        return True
    try:
        held = json.loads(lock.read_text())
        stale = (now.timestamp() - float(held.get("at", 0)) > LOCK_TTL_S
                 or not _alive(int(held.get("pid", 0))))
    except (OSError, ValueError):
        stale = False  # being written right now: someone else is ticking
    if stale:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
        return _create_exclusive(lock, me)
    return False


def _drop_lock(slot: Path) -> None:
    try:
        (slot / LOCK_FILE).unlink()
    except FileNotFoundError:
        pass


def task_id(prompt_path: str) -> str:
    return Path(prompt_path).stem


def leases(slot: Path) -> dict[str, dict]:
    out = {}
    for f in sorted((slot / "leases").glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return out


def _reap(slot: Path, counters: dict, now: _dt.datetime, grace_s: float) -> list[dict]:
    """Release finished leases and declare dead ones; returns what happened."""
    events = []
    lease_dir = slot / "leases"
    for task, lease in leases(slot).items():
        done_marker = lease_dir / f"{task}.done"
        path = lease_dir / f"{task}.json"
        if done_marker.exists():
            path.unlink(missing_ok=True)
            done_marker.unlink(missing_ok=True)
            if task not in counters["done"]:
                counters["done"].append(task)
            events.append({"task": task, "event": "done"})
            continue
        if _alive(int(lease.get("pid", 0))):
            lease["heartbeat"] = _iso(now)
            lease["expires"] = _iso(now + _dt.timedelta(seconds=grace_s))
            path.write_text(json.dumps(lease, sort_keys=True))
            continue
        expires = _dt.datetime.fromisoformat(lease["expires"].replace("Z", "+00:00"))
        if now < expires:
            continue  # gone, but inside the grace for a late `.done`
        path.unlink(missing_ok=True)
        counters["crashes"] += 1
        again = counters["redispatched"].get(task, 0) < REDISPATCH_LIMIT
        if again and task not in counters["pending_redispatch"]:
            counters["pending_redispatch"].append(task)
        if not again and task not in counters["abandoned"]:
            counters["abandoned"].append(task)
        events.append({"task": task, "event": "dead",
                       "redispatch": "allowed" if again else "spent — abandoned"})
    return events


# --- the tick --------------------------------------------------------------------

def brief_open(brief_path: Path, mind: Path, now: _dt.datetime) -> tuple[bool, str, dict | None]:
    """(open?, why, the parsed brief block)."""
    res = _brief.check(brief_path, mind)
    if not res["ok"]:
        return False, "brief refused: " + "; ".join(res["errors"]), None
    rec = _brief.parse(brief_path.read_text(encoding="utf-8"))
    at = _brief._iso(rec["top"]["review-at"]["value"])
    if now >= at:
        return False, f"review-at {rec['top']['review-at']['value']} has passed", None
    return True, "open", rec["brief"]


def tick(brief_path: Path, mind: Path, *, home: Path | None = None,
         now: _dt.datetime | None = None, spawner=None,
         grace_s: float = LEASE_GRACE_S, records: list[dict] | None = None) -> dict:
    """One watcher tick. Returns what it did; also appended to `tick.log`."""
    now = now or _now()
    brief_path = Path(brief_path)
    slot = slot_dir(brief_path, home)

    # The kill switch is the FIRST read: nothing else is touched while it exists.
    if (slot / STOP_FILE).exists():
        return {"action": "stopped", "reason": f"{STOP_FILE} present"}

    is_open, why, brief = brief_open(brief_path, mind, now)
    if not is_open:
        return {"action": "idle", "reason": why}

    (slot / "leases").mkdir(parents=True, exist_ok=True)
    if not _take_lock(slot, now):
        return {"action": "busy", "reason": "another tick holds the lock"}
    try:
        result = _tick_locked(slot, brief, mind, now, spawner or default_spawner(),
                              grace_s, records)
    finally:
        _drop_lock(slot)
    _log(slot, now, result)
    return result


def _tick_locked(slot, brief, mind, now, spawner, grace_s, records) -> dict:
    counters = read_counters(slot)
    reaped = _reap(slot, counters, now, grace_s)
    live = leases(slot)
    max_workers = _brief.cap_of(brief, "max-workers")
    max_sessions = _brief.cap_of(brief, "max-sessions")

    import _batch  # noqa: E402 — deferred: _batch imports this module's sibling
    if records is None:
        records = _batch.survey(mind)
    d = _batch.plan(records, session_lane="local-dev", brief=brief)
    spawned, refused = [], []
    for member in d["members"]:
        task = task_id(member["path"])
        if task in live or task in counters["done"] or task in counters["abandoned"]:
            continue
        if len(live) >= max_workers:
            refused.append({"task": task, "why": f"max-workers {max_workers} reached"})
            continue
        if counters["sessions"] >= max_sessions:
            refused.append({"task": task, "why": f"max-sessions {max_sessions} reached"})
            continue
        lease = {"task": task, "prompt": member["path"], "started": _iso(now),
                 "heartbeat": _iso(now),
                 "expires": _iso(now + _dt.timedelta(seconds=grace_s)),
                 "pid": 0, "session_id": None, "worktree": None}
        lease_path = slot / "leases" / f"{task}.json"
        if not _create_exclusive(lease_path, lease):
            continue  # a lease appeared since we read them: never a second worker
        try:
            lease.update(spawner.spawn(task, member["path"], slot / "leases"))
        except Exception:
            lease_path.unlink(missing_ok=True)
            raise
        lease_path.write_text(json.dumps(lease, sort_keys=True))
        if task in counters["pending_redispatch"]:
            counters["pending_redispatch"].remove(task)
            counters["redispatched"][task] = counters["redispatched"].get(task, 0) + 1
        counters["sessions"] += 1
        live[task] = lease
        spawned.append({"task": task, "pid": lease["pid"]})
    counters["refusals"] += [dict(r, at=_iso(now)) for r in refused]
    _write_counters(slot, counters)
    return {"action": "ticked", "reaped": reaped, "spawned": spawned,
            "refused": refused, "live": sorted(live)}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="orchestrator_watch",
        description="One shift-watcher tick (run by a systemd user timer the "
                    "human installs). Fake workers only until phase 3b.")
    ap.add_argument("--brief", required=True, type=Path,
                    help="the shift brief record (PyAutoMind/batches/<slot>.md)")
    ap.add_argument("--mind", required=True, type=Path)
    ap.add_argument("--home", type=Path, default=None,
                    help=f"state directory (default ${HOME_ENV}, else "
                         ".orchestrator under the worktree root)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    try:
        res = tick(a.brief, a.mind.resolve(), home=a.home)
    except OrchestratorError as e:
        print(f"orchestrator_watch: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if a.as_json else
          f"{res['action']}: " + (res.get("reason") or
                                 f"spawned {len(res['spawned'])}, "
                                 f"refused {len(res['refused'])}, "
                                 f"live {len(res['live'])}"))
    return 0

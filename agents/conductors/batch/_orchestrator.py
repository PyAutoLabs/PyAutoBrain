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

Workers are fake stubs (`PYAUTO_ORCHESTRATOR_FAKE=1`, phase 3a) or real
`claude --bg` sessions from one session template (phase 3b). A real worker's
liveness is its `claude agents --json` state; one left `blocked` past a grace
is parked for a human — never killed, never re-dispatched. Workers never
commit to PyAutoMind (phase 3c): they queue ledger ops (`bin/shift_ledger.py`)
and each tick commits them from a temporary worktree (`_mind_writer.py`); a
git hook injected through the worker's environment refuses a direct commit.
Nothing here commits, merges, posts or arms a timer: the systemd timer that
calls `bin/orchestrator_watch.py` is installed by the human.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import _brief  # noqa: E402 — the batch conductor puts this directory on sys.path
import _digest  # noqa: E402
import _mind_writer  # noqa: E402

STOP_FILE = "STOP"
LOCK_FILE = "tick.lock"
COUNTERS_FILE = "counters.json"
LOG_FILE = "tick.log"
DIGEST_FILE = "digest.md"
#: Created exclusively before the one post: its existence means "never again".
DIGEST_MARKER = "digest.posted"
#: A tick lock older than this belongs to a tick that died; it is broken.
LOCK_TTL_S = 600
#: A worker whose process is gone keeps its lease this long before it is
#: declared dead — room for a worker that writes its `.done` marker late.
LEASE_GRACE_S = 120
#: A task's lease may be re-dispatched after a crash this many times a shift.
REDISPATCH_LIMIT = 1
#: A real worker `blocked` (waiting on a human) this long is parked: its lease
#: is released, the task is not re-dispatched, and the digest names it.
STALL_GRACE_S = 900
#: The worker prompt every real worker starts from (never a bare session).
WORKER_TEMPLATE = Path(__file__).with_name("worker_template.md")
#: Hooks every worker's git runs with (core.hooksPath, set through GIT_CONFIG_*):
#: its pre-commit refuses a commit in PyAutoMind and chains to the repo's own.
WORKER_HOOKS = Path(__file__).resolve().parents[3] / "bin" / "worker_git_hooks"
SHIFT_LEDGER = Path(__file__).resolve().parents[3] / "bin" / "shift_ledger.py"

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
    c.setdefault("parked", [])
    c.setdefault("tokens", 0)
    c.setdefault("picks", {})      # task → {prompt, why, tier}, at dispatch (3d)
    c.setdefault("outcomes", {})   # task → {prs, merged}, from its `.done` (3d)
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


def worker_prompt(task: str, prompt_path: str, brief_path: Path, lease_dir: Path) -> str:
    """The session template filled in for one task."""
    return WORKER_TEMPLATE.read_text(encoding="utf-8").format(
        task=task, task_path=prompt_path, brief_path=brief_path, lease_dir=lease_dir,
        ledger_dir=Path(lease_dir).parent / _mind_writer.LEDGER_DIR,
        shift_ledger=SHIFT_LEDGER)


def worker_env(lease_dir: Path, base: dict | None = None) -> dict:
    """The environment a worker runs in: marked as a shift worker, pointed at
    the shift's ledger, and with git's hooks path overridden so a commit in
    PyAutoMind is refused whatever tool makes it."""
    env = dict(os.environ if base is None else base)
    n = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    env.update({"PYAUTO_SHIFT_WORKER": "1",
                "PYAUTO_SHIFT_LEDGER_DIR": str(Path(lease_dir).parent / _mind_writer.LEDGER_DIR),
                "GIT_CONFIG_COUNT": str(n + 1),
                f"GIT_CONFIG_KEY_{n}": "core.hooksPath",
                f"GIT_CONFIG_VALUE_{n}": str(WORKER_HOOKS)})
    return env


def session_command(task: str, prompt_path: str, brief_path: Path, lease_dir: Path,
                    mode: str) -> list[str]:
    """The exact argv that starts one worker — named, moded, templated.

    No `--session-id`: `claude --bg` (2.1.316) assigns its own, so the worker is
    tracked by the short id the launch prints."""
    if mode not in _brief.WORKER_MODES:
        raise OrchestratorError(f"worker mode {mode!r} is not one of "
                                + ", ".join(_brief.WORKER_MODES))
    return ["claude", "--bg", "--name", f"shift:{task}", "--permission-mode", mode,
            worker_prompt(task, prompt_path, brief_path, lease_dir)]


#: `claude --bg` prints `backgrounded · <8-hex id> · <name>` on its first line.
_BG_ID_RE = re.compile(r"backgrounded\W+([0-9a-f]{8})\b")


class RealSpawner:
    """`claude --bg` workers from the session template (phase 3b)."""

    real = True

    def __init__(self, brief_path: Path, mode: str, cwd: Path | None = None, run=None):
        self.brief_path, self.mode, self.cwd = Path(brief_path), mode, cwd
        self.run = run or subprocess.run

    def spawn(self, task: str, prompt_path: str, lease_dir: Path) -> dict:
        argv = session_command(task, prompt_path, self.brief_path, lease_dir, self.mode)
        res = self.run(argv, cwd=self.cwd, capture_output=True, text=True, timeout=120,
                       env=worker_env(lease_dir))
        # An untrusted folder is refused here, fast ("Workspace not trusted") —
        # never a silent stall. Workers start from a folder the human trusted.
        if res.returncode != 0:
            raise OrchestratorError(f"claude --bg failed for {task}: "
                                    + (res.stderr or res.stdout).strip()[:300])
        m = _BG_ID_RE.search(res.stdout)
        if not m:
            raise OrchestratorError(f"claude --bg printed no session id for {task}: "
                                    + res.stdout.strip()[:200])
        return {"pid": 0, "agent_id": m.group(1), "session_id": None, "mode": self.mode}


def default_spawner(brief_path: Path, brief: dict):
    if os.environ.get(FAKE_ENV) == "1":
        return FakeSpawner()
    cwd = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from _pyauto_root import pyauto_root  # noqa: E402
        cwd = pyauto_root()
    except Exception:
        cwd = None
    return RealSpawner(brief_path, _brief.worker_mode_of(brief), cwd=cwd)


# --- real-worker liveness and usage ------------------------------------------------

class AgentsView:
    """`claude agents --json --all`, read once per tick, keyed by the short id
    `claude --bg` printed (its `id` field)."""

    def __init__(self, sessions: list[dict] | None = None, run=None):
        self._sessions, self._run = sessions, run or subprocess.run

    def _load(self) -> list[dict]:
        if self._sessions is None:
            try:
                res = self._run(["claude", "agents", "--json", "--all"],
                                capture_output=True, text=True, timeout=60)
                self._sessions = json.loads(res.stdout) if res.returncode == 0 else []
            except (OSError, ValueError, subprocess.SubprocessError):
                self._sessions = []
        return self._sessions

    def _find(self, agent_id: str) -> dict | None:
        return next((s for s in self._load() if s.get("id") == agent_id), None)

    def state(self, agent_id: str) -> str | None:
        """The CLI's state word — `working` while it runs (2.1.316), `blocked`
        waiting on a person, `done` — or None if unlisted. Anything but
        `blocked` / `done` / None is read as alive."""
        s = self._find(agent_id)
        return None if s is None else (s.get("state") or "running")

    def session_of(self, agent_id: str) -> str | None:
        """The full session id — what the transcript file is named by."""
        s = self._find(agent_id)
        return s.get("sessionId") if s else None


def transcript_tokens(session_id: str, root: Path | None = None) -> int:
    """Tokens a finished session spent: input + output + cache creation, summed
    from its local transcript (a file read — no network)."""
    root = root or Path.home() / ".claude" / "projects"
    total = 0
    for f in root.glob(f"*/{session_id}.jsonl"):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                usage = (json.loads(line).get("message") or {}).get("usage") or {}
            except (ValueError, AttributeError):
                continue
            total += sum(int(usage.get(k) or 0) for k in
                         ("input_tokens", "output_tokens", "cache_creation_input_tokens"))
    return total


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


def _reap(slot: Path, counters: dict, now: _dt.datetime, grace_s: float,
          agents: AgentsView | None = None, tokens=transcript_tokens) -> list[dict]:
    """Release finished leases, park stalled ones and declare dead ones."""
    events = []
    lease_dir = slot / "leases"
    agents = agents or AgentsView()
    for task, lease in leases(slot).items():
        done_marker = lease_dir / f"{task}.done"
        path = lease_dir / f"{task}.json"
        real = bool(lease.get("agent_id")) and not lease.get("pid")
        state = agents.state(lease["agent_id"]) if real else None
        finished = done_marker.exists() or state == "done" or (
            real and state is None and now >= _parse_iso(lease["expires"]))
        if real and finished:
            sid = agents.session_of(lease["agent_id"]) or lease.get("session_id")
            counters["tokens"] += tokens(sid) if sid else 0
        if done_marker.exists():
            # The digest reads these at review-at, long after the marker is gone.
            counters["outcomes"][task] = _digest.parse_done(
                done_marker.read_text(encoding="utf-8", errors="replace"))
            proof = lease_dir / f"{task}.proof.md"
            if proof.exists():
                (slot / _digest.PROOFS_DIR).mkdir(exist_ok=True)
                proof.replace(slot / _digest.PROOFS_DIR / f"{task}.md")
            path.unlink(missing_ok=True)
            done_marker.unlink(missing_ok=True)
            if task not in counters["done"]:
                counters["done"].append(task)
            events.append({"task": task, "event": "done"})
            continue
        if real and state == "blocked":
            since = lease.setdefault("stalled_since", _iso(now))
            if (now - _parse_iso(since)).total_seconds() >= STALL_GRACE_S:
                # Waiting on a human is not a crash: never killed, never
                # re-dispatched — the digest names it and the human answers.
                path.unlink(missing_ok=True)
                if task not in counters["parked"]:
                    counters["parked"].append(task)
                events.append({"task": task, "event": "parked",
                               "why": f"blocked since {since}"})
            else:
                path.write_text(json.dumps(lease, sort_keys=True))
            continue
        alive = (state not in (None, "done")) if real else _alive(int(lease.get("pid", 0)))
        if alive:
            lease.pop("stalled_since", None)
            lease["heartbeat"] = _iso(now)
            lease["expires"] = _iso(now + _dt.timedelta(seconds=grace_s))
            path.write_text(json.dumps(lease, sort_keys=True))
            continue
        if now < _parse_iso(lease["expires"]) and state != "done":
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


def _parse_iso(value: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


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
         grace_s: float = LEASE_GRACE_S, records: list[dict] | None = None,
         agents: AgentsView | None = None, tokens=transcript_tokens,
         poster=None, health=None) -> dict:
    """One watcher tick. Returns what it did; also appended to `tick.log`.

    After `review-at:` the one remaining act is the digest (phase 3d), once."""
    now = now or _now()
    brief_path = Path(brief_path)
    slot = slot_dir(brief_path, home)

    # The kill switch is the FIRST read: nothing else is touched while it exists.
    if (slot / STOP_FILE).exists():
        return {"action": "stopped", "reason": f"{STOP_FILE} present"}

    is_open, why, brief = brief_open(brief_path, mind, now)
    if not is_open:
        if why.startswith("review-at") and (slot / "leases").is_dir() \
                and not (slot / DIGEST_MARKER).exists():
            if not _take_lock(slot, now):
                return {"action": "busy", "reason": "another tick holds the lock"}
            try:
                result = finish_shift(brief_path, mind, slot, now, poster=poster,
                                      health=health)
            finally:
                _drop_lock(slot)
            _log(slot, now, result)
            return result
        return {"action": "idle", "reason": why}

    (slot / "leases").mkdir(parents=True, exist_ok=True)
    if not _take_lock(slot, now):
        return {"action": "busy", "reason": "another tick holds the lock"}
    try:
        result = _tick_locked(slot, brief, mind, now,
                              spawner or default_spawner(brief_path, brief),
                              grace_s, records, agents, tokens)
    finally:
        _drop_lock(slot)
    _log(slot, now, result)
    return result


def _tick_locked(slot, brief, mind, now, spawner, grace_s, records, agents,
                 tokens) -> dict:
    counters = read_counters(slot)
    reaped = _reap(slot, counters, now, grace_s, agents, tokens)
    # One Mind writer: whatever the workers queued is committed here, by the
    # orchestrator alone, from a temporary worktree — never by a worker.
    ledger = {"committed": None, "ops": 0}
    if _mind_writer.pending_ops(slot):
        try:
            ledger = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: ledger from workers")
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    live = leases(slot)
    max_workers = _brief.cap_of(brief, "max-workers")
    max_sessions = _brief.cap_of(brief, "max-sessions")

    import _batch  # noqa: E402 — deferred: _batch imports this module's sibling
    if records is None:
        records = _batch.survey(mind)
    d = _batch.plan(records, session_lane="local-dev", brief=brief)
    if _brief.is_shadow(brief):
        proposed = _propose(d["members"], brief, counters, max_sessions)
        _write_counters(slot, counters)
        return {"action": "shadow", "reaped": reaped, "spawned": [],
                "proposed": proposed, "refused": [], "live": sorted(live),
                "ledger": ledger}
    spawned, refused = [], []
    for member in d["members"]:
        task = task_id(member["path"])
        if task in live or task in counters["done"] or task in counters["abandoned"] \
                or task in counters["parked"]:
            continue
        if len(live) >= max_workers:
            refused.append({"task": task, "why": f"max-workers {max_workers} reached"})
            continue
        if counters["sessions"] >= max_sessions:
            refused.append({"task": task, "why": f"max-sessions {max_sessions} reached"})
            continue
        budget = _brief._nonneg_int(brief.get("token-budget", {}).get("value", ""))
        if budget is not None and counters["tokens"] >= budget:
            refused.append({"task": task, "why": f"token-budget {budget} spent "
                                                f"({counters['tokens']})"})
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
        counters["picks"][task] = {"prompt": member["path"],
                                   "why": _brief.pick_reason(member, brief),
                                   "tier": member.get("consequence") or "?"}
        if task in counters["pending_redispatch"]:
            counters["pending_redispatch"].remove(task)
            counters["redispatched"][task] = counters["redispatched"].get(task, 0) + 1
        counters["sessions"] += 1
        live[task] = lease
        spawned.append({"task": task, "pid": lease["pid"]})
    counters["refusals"] += [dict(r, at=_iso(now)) for r in refused]
    _write_counters(slot, counters)
    return {"action": "ticked", "reaped": reaped, "spawned": spawned,
            "refused": refused, "live": sorted(live), "ledger": ledger}


# --- the digest (phase 3d) ----------------------------------------------------------

def gh_comment(issue_url: str, body_file: Path, run=None) -> dict:
    """The watcher's one write: a comment on the brief's `issue:`."""
    run = run or subprocess.run
    res = run(["gh", "issue", "comment", issue_url, "--body-file", str(body_file)],
              capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        return {"posted": False, "error": (res.stderr or res.stdout).strip()[:300]}
    return {"posted": True, "url": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""}


def _record_rel(brief_path: Path, mind: Path) -> str | None:
    """The record's path inside Mind, for the one-Mind-writer append; None when
    the record does not live in that checkout (a test brief, a scratch file)."""
    try:
        return Path(brief_path).resolve().relative_to(Path(mind).resolve()).as_posix()
    except ValueError:
        return None


def finish_shift(brief_path: Path, mind: Path, slot: Path, now: _dt.datetime, *,
                 poster=None, health=None) -> dict:
    """Write the digest into the record and post it once on the brief's issue.

    The marker is created **before** the post, exclusively: a crash between the
    two leaves a shift with no comment, never one with two (AUTONOMY.md "The
    watcher's network surface" — a second comment retires the watcher). Nothing
    is read back from GitHub to check.
    """
    if (slot / DIGEST_MARKER).exists():
        # A finished shift writes nothing more: no second record append, no
        # second pilot row, no second comment.
        return {"action": "digest", "ledger": None, "packet": None,
                "post": {"posted": False, "error": "already posted this shift"}}
    rec = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))
    brief, top = rec["brief"] or {}, rec["top"]
    counters = read_counters(slot)
    digest = _digest.build(brief, slot, counters, health=health)
    (slot / DIGEST_FILE).write_text(digest, encoding="utf-8")
    result = {"action": "digest", "ledger": None, "post": None, "packet": None}

    rel = _record_rel(brief_path, mind)
    if rel is not None:
        _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                              {"op": "append", "path": rel, "text": "\n" + digest})
        # The pilot ledger (phase 4a): one row per shift, in the same commit.
        header = "" if (Path(mind) / _digest.PILOT_PATH).is_file() else _digest.PILOT_HEADER
        _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                              {"op": "append", "path": _digest.PILOT_PATH,
                               "text": header + _digest.pilot_row(slot.name, brief, counters)})
        try:
            result["ledger"] = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: digest")
        except _mind_writer.MindWriteError as e:
            result["ledger"] = {"committed": None, "error": str(e)}

    if top.get("packet", {}).get("value", "").lower() == "yes":
        result["packet"] = str(_write_packet(slot, digest))

    issue = top.get("issue", {}).get("value", "")
    claim = {"at": _iso(now), "issue": issue}
    if not _create_exclusive(slot / DIGEST_MARKER, claim):
        result["post"] = {"posted": False, "error": "already posted this shift"}
        return result
    if not issue.startswith("http"):
        result["post"] = {"posted": False, "error": "the brief names no issue:"}
    else:
        result["post"] = (poster or gh_comment)(issue, slot / DIGEST_FILE)
    (slot / DIGEST_MARKER).write_text(json.dumps({**claim, **result["post"]},
                                                 sort_keys=True))
    return result


def _write_packet(slot: Path, digest: str) -> Path:
    """The opt-in HTML packet (`packet: yes`): the digest on one page."""
    import html
    css = Path(__file__).with_name("packet.css")
    style = css.read_text(encoding="utf-8") if css.is_file() else ""
    page = ("<!doctype html><meta charset=\"utf-8\"><title>Shift digest "
            f"{html.escape(slot.name)}</title><style>{style}</style>"
            f"<main><pre>{html.escape(digest)}</pre></main>\n")
    out = slot / "digest.html"
    out.write_text(page, encoding="utf-8")
    return out


def _propose(members: list[dict], brief: dict, counters: dict, max_sessions: int) -> list[str]:
    """A shadow shift's tick (phase 4a): record what a live shift would have
    dispatched — no lease, no worker — up to the brief's `max-sessions:`."""
    out = []
    for member in members:
        task = task_id(member["path"])
        if task in counters["picks"]:
            continue
        if len(counters["picks"]) >= max_sessions:
            break
        counters["picks"][task] = {"prompt": member["path"],
                                   "why": _brief.pick_reason(member, brief),
                                   "tier": member.get("consequence") or "?",
                                   "proposed": True}
        out.append(task)
    return out


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

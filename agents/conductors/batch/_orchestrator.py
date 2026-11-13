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
Nothing here commits, merges or arms a timer: the systemd timer that calls
`bin/orchestrator_watch.py` is installed by the human. Its only GitHub writes
are the comments AUTONOMY.md "The watcher's network surface" lists — the
digest, one @mention per worker per state that needs the human (#611), one
correction for a late arrival (#610) and one live status comment, then only
edited (#622) — each claimed by marker first. Each open tick also reads the
shift issue's comments once, for the human's `/pause` `/resume` `/drop`
`/stop` (#622).
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
#: declared dead — room for a worker that writes its `.done` marker late. At
#: least two measured tick intervals (median 184 s over 566 ticks to
#: 2026-11-09; PyAutoBrain#603), so one slow tick never outlives a lease.
LEASE_GRACE_S = 420
#: A real worker missing from `claude agents` is a crash only after this many
#: consecutive unlisted reads (and the grace) — or a positive ended state.
UNLISTED_READS_FOR_CRASH = 2
#: A task's lease may be re-dispatched after a crash this many times a shift.
REDISPATCH_LIMIT = 1
#: A real worker `blocked` (waiting on a human) this long is parked: its lease
#: stays (state `parked`, holding no worker slot) so a late `.done` is still
#: read, the task is not re-dispatched, and the digest names it.
STALL_GRACE_S = 900
#: Sessions that ended without succeeding — reaped as crashes (`_digest`, #592).
ENDED_STATES = _digest.ENDED_STATES
#: The worker prompt every real worker starts from (never a bare session).
WORKER_TEMPLATE = Path(__file__).with_name("worker_template.md")
CLOSEOUT_TEMPLATE = Path(__file__).with_name("closeout_template.md")
#: The close-out session's model (phase 4b). The same model as the workers —
#: the human's call 2026-11-04 (AUTONOMY.md "Stage-2 adversary amendment"): a
#: fresh, independent session that runs the witness itself is the leg.
CLOSEOUT_MODEL = "opus"
STAGE2_HEADING = "## Unattended `glance` sub-window (stage 2)"
STAGE2_LOG = "autonomy_log.md"
#: Hooks every worker's git runs with (core.hooksPath, set through GIT_CONFIG_*):
#: its pre-commit refuses a commit in PyAutoMind and chains to the repo's own.
WORKER_HOOKS = Path(__file__).resolve().parents[3] / "bin" / "worker_git_hooks"
SHIFT_LEDGER = Path(__file__).resolve().parents[3] / "bin" / "shift_ledger.py"
#: The Brain CLI a worker runs its first step with (`batch premise`).
BRAIN_CLI = Path(__file__).resolve().parents[3] / "bin" / "pyauto-brain"

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
    c.setdefault("closeouts", {})  # PR url → {task, state, why, …} (4b)
    c.setdefault("glance_auto_merges", 0)
    # PyAutoBrain#610: tokens per session (replaced each read, never added),
    # the sessions whose usage could not be read this tick, one exit record
    # per worker, and GitHub's merge state per PR at `review-at:`.
    c.setdefault("usage", {})
    c.setdefault("usage_unavailable", [])
    c.setdefault("workers", [])
    c.setdefault("github", {})
    c.setdefault("pushes", 0)        # @mentions sent (PyAutoBrain#611)
    # PyAutoBrain#622: tasks the human dropped, and every steering command
    # enacted with its acknowledgement (`paused` is present only while paused).
    c.setdefault("dropped", {})
    c.setdefault("commands", [])
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

    def spawn_closeout(self, task: str, pr_url: str, prompt_path: str, lease_dir: Path) -> dict:
        """A dry close-out: it refuses, because a fake session merged nothing."""
        verdict = {"result": "refused", "pr": pr_url,
                   "why": "fake close-out (dry shift) — nothing merged", "gate": "",
                   "model": "fake"}
        (Path(lease_dir) / f"{task}.closeout").write_text(json.dumps(verdict))
        return {"pid": 0, "agent_id": None}

    def pr_state(self, url: str) -> dict:
        """A dry shift merges nothing, so GitHub is never asked."""
        return {"state": "OPEN", "mergedAt": "", "mergedBy": ""}


def worker_prompt(task: str, prompt_path: str, brief_path: Path, lease_dir: Path) -> str:
    """The session template filled in for one task."""
    return WORKER_TEMPLATE.read_text(encoding="utf-8").format(
        task=task, task_path=prompt_path, brief_path=brief_path, lease_dir=lease_dir,
        ledger_dir=Path(lease_dir).parent / _mind_writer.LEDGER_DIR,
        shift_ledger=SHIFT_LEDGER, brain_cli=BRAIN_CLI)


#: The Brain helpers a close-out sources for the scoped Heart gate.
COMMON_SH = Path(__file__).resolve().parents[2] / "_common.sh"


def pr_repos(pr_url: str) -> str:
    """The repo a PR belongs to, as the dev-ship gate's `--repos` (bare name).
    Empty for a URL that is not a GitHub pull request — the gate then cannot
    be scoped, and the close-out refuses."""
    m = re.match(r"^https://github\.com/[^/]+/([^/]+)/pull/\d+", pr_url or "")
    return m.group(1) if m else ""


def closeout_prompt(task: str, pr_url: str, prompt_path: str, brief_path: Path,
                    lease_dir: Path) -> str:
    """The close-out session template filled in for one PR (phase 4b). Its
    Heart check is the scoped development-ship gate for the PR's repo (leg 4,
    PyAutoHeart#340): only `green` merges."""
    repos = pr_repos(pr_url)
    heart_cmd = (f"bash -c 'source \"{COMMON_SH}\"; consult_vitals_verdict --repos {repos}'"
                 if repos else "")
    return CLOSEOUT_TEMPLATE.read_text(encoding="utf-8").format(
        task=task, pr_url=pr_url, task_path=prompt_path, brief_path=brief_path,
        lease_dir=lease_dir, ledger_dir=Path(lease_dir).parent / _mind_writer.LEDGER_DIR,
        shift_ledger=SHIFT_LEDGER, pr_repos=repos or "(none — not a GitHub PR URL)",
        heart_cmd=heart_cmd or "(cannot be scoped — refuse)")


def closeout_command(task: str, pr_url: str, prompt_path: str, brief_path: Path,
                     lease_dir: Path, mode: str) -> list[str]:
    """The argv that starts one close-out session: its own name, the close-out
    model, the brief's worker mode."""
    if mode not in _brief.WORKER_MODES:
        raise OrchestratorError(f"worker mode {mode!r} is not one of "
                                + ", ".join(_brief.WORKER_MODES))
    return ["claude", "--bg", "--name", f"shift-close:{task}", "--model", CLOSEOUT_MODEL,
            "--permission-mode", mode,
            closeout_prompt(task, pr_url, prompt_path, brief_path, lease_dir)]


def worker_env(lease_dir: Path, base: dict | None = None) -> dict:
    """The environment a worker runs in: marked as a shift worker, pointed at
    the shift's ledger, and with git's hooks path overridden so a commit in
    PyAutoMind is refused whatever tool makes it. The watcher's own posting
    token (`PYAUTO_SHIFT_GH_TOKEN`) never reaches a worker or close-out, nor
    a `GH_TOKEN` / `GITHUB_TOKEN` that carries it; the human's own gh auth
    stays (#611 re-review)."""
    env = dict(os.environ if base is None else base)
    bot = env.pop(GH_TOKEN_ENV, "").strip()
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if bot and env.get(key, "").strip() == bot:
            env.pop(key)
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

    def __init__(self, brief_path: Path, mode: str, cwd: Path | None = None, run=None,
                 gh=None):
        self.brief_path, self.mode, self.cwd = Path(brief_path), mode, cwd
        self.run = run or subprocess.run
        self.gh = gh or gh_pr_state

    def pr_state(self, url: str) -> dict | None:
        """GitHub's word on a PR — the merge truth for a close-out (#603)."""
        return self.gh(url)

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

    def spawn_closeout(self, task: str, pr_url: str, prompt_path: str, lease_dir: Path) -> dict:
        argv = closeout_command(task, pr_url, prompt_path, self.brief_path, lease_dir,
                                self.mode)
        res = self.run(argv, cwd=self.cwd, capture_output=True, text=True, timeout=120,
                       env=worker_env(lease_dir))
        if res.returncode != 0:
            raise OrchestratorError(f"claude --bg close-out failed for {task}: "
                                    + (res.stderr or res.stdout).strip()[:300])
        m = _BG_ID_RE.search(res.stdout)
        if not m:
            raise OrchestratorError(f"claude --bg printed no session id for {task}'s close-out")
        return {"pid": 0, "agent_id": m.group(1)}


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
    `claude --bg` printed (its `id` field).

    A read that fails, times out or prints something other than a JSON list is
    *unknown* (`known()` is False) — never an empty list, which would declare
    every worker gone (PyAutoBrain#603)."""

    def __init__(self, sessions: list[dict] | None = None, run=None):
        self._sessions, self._run = sessions, run or subprocess.run
        self._failed = False

    def _load(self) -> list[dict] | None:
        if self._sessions is None and not self._failed:
            try:
                res = self._run(["claude", "agents", "--json", "--all"],
                                capture_output=True, text=True, timeout=60)
                if res.returncode != 0:
                    raise ValueError(f"exit {res.returncode}")
                sessions = json.loads(res.stdout)
                if not isinstance(sessions, list):
                    raise TypeError("not a JSON list")
                self._sessions = sessions
            except (OSError, ValueError, TypeError, subprocess.SubprocessError):
                self._failed = True
        return self._sessions

    def known(self) -> bool:
        """Whether this tick's read says anything at all about the workers."""
        return self._load() is not None

    def _find(self, agent_id: str) -> dict | None:
        return next((s for s in self._load() or [] if s.get("id") == agent_id), None)

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


def _liveness_known(agents) -> bool:
    """`agents.known()`, for any view; a view without one is always known."""
    known = getattr(agents, "known", None)
    return True if known is None else bool(known())


def gh_pr_state(url: str, run=None) -> dict | None:
    """One read-only `gh pr view`: {state, mergedAt, mergedBy} as GitHub has
    it, or None when GitHub could not say (#603: the merge truth)."""
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "view", url, "--json", "state,mergedAt,mergedBy"],
                  capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(data, dict) or not data.get("state"):
        return None
    by = data.get("mergedBy") or {}
    return {"state": str(data["state"]).upper(), "mergedAt": data.get("mergedAt") or "",
            "mergedBy": by.get("login", "") if isinstance(by, dict) else str(by)}


_USAGE_FIELDS = (("input", "input_tokens"), ("output", "output_tokens"),
                 ("cache_creation", "cache_creation_input_tokens"),
                 ("cache_read", "cache_read_input_tokens"))
_USAGE_KEYS = ("total", "input", "output", "cache_creation", "cache_read", "subagents")
#: Consecutive unreadable reads after which one session stops refusing every
#: spawn: its reservation stands in for its usage and it is `unmeasured` (#610).
UNREADABLE_READS = 3


def _read_usages(f: Path, by_id: dict, anonymous: list, source: str) -> None:
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            msg = json.loads(line).get("message") or {}
        except (ValueError, AttributeError):
            continue
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        if msg.get("id"):
            by_id[msg["id"]] = (source, usage)    # the last line of a message wins
        else:
            anonymous.append((source, usage))


def transcript_usage(session_id: str, root: Path | None = None) -> dict | None:
    """What a session has spent so far, from its local transcripts (file
    reads — no network): input, output, cache creation and cache read, with
    `total` = input + output + cache creation (cache reads are reported, not
    counted). A transcript repeats one assistant message on several lines with
    the same usage, so usage is taken once per message id (PyAutoBrain#610:
    summing every line read about 1.6× high). The session's subagents write
    their own transcripts under `<sid>/subagents/agent-*.jsonl`; they are
    included, deduped the same way, and `subagents` reports their share of
    `total`. None when there is no transcript or one cannot be read — never 0."""
    root = root or Path.home() / ".claude" / "projects"
    main = list(root.glob(f"*/{session_id}.jsonl"))
    subs = list(root.glob(f"*/{session_id}/subagents/agent-*.jsonl"))
    if not main and not subs:
        return None
    by_id, anonymous = {}, []
    try:
        for f in main:
            _read_usages(f, by_id, anonymous, "main")
        for f in subs:
            _read_usages(f, by_id, anonymous, "subagent")
    except OSError:
        return None
    seen = [*by_id.values(), *anonymous]
    out = {name: sum(int(u.get(field) or 0) for _, u in seen)
           for name, field in _USAGE_FIELDS}
    out["total"] = out["input"] + out["output"] + out["cache_creation"]
    out["subagents"] = sum(int(u.get(field) or 0) for src, u in seen if src == "subagent"
                           for field in ("input_tokens", "output_tokens",
                                         "cache_creation_input_tokens"))
    return out


def transcript_tokens(session_id: str, root: Path | None = None) -> int | None:
    """`transcript_usage`'s total, or None when unavailable."""
    usage = transcript_usage(session_id, root)
    return None if usage is None else usage["total"]


def _as_usage(raw) -> dict | None:
    """A usage read in either form a seam returns: a dict, a bare total, None."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        if raw.get("total") is None:
            return None
        return {k: raw[k] for k in _USAGE_KEYS if k in raw}
    return {"total": int(raw)}


def _measure(counters: dict, key: str, sid: str | None, tokens, *, kind: str,
             task: str, final: bool = False) -> None:
    """Read one session's usage and store it **replacing** the last read
    (PyAutoBrain#610) — so a re-read never adds twice. An unreadable usage
    keeps the last value and marks the session unavailable for this tick,
    which refuses the next spawn; it is never stored as 0. After
    `UNREADABLE_READS` unreadable reads in a row the session is `unmeasured`:
    it stops refusing spawns, and its reservation counts as its usage."""
    entry = counters["usage"].setdefault(key, {"kind": kind, "task": task, "total": None})
    usage = _as_usage(tokens(sid)) if sid else None
    if usage is None:
        entry["unreadable"] = int(entry.get("unreadable") or 0) + 1
        if entry["unreadable"] >= UNREADABLE_READS:
            entry["unmeasured"] = True
        elif key not in counters["usage_unavailable"]:
            counters["usage_unavailable"].append(key)
    else:
        entry.update(usage)
        entry.pop("unreadable", None)
        entry.pop("unmeasured", None)
    if final:
        entry["final"] = True
    _sum_tokens(counters)


def _sum_tokens(counters: dict) -> None:
    counters["tokens"] = sum(int(u["total"]) for u in counters["usage"].values()
                             if u.get("total") is not None)


def _committed_tokens(counters: dict) -> int:
    """What the shift has spent or holds: a live or unmeasured session counts
    the larger of its usage and its spawn reservation; a finished one its
    usage, or its reservation if it was never measured."""
    total = 0
    for u in counters["usage"].values():
        used, reserve = u.get("total"), int(u.get("reserve") or 0)
        if u.get("final") and not u.get("unmeasured"):
            total += int(used) if used is not None else reserve
        else:
            total += max(int(used or 0), reserve)
    return total


def default_token_reserve(budget: int | None, max_sessions: int) -> int:
    """The per-worker estimate held at spawn until real usage passes it: an
    even share of the budget among the sessions the shift may start."""
    return budget // max(max_sessions, 1) if budget else 0


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


def _worker_key(lease: dict, task: str) -> str:
    """The worker a lease holds: its `claude --bg` id, else its pid."""
    return lease.get("worker") or lease.get("agent_id") or f"pid-{lease.get('pid') or task}"


def worker_record(counters: dict, key: str, task: str, started: str | None = None) -> dict:
    """The one exit record of one worker, created on first sight."""
    for w in counters["workers"]:
        if w.get("key") == key:
            return w
    w = {"key": key, "task": task, "spawned": started, "exits": ["spawned"]}
    counters["workers"].append(w)
    return w


def _exit(rec: dict, word: str) -> None:
    """Append one exit word; a repeat of the last (a re-reaped lease) is not."""
    if not rec["exits"] or rec["exits"][-1] != word:
        rec["exits"].append(word)


def last_worker(counters: dict, task: str) -> dict | None:
    """The newest worker record for a task (a re-dispatch makes a second)."""
    return next((w for w in reversed(counters["workers"]) if w["task"] == task), None)


def _reap(slot: Path, counters: dict, now: _dt.datetime, grace_s: float,
          agents: AgentsView | None = None, tokens=transcript_usage, *,
          late: bool = False) -> list[dict]:
    """Release finished leases, park stalled ones and declare dead ones.

    Every transition is written to `counters.json` as it happens, and a lease
    or `.done` marker is deleted only after that write — a tick that fails
    later never forgets a reap (PyAutoBrain#603). A parked worker keeps its
    lease (`state: parked`), so its late `.done` is still read here.

    Every real session's usage is read on every tick, live, parked or
    finishing, and stored per session (PyAutoBrain#610). Each transition is
    also written to the worker's exit record (`spawned/…`); `late` (the late
    sweep) marks what arrives after `review-at:`.
    """
    events = []
    lease_dir = slot / "leases"
    agents = agents or AgentsView()
    known = None  # read lazily: a slot of fake workers never calls `claude agents`
    for task, lease in leases(slot).items():
        done_marker = lease_dir / f"{task}.done"
        path = lease_dir / f"{task}.json"
        real = bool(lease.get("agent_id")) and not lease.get("pid")
        parked = lease.get("state") == "parked"
        rec = worker_record(counters, _worker_key(lease, task), task, lease.get("started"))

        def mark(word, rec=rec):
            if late and "late" not in rec["exits"]:
                _exit(rec, "late")
            _exit(rec, word)
        state = None
        if real:
            if known is None:
                known = _liveness_known(agents)
                if not known:
                    events.append({"event": "liveness-unknown",
                                   "why": "the `claude agents` read failed — "
                                          "no liveness decision this tick"})
            if not known:
                # No liveness decision, but the usage still counts: a known
                # transcript is read; without one the session is unavailable.
                _measure(counters, lease["agent_id"], lease.get("session_id"), tokens,
                         kind="worker", task=task)
                continue
            state = agents.state(lease["agent_id"])
            if state is None:
                lease["unlisted"] = int(lease.get("unlisted", 0)) + 1
            else:
                lease.pop("unlisted", None)
            if state == "blocked":
                seen = rec.get("blocked_seen")
                if seen:
                    rec["stalled_s"] = float(rec.get("stalled_s") or 0) \
                        + max((now - _parse_iso(seen)).total_seconds(), 0.0)
                rec["blocked_seen"] = _iso(now)
            else:
                rec.pop("blocked_seen", None)
        ended = real and state in ENDED_STATES
        gone = (real and state is None
                and lease.get("unlisted", 0) >= UNLISTED_READS_FOR_CRASH
                and now >= _parse_iso(lease["expires"]))
        finished = done_marker.exists() or state == "done" or ended or gone
        if real:
            sid = agents.session_of(lease["agent_id"]) or lease.get("session_id")
            if sid:
                lease["session_id"] = sid
            _measure(counters, lease["agent_id"], sid, tokens, kind="worker", task=task,
                     final=finished)
        if done_marker.exists():
            # The digest reads these at review-at, long after the marker is gone.
            counters["outcomes"][task] = _digest.parse_done(
                done_marker.read_text(encoding="utf-8", errors="replace"))
            if task not in counters["done"]:
                counters["done"].append(task)
            if task in counters["parked"]:
                counters["parked"].remove(task)
            mark("finished")
            _write_counters(slot, counters)
            proof = lease_dir / f"{task}.proof.md"
            if proof.exists():
                (slot / _digest.PROOFS_DIR).mkdir(exist_ok=True)
                proof.replace(slot / _digest.PROOFS_DIR / f"{task}.md")
            path.unlink(missing_ok=True)
            done_marker.unlink(missing_ok=True)
            event = {"task": task, "event": "done"}
            if parked:
                event["was"] = "parked"
            events.append(event)
            continue
        if parked:
            if finished:
                # Ended without a `.done`: released, never a crash and never
                # re-dispatched — it stays parked for the human.
                mark("ended")
                _write_counters(slot, counters)
                path.unlink(missing_ok=True)
                events.append({"task": task, "event": "parked-ended"})
            else:
                path.write_text(json.dumps(lease, sort_keys=True))
            continue
        if real and state == "blocked":
            since = lease.setdefault("stalled_since", _iso(now))
            if (now - _parse_iso(since)).total_seconds() >= STALL_GRACE_S:
                # Waiting on a human is not a crash: never killed, never
                # re-dispatched — the digest names it and the human answers.
                # The lease stays (state `parked`) so a late `.done` is read.
                if task not in counters["parked"]:
                    counters["parked"].append(task)
                mark("parked")
                _write_counters(slot, counters)
                lease.update(state="parked", parked_at=_iso(now))
                events.append({"task": task, "event": "parked",
                               "why": f"blocked since {since}"})
            path.write_text(json.dumps(lease, sort_keys=True))
            continue
        alive = (state not in (None, "done") and not ended) if real \
            else _alive(int(lease.get("pid", 0)))
        if alive:
            lease.pop("stalled_since", None)
            lease["heartbeat"] = _iso(now)
            lease["expires"] = _iso(now + _dt.timedelta(seconds=grace_s))
            path.write_text(json.dumps(lease, sort_keys=True))
            continue
        dead = (state == "done" or ended or gone) if real \
            else now >= _parse_iso(lease["expires"])
        if not dead:
            if real:
                path.write_text(json.dumps(lease, sort_keys=True))  # the unlisted count
            continue  # gone, but inside the grace for a late `.done`
        counters["crashes"] += 1
        mark("crashed")
        again = counters["redispatched"].get(task, 0) < REDISPATCH_LIMIT
        if again and task not in counters["pending_redispatch"]:
            counters["pending_redispatch"].append(task)
        if not again and task not in counters["abandoned"]:
            counters["abandoned"].append(task)
        _write_counters(slot, counters)
        path.unlink(missing_ok=True)
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
    # The shift is `dispatched:` → `review-at:`. Landing the brief early is
    # allowed; it grants nothing until its start (PyAutoBrain#589 — shadow
    # shift 1 opened on landing, a day early).
    start = _brief._iso(rec["top"]["dispatched"]["value"])
    if now < start:
        return False, f"not yet open: opens at dispatched {rec['top']['dispatched']['value']}", None
    return True, "open", rec["brief"]


def _default_pr_state():
    """GitHub's word on a PR at `review-at:` — none asked in a dry shift."""
    return FakeSpawner().pr_state if os.environ.get(FAKE_ENV) == "1" else gh_pr_state


def tick(brief_path: Path, mind: Path, *, home: Path | None = None,
         now: _dt.datetime | None = None, spawner=None,
         grace_s: float = LEASE_GRACE_S, records: list[dict] | None = None,
         agents: AgentsView | None = None, tokens=transcript_usage,
         poster=None, health=None, pr_state=None,
         token_reserve: int | None = None, whoami=None, github=None) -> dict:
    """One watcher tick. Returns what it did; also appended to `tick.log`.

    `github` is the `run` seam for the live status comment and the steering
    read (PyAutoBrain#622) — a test's fake `gh`; unset, the real one.

    After `review-at:` the one remaining act is the digest (phase 3d), once —
    then the late sweep, while a worker is still out, an op is queued or a
    failed post is due its retry."""
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
                result = finish_shift(
                    brief_path, mind, slot, now, poster=poster, health=health,
                    agents=agents, tokens=tokens, grace_s=grace_s, github=github,
                    pr_state=(pr_state or getattr(spawner, "pr_state", None)
                              or _default_pr_state()))
            finally:
                _drop_lock(slot)
            _log(slot, now, result)
            return result
        if why.startswith("review-at") and (slot / DIGEST_MARKER).exists() and (
                leases(slot) or _mind_writer.pending_ops(slot)
                or post_due(slot / DIGEST_MARKER) or post_due(slot / CORRECTION_MARKER)
                or mentions_due(slot)):
            if not _take_lock(slot, now):
                return {"action": "busy", "reason": "another tick holds the lock"}
            try:
                result = late_sweep(brief_path, mind, slot, now, grace_s=grace_s,
                                    agents=agents, tokens=tokens, poster=poster)
            finally:
                _drop_lock(slot)
            _log(slot, now, result)
            return result
        return {"action": "idle", "reason": why}

    top = _brief.parse(brief_path.read_text(encoding="utf-8"))["top"]
    shift = {"issue": (top.get("issue") or {}).get("value", ""),
             "review_at": (top.get("review-at") or {}).get("value", ""),
             "dispatched": (top.get("dispatched") or {}).get("value", ""),
             "brief_path": brief_path}
    (slot / "leases").mkdir(parents=True, exist_ok=True)
    if not _take_lock(slot, now):
        return {"action": "busy", "reason": "another tick holds the lock"}
    try:
        result = _tick_locked(slot, brief, mind, now,
                              spawner or default_spawner(brief_path, brief),
                              grace_s, records, agents, tokens, health, pr_state,
                              poster=poster, shift=shift, token_reserve=token_reserve,
                              whoami=whoami, github=github)
    finally:
        _drop_lock(slot)
    _log(slot, now, result)
    return result


def active_leases(slot: Path) -> dict[str, dict]:
    """The leases that hold a worker slot: a parked worker's does not."""
    return {t: l for t, l in leases(slot).items() if l.get("state") != "parked"}


def _tick_locked(slot, brief, mind, now, spawner, grace_s, records, agents,
                 tokens, health=None, pr_state=None, *, poster=None, shift=None,
                 token_reserve=None, whoami=None, github=None) -> dict:
    """The tick under its lock, then the live status (PyAutoBrain#622): one
    `claude agents` view and one set of `gh pr checks` reads serve both."""
    shift = shift or {}
    agents = agents or AgentsView()
    health = _TickHealth(health)
    out = _tick_body(slot, brief, mind, now, spawner, grace_s, records, agents, tokens,
                     health, pr_state, poster=poster, shift=shift,
                     token_reserve=token_reserve, whoami=whoami, github=github)
    status = _live_status(slot, mind, shift, now, agents, health.cached, github,
                          stopped=out.get("action") == "stopped")
    if status:
        out["status"] = status
    return out


def _tick_body(slot, brief, mind, now, spawner, grace_s, records, agents,
               tokens, health=None, pr_state=None, *, poster=None, shift=None,
               token_reserve=None, whoami=None, github=None) -> dict:
    counters = read_counters(slot)
    counters["usage_unavailable"] = []   # this tick's reads decide
    reaped = _reap(slot, counters, now, grace_s, agents, tokens)
    import _batch  # noqa: E402 — deferred: _batch imports this module's sibling
    planned = {}

    def plan() -> dict:
        """The plan inside the brief, made once a tick when first needed."""
        if "d" not in planned:
            recs = records if records is not None else _batch.survey(mind)
            # Unattended by construction: an absent Lane is excluded and an
            # empty queue.md stops the backlog dip (M2.3, AUTONOMY.md "M2
            # rulings — 2026-11-12"). Recorded each tick so the digest can say so.
            planned["d"] = _batch.plan(recs, session_lane="local-dev", brief=brief,
                                       queue=_batch.read_queue(mind))
        return planned["d"]

    def known(task: str) -> bool:
        named = {task_id(p) for p in _brief.tasks_of(brief)}
        return task in named or task in {task_id(m["path"]) for m in plan()["members"]}

    # The human steers from the shift issue (#622): read once, before anything
    # this tick starts, so a /pause or /drop binds on the tick that reads it.
    commands = _steer(slot, counters, shift or {}, now, github, whoami, known)
    _write_counters(slot, counters)
    if (slot / STOP_FILE).exists():
        # A /stop this tick: from here on it is the STOP file's tick.
        return {"action": "stopped", "reason": f"{STOP_FILE} written by /stop",
                "reaped": reaped, "commands": commands}
    # One Mind writer: whatever the workers queued is committed here, by the
    # orchestrator alone, from a temporary worktree — never by a worker.
    ledger = {"committed": None, "ops": 0}
    if _mind_writer.pending_ops(slot):
        try:
            ledger = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: ledger from workers")
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    closeouts = _closeouts(slot, brief, counters, spawner, now, agents, health, pr_state,
                           tokens=tokens)
    if _mind_writer.pending_ops(slot):  # a stage-2 row queued by a merged close-out
        try:
            ledger = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: unattended close-out")
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    mentions = _mentions(slot, counters, shift or {}, poster, now, whoami)
    _write_counters(slot, counters)
    live = active_leases(slot)
    max_workers = _brief.cap_of(brief, "max-workers")
    max_sessions = _brief.cap_of(brief, "max-sessions")

    d = plan()
    counters["backlog_gates"] = {"lane_absent": sorted(d["lane_absent"]),
                                 "queue_stop": d["queue_stop"]}
    paused = bool(counters.get("paused"))
    if _brief.is_shadow(brief):
        proposed = [] if paused else _propose(
            [m for m in d["members"] if task_id(m["path"]) not in counters["dropped"]],
            brief, counters, max_sessions)
        _write_counters(slot, counters)
        out = {"action": "shadow", "reaped": reaped, "spawned": [],
               "proposed": proposed, "refused": [], "live": sorted(live),
               "ledger": ledger}
        return _steered(out, commands, paused)
    budget = _brief._nonneg_int(brief.get("token-budget", {}).get("value", ""))
    # A real worker holds a reservation from its spawn until its measured
    # usage passes it, so the budget binds on the first tick (#610). A fake
    # (dry-shift) worker spends nothing.
    reserve = 0
    if getattr(spawner, "real", False):
        reserve = token_reserve if token_reserve is not None \
            else default_token_reserve(budget, max_sessions)
    spawned, refused = [], []
    for member in [] if paused else d["members"]:
        task = task_id(member["path"])
        if task in live or task in counters["done"] or task in counters["abandoned"] \
                or task in counters["parked"] or task in counters["dropped"]:
            continue
        if len(live) >= max_workers:
            refused.append({"task": task, "why": f"max-workers {max_workers} reached"})
            continue
        if counters["sessions"] >= max_sessions:
            refused.append({"task": task, "why": f"max-sessions {max_sessions} reached"})
            continue
        if counters["usage_unavailable"]:
            # Never counted as 0: a spend the watcher cannot read could be
            # anything, so nothing more starts until it can be read.
            refused.append({"task": task, "why": "token usage unavailable ("
                            + ", ".join(counters["usage_unavailable"]) + ")"})
            continue
        if budget is not None and counters["tokens"] >= budget:
            refused.append({"task": task, "why": f"token-budget {budget} spent "
                                                f"({counters['tokens']})"})
            continue
        committed = _committed_tokens(counters)
        if budget is not None and committed + reserve > budget:
            refused.append({"task": task, "why": f"token-budget {budget}: {committed} "
                                                f"committed + {reserve} reserved per worker"})
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
        except Exception as e:
            # One task's failed launch is that task's refusal, not the tick's:
            # what this tick already reaped stays written, the rest carry on.
            lease_path.unlink(missing_ok=True)
            refused.append({"task": task, "why": f"spawn failed: {str(e)[:300]}"})
            # One record per task however often the launch is retried: a
            # failed launch is a crashed worker in the digest (#610).
            rec = worker_record(counters, f"launch-{task}", task, _iso(now))
            rec["exits"] = ["launch-failed"]
            rec["attempts"] = int(rec.get("attempts") or 0) + 1
            _write_counters(slot, counters)
            continue
        lease["worker"] = _worker_key(lease, task)
        lease_path.write_text(json.dumps(lease, sort_keys=True))
        worker_record(counters, lease["worker"], task, lease["started"])
        if lease.get("agent_id"):
            counters["usage"][lease["worker"]] = {"kind": "worker", "task": task,
                                                  "total": None, "reserve": reserve}
        counters["picks"][task] = pick_record(member, brief)
        if task in counters["pending_redispatch"]:
            counters["pending_redispatch"].remove(task)
            counters["redispatched"][task] = counters["redispatched"].get(task, 0) + 1
        counters["sessions"] += 1
        _write_counters(slot, counters)
        live[task] = lease
        spawned.append({"task": task, "pid": lease["pid"]})
    counters["refusals"] += [dict(r, at=_iso(now)) for r in refused]
    _write_counters(slot, counters)
    out = {"action": "ticked", "reaped": reaped, "spawned": spawned,
           "refused": refused, "live": sorted(live), "ledger": ledger,
           "closeouts": closeouts}
    if mentions:
        out["mentions"] = mentions
    return _steered(out, commands, paused)


def _steered(out: dict, commands: list, paused: bool) -> dict:
    """A tick's result with what the human's commands did to it."""
    if commands:
        out["commands"] = commands
    if paused:
        out["paused"] = True
    return out


# --- posting: marker before post, a failed post retried (#610, #611) -----------------

#: Attempts per comment, the first included. Only a post `gh` says failed is
#: retried; a timeout may have landed, so it never is.
POST_TRIES = 3
#: The one correction comment a late arrival may add after the digest (#610).
CORRECTION_MARKER = "correction.posted"
CORRECTION_FILE = "correction.md"


#: An optional separate GitHub token for the watcher's writes (a bot account),
#: given to its own `gh` calls as `GH_TOKEN` and to nothing else: then the
#: human's account is the one notified by an @mention (#611 review).
GH_TOKEN_ENV = "PYAUTO_SHIFT_GH_TOKEN"


def _gh_env() -> dict | None:
    token = os.environ.get(GH_TOKEN_ENV, "").strip()
    return {**os.environ, "GH_TOKEN": token} if token else None


def gh_login(run=None) -> str | None:
    """The login the watcher's comments post as (`gh api user`, under the
    posting token); None when it cannot say."""
    run = run or subprocess.run
    try:
        res = run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True,
                  timeout=60, env=_gh_env())
    except (OSError, subprocess.SubprocessError):
        return None
    login = (res.stdout or "").strip()
    return login if res.returncode == 0 and login else None


def gh_comment(issue_url: str, body_file: Path, run=None) -> dict:
    """The watcher's one kind of write: a comment on the brief's `issue:`,
    posted as `PYAUTO_SHIFT_GH_TOKEN`'s account when it is set. `retry: False`
    marks a failure after which the comment may have landed."""
    run = run or subprocess.run
    try:
        res = run(["gh", "issue", "comment", issue_url, "--body-file", str(body_file)],
                  capture_output=True, text=True, timeout=120, env=_gh_env())
    except subprocess.TimeoutExpired:
        return {"posted": False, "retry": False,
                "error": "gh timed out — the comment may have landed; not retried"}
    except OSError as e:
        return {"posted": False, "error": f"gh could not run: {e}"[:300]}
    if res.returncode != 0:
        return {"posted": False, "error": (res.stderr or res.stdout).strip()[:300]}
    return {"posted": True, "url": res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""}


def _post_and_record(marker: Path, rec: dict, body_file: Path, poster) -> dict:
    issue = rec.get("issue", "")
    if not issue.startswith("http"):
        res = {"posted": False, "retry": False, "error": "the brief names no issue:"}
    else:
        res = (poster or gh_comment)(issue, body_file)
    rec = {k: v for k, v in rec.items() if k not in ("error", "retry")}
    rec.update(res)
    rec["state"] = ("posted" if res.get("posted")
                    else "failed" if res.get("retry", True) else "unknown")
    marker.write_text(json.dumps(rec, sort_keys=True))
    return rec


def post_once(marker: Path, issue: str, body_file: Path, poster, now: _dt.datetime,
              **meta) -> dict | None:
    """Claim `marker` exclusively, then post: a crash between the two leaves
    no comment, never two. None when the marker was already claimed."""
    claim = {"at": _iso(now), "issue": issue, "tries": 1, "state": "claimed", **meta}
    if not _create_exclusive(marker, claim):
        return None
    return _post_and_record(marker, claim, body_file, poster)


def post_due(marker: Path) -> bool:
    """Whether a marker's post failed outright and has tries left. A marker
    written before retries existed (no `state`) is never retried."""
    try:
        rec = json.loads(Path(marker).read_text())
    except (OSError, ValueError):
        return False
    return rec.get("state") == "failed" and int(rec.get("tries", 1)) < POST_TRIES


def retry_post(marker: Path, body_file: Path, poster, now: _dt.datetime) -> dict | None:
    """Re-post a failed comment, re-claiming the marker first."""
    if not post_due(marker):
        return None
    rec = json.loads(marker.read_text())
    rec.update(tries=int(rec.get("tries", 1)) + 1, state="claimed", retried_at=_iso(now))
    marker.write_text(json.dumps(rec, sort_keys=True))
    return _post_and_record(marker, rec, body_file, poster)


# --- the human, reached by @mention (#611) -----------------------------------------

MENTIONS_DIR = "mentions"
#: The GitHub login a blocked worker @-mentions: this variable, else
#: `config/policy.yaml` `shift_watcher: mention_login:` — never written here.
MENTION_ENV = "PYAUTO_SHIFT_MENTION"
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "policy.yaml"


def mention_login() -> str:
    login = os.environ.get(MENTION_ENV, "").strip().lstrip("@")
    if not login:
        try:
            import yaml
            cfg = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
            login = str((cfg.get("shift_watcher") or {}).get("mention_login") or "")
            login = login.strip().lstrip("@")
        except Exception:
            login = ""
    return login if _LOGIN_RE.fullmatch(login) else ""


def _mention_triggers(counters: dict, held: dict) -> list[tuple[str, str, str]]:
    """(task, state, reason) for each worker that needs the human — the push
    test (AUTONOMY.md): a worker blocked on a person past the grace (parked),
    or one that parked on its issue with a question. Read from durable state
    (`counters.json`, the leases), not from this tick's events, so a tick that
    died between parking a worker and posting still mentions it on the next;
    the marker makes it once. A crash, a refusal, a finished worker or an
    obsolete premise waits for the digest."""
    out = []
    for task in counters["parked"]:
        since = (held.get(task) or {}).get("stalled_since")
        out.append((task, "parked", "blocked on a person"
                    + (f" (blocked since {since})" if since else "")))
    for task, o in counters["outcomes"].items():
        if not o.get("prs") and o.get("issues") and "obsolete" not in o:
            out.append((task, "awaiting-input",
                        "parked on its issue with a question: " + ", ".join(o["issues"])))
    return out


def mention_body(login: str, slot_name: str, task: str, state: str, reason: str,
                 counters: dict, worker: dict | None, lease: dict | None,
                 review_at: str) -> str:
    who = f"@{login} " if login else ""
    prompt = counters["picks"].get(task, {}).get("prompt") or (lease or {}).get("prompt") or task
    urls = _digest.urls_of(counters["outcomes"].get(task))
    where = [f"session `{(worker or {}).get('key') or '?'}` (`claude agents` on the laptop)"]
    if (lease or {}).get("worktree"):
        where.append(f"worktree `{lease['worktree']}`")
    lines = [f"{who}shift `{slot_name}`: the worker on `{task}` needs you — {state}.", "",
             f"- reason: {reason}", f"- task: `{prompt}`",
             f"- worker: {'; '.join(where)}",
             f"- PR / issue: {', '.join(urls) or 'none yet'}", "",
             f"The shift carries on without it; the digest at review-at {review_at} "
             "lists it too. One comment per worker per state."]
    if not login:
        lines.append(f"(No login to mention: set `{MENTION_ENV}` or `config/policy.yaml` "
                     "`shift_watcher: mention_login:`.)")
    return "\n".join(lines) + "\n"


def _note_mention(counters: dict, worker: dict | None, name: str, rec: dict) -> None:
    if rec.get("state") == "posted":
        counters["pushes"] += 1
    if worker is None:
        return
    for m in worker.setdefault("mentions", []):
        if m.get("marker") == name:
            m["posted"] = rec.get("state") == "posted"
            return
    worker["mentions"].append({"marker": name, "state": rec.get("mention_state"),
                               "posted": rec.get("state") == "posted"})


def mentions_due(slot: Path) -> bool:
    d = slot / MENTIONS_DIR
    return d.is_dir() and any(post_due(m) for m in d.glob("*.json"))


def _retry_mentions(slot: Path, counters: dict, poster, now: _dt.datetime) -> list[dict]:
    """Re-post every mention `gh` said failed, up to `POST_TRIES` — on a live
    tick and in the late sweep alike."""
    d = slot / MENTIONS_DIR
    out = []
    if d.is_dir():
        for marker in sorted(d.glob("*.json")):
            rec = retry_post(marker, marker.with_suffix(".md"), poster, now)
            if rec is not None:
                w = last_worker(counters, rec.get("task", ""))
                _note_mention(counters, w if w and w.get("key") == rec.get("worker") else None,
                              marker.stem, rec)
                out.append({"task": rec.get("task"), "state": rec.get("mention_state"),
                            "post": rec["state"], "retry": rec["tries"]})
    return out


def _mentions(slot: Path, counters: dict, shift: dict, poster, now: _dt.datetime,
              whoami=None) -> list[dict]:
    """One comment on the shift's digest issue per worker per state that
    needs the human (#611), claimed by marker before the post; a post `gh`
    said failed is retried on the next tick, up to `POST_TRIES`."""
    d = slot / MENTIONS_DIR
    out = _retry_mentions(slot, counters, poster, now)
    held = leases(slot)
    todo = []
    for task, state, reason in _mention_triggers(counters, held):
        w = last_worker(counters, task)
        key = (w or {}).get("key") or task
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{task}.{state}.{key}")
        if not (d / f"{name}.json").exists():
            todo.append((task, state, reason, w, key, name))
    if not todo:
        return out
    login = mention_login()
    if login and "poster_login" not in counters:
        # Once per shift: who the comments post as. The human's own login
        # gets no notification for its own comment (#611 review).
        counters["poster_login"] = (whoami or gh_login)() or ""
    if login:
        counters["mention_login"] = login
    for task, state, reason, w, key, name in todo:
        marker = d / f"{name}.json"
        d.mkdir(parents=True, exist_ok=True)
        body = d / f"{name}.md"
        body.write_text(mention_body(login, slot.name, task, state, reason, counters, w,
                                     held.get(task), shift.get("review_at", "?")),
                        encoding="utf-8")
        rec = post_once(marker, shift.get("issue", ""), body, poster, now,
                        task=task, mention_state=state, worker=key)
        if rec is None:
            continue
        _note_mention(counters, w, name, rec)
        out.append({"task": task, "state": state, "post": rec["state"], "retry": 1})
    return out


# --- the live shift view you can steer (PyAutoBrain#622) ----------------------------

#: The one live status comment of a shift: claimed by this marker before its
#: create, then only edited — never a second (AUTONOMY.md watcher network
#: surface, amendment 2026-11-13).
STATUS_MARKER = "status.json"
STATUS_FILE = "status.md"
#: An unchanged status is re-edited this often (time left, tokens); any change
#: of state edits it on the tick that sees it. Never more than one edit a tick.
STATUS_REFRESH_S = 600
#: The hidden first line of the status comment; the comments read adopts a
#: create that may have landed (a timeout, a crash after the claim) by it.
STATUS_TAG = "<!-- pyauto-shift-status {slot} {nonce} -->"
STATUS_TAG_PREFIX = "<!-- pyauto-shift-status "
#: The dashboard's copy of the status: one `- live:` line in the brief record,
#: rewritten through the one Mind writer when the shift's state changes.
LIVE_KEY_FILE = "live.key"
#: The steering commands, read from the human's comments on the shift issue.
COMMANDS = ("pause", "resume", "drop", "stop")
_COMMAND_RE = re.compile(r"^/(pause|resume|drop|stop)\b[ \t]*(\S+)?[ \t]*$")
_TASK_ARG_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
#: `<lease dir>/<task>.dropped`: a dropped task's close-out session checks it
#: just before it merges, and refuses (closeout_template.md).
DROPPED_SUFFIX = ".dropped"
#: The `/pause` acknowledgement — the one wording AUTONOMY.md and the docs use.
PAUSE_ACK = ("paused: spawns, re-dispatches and new close-outs are held until /resume; "
             "reaps and mentions continue")
_ISSUE_API_RE = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/issues/(\d+)$")
_COMMENT_API_RE = re.compile(
    r"^https://github\.com/([^/\s]+)/([^/\s]+)/(?:issues|pull)/\d+#issuecomment-(\d+)$")


def gh_comment_edit(comment_url: str, body_file: Path, run=None) -> dict:
    """Edit the watcher's own status comment in place (`gh api PATCH`), as
    `PYAUTO_SHIFT_GH_TOKEN`'s account when it is set — the only edit the
    watcher makes. An edit is idempotent, so any failure is retried next tick."""
    m = _COMMENT_API_RE.match(comment_url or "")
    if not m:
        return {"edited": False, "error": f"not a comment URL: {comment_url!r}"[:300]}
    payload = Path(body_file).with_suffix(".json")
    payload.write_text(json.dumps({"body": Path(body_file).read_text(encoding="utf-8")}),
                       encoding="utf-8")
    run = run or subprocess.run
    try:
        res = run(["gh", "api", "-X", "PATCH",
                   f"repos/{m.group(1)}/{m.group(2)}/issues/comments/{m.group(3)}",
                   "--input", str(payload), "--jq", ".html_url"],
                  capture_output=True, text=True, timeout=120, env=_gh_env())
    except (OSError, subprocess.SubprocessError) as e:
        return {"edited": False, "error": f"gh could not edit: {e}"[:300]}
    if res.returncode != 0:
        return {"edited": False, "error": (res.stderr or res.stdout).strip()[:300]}
    return {"edited": True}


def gh_issue_comments(issue_url: str, since: str, run=None) -> list[dict] | None:
    """The shift issue's comments updated since `since`, oldest first: one
    read-only `gh api` call, one page of 100 (the next tick reads on). None
    when GitHub could not say — the tick carries on without steering."""
    m = _ISSUE_API_RE.match(issue_url or "")
    if not m:
        return None
    run = run or subprocess.run
    query = f"?per_page=100&since={since}" if since else "?per_page=100"
    try:
        res = run(["gh", "api", f"repos/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}"
                   f"/comments{query}"],
                  capture_output=True, text=True, timeout=60, env=_gh_env())
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout or "")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(data, list):
        return None
    out = []
    for c in data:
        if not isinstance(c, dict) or c.get("id") is None:
            continue
        user = c.get("user") if isinstance(c.get("user"), dict) else {}
        out.append({"id": str(c["id"]), "login": str(user.get("login") or ""),
                    "body": str(c.get("body") or ""), "created_at": str(c.get("created_at") or ""),
                    "url": str(c.get("html_url") or "")})
    return out


def _read_json(path: Path) -> dict | None:
    try:
        rec = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def status_url(slot: Path) -> str:
    """The live status comment's URL, once it is known to exist."""
    rec = _read_json(slot / STATUS_MARKER) or {}
    return rec.get("url", "") if rec.get("state") == "posted" else ""


def _parse_command(body: str) -> tuple[str, str] | None:
    """(command, argument) when a comment's first non-empty line is a
    steering command and nothing else; None otherwise."""
    first = next((ln.strip() for ln in (body or "").splitlines() if ln.strip()), "")
    m = _COMMAND_RE.match(first)
    return (m.group(1), (m.group(2) or "").strip("`")) if m else None


def _apply_command(slot: Path, counters: dict, cmd: str, arg: str, who: str,
                   at: str, known=None) -> str:
    """Enact one command; returns its acknowledgement. `known(task)` says
    whether a task belongs to this shift (a pick, a lease, a brief or plan
    member)."""
    if cmd == "pause":
        if counters.get("paused"):
            return "already paused"
        counters["paused"] = {"by": who, "at": at}
        return PAUSE_ACK
    if cmd == "resume":
        if not counters.get("paused"):
            return "not paused: nothing to resume"
        counters.pop("paused")
        return "resumed"
    if cmd == "stop":
        (slot / STOP_FILE).write_text(f"/stop by {who} at {at}\n", encoding="utf-8")
        return (f"stopped: {STOP_FILE} written; the watcher does nothing from now on and "
                f"workers out are not killed (remove {STOP_FILE} by hand to restart)")
    # drop
    if not arg or not _TASK_ARG_RE.match(arg):
        return "ignored: /drop needs a task name"
    task = Path(arg).stem
    held = leases(slot)
    if not (task in held or task in counters["picks"] or task in counters["outcomes"]
            or (known is not None and known(task))):
        return f"ignored: no such task in this shift (`{task}`)"
    counters["dropped"][task] = {"by": who, "at": at}
    (slot / "leases").mkdir(parents=True, exist_ok=True)
    (slot / "leases" / f"{task}{DROPPED_SUFFIX}").write_text(f"/drop by {who} at {at}\n",
                                                            encoding="utf-8")
    running = [pr for pr, co in counters["closeouts"].items()
               if co.get("task") == task and co.get("state") == "running"]
    tail = "".join(f"; a close-out already running may still merge PR {pr} (it is told "
                   "to refuse by a `.dropped` marker it checks before merging; a merge "
                   "that lands anyway is recorded as merged outside the close-out)"
                   for pr in running)
    lease = held.get(task)
    if lease is not None:
        key = _worker_key(lease, task)
        return (f"dropped `{task}`: its worker {key} is still running; it is never "
                "re-dispatched and its PR never merged unattended. Stopping it is "
                f"yours, by hand on the laptop (`claude stop {key}`)" + tail)
    if task in counters["outcomes"] or task in counters["done"]:
        return (f"dropped `{task}`: it had already finished; its PR is never merged "
                "unattended" + tail)
    return f"dropped `{task}`: it will not be picked this shift" + tail


def _steer(slot: Path, counters: dict, shift: dict, now: _dt.datetime, github=None,
           whoami=None, known=None) -> list[dict]:
    """Read the shift issue's comments once and enact each new steering
    command from the human's login (`mention_login`), in order, once.

    Not spoofable by another account (only the configured login counts), nor
    by the watcher's own comments (the status comment carries its tag and is
    skipped by id; no other comment it writes opens with a command), nor by
    a comment older than the shift's `dispatched:` (an issue reused across
    shifts). Each comment is acted on once, by id; its acknowledgement is a
    line in the status comment, so a command costs no extra GitHub write.

    The same read adopts a status comment whose create may have landed — even
    with no login set, when it is the only reason to read — and only one
    written by the posting identity (`gh api user`, once per shift)."""
    issue = shift.get("issue", "")
    login = mention_login()
    marker = slot / STATUS_MARKER
    rec = _read_json(marker)
    adopting = bool(rec) and rec.get("state") in ("claimed", "unknown")
    if not issue.startswith("http") or not (login or adopting):
        return []
    start = _brief._iso(shift.get("dispatched") or "")
    since = counters.get("commands_since") or (_iso(start) if start else "")
    comments = gh_issue_comments(issue, since, run=github)
    if comments is None:
        counters["commands_unread"] = _iso(now)
        return []
    counters.pop("commands_unread", None)
    if adopting and "poster_login" not in counters:
        counters["poster_login"] = (whoami or gh_login)() or ""
    poster = counters.get("poster_login") or ""
    seen = set(counters.get("commands_seen") or [])
    out = []
    for c in sorted(comments, key=lambda c: (c["created_at"], c["id"])):
        if c["created_at"] > (counters.get("commands_since") or ""):
            counters["commands_since"] = c["created_at"]
        if c["body"].lstrip().startswith(STATUS_TAG_PREFIX):
            if rec and rec.get("state") in ("claimed", "unknown") and poster \
                    and c["login"].lower() == poster.lower() \
                    and f" {rec.get('nonce')} -->" in c["body"].split("\n", 1)[0] and c["url"]:
                # A create that timed out (or a tick that died after its
                # claim) did land: adopt it, and edit it from now on.
                rec.update(state="posted", url=c["url"], due=True, adopted_at=_iso(now))
                marker.write_text(json.dumps(rec, sort_keys=True))
            continue
        if not login or c["id"] in seen or (rec and c["url"] and c["url"] == rec.get("url")):
            continue
        if c["login"].lower() != login.lower():
            continue
        try:
            created = _parse_iso(c["created_at"])
        except ValueError:
            continue
        if start is not None and created < start:
            continue
        parsed = _parse_command(c["body"])
        if parsed is None:
            continue
        cmd, arg = parsed
        seen.add(c["id"])
        ack = _apply_command(slot, counters, cmd, arg, c["login"], c["created_at"], known)
        counters["commands"].append({"id": c["id"], "command": "/" + cmd + (f" {arg}" if arg else ""),
                                     "by": c["login"], "at": c["created_at"], "url": c["url"],
                                     "ack": ack})
        out.append({"command": cmd, "arg": arg, "ack": ack})
    counters["commands_seen"] = sorted(seen)
    return out


class _TickHealth:
    """One tick's `gh pr checks` reads, remembered: the status comment shows
    what the close-outs read and never makes a read of its own."""

    def __init__(self, health=None):
        self._health, self.seen = health, {}

    def __call__(self, url: str) -> str:
        if url not in self.seen:
            self.seen[url] = (self._health or _digest.pr_health)(url)
        return self.seen[url]

    def cached(self, url: str) -> str:
        return self.seen.get(url, "open (CI not read this tick)")


def _post_status(slot: Path, issue: str, text: str, key: str, now: _dt.datetime,
                 github=None) -> dict:
    """At most one GitHub write: create the status comment (marker claimed
    first, exclusively), or edit it. A create `gh` said failed landed nothing
    and is made again next tick; one that timed out, or a claim whose tick
    died, may have landed: it is never made again, only adopted by the
    comments read. An edit that fails is retried next tick."""
    marker, body = slot / STATUS_MARKER, slot / STATUS_FILE
    rec = _read_json(marker)
    if rec is None or rec.get("state") == "failed":
        if rec is None:
            rec = {"at": _iso(now), "issue": issue, "state": "claimed", "tries": 1,
                   "nonce": os.urandom(6).hex()}
            if not _create_exclusive(marker, rec):
                return {"status": "busy"}
        else:
            rec.update(state="claimed", tries=int(rec.get("tries", 1)) + 1, error=None)
            marker.write_text(json.dumps(rec, sort_keys=True))
        body.write_text(STATUS_TAG.format(slot=slot.name, nonce=rec["nonce"]) + "\n" + text,
                        encoding="utf-8")
        res = gh_comment(issue, body, run=github)
        if res.get("posted") and "#issuecomment-" in res.get("url", ""):
            rec.update(state="posted", url=res["url"], key=key, edited_at=_iso(now), due=False)
        elif res.get("posted"):
            # Landed, but gh printed no comment URL: adopted by the next read.
            rec.update(state="unknown", error="posted without a comment URL")
        else:
            rec.update(state="failed" if res.get("retry", True) else "unknown",
                       error=res.get("error", ""))
        marker.write_text(json.dumps(rec, sort_keys=True))
        return {"status": "created" if rec["state"] == "posted" else "create " + rec["state"]}
    if rec.get("state") != "posted":
        return {"status": "unknown — never re-created; adopted when the comments read sees it"}
    try:
        stale = (now - _parse_iso(rec.get("edited_at") or "")).total_seconds() >= STATUS_REFRESH_S
    except ValueError:
        stale = True
    if not (rec.get("due") or rec.get("key") != key or stale):
        return {"status": "unchanged"}
    body.write_text(STATUS_TAG.format(slot=slot.name, nonce=rec["nonce"]) + "\n" + text,
                    encoding="utf-8")
    res = gh_comment_edit(rec.get("url", ""), body, run=github)
    if res.get("edited"):
        rec.update(key=key, edited_at=_iso(now), due=False, edits=int(rec.get("edits", 0)) + 1)
        rec.pop("error", None)
    else:
        rec.update(due=True, error=res.get("error", ""))
    marker.write_text(json.dumps(rec, sort_keys=True))
    return {"status": "edited" if res.get("edited") else "edit failed — retried next tick"}


def _live_status(slot: Path, mind: Path, shift: dict, now: _dt.datetime, agents,
                 health, github=None, *, stopped: bool = False) -> dict | None:
    """The end of every open tick: the status comment (create once, then edit)
    and the dashboard's `- live:` line. Built from the same snapshot as
    `batch watch`, from what this tick already read — no read of its own.
    On the `/stop` tick only the status write runs, as the acknowledgement:
    nothing is queued or committed to Mind, exactly as under `STOP`."""
    brief_path = shift.get("brief_path")
    if brief_path is None:
        return None
    import _watch  # noqa: E402 — deferred: _watch imports this module
    snap = _watch.snapshot(brief_path, slot, now, agents=agents, health=health)
    out = {}
    issue = shift.get("issue", "")
    if issue.startswith("http"):
        snap["commands_on"] = bool(mention_login())
        out = _post_status(slot, issue, _watch.render_status(snap),
                           _watch.status_key(snap), now, github)
    if stopped:
        return out or None
    snap["status_url"] = status_url(slot)
    line, key = _watch.live_line(snap)
    rel = _record_rel(Path(brief_path), mind)
    keyfile = slot / LIVE_KEY_FILE
    old = keyfile.read_text(encoding="utf-8") if keyfile.exists() else ""
    if rel is not None and key != old:
        _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                              {"op": "record-key", "path": rel, "key": "live", "value": line})
        keyfile.write_text(key, encoding="utf-8")
        try:
            out["ledger"] = _mind_writer.commit_ledger(slot, mind,
                                                       f"shift {slot.name}: live status")
        except _mind_writer.MindWriteError as e:
            out["ledger"] = {"committed": None, "error": str(e)}
    return out or None


# --- the digest (phase 3d) ----------------------------------------------------------

def _record_rel(brief_path: Path, mind: Path) -> str | None:
    """The record's path inside Mind, for the one-Mind-writer append; None when
    the record does not live in that checkout (a test brief, a scratch file)."""
    try:
        return Path(brief_path).resolve().relative_to(Path(mind).resolve()).as_posix()
    except ValueError:
        return None


LATE_HEADING = "### Late arrivals"


def _queue_pilot(slot: Path, brief: dict, counters: dict, *, amended: bool) -> None:
    """The shift's one pilot row, as an upsert keyed by slot: `pilot.jsonl`
    (machine-readable) and `pilot.md` (its render, the human's `?` cells kept)."""
    record = _digest.pilot_record(slot.name, brief, counters, amended=amended)
    ledger = slot / _mind_writer.LEDGER_DIR
    _mind_writer.queue_op(ledger, {"op": "jsonl-upsert", "path": _digest.PILOT_JSONL,
                                   "key": "slot", "row": record})
    _mind_writer.queue_op(ledger, {"op": "table-upsert", "path": _digest.PILOT_PATH,
                                   "key": slot.name, "header": _digest.PILOT_HEADER,
                                   "row": _digest.pilot_md_row(record).rstrip("\n")})


def late_sweep(brief_path: Path, mind: Path, slot: Path, now: _dt.datetime, *,
               grace_s: float = LEASE_GRACE_S, agents=None,
               tokens=transcript_usage, poster=None) -> dict:
    """A closed shift whose digest is posted, with a worker still out, Mind
    ops still queued (PyAutoBrain#594: a worker finished 12 minutes after
    `review-at:` and its `.done` and ledger ops were stranded) or a failed
    post due its retry.

    Reaps as a live tick does and commits the queued ops through the one Mind
    writer, then names each late arrival in the record under `### Late
    arrivals`, amends the shift's pilot row in place (`amended: true`) and
    posts one correction comment for the shift (#610). Never a spawn, a
    re-dispatch or a close-out: the grant ended at `review-at:`, so what
    arrives late waits for `/prm`."""
    counters = read_counters(slot)
    counters["usage_unavailable"] = []
    reaped = _reap(slot, counters, now, grace_s, agents, tokens, late=True)
    counters["pending_redispatch"] = []      # the grant has ended: never re-dispatched
    counters.setdefault("late", [])
    first = not counters["late"]             # the heading goes in once, with the first
    rel = _record_rel(brief_path, mind)
    lines = []
    for e in reaped:
        task = e.get("task")
        if task is None:
            continue  # liveness unknown this tick: nothing was decided
        if e["event"] == "done":
            urls = _digest.urls_of(counters["outcomes"].get(task))
            what = ", ".join(urls) or "finished, no PR or issue named in its .done"
            if e.get("was") == "parked":
                what += " (was parked)"
        elif e["event"] == "parked":
            what = "parked: awaiting-input (blocked on a person)"
        elif e["event"] == "parked-ended":
            what = "parked worker ended without a .done; not re-dispatched"
        else:
            what = "ended without a .done (crashed); not re-dispatched"
        lines.append(f"- late: {task} — {what} (after review-at, {_iso(now)})")
        counters["late"].append(task)
    rec = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))
    brief, top = rec["brief"] or {}, rec["top"]
    if rel is not None and lines:
        head = f"\n{LATE_HEADING}\n" if first else ""
        _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                              {"op": "append", "path": rel,
                               "text": head + "\n".join(lines) + "\n"})
        _queue_pilot(slot, brief, counters, amended=True)
    _write_counters(slot, counters)
    ledger = {"committed": None, "ops": 0}
    if _mind_writer.pending_ops(slot):
        try:
            ledger = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: late arrivals after review-at")
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    posts = {}
    retried = retry_post(slot / DIGEST_MARKER, slot / DIGEST_FILE, poster, now)
    if retried is not None:
        posts["digest"] = retried["state"]
    retried = retry_post(slot / CORRECTION_MARKER, slot / CORRECTION_FILE, poster, now)
    if retried is not None:
        posts["correction"] = retried["state"]
    mentions = _retry_mentions(slot, counters, poster, now)
    if mentions:
        posts["mentions"] = mentions
        _write_counters(slot, counters)
    if lines and not (slot / CORRECTION_MARKER).exists():
        issue = (top.get("issue") or {}).get("value", "")
        (slot / CORRECTION_FILE).write_text(
            f"Late arrivals after review-at, shift `{slot.name}` — the record's "
            f"`{LATE_HEADING[4:]}` and the pilot row are amended:\n\n"
            + "\n".join(lines) + "\n", encoding="utf-8")
        posted = post_once(slot / CORRECTION_MARKER, issue, slot / CORRECTION_FILE,
                           poster, now)
        if posted is not None:
            posts["correction"] = posted["state"]
    out = {"action": "late", "reaped": reaped, "late": lines, "ledger": ledger}
    if posts:
        out["posts"] = posts
    return out


def _github_merges(counters: dict, review_at, pr_state) -> None:
    """GitHub's merge state for every PR the shift's workers named, read once
    at `review-at:` — `in_window` when merged at or before it (#610). A PR
    GitHub cannot say about is left to what the watcher recorded."""
    for o in counters["outcomes"].values():
        for url in o.get("prs") or []:
            if "/pull/" not in url:
                continue
            gh = pr_state(url) if pr_state else None
            if not gh:
                continue
            merged = gh.get("state") == "MERGED"
            try:
                inside = not gh.get("mergedAt") or review_at is None \
                    or _parse_iso(gh["mergedAt"]) <= review_at
            except ValueError:
                inside = True
            counters["github"][url] = {**gh, "in_window": merged and inside}


def finish_shift(brief_path: Path, mind: Path, slot: Path, now: _dt.datetime, *,
                 poster=None, health=None, agents=None, tokens=transcript_usage,
                 grace_s: float = LEASE_GRACE_S, pr_state=None, github=None) -> dict:
    """Reap, then write the digest into the record and post it on the brief's issue.

    Reaping first (#610) puts a `.done` written after the last live tick into
    the digest. The marker is created **before** the post, exclusively: a
    crash between the two leaves a shift with no comment, never one with two
    (AUTONOMY.md "The watcher's network surface"); a post `gh` said failed is
    retried by the late sweep, up to `POST_TRIES`. Nothing is read back from
    GitHub to check.
    """
    if (slot / DIGEST_MARKER).exists():
        # A finished shift writes nothing more: no second record append, no
        # second pilot row, no second comment.
        return {"action": "digest", "ledger": None, "packet": None,
                "post": {"posted": False, "error": "already posted this shift"}}
    rec = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))
    brief, top = rec["brief"] or {}, rec["top"]
    counters = read_counters(slot)
    counters["usage_unavailable"] = []
    agents = agents or AgentsView()   # one `claude agents` read serves the closing status
    _reap(slot, counters, now, grace_s, agents, tokens)
    counters["pending_redispatch"] = []      # the grant has ended: never re-dispatched
    if not _brief.is_shadow(brief):
        _github_merges(counters, _brief._iso((top.get("review-at") or {}).get("value", "")),
                       pr_state)
    _write_counters(slot, counters)
    issue = (top.get("issue") or {}).get("value", "")
    digest = _digest.build(brief, slot, counters, health=health, issue=issue)
    (slot / DIGEST_FILE).write_text(digest, encoding="utf-8")
    result = {"action": "digest", "ledger": None, "post": None, "packet": None}

    rel = _record_rel(brief_path, mind)
    if rel is not None:
        _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                              {"op": "append", "path": rel, "text": "\n" + digest})
        # The pilot ledger (phase 4a; jsonl #610): one row per shift, in the
        # same commit, upserted by slot so a rerun never writes a second.
        _queue_pilot(slot, brief, counters, amended=False)
        if (slot / LIVE_KEY_FILE).exists():
            # The dashboard's live line ends with the shift (#622).
            _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, {
                "op": "record-key", "path": rel, "key": "live",
                "value": "closed at review-at — the digest is below"
                         + (f" — status: {status_url(slot)}" if status_url(slot) else "")})
        try:
            result["ledger"] = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: digest")
        except _mind_writer.MindWriteError as e:
            result["ledger"] = {"committed": None, "error": str(e)}

    if top.get("packet", {}).get("value", "").lower() == "yes":
        result["packet"] = str(_write_packet(slot, digest))

    posted = post_once(slot / DIGEST_MARKER, issue, slot / DIGEST_FILE, poster, now)
    if posted is None:
        result["post"] = {"posted": False, "error": "already posted this shift"}
        return result
    result["post"] = {k: posted[k] for k in ("posted", "url", "error") if k in posted}
    closing = _close_status(brief_path, slot, issue, now, agents, github)
    if closing:
        result["status"] = closing
    return result


def _close_status(brief_path: Path, slot: Path, issue: str, now: _dt.datetime,
                  agents, github=None) -> dict | None:
    """One last edit of the status comment at `review-at:`, saying the shift
    is closed (#622); never retried — the digest is the record from here."""
    rec = _read_json(slot / STATUS_MARKER)
    if not rec or rec.get("state") != "posted":
        return None
    import _watch  # noqa: E402
    snap = _watch.snapshot(brief_path, slot, now, agents=agents,
                           health=lambda u: "see the digest")
    snap["commands_on"] = False
    rec["due"] = True
    (slot / STATUS_MARKER).write_text(json.dumps(rec, sort_keys=True))
    return _post_status(slot, issue, _watch.render_status(snap), _watch.status_key(snap),
                        now, github)


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


# --- unattended `glance` close-out (phase 4b) ------------------------------------

def _closeouts(slot: Path, brief: dict, counters: dict, spawner, now: _dt.datetime,
               agents: AgentsView | None, health, pr_state=None,
               tokens=transcript_usage) -> dict:
    """Reap finished close-out sessions, then start one per newly green PR.

    The watcher's guards are the ones it can judge from its own reads (AUTONOMY
    "Unattended `glance` merges"): the recorded tier, green CI by `gh pr checks`
    (at least one completed check, all green — a PR with none is refused,
    PyAutoHeart#343), the brief's `merge-cap:`, and never in a shadow shift. The label, Heart and
    the witness are the close-out session's to check — it is the independent
    session, and it refuses rather than merges when one fails.

    GitHub is the merge truth (#603): before a finished close-out is counted
    merged or refused — which frees its `merge-cap:` slot — the PR's state is
    read (`pr_state`, else the spawner's, `gh pr view`). Only a GitHub MERGED
    counts: with a `merged` verdict or no file at all. A `merged` verdict on a
    PR still OPEN holds its slot and is asked again each tick; one GitHub shows
    CLOSED is refused. A non-merged verdict on a PR GitHub shows MERGED was
    merged by someone else — never counted, never a stage-2 row. While GitHub
    cannot be read the slot stays held.
    Every transition is written as it happens; a `.closeout` file is deleted
    only after that write.
    """
    events = {"started": [], "merged": [], "refused": []}
    lease_dir = slot / "leases"
    agents = agents or AgentsView()
    health = health or _digest.pr_health
    pr_state = pr_state or getattr(spawner, "pr_state", None)
    known = None

    for pr, co in counters["closeouts"].items():
        if co["state"] != "running":
            continue
        if co.get("agent_id"):
            # A close-out session spends tokens too: read every tick (#610).
            if known is None:
                known = _liveness_known(agents)
            sid = (agents.session_of(co["agent_id"]) if known else None) or co.get("session_id")
            if sid:
                co["session_id"] = sid
            _measure(counters, co["agent_id"], sid, tokens, kind="closeout", task=co["task"])
        verdict_file = lease_dir / f"{co['task']}.closeout"
        verdict = None
        if verdict_file.exists():
            try:
                verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
            except ValueError:
                verdict = None
            if not isinstance(verdict, dict):
                verdict = {"result": "refused", "why": "unreadable .closeout file"}
        elif co.get("agent_id"):
            if known is None:
                known = _liveness_known(agents)
            if not known:
                continue  # liveness unknown this tick: no decision
            state = agents.state(co["agent_id"])
            if not (state in (None, "done") or state in ENDED_STATES):
                continue
        elif _alive(int(co.get("pid") or 0)):
            continue
        gh = pr_state(pr) if pr_state else None
        if pr_state is not None and gh is None:
            continue  # GitHub could not say: the slot stays held, asked again next tick
        if gh:
            co["github"] = gh
        said_merged = bool(verdict) and verdict.get("result") == "merged"
        gh_state = (gh or {}).get("state")
        # GitHub decides every merge count. Without a GitHub seam (a test
        # spawner) the verdict file is all there is.
        merged = gh_state == "MERGED" if gh else said_merged
        if said_merged and gh and gh_state == "OPEN":
            co["why"] = "close-out said merged; GitHub still OPEN — re-checked each tick"
            _write_counters(slot, counters)
            continue  # e.g. `--auto` pending: not counted, the cap slot stays held
        if merged and co["task"] in counters["dropped"]:
            # Dropped by the human (#622): a merge that landed anyway is never
            # an unattended merge — no count, no stage-2 row.
            co.update(state="refused",
                      why="merged outside the close-out after /drop "
                          f"(mergedBy={(gh or {}).get('mergedBy') or '?'})")
            events.setdefault("merged_outside", []).append(pr)
            events["refused"].append(pr)
        elif merged and verdict is not None and not said_merged:
            # The close-out refused, yet the PR is merged: someone else merged
            # it. Never an unattended merge — no count, no stage-2 row.
            co.update(state="refused",
                      why=f"merged outside the close-out (mergedBy={gh.get('mergedBy') or '?'})")
            events.setdefault("merged_outside", []).append(pr)
            events["refused"].append(pr)
        elif merged:
            if said_merged:
                gate, model = verdict.get("gate", ""), verdict.get("model", "")
            else:
                gate = ("merge confirmed on GitHub"
                        + (f" at {gh['mergedAt']}" if gh.get("mergedAt") else "")
                        + (f" by {gh['mergedBy']}" if gh.get("mergedBy") else "")
                        + " (no .closeout)")
                model = CLOSEOUT_MODEL
            co.update(state="merged", gate=gate, model=model)
            co.pop("why", None)
            counters["glance_auto_merges"] += 1
            out = counters["outcomes"].setdefault(co["task"], {"prs": [pr], "merged": []})
            if pr not in out["merged"]:
                out["merged"].append(pr)
            _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, {
                "op": "table-append", "path": STAGE2_LOG, "heading": STAGE2_HEADING,
                "row": stage2_row(now, co["task"], pr, slot.name, co["gate"], co["model"],
                                  merged_by=(gh or {}).get("mergedBy") or "")})
            events["merged"].append(pr)
        else:
            # Never retried: a close-out that ended without a verdict is the
            # human's to look at, not a second unattended attempt.
            if said_merged:
                why = f"close-out said merged, GitHub {str(gh_state).lower()}"
            elif verdict:
                why = verdict.get("why") or "refused, no reason given"
            else:
                why = "the close-out session ended without a verdict"
            co.update(state="refused", why=why)
            events["refused"].append(pr)
        if co.get("agent_id") in counters["usage"]:
            counters["usage"][co["agent_id"]]["final"] = True   # its last read stands
        _write_counters(slot, counters)
        verdict_file.unlink(missing_ok=True)

    if _brief.is_shadow(brief) or counters.get("paused"):
        return events   # paused (#622): a green PR waits; it is not refused
    cap = _brief._nonneg_int(brief.get("merge-cap", {}).get("value", "")) or 0
    for task, out in counters["outcomes"].items():
        for pr in out["prs"]:
            if "/pull/" not in pr or pr in out["merged"] or pr in counters["closeouts"]:
                continue
            tier = counters["picks"].get(task, {}).get("tier", "?")
            if task in counters["dropped"]:
                counters["closeouts"][pr] = {"task": task, "state": "refused",
                                             "why": "dropped by /drop — the human's /prm"}
                events["refused"].append(pr)
                continue
            if tier != "glance":
                counters["closeouts"][pr] = {"task": task, "state": "refused",
                                             "why": f"tier {tier} — only glance merges unattended"}
                events["refused"].append(pr)
                continue
            verdict = health(pr)
            if verdict == "RUNNING":
                continue  # CI has not landed yet; look again next tick
            if verdict != "HEALTHY":
                counters["closeouts"][pr] = {"task": task, "state": "refused",
                                             "why": f"CI {verdict} — never merged unattended"}
                events["refused"].append(pr)
                continue
            in_flight = sum(1 for c in counters["closeouts"].values() if c["state"] == "running")
            if counters["glance_auto_merges"] + in_flight >= cap:
                # Final for this shift, like every refusal: the PR waits for a
                # human `/prm`, and the digest says why.
                counters["closeouts"][pr] = {"task": task, "state": "refused",
                                             "why": f"merge-cap {cap} reached this shift"}
                events["refused"].append(pr)
                continue
            prompt = counters["picks"].get(task, {}).get("prompt", "")
            co = {"task": task, "state": "running", "started": _iso(now)}
            try:
                co.update(spawner.spawn_closeout(task, pr, prompt, lease_dir))
            except Exception as e:
                counters["closeouts"][pr] = {"task": task, "state": "refused",
                                             "why": f"the close-out could not start: {str(e)[:300]}"}
                events["refused"].append(pr)
                _write_counters(slot, counters)
                continue
            counters["closeouts"][pr] = co
            _write_counters(slot, counters)  # a started close-out is never started twice
            events["started"].append(pr)
    return events


#: The merge-actor class the watcher writes on every stage-2 row (AUTONOMY.md
#: "Merge actor and random audit — 2026-11-12"); the Mind's lifecycle.py holds
#: the full set.
STAGE2_ACTOR = "unattended-watcher"


def stage2_row(now: _dt.datetime, task: str, pr: str, slot_name: str, gate: str,
               model: str, merged_by: str = "") -> str:
    """One row of autonomy_log.md's stage-2 table (its columns: date, task,
    brief, gate with the adversary leg, human action — `merged-unchanged` at
    merge, amended by the human later — merge actor, read by human). The actor
    is always `unattended-watcher`, with GitHub's `mergedBy` as its evidence
    when the watcher has it; `read by human` starts empty."""
    actor = STAGE2_ACTOR + (f" (mergedBy {merged_by})" if merged_by else "")
    cells = (now.strftime("%Y-%m-%d"), f"{task} ({pr})", slot_name,
             f"{gate} / adversary: independent close-out session ({model})",
             "merged-unchanged", actor, "")
    return "| " + " | ".join(" ".join(str(c).replace("|", "/").split()) for c in cells) + " |"


def pick_record(member: dict, brief: dict, *, proposed: bool = False) -> dict:
    """What `counters.json` keeps about one pick — enough for the digest and
    `batch watch` to show it by title, size and repo, not by file name."""
    rec = {"prompt": member["path"], "why": _brief.pick_reason(member, brief),
           "tier": member.get("consequence") or "?",
           "title": member.get("title") or "", "size": member.get("difficulty") or "",
           "repos": list(member.get("repos") or [])}
    if proposed:
        rec["proposed"] = True
    return rec


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
        counters["picks"][task] = pick_record(member, brief, proposed=True)
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
                                 f"spawned {len(res.get('spawned', []))}, "
                                 f"refused {len(res.get('refused', []))}, "
                                 f"live {len(res.get('live', []))}"))
    return 0

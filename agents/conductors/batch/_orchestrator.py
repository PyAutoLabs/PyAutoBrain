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
digest, one correction for a late arrival (#610) and one live status
comment, then only edited (#622) — each claimed by marker first. A parked
worker's question no longer @-mentions the human (M3.5, #645): it lands in
PyAutoMind `questions.md` through the one Mind writer, and the digest counts
it. Each open tick also reads the
shift issue's comments once, for the human's `/pause` `/resume` `/drop`
`/stop` (#622) and `/add` `/cap` `/kill` (#644). Every tick that does work
appends what it did to the slot's `events.jsonl` (`_events`, #644), which
`batch watch --stream` prints; a needs-you event is also one short comment on
the shift issue, at most `EVENT_COMMENTS_MAX` a shift.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _app_token  # noqa: E402 — the batch conductor puts this directory on sys.path
import _brief  # noqa: E402
import _digest  # noqa: E402
import _events  # noqa: E402
import _login  # noqa: E402 — the CLI login probe (M3.6a, PyAutoBrain#659)
import _merge_slots  # noqa: E402 — one merge-cap count per shift (R3, #661)
import _mind_writer  # noqa: E402
import _questions  # noqa: E402

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
#: Sessions a re-dispatch may start beyond the brief's `max-sessions:`
#: (PyAutoBrain#637, item 1) — so a backlog dip can never use up the session
#: a killed worker's task needs. The shift's sessions stay under max + this.
REDISPATCH_SESSIONS = 1
#: A real worker `blocked` (waiting on a human) this long is parked: its lease
#: stays (state `parked`, holding no worker slot) so a late `.done` is still
#: read, the task is not re-dispatched, and the digest names it.
STALL_GRACE_S = 900
#: Sessions that ended without succeeding — reaped as crashes (`_digest`, #592).
ENDED_STATES = _digest.ENDED_STATES
#: The worker prompt every real worker starts from (never a bare session).
WORKER_TEMPLATE = Path(__file__).with_name("worker_template.md")
CLOSEOUT_TEMPLATE = Path(__file__).with_name("closeout_template.md")
#: The branch-update session's prompt (M3.6j, PyAutoBrain#683): one
#: `gh pr update-branch` after an earlier PR of the shift on the same library
#: merged, then end — never a merge, never a wait.
UPDATE_TEMPLATE = Path(__file__).with_name("closeout_update_template.md")
#: The model and effort every spawned worker starts on — the human's ruling of
#: 2026-11-18 (PyAutoBrain#672): Opus at medium effort, whatever the effort of
#: the session that composed the shift.
WORKER_MODEL = "opus"
WORKER_EFFORT = "medium"
#: The close-out session's model (phase 4b). The same model as the workers —
#: the human's call 2026-11-04 (AUTONOMY.md "Stage-2 adversary amendment"): a
#: fresh, independent session that runs the witness itself is the leg. Its
#: effort follows the workers too (2026-11-18). Stage-2 rows record this name.
CLOSEOUT_MODEL = WORKER_MODEL
STAGE2_HEADING = "## Unattended `glance` sub-window (stage 2)"
#: A merged close-out that did not say what became of the task's worktree.
CLEANUP_UNREPORTED = ("not reported by the close-out — check for a worktree left "
                      "behind (`worktree_remove <task>`)")
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
    # PR url → {task, behind, since}: waiting in merge order (M3.6j, #683)
    c.setdefault("merge_waits", {})
    # M3.7b (#688): when the watcher first saw each PR (the NO-CHECKS grace),
    # and each PR's changed files, read once per shift (the S6 overlap rule).
    c.setdefault("pr_seen", {})
    c.setdefault("pr_files", {})
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


def _auth_note(result: dict) -> None:
    """A GitHub identity that failed this tick is named in its result (and in
    what the tick returns, logs and streams) — its writes were held."""
    if _AUTH is not None and _AUTH.used and _AUTH.error and "github_auth" not in result:
        result["github_auth"] = {"error": _AUTH.error, "writes": "held"}


def _log(slot: Path, now: _dt.datetime, result: dict) -> None:
    """Append the tick's result to `tick.log`."""
    _auth_note(result)
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

    def spawn(self, task: str, prompt_path: str, lease_dir: Path,
              redispatch: bool = False, resume: dict | None = None,
              siblings: list[str] | None = None) -> dict:
        mode = "crash" if task in self.crash else "ok"
        proc = subprocess.Popen(
            [sys.executable, "-c", _FAKE_WORKER, str(lease_dir), task, mode,
             str(self.seconds)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        return {"pid": proc.pid, "session_id": f"fake-{proc.pid}", "worktree": None}

    def spawn_closeout(self, task: str, pr_url: str, prompt_path: str, lease_dir: Path,
                       **_order) -> dict:
        """A dry close-out (or branch update): it refuses, because a fake
        session merged and pushed nothing."""
        verdict = {"result": "refused", "pr": pr_url,
                   "why": "fake close-out (dry shift) — nothing merged", "gate": "",
                   "model": "fake"}
        (Path(lease_dir) / f"{task}.closeout").write_text(json.dumps(verdict))
        return {"pid": 0, "agent_id": None}

    def pr_state(self, url: str) -> dict:
        """A dry shift merges nothing, so GitHub is never asked."""
        return {"state": "OPEN", "mergedAt": "", "mergedBy": "", "labels": []}

    def pr_files(self, url: str) -> None:
        """Never asked in a dry shift: nothing merges ahead of anything."""
        return None


#: Prepended to a re-dispatched worker's prompt (PyAutoBrain#632, B1): the
#: crashed worker may already have claimed the task through the ledger.
REDISPATCH_NOTE = """\
This is a RE-DISPATCH: an earlier worker on this task crashed. Its claim may
already be on PyAutoMind main — the `{task_path}` → `active/` move and the
`## {task}` section in `active.md` — and its issue, branch, worktree or PR may
exist. Look before you create: `git -C <PyAutoMind> fetch -q origin main` and
`git -C <PyAutoMind> show origin/main:active.md` (the canonical checkout is not
pulled during a shift). Reuse what exists and do not queue the claim again; a
repeated claim op is skipped by the orchestrator's Mind writer anyway.

"""


#: Prepended to the prompt of a task resumed after the human answered the
#: question an earlier shift parked it on (M3.5, PyAutoBrain#645, Decision H11).
RESUME_NOTE = """\
This task parked on a question in shift `{shift}` and the human has answered
it ({ids}): see "## Answers from the human" in your prompt{comments}. The
canonical Mind checkout is not pulled mid-shift, so read the prompt from
`git -C <PyAutoMind> show origin/main:<its path>`. The answer:
{answers}
Its claim, issue, branch and worktree may exist: reuse them (look before you
create, as a re-dispatch does: `git -C <PyAutoMind> show origin/main:active.md`),
continue from where the earlier worker stopped, and do not queue the claim
again.

"""


#: Prepended to the prompt of a worker whose library already has open PRs
#: from this shift (M3.6j, PyAutoBrain#683): its start no longer waits for
#: them to merge, so it must not build on them, and its merge waits for them.
SIBLING_NOTE = """\
Open sibling PRs: this shift already has these PRs OPEN on the same library
repo, and they merge BEFORE yours (the close-out merges a library's shift PRs
in PR order):
{siblings}
Branch from `main`, never from a sibling's branch: no stacked PRs. Read what
each sibling changes first (`gh pr diff <url> --name-only`). If a sibling
already does your task, end with outcome `obsolete` and name it. If you must
touch the same lines, keep the change minimal and say so in the PR body and
your proof packet: after a sibling merges, the close-out updates your branch
from main and refuses (leaving it for the human's /prm) on a conflict. A
`worktree_check_conflict` hit that names only a listed sibling's branch slug
is not a conflict (ruling e, 2026-11-19): go on. End at PR-open, as every
shift worker does.

"""


def sibling_note(siblings: list[str]) -> str:
    """`SIBLING_NOTE` filled in with the open sibling PRs, one per line."""
    return SIBLING_NOTE.format(siblings="\n".join(f"- {u}" for u in siblings))


def resume_note(resume: dict) -> str:
    """`RESUME_NOTE` filled in from a `parked_elsewhere` release."""
    comments = [c for c in resume.get("comments") or [] if c]
    return RESUME_NOTE.format(
        shift=resume.get("shift", "?"), ids=", ".join(resume.get("ids") or []) or "?",
        comments=(" (and " + ", ".join(comments) + ")") if comments else "",
        answers="\n".join(f"> {a}" for a in resume.get("answers") or []) or "> (see the prompt)")


def worker_prompt(task: str, prompt_path: str, brief_path: Path, lease_dir: Path,
                  redispatch: bool = False, resume: dict | None = None,
                  siblings: list[str] | None = None) -> str:
    """The session template filled in for one task; a re-dispatch is told
    that its predecessor's claim may already exist (#632), a resumed task
    that the human answered its question (M3.5, #645), and a task whose
    library has open PRs from this shift which merge first (M3.6j, #683)."""
    head = REDISPATCH_NOTE.format(task=task, task_path=prompt_path) if redispatch else ""
    head += resume_note(resume) if resume else ""
    head += sibling_note(siblings) if siblings else ""
    return head + WORKER_TEMPLATE.read_text(encoding="utf-8").format(
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


def after_step(after: list[str] | None = None, before: list[str] | None = None,
               disjoint: list[str] | None = None) -> str:
    """The close-out's merge-order step (M3.6j, PyAutoBrain#683), or "" when
    no earlier PR of the shift shares this PR's library: every earlier PR
    must no longer be OPEN, and every one merged after this branch was cut
    must be in it (the update session merged `main` in) — except those whose
    changed files are disjoint from this PR's (S6, M3.7b), which are named
    and not checked."""
    if not (after or before or disjoint):
        return ""
    out = ["4b. Merge order (M3.6j, PyAutoBrain#683): this shift's earlier PRs on this\n"
           "   library merge before this one.\n"]
    if before:
        out.append("   Refuse with why `<url> still open → merge it first` if any of these\n"
                   "   is still OPEN (`gh pr view <url> --json state`):\n"
                   + "".join(f"   - {u}\n" for u in before))
    if after:
        out.append("   This branch was updated from main after these merged. For each, read\n"
                   "   its merge commit (`gh pr view <url> --json mergeCommit`) and this\n"
                   "   PR's head (`gh pr view <this PR> --json headRefOid`), then\n"
                   "   `gh api repos/<owner>/<repo>/compare/<mergeCommit>...<head> --jq .status`:\n"
                   "   only `ahead` or `identical` passes; anything else refuses with why\n"
                   "   `branch not updated after <url> → your /prm`:\n"
                   + "".join(f"   - {u}\n" for u in after))
    if disjoint:
        out.append("   These merged ahead after this branch was cut, but their changed files\n"
                   "   are disjoint from this PR's and GitHub reported no conflict, so the\n"
                   "   branch was not updated for them. Do not compare them; PR CI on this\n"
                   "   head is the verdict (AUTONOMY.md \"Shift speed\", ruling S6):\n"
                   + "".join(f"   - {u} — merged ahead, disjoint files, not updated (S6)\n"
                             for u in disjoint))
    return "".join(out)


def update_prompt(task: str, pr_url: str, prompt_path: str, brief_path: Path,
                  lease_dir: Path, after: list[str]) -> str:
    """The branch-update session's template filled in (M3.6j, #683)."""
    return UPDATE_TEMPLATE.read_text(encoding="utf-8").format(
        task=task, pr_url=pr_url, task_path=prompt_path, brief_path=brief_path,
        lease_dir=lease_dir, after="\n".join(f"- {u}" for u in after))


#: How long a close-out started at PR-open waits in-turn for CI before it
#: refuses (`CI not finished by <deadline> → /prm`; ruling S5, M3.7b). The
#: deadline is never later than `review-at:`.
CLOSEOUT_CI_WAIT_S = 1800
#: The CI deadline ends this long before `review-at:`, leaving room for the
#: `/prm` run after GREEN, so no close-out merges after `review-at:` (#632 F1).
CLOSEOUT_MERGE_MARGIN_S = 300


def closeout_prompt(task: str, pr_url: str, prompt_path: str, brief_path: Path,
                    lease_dir: Path, after: list[str] | None = None,
                    before: list[str] | None = None, disjoint: list[str] | None = None,
                    ci_until: str = "") -> str:
    """The close-out session template filled in for one PR (phase 4b). Its
    Heart check is the scoped development-ship gate for the PR's repo (leg 4,
    PyAutoHeart#340): only `green` merges. Its CI check is `pyauto-brain
    ci-verdict --until <ci_until>` on the PR (PyAutoBrain#628; the in-turn
    wait of ruling S5, M3.7b): only `GREEN` merges. Its public-name check is
    `pyauto-brain public-names` (PyAutoBrain#641): an added or renamed public
    library name, or a diff it cannot read, refuses. It runs no full affected
    smoke (ruling S2). `ci_until` is the watcher's deadline; without one it is
    CLOSEOUT_CI_WAIT_S from now."""
    ci_until = ci_until or _iso(_now() + _dt.timedelta(seconds=CLOSEOUT_CI_WAIT_S))
    repos = pr_repos(pr_url)
    heart_cmd = (f"bash -c 'source \"{COMMON_SH}\"; consult_vitals_verdict --repos {repos}'"
                 if repos else "")
    return CLOSEOUT_TEMPLATE.read_text(encoding="utf-8").format(
        task=task, pr_url=pr_url, task_path=prompt_path, brief_path=brief_path,
        lease_dir=lease_dir, ledger_dir=Path(lease_dir).parent / _mind_writer.LEDGER_DIR,
        shift_ledger=SHIFT_LEDGER, pr_repos=repos or "(none — not a GitHub PR URL)",
        heart_cmd=heart_cmd or "(cannot be scoped — refuse)",
        ci_verdict_cmd=f"{BRAIN_CLI} ci-verdict {pr_url} --until {ci_until}" if repos
        else "(not a GitHub PR URL — refuse)", ci_until=ci_until,
        public_names_cmd=f"{BRAIN_CLI} public-names {pr_url}" if repos
        else "(not a GitHub PR URL — refuse)",
        after_step=after_step(after, before, disjoint))


def closeout_command(task: str, pr_url: str, prompt_path: str, brief_path: Path,
                     lease_dir: Path, mode: str, *, update_after: list[str] | None = None,
                     after: list[str] | None = None,
                     before: list[str] | None = None, disjoint: list[str] | None = None,
                     ci_until: str = "") -> list[str]:
    """The argv that starts one close-out session: its own name, the close-out
    model at the workers' effort, the brief's worker mode. The prompt is last.
    With `update_after` it is the branch-update session instead (M3.6j)."""
    if mode not in _brief.WORKER_MODES:
        raise OrchestratorError(f"worker mode {mode!r} is not one of "
                                + ", ".join(_brief.WORKER_MODES))
    if update_after:
        return ["claude", "--bg", "--name", f"shift-update:{task}", "--model",
                CLOSEOUT_MODEL, "--effort", WORKER_EFFORT, "--permission-mode", mode,
                update_prompt(task, pr_url, prompt_path, brief_path, lease_dir, update_after)]
    return ["claude", "--bg", "--name", f"shift-close:{task}", "--model", CLOSEOUT_MODEL,
            "--effort", WORKER_EFFORT, "--permission-mode", mode,
            closeout_prompt(task, pr_url, prompt_path, brief_path, lease_dir, after, before,
                            disjoint, ci_until)]


#: The variable that names the kick file to every session (M3.7c, #690).
KICK_ENV = "PYAUTO_SHIFT_KICK"


def kick_path(env: dict | None = None) -> Path:
    """The kick file `pyauto-orchestrator.path` watches: systemd's `%S` for a
    user unit — `$XDG_STATE_HOME`, else `~/.local/state` — then
    `pyauto/orchestrator.kick` (M3.7c, PyAutoBrain#690). A session appends a
    line to it after its verdict file, so the next tick starts at once; the
    60-second timer is the backstop. Local only: no network act."""
    env = os.environ if env is None else env
    state = str(env.get("XDG_STATE_HOME") or "").strip()
    if not state or not os.path.isabs(state):
        home = str(env.get("HOME") or "").strip() or str(Path.home())
        state = os.path.join(home, ".local", "state")
    return Path(state) / "pyauto" / "orchestrator.kick"


def _ensure_kick_dir(env: dict) -> None:
    """Create the kick file's folder, best effort: the path unit's
    `MakeDirectory=yes` makes it too, and a session's failed kick changes
    nothing."""
    try:
        Path(env[KICK_ENV]).parent.mkdir(parents=True, exist_ok=True)
    except (KeyError, OSError):
        pass


def worker_env(lease_dir: Path, base: dict | None = None) -> dict:
    """The environment a worker runs in: marked as a shift worker, pointed at
    the shift's ledger, and with git's hooks path overridden so a commit in
    PyAutoMind is refused whatever tool makes it. The watcher's own GitHub
    identity never reaches a worker or close-out: not its static token
    (`PYAUTO_SHIFT_GH_TOKEN`), not its App settings (`PYAUTO_SHIFT_APP_*`,
    the key's path among them, PyAutoBrain#630), and no variable carrying
    either token or an App installation token it minted; the human's own gh
    auth stays (#611 re-review). `PYAUTO_SHIFT_KICK` names the kick file
    (`kick_path`, M3.7c)."""
    env = dict(os.environ if base is None else base)
    secrets = {env.pop(GH_TOKEN_ENV, "").strip()} | _auth().secrets()
    for key in _app_token.APP_ENVS:
        env.pop(key, None)
    secrets.discard("")
    for key in [k for k, v in env.items() if isinstance(v, str) and v.strip() in secrets]:
        env.pop(key)
    n = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    env.update({"PYAUTO_SHIFT_WORKER": "1",
                "PYAUTO_SHIFT_LEDGER_DIR": str(Path(lease_dir).parent / _mind_writer.LEDGER_DIR),
                "GIT_CONFIG_COUNT": str(n + 1),
                f"GIT_CONFIG_KEY_{n}": "core.hooksPath",
                f"GIT_CONFIG_VALUE_{n}": str(WORKER_HOOKS),
                KICK_ENV: str(kick_path(env))})
    return env


def session_command(task: str, prompt_path: str, brief_path: Path, lease_dir: Path,
                    mode: str, redispatch: bool = False,
                    resume: dict | None = None,
                    siblings: list[str] | None = None) -> list[str]:
    """The exact argv that starts one worker — named, on `WORKER_MODEL` at
    `WORKER_EFFORT`, moded, templated; the prompt is the last element.

    No `--session-id`: `claude --bg` (2.1.316) assigns its own, so the worker is
    tracked by the short id the launch prints."""
    if mode not in _brief.WORKER_MODES:
        raise OrchestratorError(f"worker mode {mode!r} is not one of "
                                + ", ".join(_brief.WORKER_MODES))
    return ["claude", "--bg", "--name", f"shift:{task}", "--model", WORKER_MODEL,
            "--effort", WORKER_EFFORT, "--permission-mode", mode,
            worker_prompt(task, prompt_path, brief_path, lease_dir, redispatch, resume,
                          siblings)]


#: `claude --bg` prints `backgrounded · <8-hex id> · <name>` on its first line.
_BG_ID_RE = re.compile(r"backgrounded\W+([0-9a-f]{8})\b")

#: systemd-run's own failures: the scope was never made, so `claude` never
#: ran and a plain launch cannot double-spawn.
_SCOPE_FAILED_RE = re.compile(r"Failed to (start transient scope unit|connect to bus"
                              r"|create bus connection)", re.I)


def scope_command(argv: list[str], task: str, env: dict | None = None,
                  which=shutil.which) -> list[str]:
    """`argv` wrapped in its own transient systemd user scope, when the watcher
    runs inside a systemd unit and `systemd-run` is on PATH (PyAutoBrain#634).

    The first `claude --bg` starts the per-user background-session daemon
    (`claude daemon run`, `origin=transient`) and its `bg-pty-host` spares.
    They inherit the cgroup of whoever launched them. Launched from the
    watcher's oneshot `pyauto-orchestrator.service`, they lived in that
    unit's cgroup, outlived each tick, and systemd logged "Found left-over
    process" on every tick of the first live shift (211 lines). In a scope
    of their own (`app.slice/run-*.scope`) they never share the unit's
    cgroup, and the scope goes away when its last process exits: the daemon
    already quits on its own 5 s after its last client. A daemon some other
    session already runs is only connected to; the scope then holds the
    short-lived client and closes at once. Nothing here stops anything.

    `--scope` runs the command as systemd-run's own child, so the worker's
    environment and working folder pass through unchanged. Outside a unit
    (no `INVOCATION_ID`: a hand-run tick, CI, macOS) or without
    `systemd-run`, the argv comes back unchanged — spawned as before."""
    env = os.environ if env is None else env
    if not env.get("INVOCATION_ID") or not which("systemd-run"):
        return list(argv)
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect",
            f"--description=PyAuto shift session {task}", "--", *argv]


def run_scoped(run, argv: list[str], task: str, **kw):
    """Run `argv` through `scope_command`; if systemd-run itself could not
    make the scope (no user bus), run it plain, exactly as before #634."""
    wrapped = scope_command(argv, task, kw.get("env"))
    res = run(wrapped, **kw)
    if wrapped != argv and res.returncode != 0 and _SCOPE_FAILED_RE.search(res.stderr or ""):
        return run(list(argv), **kw)
    return res


#: The verdict fields of a close-out the watcher refused before any session.
PRESPAWN_GATE = "public-name check (watcher, before spawn)"
PRESPAWN_MODEL = "none — no close-out session started"


def public_names_gate(pr_url: str, check=None) -> str:
    """The deterministic public-name check (AUTONOMY.md "Public-name
    narrowing of `glance` — 2026-11-16", PyAutoBrain#641) on one PR, run by
    the watcher before a close-out session spawns: '' to go on, else the
    refusal's `why`. A repo outside the ruled libraries goes on; a hit or a
    check that cannot tell refuses."""
    try:
        if check is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bin"))
            import public_names as check  # noqa: E402 — bin/, beside ci_verdict.py
        v = check.for_pr(pr_url)
    except Exception as e:   # anything unexpected: fail closed
        return f"public-name check could not tell: {str(e)[:200]} → human /prm"
    return check.reason(v) if v.get("verdict") != "CLEAN" else ""


class RealSpawner:
    """`claude --bg` workers from the session template (phase 3b)."""

    real = True

    def __init__(self, brief_path: Path, mode: str, cwd: Path | None = None, run=None,
                 gh=None, public_names=None, files=None):
        self.brief_path, self.mode, self.cwd = Path(brief_path), mode, cwd
        self.run = run or subprocess.run
        self.gh = gh or gh_pr_state
        self.files = files or gh_pr_files
        self.public_names = public_names or public_names_gate

    def pr_state(self, url: str) -> dict | None:
        """GitHub's word on a PR — the merge truth for a close-out (#603)."""
        return self.gh(url)

    def pr_files(self, url: str) -> list[str] | None:
        """A PR's changed files — the branch-update decision (S6, M3.7b)."""
        return self.files(url)

    def spawn(self, task: str, prompt_path: str, lease_dir: Path,
              redispatch: bool = False, resume: dict | None = None,
              siblings: list[str] | None = None) -> dict:
        argv = session_command(task, prompt_path, self.brief_path, lease_dir, self.mode,
                               redispatch, resume, siblings)
        env = worker_env(lease_dir)
        _ensure_kick_dir(env)
        res = run_scoped(self.run, argv, task, cwd=self.cwd, capture_output=True, text=True,
                         timeout=120, env=env)
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

    def spawn_closeout(self, task: str, pr_url: str, prompt_path: str, lease_dir: Path,
                       update_after: list[str] | None = None, after: list[str] | None = None,
                       before: list[str] | None = None, disjoint: list[str] | None = None,
                       ci_until: str = "") -> dict:
        # The public-name check runs here, deterministically, before any
        # session (#641): a hit or a cannot-tell is this PR's refusal, written
        # as the verdict a close-out would write, and nothing is spawned.
        why = self.public_names(pr_url)
        if why:
            verdict = {"result": "refused", "pr": pr_url, "why": why,
                       "gate": PRESPAWN_GATE, "model": PRESPAWN_MODEL}
            (Path(lease_dir) / f"{task}.closeout").write_text(json.dumps(verdict))
            return {"pid": 0, "agent_id": None}
        argv = closeout_command(task, pr_url, prompt_path, self.brief_path, lease_dir,
                                self.mode, update_after=update_after, after=after,
                                before=before, disjoint=disjoint, ci_until=ci_until)
        # The same scoped route as a worker (#634): a close-out may be the
        # session that starts the daemon.
        env = worker_env(lease_dir)
        _ensure_kick_dir(env)
        res = run_scoped(self.run, argv, task, cwd=self.cwd, capture_output=True, text=True,
                         timeout=120, env=env)
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
    """One read-only `gh pr view`: {state, mergedAt, mergedBy, head,
    mergeable} as GitHub has it, or None when GitHub could not say (#603: the
    merge truth). `head` (the head sha) tells an updated branch's CI from an
    older head's (M3.6j); `mergeable` (`MERGEABLE`, `CONFLICTING` or
    `UNKNOWN`) sends a conflicting PR to its branch update (S6, M3.7b);
    `labels` (their names) refuses a `decision-taken` PR at PR-open (S7,
    M3.7c) — one more field of the same read."""
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "view", url, "--json",
                   "state,mergedAt,mergedBy,headRefOid,mergeable,labels"],
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
            "mergedBy": by.get("login", "") if isinstance(by, dict) else str(by),
            "head": str(data.get("headRefOid") or ""),
            "mergeable": str(data.get("mergeable") or "").upper(),
            "labels": [str(lb.get("name") if isinstance(lb, dict) else lb)
                       for lb in data.get("labels") or []]}


#: `gh pr view --json files` lists at most this many files; a list this long
#: may be cut short, so it is read as unknown (and the branch is updated).
PR_FILES_LIMIT = 100


def gh_pr_files(url: str, run=None) -> list[str] | None:
    """One read-only `gh pr view --json files`: the PR's changed paths, or
    None when GitHub could not say or the list may be truncated (S6, M3.7b:
    the branch-update decision; AUTONOMY.md "The watcher's network surface",
    amendment 2026-11-19). The watcher reads it at most once per PR per shift."""
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "view", url, "--json", "files"],
                  capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or len(files) >= PR_FILES_LIMIT:
        return None
    paths = [f.get("path") for f in files if isinstance(f, dict)]
    if not all(isinstance(p, str) and p for p in paths):
        return None
    return paths


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


def default_token_reserve(budget: int | None, max_sessions: int,
                          estimate: int | None = None) -> int:
    """The per-worker estimate held at spawn until real usage passes it: an
    even share of the budget among the sessions the shift may start, or the
    measured spend of a finished worker when that is larger (#637, item 8).

    An even share alone never refuses a spawn before `max-sessions` does: N
    reservations of budget/N fit the budget exactly. Shift B (400k, 4
    sessions) reserved 100k a worker while its workers spent ~125k, so the
    session cap bound and the shift ended at 498k. With the measured figure
    held instead, a budget sized below the sessions' real cost refuses the
    spawn that would pass it."""
    if not budget:
        return 0
    share = budget // max(max_sessions, 1)
    # Never above half the budget: one outlier worker (450k in a 400k shift)
    # must not refuse the first spawn (#637 review). Never below the share.
    return max(share, min(int(estimate or 0), budget // 2))


#: Earlier shifts whose finished workers the reservation estimate reads.
ESTIMATE_SHIFTS = 3


def worker_token_estimate(slot: Path, counters: dict, budget: int | None = None,
                          mind: Path | None = None) -> int | None:
    """The median measured spend of a worker that finished — in this shift and
    the last `ESTIMATE_SHIFTS` earlier ones in this watcher's home whose
    `token-budget:` is within 2x of `budget` (their `counters.json` and brief
    record: local files, no network). A crashed or unmeasured session is left
    out: it says nothing about a whole task's cost; so is a slot whose files
    have the wrong shape. None when there is no such worker yet."""
    import statistics
    home, here = Path(slot).parent, Path(slot).name
    try:
        earlier = sorted(d for d in home.iterdir() if d.is_dir() and d.name < here
                         and (d / COUNTERS_FILE).is_file())
    except OSError:
        earlier = []
    if budget:
        earlier = [d for d in earlier
                   if (b := slot_budget(d, mind)) and budget / 2 <= b <= budget * 2]
    totals = []
    for c in [_safe_counters(d) for d in earlier[-ESTIMATE_SHIFTS:]] + [counters]:
        try:
            finished = {w.get("key") for w in c["workers"]
                        if "finished" in (w.get("exits") or [])}
            totals += [int(u["total"]) for k, u in c["usage"].items()
                       if k in finished and u.get("kind") == "worker" and u.get("final")
                       and not u.get("unmeasured") and u.get("total")]
        except (AttributeError, TypeError, ValueError, KeyError):
            continue
    return int(statistics.median(totals)) if totals else None


def slot_budget(slot: Path, mind: Path | None = None) -> int | None:
    """An earlier shift's `token-budget:` — recorded in its `counters.json`
    (from #637), else read from its brief record in Mind's working tree."""
    c = _safe_counters(slot)
    b = c.get("token_budget") if isinstance(c, dict) else None
    if isinstance(b, int) and b > 0:
        return b
    if mind is None:
        return None
    try:
        brief = _brief.parse((Path(mind) / "batches" / f"{Path(slot).name}.md")
                             .read_text(encoding="utf-8"))["brief"] or {}
    except (OSError, _brief.BriefError):
        return None
    return _brief._nonneg_int(brief.get("token-budget", {}).get("value", "")) or None


def _safe_counters(slot: Path) -> dict:
    """Another slot's counters, or {} when its file has the wrong shape — a
    note on stderr, never a planner crash (#637 review)."""
    try:
        c = read_counters(slot)
        for key in ("outcomes", "usage"):
            if not isinstance(c[key], dict):
                raise TypeError(f"{key} is not an object")
        for key in ("parked", "workers"):
            if not isinstance(c[key], list):
                raise TypeError(f"{key} is not a list")
        return c
    except (AttributeError, TypeError, ValueError, KeyError) as e:
        print(f"orchestrator: {Path(slot).name}/{COUNTERS_FILE} has the wrong shape "
              f"({e}) — read as no hold and no measure", file=sys.stderr)
        return {}


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
            # Each question lands in the inbox (M3.5, #645): one Mind writer
            # op per issue, queued before the counters write; a replay after a
            # crash is a silent repeat in `questions_edit.add_text`.
            done = counters["outcomes"][task]
            if done.get("questions") and "obsolete" not in done and not done.get("merged"):
                for url in done["questions"]:
                    ask, options = _questions.sidecar(lease_dir, task, url)
                    land_question(slot, counters, lease, task, url, "question", ask,
                                  options, rec.get("key") or task, now)
            if task not in counters["done"]:
                counters["done"].append(task)
            if task in counters["parked"]:
                counters["parked"].remove(task)
            mark("finished")
            # A worker that merged in-turn (`notify`) ran no close-out here:
            # retire its live queue.md entry as an unattended merge does
            # (#637, item 11). Queued before the counters write, and a second
            # retire of the same entry finds none live and is silent.
            for pr in counters["outcomes"][task].get("merged") or []:
                retire = queue_retire_op(counters, task, pr, now, by="the shift worker, in-turn")
                if retire:
                    _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, retire)
                    # Its inbox questions are moot once merged (#645 review):
                    # answered as `(task completed)`, as `lifecycle.py close` would.
                    _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                                          question_retire_op(counters, task, now,
                                                             by="the shift worker, in-turn"))
                    break
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
                key = rec.get("key") or task
                land_question(slot, counters, lease, task, lease.get("shift_issue") or "",
                              "blocked",
                              f"the worker stopped at a prompt nobody answered (session "
                              f"{key}, since {since})", [], key, now)
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
        # A worker the human stopped by `/kill` (#644) ends as `killed`, not
        # `crashed`: it counts for the re-dispatch rule, not as a crash.
        killed = (counters.get("killed") or {}).get(task) or {}
        by_kill = bool(killed) and killed.get("key") == rec.get("key")
        if not by_kill:
            counters["crashes"] += 1
        mark("killed" if by_kill else "crashed")
        again = counters["redispatched"].get(task, 0) < REDISPATCH_LIMIT
        if again and task not in counters["pending_redispatch"]:
            counters["pending_redispatch"].append(task)
        if not again and task not in counters["abandoned"]:
            counters["abandoned"].append(task)
        _write_counters(slot, counters)
        path.unlink(missing_ok=True)
        events.append({"task": task, "event": "dead",
                       "redispatch": "allowed" if again else "spent — abandoned",
                       **({"killed": True} if by_kill else {})})
    return events


def land_question(slot: Path, counters: dict, lease: dict, task: str, issue: str,
                  kind: str, ask: str, options: list, worker: str,
                  now: _dt.datetime) -> bool:
    """Queue one `question-add` op for the Mind writer (M3.5, #645) and note
    it in `counters["inbox"]`. Nothing without the task's prompt or an issue
    (a lease from before M3.5 carries no shift issue: held as before). The
    watcher never reads the issue: the ask is the worker's sidecar, else
    `see the question on the issue`. True when it was queued."""
    prompt = lease.get("prompt") or (counters["picks"].get(task) or {}).get("prompt") or ""
    why = ("no prompt recorded for the task" if not prompt
           else "no shift issue on its lease (spawned before M3.5)" if not issue
           else f"issue `{str(issue)[:80]}` is not an https URL"
           if not str(issue).startswith("https://") else "")
    if why:
        # Never silent (#645 review): the digest names what was not filed.
        unfiled = counters.setdefault("inbox_unfiled", [])
        if not any(u.get("task") == task and u.get("kind") == kind for u in unfiled):
            unfiled.append({"task": task, "kind": kind, "why": why})
        return False
    entry = {"task": prompt, "issue": issue, "kind": kind,
             "ask": _questions.sanitise(ask, _questions.ASK_MAX),
             "options": list(options or []), "shift": Path(slot).name,
             "asked": now.strftime("%Y-%m-%dT%H:%MZ"), "worker": str(worker)}
    if not _questions.note_added(counters, entry):
        return False
    _mind_writer.queue_op(Path(slot) / _mind_writer.LEDGER_DIR, _questions.add_op(entry))
    return True


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


def late_owed(slot: Path) -> bool:
    """What the watcher still owes a shift once its late window has closed
    (M3.6a review): the digest not yet claimed, a digest or correction post
    that failed with tries left, or a queued Mind op. Local reads only."""
    slot = Path(slot)
    return (not (slot / DIGEST_MARKER).exists() or post_due(slot / DIGEST_MARKER)
            or post_due(slot / CORRECTION_MARKER) or bool(_mind_writer.pending_ops(slot)))


def _late_closed(brief_path: Path, now: _dt.datetime) -> str:
    """When the late window closed (`review-at:` + `_brief.LATE_WINDOW_S`) as
    ISO, if it has; else "" (M3.6a, PyAutoBrain#659). Local reads only."""
    try:
        top = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))["top"]
    except (OSError, _brief.BriefError):
        return ""
    at = _brief._iso((top.get("review-at") or {}).get("value", ""))
    if at is None:
        return ""
    closes = at + _dt.timedelta(seconds=_brief.LATE_WINDOW_S)
    return _iso(closes) if now >= closes else ""


def _default_pr_state():
    """GitHub's word on a PR at `review-at:` — none asked in a dry shift."""
    return FakeSpawner().pr_state if os.environ.get(FAKE_ENV) == "1" else gh_pr_state


def tick(brief_path: Path, mind: Path, *, home: Path | None = None,
         now: _dt.datetime | None = None, auth=None, **kw) -> dict:
    """One watcher tick, with its GitHub identity bound for the tick's own
    `gh` calls (PyAutoBrain#630): a `_app_token.WatcherAuth` over the state
    directory — the App's installation token, minted when the tick's first
    watcher GitHub call needs it and held in memory for this tick only —
    unless a test passes its own `auth`."""
    global _AUTH
    now = now or _now()
    prev = _AUTH
    _AUTH = auth or _app_token.WatcherAuth(slot_dir(Path(brief_path), home).parent,
                                           now=now.timestamp())
    try:
        return _tick(brief_path, mind, home=home, now=now, **kw)
    finally:
        _AUTH = prev


def _tick(brief_path: Path, mind: Path, *, home: Path | None = None,
          now: _dt.datetime | None = None, spawner=None,
         grace_s: float = LEASE_GRACE_S, records: list[dict] | None = None,
         agents: AgentsView | None = None, tokens=transcript_usage,
         poster=None, health=None, pr_state=None,
         token_reserve: int | None = None, whoami=None, github=None,
         pr_files=None) -> dict:
    """One watcher tick. Returns what it did; also appended to `tick.log`.

    `pr_state` and `pr_files` are the `gh pr view` seams (a PR's state, and
    its changed files for the branch-update decision, S6); unset, the
    spawner's.

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
        # The late window has closed and nothing is owed (M3.6a,
        # PyAutoBrain#659): the digest is out with no retry due and no Mind op
        # is queued. The shift is over for the watcher: no lock, no reap, no
        # lease renewed, no log line — a worker still out is the human's, by
        # the digest. Anything still owed is caught up first, below.
        closed = _late_closed(brief_path, now)
        if closed and not late_owed(slot):
            return {"action": "idle", "reason": f"late window closed at {closed} "
                                                "(review-at + 45 min); the digest is posted"}
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
                _record_events(slot, now, result, brief_path, poster)
            finally:
                _drop_lock(slot)
            _log(slot, now, result)
            return result
        if why.startswith("review-at") and (slot / DIGEST_MARKER).exists() and (
                leases(slot) or _mind_writer.pending_ops(slot) or closeouts_running(slot)
                or ledger_unreported(slot)
                or post_due(slot / DIGEST_MARKER) or post_due(slot / CORRECTION_MARKER)
                or mentions_due(slot)):
            if not _take_lock(slot, now):
                return {"action": "busy", "reason": "another tick holds the lock"}
            try:
                result = late_sweep(brief_path, mind, slot, now, grace_s=grace_s,
                                    agents=agents, tokens=tokens, poster=poster,
                                    pr_state=(pr_state or getattr(spawner, "pr_state", None)
                                              or _default_pr_state()))
                _record_events(slot, now, result, brief_path, poster)
            finally:
                _drop_lock(slot)
            _log(slot, now, result)
            return result
        return {"action": "idle", "reason": why}

    if (slot / DIGEST_MARKER).exists():
        # Closed early (M3.7c, #690): the digest is out before `review-at:`.
        # As after `review-at:`, the late sweep runs while something is
        # still owed; nothing is spawned, closed out or posted again.
        return _after_early_close(brief_path, mind, slot, now, spawner=spawner,
                                  grace_s=grace_s, agents=agents, tokens=tokens,
                                  poster=poster, pr_state=pr_state)
    top = _brief.parse(brief_path.read_text(encoding="utf-8"))["top"]
    shift = {"issue": (top.get("issue") or {}).get("value", ""),
             "review_at": (top.get("review-at") or {}).get("value", ""),
             "dispatched": (top.get("dispatched") or {}).get("value", ""),
             "brief_path": brief_path}
    (slot / "leases").mkdir(parents=True, exist_ok=True)
    if not _take_lock(slot, now):
        return {"action": "busy", "reason": "another tick holds the lock"}
    try:
        spawner = spawner or default_spawner(brief_path, brief)
        result = _tick_locked(slot, brief, mind, now, spawner,
                              grace_s, records, agents, tokens, health, pr_state,
                              poster=poster, shift=shift, token_reserve=token_reserve,
                              whoami=whoami, github=github, pr_files=pr_files)
        _record_events(slot, now, result, brief_path, poster)
        if early_close_ready(slot, read_counters(slot), result):
            closed = close_early(brief_path, mind, slot, now, shift, poster=poster,
                                 health=health, agents=agents, tokens=tokens,
                                 grace_s=grace_s, github=github,
                                 pr_state=(pr_state or getattr(spawner, "pr_state", None)
                                           or _default_pr_state()))
            result["closed_early"] = _iso(now)
            result["digest"] = {k: closed.get(k) for k in ("post", "ledger", "packet")}
    finally:
        _drop_lock(slot)
    _log(slot, now, result)
    return result


def _fetch_once(mind: Path, counters: dict, now: _dt.datetime) -> None:
    """One `git fetch` of Mind per shift, before its first plan, through the
    one Mind writer's own fetch (#632 review; AUTONOMY.md "The watcher's
    network surface"). A failed fetch is recorded and the local ref read."""
    if counters.get("origin_fetch"):
        return
    try:
        _mind_writer.fetch(mind)
        counters["origin_fetch"] = {"at": _iso(now), "ok": True}
    except _mind_writer.MindWriteError as e:
        counters["origin_fetch"] = {"at": _iso(now), "ok": False, "error": str(e)[:200]}


_DATED_SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
#: An answer restarts its task this shift only with more than this left (M3.6c).
INSHIFT_RESTART_S = 30 * 60
#: The bounded re-fetch for an in-shift answer: at most this often (M3.6c).
ANSWER_FETCH_EVERY_S = 10 * 60


def _open_parks(counters: dict) -> list[str]:
    """Tasks of this shift parked on a question whose answer is not yet in
    hand (a release pending its spawn is not open: the answer was seen)."""
    pending = counters.get("inshift_pending") or {}
    return [t for t, o in (counters.get("outcomes") or {}).items()
            if isinstance(o, dict) and o.get("questions") and "obsolete" not in o
            and not o.get("merged") and t not in pending]


def _fetch_for_answers(mind: Path, counters: dict, now: _dt.datetime,
                       review_at: _dt.datetime | None) -> None:
    """The shift's one fetch (`_fetch_once`), then — M3.6c, human-approved
    2026-11-17 (AUTONOMY.md "The watcher's network surface") — the same
    writer's fetch again, only while a task of this shift is parked on a
    question, more than `INSHIFT_RESTART_S` remain before `review-at:`, and at
    most every `ANSWER_FETCH_EVERY_S`: an answer from the phone moves only
    the remote, and the inbox is read from the local `origin/main`."""
    last = counters.get("origin_fetch")
    if not last:
        _fetch_once(mind, counters, now)
        return
    if not _open_parks(counters) or review_at is None \
            or (review_at - now).total_seconds() <= INSHIFT_RESTART_S:
        return
    at = _parse_iso(last.get("at") or "") if last.get("at") else None
    if at is not None and (now - at).total_seconds() < ANSWER_FETCH_EVERY_S:
        return
    try:
        _mind_writer.fetch(mind)
        counters["origin_fetch"] = {"at": _iso(now), "ok": True}
    except _mind_writer.MindWriteError as e:
        counters["origin_fetch"] = {"at": _iso(now), "ok": False, "error": str(e)[:200]}
    counters["answer_fetches"] = int(counters.get("answer_fetches") or 0) + 1


def released_here(slot: Path, counters: dict, inbox: dict | None, now: _dt.datetime,
                  review_at: _dt.datetime | None) -> dict[str, dict]:
    """{task: release} for each task THIS shift parked on a question that the
    inbox has answered, while more than `INSHIFT_RESTART_S` remain (M3.6c):
    the task restarts this shift instead of the next.

    Idempotent and durable (M3.6c review): the release is held in
    `inshift_pending` and returned on every tick until the task actually
    spawns (`_spawned_release` then uses it up); the parked outcome stays put
    meanwhile, so a release that never spawns — a full cap, a pause, the
    clock — still leaves the park for the next shift's `parked_elsewhere`.
    Once per answer: ids already used to restart the task never release it
    again; a new question answered later does."""
    pending = counters.setdefault("inshift_pending", {})
    if review_at is None or (review_at - now).total_seconds() <= INSHIFT_RESTART_S:
        pending.clear()
        return {}
    used = counters.get("inshift_released") or {}
    if inbox is not None:
        # A pending release the human reopened or dropped since is withdrawn.
        for task in list(pending):
            if _questions.hold_for(task, Path(slot).name, inbox)[0] != "answered":
                pending.pop(task)
    for task in _open_parks(counters):
        rule, info = _questions.hold_for(task, Path(slot).name, inbox)
        if rule != "answered":
            continue
        spent = {i for r in used.get(task) or [] for i in r.get("ids") or []}
        fresh = [i for i in info["ids"] if i not in spent]
        if fresh:
            pending[task] = dict(info, ids=fresh, picked_in=[Path(slot).name])
    return {t: dict(v) for t, v in pending.items()
            if t in (counters.get("outcomes") or {})}


def _spawned_release(counters: dict, task: str, now: _dt.datetime) -> None:
    """A pending in-shift release whose task has just spawned: its parked
    outcome moves to `inshift_released` (the ids are used), it leaves `done`."""
    info = (counters.get("inshift_pending") or {}).pop(task, None)
    if info is None:
        return
    counters.setdefault("inshift_released", {}).setdefault(task, []).append(
        {"ids": info.get("ids") or [], "at": _iso(now),
         "outcome": counters["outcomes"].pop(task, None)})
    if task in counters["done"]:
        counters["done"].remove(task)


def carry_in(slot: Path, counters: dict, now: _dt.datetime) -> dict:
    """Carry-over at a shift's first tick (M3.6c): the newest earlier slot's
    late `glance`/`notify` PRs — never closed out (a merge-order wait among
    them), updated from main but not yet closed out (M3.6j), or refused only
    because they went green too close to `review-at:` — enter this shift's outcomes,
    so its close-out path takes them under this shift's grant (`merge-cap:`,
    CI green, the close-out session's own checks). A PR refused for its tier,
    its CI or a `/drop` stays the human's. Recorded once, as `carried_in`."""
    home, here = Path(slot).parent, Path(slot).name
    try:
        # Dated slots only (`YYYY-MM-DD-…`, a brief record's stem), the newest
        # one that ran something: a shadow or empty slot carries nothing and
        # must not hide an older one; an override brief's stem carries nothing.
        earlier = sorted(d for d in home.iterdir() if d.is_dir() and d.name < here
                         and _DATED_SLOT_RE.match(d.name) and (d / COUNTERS_FILE).is_file()
                         and (_safe_counters(d) or {}).get("outcomes")) \
            if _DATED_SLOT_RE.match(here) else []
    except OSError:
        earlier = []
    rec = {"from": earlier[-1].name if earlier else "", "prs": [], "at": _iso(now)}
    prev = _safe_counters(earlier[-1]) if earlier else {}
    try:
        cut = "green within "
        for task, o in (prev.get("outcomes") or {}).items():
            pick = (prev.get("picks") or {}).get(task) or {}
            if pick.get("tier") not in ("glance", "notify") or task in counters["outcomes"] \
                    or o.get("questions") or task in (prev.get("dropped") or {}):
                # A `/drop`ped task's PR is the human's, whatever its shift
                # recorded for it (M3.6c review: a late or paused one has no
                # close-out refusal to read).
                # A task parked on a question stays parked: its PR waits on
                # the answer, and `parked_elsewhere` keeps its hold (review).
                continue
            # A PR still waiting in merge order, or whose branch was updated
            # but not yet closed out (M3.6j), carries too.
            prs = [u for u in o.get("prs") or [] if "/pull/" in u
                   and u not in (o.get("merged") or [])
                   and ((prev.get("closeouts") or {}).get(u) is None
                        or ((prev.get("closeouts") or {}).get(u) or {}).get("state")
                        in ORDER_STATES
                        or str(((prev.get("closeouts") or {}).get(u) or {}).get("why", ""))
                        .startswith(cut))]
            if not prs:
                continue
            counters["outcomes"][task] = {"prs": prs, "merged": [], "issues": [],
                                          "carried_from": rec["from"]}
            # What each waited behind comes along, so a carried PR never
            # merges ahead of an earlier one that was not carried (M3.6j).
            behind = [b for u in prs
                      for b in ((prev.get("merge_waits") or {}).get(u) or {}).get("behind") or []]
            if behind:
                counters["outcomes"][task]["behind"] = list(dict.fromkeys(behind))
            counters["picks"][task] = dict(pick, why=f"carried over from {rec['from']} · "
                                                     + str(pick.get("why") or ""))
            if task not in counters["done"]:
                counters["done"].append(task)
            rec["prs"] += prs
    except (AttributeError, TypeError) as e:
        print(f"orchestrator: {rec['from']}/{COUNTERS_FILE} has the wrong shape ({e}) — "
              "carry-over stopped there", file=sys.stderr)
    counters["carried_in"] = rec
    return rec


def origin_claims(mind: Path, ref: str = "origin/main", fetch=None) -> dict | None:
    """What Mind `origin/main` holds, read locally and read-only (#632, F4):
    its `draft/` paths and the `## slug` sections of its `active.md`.

    Never a pull. `fetch` (the writer's own `git fetch`, once per shift) runs
    first; after it, the one Mind writer fetches and pushes through this
    checkout on every commit, so the local `origin/main` ref holds every
    claim this watcher committed — the claims a stale canonical `draft/`
    hides. None when `mind` is not a git
    checkout (a scratch Mind: nothing to read); `{"error": …}` when it is one
    and the ref cannot be read — the caller then fails closed."""
    def git(*args):
        return subprocess.run(["git", "-C", str(mind), *args], capture_output=True,
                              text=True, timeout=60)
    try:
        top = git("rev-parse", "--show-toplevel")
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(mind).resolve():
            return None   # not a Mind checkout of its own
        if fetch is not None:
            fetch()
        tree = git("ls-tree", "-r", "-z", "--name-only", ref, "--", "draft/")
        if tree.returncode != 0:
            return {"error": f"{ref} unreadable: " + (tree.stderr or "").strip()[:200]}
        active = git("show", f"{ref}:active.md")
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": f"git could not run: {e}"[:200]}
    if active.returncode != 0:
        # No claims read is not "no claims" (#637 review): fail closed, as an
        # unreadable `draft/` tree does — unless the ref truly has no
        # active.md (a Mind with no registry claims nothing).
        listed = git("ls-tree", "--name-only", ref, "--", "active.md")
        if listed.returncode != 0 or listed.stdout.strip():
            return {"error": f"{ref}:active.md unreadable: "
                             + (active.stderr or "").strip()[:160]}
    sections = claim_sections(active.stdout if active.returncode == 0 else "")
    return {"drafts": set(filter(None, tree.stdout.split("\0"))), "active": set(sections),
            "repos": claimed_repos(sections), "sections": sections}


#: A claim that records human-authorized sharing of its repos (#637, item 4).
_COORDINATION_RE = re.compile(r"^- (coordination|conflict-override):\s*\S", re.M)
_CLAIM_REPO_RE = re.compile(r"^\s+- ([A-Za-z0-9_.-]+)")
_COORDINATION_LINE_RE = re.compile(r"(?m)^- (?:coordination|conflict-override):(.*)$")


def _slug_form(text: str) -> str:
    return re.sub(r"[-_]+", "-", text.lower())


def coordinated_for(sec: dict, task: str) -> bool:
    """Whether a claim's `coordination:` / `conflict-override:` line frees its
    repos for `task` (ruling R2, 2026-11-17): only when it names the task, by
    its slug or prompt stem (`-` and `_` alike). Such a line records sharing
    the human approved with one named task — in shift 2026-11-16-pm a task was
    dispatched onto a claim whose override named another task — never a free
    pass for any."""
    text = _slug_form(sec.get("coordination") or "")
    name = _slug_form(task or "")
    return bool(name) and bool(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text))


def claim_sections(active_text: str) -> dict[str, dict]:
    """The `## slug` sections of an `active.md`: each one's claimed repos (its
    `- repos:` block, in either schema `worktree.sh` reads) and whether it
    records human-authorized coordination (`coordination:` or
    `conflict-override:`)."""
    out: dict[str, dict] = {}
    slug, body = None, []

    def flush():
        if slug is None:
            return
        repos, inside = [], False
        for ln in body:
            if ln.startswith("- repos:"):
                inside = True
                inline = ln[len("- repos:"):].strip()
                repos += [x for x in re.split(r"[,\s]+", inline) if x]
                continue
            if inside:
                m = _CLAIM_REPO_RE.match(ln)
                if m:
                    repos.append(m.group(1))
                    continue
                if ln.strip():
                    inside = False
        keys = dict(re.findall(r"(?m)^- (session|prompt):[ \t]*(.*?)\s*$", "\n".join(body)))
        out[slug] = {"repos": repos,
                     "coordinated": bool(_COORDINATION_RE.search("\n".join(body))),
                     "coordination": " ".join(m.group(1) for m in
                                              _COORDINATION_LINE_RE.finditer("\n".join(body))),
                     "session": keys.get("session", ""), "prompt": keys.get("prompt", "")}
    for ln in active_text.splitlines():
        if ln.startswith("## "):
            flush()
            slug, body = ln[3:].strip(), []
        elif slug is not None:
            body.append(ln)
    flush()
    return out


def _repo_key(name: str) -> str:
    """One spelling per repo: the survey's (`_sizing.normalise_repo`)."""
    from _sizing import normalise_repo  # noqa: E402 — the batch conductor's path
    return normalise_repo(name)


def _library_key(pr_url: str) -> str:
    """The library repo key a PR URL belongs to (`_repo_key` of its repo),
    or "" when its repo is not a library — only library PRs merge in order
    (ruling f, 2026-11-19)."""
    from _sizing import LIBRARY_REPOS  # noqa: E402 — the batch conductor's path
    repo = pr_repos(pr_url)
    key = _repo_key(repo) if repo else ""
    return key if key in LIBRARY_REPOS else ""


def sibling_prs(counters: dict, repos) -> list[str]:
    """This shift's PRs not yet merged on one of `repos`' library repos
    (M3.6j, #683), in PR-number order: the PRs a new worker on that library
    must not stack on, and whose merges come before its own."""
    libs = {_repo_key(r) for r in repos}
    out = []
    for o in (counters.get("outcomes") or {}).values():
        if not isinstance(o, dict):
            continue
        merged = set(o.get("merged") or [])
        out += [u for u in o.get("prs") or [] if "/pull/" in u and u not in merged
                and (k := _library_key(u)) and k in libs]
    return sorted(set(out), key=_pr_number)


def _library_holder(counters: dict, live: dict, task: str, repos) -> tuple[str, str] | None:
    """(library repo, holding task) when a live, parked or re-dispatch-pending
    task other than `task` already holds one of `repos`' library repos."""
    from _sizing import LIBRARY_REPOS  # noqa: E402 — the batch conductor's path
    mine = {_repo_key(r) for r in repos} & LIBRARY_REPOS
    if not mine:
        return None
    holders = [*live, *(counters.get("parked") or []),
               *(counters.get("pending_redispatch") or [])]
    for other in dict.fromkeys(holders):
        if other == task:
            continue
        theirs = {_repo_key(r) for r in ((counters.get("picks") or {}).get(other) or {})
                  .get("repos") or []}
        hit = next((r for r in sorted(mine) if r in theirs), None)
        if hit:
            return hit, other
    return None


def _pr_number(url: str) -> int:
    """A PR URL's number (0 when it is not a PR URL)."""
    key = _merge_slots.pr_key(url)
    return int(key.rsplit("/", 1)[1]) if key else 0


def claimed_repos(sections: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """{repo key: (repo as written, the claiming slug)} for every claim that
    does not record human-authorized coordination."""
    out: dict[str, tuple[str, str]] = {}
    for slug, sec in sections.items():
        if sec["coordinated"]:
            continue
        for repo in sec["repos"]:
            out.setdefault(_repo_key(repo), (repo, slug))
    return out


#: A claim's `- session:` that names a shift worker, in exactly the wording
#: `worker_template.md` pins: `shift worker <slot> (<session id>)`. Anything
#: else (a desktop session, a human who took the task over and rewrote the
#: line, the free wording of the first shifts) is not resumed unattended.
SHIFT_WORKER_SESSION_RE = _mind_writer.SHIFT_WORKER_SESSION_RE


def shift_worker_slot(session: str) -> str:
    """The slot a `- session:` line names, when it is a shift worker's; else ""."""
    m = SHIFT_WORKER_SESSION_RE.match((session or "").strip())
    return m.group(1) if m else ""


def claim_of(sections: dict[str, dict], task: str) -> tuple[str, dict] | None:
    """(slug, section) of the `active.md` claim on a task: the section named
    for it, else the one whose `- prompt:` is its file (a worker picks its
    own slug)."""
    if task in sections:
        return task, sections[task]
    return next(((s, sec) for s, sec in sections.items()
                 if Path(sec.get("prompt") or "").stem == task), None)


def released_picks(counters: dict, live: set[str] | None = None) -> set[str]:
    """This shift's own picks that no longer hold their library repos for a
    START (M3.6j, PyAutoBrain#683; first PyAutoBrain#679): a library is held
    only while a worker on it is live. A pick that finished (done or
    abandoned) releases it, PR open or not: work does not collide, merges do,
    and the close-out serialises merges in PR order (`_merge_blockers`).
    Still holding: a live lease, a park on a question or a person (ruling d),
    an outcome with an open question, a pending re-dispatch (`/kill` or a
    crash: the re-dispatch reuses its PR) or an answered park waiting to
    restart. A task the human `/drop`ped holds nothing once no worker of it
    is live (`live`, the tick's active leases), started or not."""
    hold = {*(counters.get("parked") or []), *(counters.get("pending_redispatch") or []),
            *(counters.get("inshift_pending") or {})}
    live = set(live or ())
    out = set()
    for task in {*(counters.get("done") or []), *(counters.get("abandoned") or [])}:
        if task not in (counters.get("picks") or {}) or task in hold:
            continue
        o = (counters.get("outcomes") or {}).get(task)
        o = o if isinstance(o, dict) else {}
        if not o.get("questions"):
            out.add(task)
    out |= {t for t in (counters.get("dropped") or {}) if t not in live and t not in hold}
    return out


def on_origin(records: list[dict], mind: Path, own: set[str],
              fetch=None, resumes: dict | None = None, released: set[str] | None = None,
              slot_name: str = "") -> tuple[list[dict], dict]:
    """`records` without the drafts Mind origin/main no longer holds as
    unclaimed: a path not under its `draft/` (moved to `active/`, retired, or
    never pushed — the writer's claim move would fail) or a task with a
    `## <task>` section in its `active.md`. A task this shift already picked
    stays (its own re-dispatch). A task whose repo a claim in that
    `active.md` holds is out too, unless the claim records human-authorized
    coordination (PyAutoBrain#637, item 4: a named task started twice, then
    parked on a repo an earlier shift's pick held). Returns (kept, {path: why}).

    `resumes` are the tasks an answer released (M3.5, #645, Decision H11): a
    resume task already claimed is kept, at its `active/` path, but only when
    its claim's `- session:` is `shift worker <slot> (<id>)` for a slot of
    this home that picked it — a claim an interactive session owns, or one a
    human took over, is the human's work and is left alone. Its own claim
    never counts against its repos; every other claim on them does.

    `released` (PyAutoBrain#679) are this shift's own picks that hold no
    library start any more (`released_picks`: finished, PR may still be
    open). A claim one of them left behind — the close-out drops it only
    after the merge, and a set-aside op, a failed push or a close-out that
    skipped it leaves the section — holds nothing, when
    its `- session:` is this shift's own worker (`slot_name`). Any other
    claim still holds."""
    claims = origin_claims(mind, fetch=fetch)
    if claims is None:
        return records, {}
    resumes = resumes or {}
    spent = set()   # claim slugs of this shift's released picks
    if released and slot_name and "error" not in claims:
        for t in released:
            c = claim_of(claims.get("sections") or {}, t)
            if c and shift_worker_slot(c[1].get("session")) == slot_name:
                spent.add(c[0])
    kept, out = [], {}
    for r in records:
        task = task_id(r.get("path") or "")
        claim = claim_of(claims.get("sections") or {}, task) if task in resumes \
            and "error" not in claims else None
        if task in own:
            kept.append(r)
        elif "error" in claims:
            out[r["path"]] = f"Mind {claims['error']} — fail closed"
        elif claim is not None:
            slug, sec = claim
            mine = {_repo_key(x) for x in r.get("declared_repos") or r.get("repos") or []}
            ids = ", ".join(resumes[task].get("ids") or [])
            if shift_worker_slot(sec.get("session")) not in (resumes[task].get("picked_in")
                                                              or ()):
                # Only a claim this watcher's own shift worker wrote, with the
                # pinned wording and a slot that picked the task: a session
                # line a human rewrote (or never a shift's) is the human's.
                out[r["path"]] = (f"resumed after {ids}, but its claim `{slug}` in active.md "
                                  "is not this home's shift worker's (session: "
                                  f"{(sec.get('session') or 'none')[:60]}) — left to the human")
            elif held := next(((repo, other) for other, sec2 in claims["sections"].items()
                               if other != slug and other not in spent
                               and not coordinated_for(sec2, task)
                               for repo in sec2["repos"] if _repo_key(repo) in mine), None):
                # Every other claim on the repo counts, not only the first
                # (`claimed_repos` keeps one per repo): its own does not.
                out[r["path"]] = (f"repo {held[0]} claimed by `{held[1]}` in active.md on "
                                  "Mind origin/main")
            else:
                kept.append(r)
        elif r["path"] not in claims["drafts"]:
            out[r["path"]] = "not in draft/ on Mind origin/main (claimed or retired)"
        elif task in claims["active"]:
            out[r["path"]] = "claimed in active.md on Mind origin/main"
        elif held := _held_for(claims.get("sections") or {}, task,
                               r.get("declared_repos") or r.get("repos") or [],
                               ignore=spent):
            out[r["path"]] = (f"repo {held[0]} claimed by `{held[1]}` in active.md on "
                              "Mind origin/main")
        else:
            kept.append(r)
    return kept, out


def _held_for(sections: dict[str, dict], task: str, repos,
              ignore=frozenset()) -> tuple[str, str] | None:
    """(repo as written, claiming slug) of the first claim on one of `repos`
    that does not free it for `task` (R2: a coordination line frees a repo
    only for the task it names), or None. A slug in `ignore` holds nothing."""
    mine = {_repo_key(x) for x in repos}
    return next(((repo, slug) for slug, sec in sections.items()
                 if slug not in ignore and not coordinated_for(sec, task)
                 for repo in sec["repos"] if _repo_key(repo) in mine), None)


def parked_elsewhere(slot: Path, inbox: dict | None = None,
                     resumes: dict | None = None) -> dict[str, str]:
    """{task: why} for every task an earlier shift in this watcher's home left
    parked on a question — a `question:` (or other push) issue in its `.done`,
    or blocked on a person past the grace — and that no later shift finished
    (PyAutoBrain#637, item 3: a prompt still in `draft/` with no claim was
    picked again by the next shift). Read from the slots' own `counters.json`:
    local files, no network.

    `inbox` is `questions.md` on Mind origin/main (`_questions.read_origin`,
    M3.5 #645). Per task parked in shift `d`: every inbox entry for it from
    `d` answered → released, and recorded in `resumes` (`{task: {shift, ids,
    comments}}`); one dropped → held, shelved (Decision H9 a); one open or
    deferred → held, waiting on it; none (a park from before M3.5), or an
    unreadable inbox (None) → held as before (fail closed).

    A release is used up by the first later shift that picks the task: if
    that worker is still out at its review-at, crashes or is abandoned, the
    task is held again, never resumed twice on one claim. Only an answer
    given after that pick (a re-answer, or a new question answered) releases
    it again; a brief that names it is the human's word, as before."""
    out: dict[str, str] = {}
    released: dict[str, dict] = {}
    picked_in: dict[str, list[str]] = {}
    used: dict[str, tuple[str, str]] = {}    # task → (pick time, slot) of a used release
    home = Path(slot).parent
    try:
        others = sorted(d for d in home.iterdir()
                        if d.is_dir() and d != Path(slot) and (d / COUNTERS_FILE).is_file())
    except OSError:
        return out
    for d in others:
        c = _safe_counters(d)
        if not c:
            continue
        held, freed = dict(out), dict(released)
        touched: set[str] = set()

        def park(task: str, why: str, d=d, held=held, freed=freed, touched=touched) -> None:
            """Hold `task`, unless the inbox answered its questions from `d`."""
            rule, info = _questions.hold_for(task, d.name, inbox)
            touched.add(task)
            used.pop(task, None)
            freed.pop(task, None)
            if rule == "answered":
                held.pop(task, None)
                freed[task] = info
            elif rule == "dropped":
                held[task] = (f"question {', '.join(info['ids'])} dropped by the human: task "
                              "shelved (reopen it, name it in a brief, or /add it)")
            elif rule == "waiting":
                held[task] = f"waiting on {', '.join(info['ids'])} in your inbox"
            else:
                held[task] = why
        try:
            for task, o in c["outcomes"].items():
                if not isinstance(o, dict):
                    raise TypeError(f"outcome of {task!r} is not an object")
                if o.get("questions") and "obsolete" not in o and not o.get("merged"):
                    park(task, f"parked on a question in shift {d.name} ("
                               + ", ".join(map(str, o["questions"]))
                               + ") — not startable until answered")
                elif o.get("prs") or o.get("verdicts") or "obsolete" in o:
                    held.pop(task, None)   # finished since: answered
                    freed.pop(task, None)
                    used.pop(task, None)
                    touched.add(task)
            for task in c["parked"]:
                if task not in c["outcomes"]:
                    park(str(task), f"parked in shift {d.name} (blocked on a person) — "
                                    "not startable until answered")
            for task in c.get("picks") or {}:
                picked_in.setdefault(task, []).append(d.name)
                if task in released and task in freed and task not in touched:
                    # Picked on the release, and no park or finish since:
                    # still out, crashed or abandoned. The release is used.
                    info = freed.pop(task)
                    at = max((str(w.get("spawned") or "") for w in c.get("workers") or []
                              if w.get("task") == task), default="") or d.name
                    used[task] = (at, d.name)
                    held[task] = (f"resumed in shift {d.name} after "
                                  f"{', '.join(info.get('ids') or [])} and not finished — "
                                  "not resumed again until a new answer (or name it in a "
                                  "brief)")
        except (AttributeError, TypeError, ValueError) as e:
            # One malformed file holds nothing and releases nothing (#637 review).
            print(f"orchestrator: {d.name}/{COUNTERS_FILE} has the wrong shape ({e}) — "
                  "read as no hold", file=sys.stderr)
            continue
        out, released = held, freed
    # A used release comes back only with an answer given after that pick.
    for task, (at, where) in used.items():
        info = _questions.answered_since(task, inbox, at)
        if info is not None and task in out:
            out.pop(task)
            released[task] = info
    for task, info in released.items():
        info["picked_in"] = list(picked_in.get(task) or [])
    if resumes is not None:
        resumes.update(released)
    return out


def resume_records(records: list[dict], mind: Path, resumes: dict,
                   ref: str = "origin/main") -> list[dict]:
    """`records` with each released task that a shift already claimed graded
    from its `active/<task>.md` on Mind origin/main (M3.5, #645): `survey`
    reads only `draft/`, and the canonical checkout nobody pulls mid-shift may
    still show the stale draft, which `on_origin` would drop. A task still in
    `draft/` on origin keeps its draft record. Each resume record carries
    `resume` (its ids) for the pick's `why:`. Local git only."""
    import _batch  # noqa: E402 — deferred, as in `_tick_body`
    import tempfile
    if not resumes:
        return records
    out = [r for r in records]
    for task, info in resumes.items():
        try:
            shown = subprocess.run(["git", "-C", str(mind), "show", f"{ref}:active/{task}.md"],
                                   capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            shown = None
        if shown is not None and shown.returncode == 0 and shown.stdout.strip():
            with tempfile.TemporaryDirectory(prefix="resume-") as tmp:
                f = Path(tmp) / "active" / f"{task}.md"
                f.parent.mkdir()
                f.write_text(shown.stdout, encoding="utf-8")
                g = _batch.grade(f, Path(tmp))
            text = shown.stdout
            g.update(looks_shipped=False, epic=_batch._epic_of(text),
                     phase=_batch._phase_of(text),
                     phase_declared=_batch._phase_declared(text), done=_batch._is_done(text),
                     themes=_batch._themes_of(text), title=_batch._title_of(text))
            out = [r for r in out if task_id(r["path"]) != task] + [g]
        for r in out:
            if task_id(r["path"]) == task:
                r["resume"] = dict(info)
    return out


def active_leases(slot: Path) -> dict[str, dict]:
    """The leases that hold a worker slot: a parked worker's does not."""
    return {t: l for t, l in leases(slot).items() if l.get("state") != "parked"}


def _tick_locked(slot, brief, mind, now, spawner, grace_s, records, agents,
                 tokens, health=None, pr_state=None, *, poster=None, shift=None,
                 token_reserve=None, whoami=None, github=None, pr_files=None) -> dict:
    """The tick under its lock, then the live status (PyAutoBrain#622): one
    `claude agents` view and one set of `gh pr checks` reads serve both."""
    shift = shift or {}
    agents = agents or AgentsView()
    health = _TickHealth(health)
    out = _tick_body(slot, brief, mind, now, spawner, grace_s, records, agents, tokens,
                     health, pr_state, poster=poster, shift=shift,
                     token_reserve=token_reserve, whoami=whoami, github=github,
                     pr_files=pr_files)
    status = _live_status(slot, mind, shift, now, agents, health.cached, github,
                          stopped=out.get("action") == "stopped")
    if status:
        out["status"] = status
    if health.seen:
        # Every CI verdict this tick read, for the event stream's `ci` line
        # (#644): no read of its own — the close-outs made these.
        out["health"] = dict(health.seen)
    _note_auth_file(slot, now)
    return out


#: A named task the plan never saw: not in the survey of `draft/`.
NAMED_NO_DRAFT = "no draft prompt for it (already issued to active/, retired or never pushed)"


def _named_reasons(brief: dict, d: dict, planned: dict) -> dict[str, str]:
    """{named task: why it did not start} for the digest (M3.6b): the plan's
    rejection, or — for a named task neither picked, rejected, held by a claim
    nor parked — that it has no draft prompt to start."""
    named = _brief.tasks_of(brief)
    names = {Path(t).name for t in named}
    out = {p: w for p, w in d["rejected"] if Path(p).name in names}
    seen = {Path(p).name for p in [*out, *(m["path"] for m in d["members"]),
                                   *(planned.get("claimed") or {}),
                                   *(planned.get("parked") or {})]}
    out.update({t: NAMED_NO_DRAFT for t in named if Path(t).name not in seen})
    return out


def _tick_body(slot, brief, mind, now, spawner, grace_s, records, agents,
               tokens, health=None, pr_state=None, *, poster=None, shift=None,
               token_reserve=None, whoami=None, github=None, pr_files=None) -> dict:
    counters = read_counters(slot)
    counters["usage_unavailable"] = []   # this tick's reads decide
    reaped = _reap(slot, counters, now, grace_s, agents, tokens)
    import _batch  # noqa: E402 — deferred: _batch imports this module's sibling
    planned = {}

    def plan() -> dict:
        """The plan inside the brief, made once a tick when first needed."""
        if "d" not in planned:
            recs = records if records is not None else _batch.survey(mind)
            # A task the human added by `/add` (#644) is graded from Mind
            # origin/main when it is added: a prompt filed mid-shift is in no
            # survey of the canonical checkout, which nobody pulls mid-shift.
            have = {r["path"] for r in recs}
            recs = recs + [a["record"] for a in (counters.get("added") or {}).values()
                           if isinstance(a.get("record"), dict)
                           and a["record"].get("path") not in have]
            # Parked on a question by an earlier shift (#637, item 3): not
            # startable until answered. A brief that names it again is the
            # human's word that it is; a task this shift picked stays. Read
            # first, so the digest gives the park as the reason.
            named = {Path(t).name for t in _brief.tasks_of(brief)}
            # The inbox releases a hold once its questions are answered (M3.5,
            # #645): read from Mind origin/main after the shift's one fetch.
            resumes: dict = {}
            review_at = _brief._iso((shift or {}).get("review_at") or "")
            inbox = _questions.read_origin(
                mind, fetch=lambda: _fetch_for_answers(mind, counters, now, review_at))
            parked = parked_elsewhere(slot, inbox, resumes)
            # This shift's own parks an answer released with time left (M3.6c).
            here = released_here(slot, counters, inbox, now, review_at)
            resumes.update(here)
            _write_counters(slot, counters)
            planned["parked"] = {r["path"]: parked[task_id(r["path"])] for r in recs
                                 if task_id(r["path"]) in parked
                                 and task_id(r["path"]) not in counters["picks"]
                                 and Path(r["path"]).name not in named}
            recs = [r for r in recs if r["path"] not in planned["parked"]]
            # A task this shift picked is never resumed from an earlier park —
            # except one this shift's own answer just released (M3.6c).
            resumes = {t: v for t, v in resumes.items()
                       if t not in counters["picks"] or t in here}
            recs = resume_records(recs, mind, resumes)
            # Against Mind origin/main, not the canonical checkout nobody
            # pulls mid-shift (#632, F4): a draft another shift already
            # claimed is never picked again, nor one whose repo a claim holds.
            # A carried task (M3.6c) is closed out, never planned: not this
            # shift's own pick for the claim gate, and out of the plan.
            carried = {t for t, o in (counters.get("outcomes") or {}).items()
                       if isinstance(o, dict) and o.get("carried_from")}
            recs = [r for r in recs if task_id(r["path"]) not in carried]
            # A pick whose worker has ended frees its library for a start
            # (M3.6j, #683); its PR's merge waits in order at the close-out.
            freed = released_picks(counters, live=set(active_leases(slot))) - carried
            recs, claimed = on_origin(recs, mind, set(counters["picks"]) - carried,
                                      fetch=lambda: _fetch_once(mind, counters, now),
                                      resumes=resumes, released=freed, slot_name=slot.name)
            planned["claimed"] = claimed
            planned["resume"] = {t: v for t, v in resumes.items()
                                 if any(task_id(r["path"]) == t for r in recs)}
            # Unattended by construction: an absent Lane is excluded and an
            # empty queue.md stops the backlog dip (M2.3, AUTONOMY.md "M2
            # rulings — 2026-11-12"). Recorded each tick so the digest can say so.
            planned["d"] = _batch.plan(recs, session_lane="local-dev", brief=brief,
                                       queue=_batch.read_queue(mind), released=freed)
        return planned["d"]

    def known(task: str) -> bool:
        named = {task_id(p) for p in _brief.tasks_of(brief)}
        return task in named or task in {task_id(m["path"]) for m in plan()["members"]}

    # The human steers from the shift issue (#622): read once, before anything
    # this tick starts, so a /pause or /drop binds on the tick that reads it.
    ctx = {"brief": brief, "now": now, "mind": mind,
           "review_at": _brief._iso((shift or {}).get("review_at") or "")}
    commands = _steer(slot, counters, shift or {}, now, github, whoami, known, ctx=ctx)
    _write_counters(slot, counters)
    if any(c["command"] in ("add", "cap") for c in commands):
        planned.clear()   # an /add or /cap changes what this tick's plan admits
    # `/cap` overrides and `/add`ed tasks (#644), from here on in this tick:
    # every later reader (the spawn gates, the close-out gates) sees them.
    written = brief
    brief = _brief.effective(brief, counters)
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
                slot, mind, f"shift {slot.name}: ledger from workers",
                own_tasks=counters["redispatched"])
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    if "carried_in" not in counters and not _brief.is_shadow(brief):
        carry_in(slot, counters, now)       # the shift's first tick (M3.6c)
        _write_counters(slot, counters)
    closeouts = _closeouts(slot, brief, counters, spawner, now, agents, health, pr_state,
                           tokens=tokens, pr_files=pr_files,
                           review_at=_brief._iso((shift or {}).get("review_at") or ""))
    if _mind_writer.pending_ops(slot):  # a stage-2 row queued by a merged close-out
        try:
            ledger = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: unattended close-out",
                own_tasks=counters["redispatched"])
        except _mind_writer.MindWriteError as e:
            ledger = {"committed": None, "error": str(e)}
    mentions = _mentions(slot, counters, shift or {}, poster, now, whoami)
    _write_counters(slot, counters)
    live = active_leases(slot)
    max_workers = _brief.cap_of(brief, "max-workers")
    max_sessions = _brief.cap_of(brief, "max-sessions")

    d = plan()
    counters["backlog_gates"] = {"lane_absent": sorted(d["lane_absent"]),
                                 "queue_stop": d["queue_stop"],
                                 "origin": planned.get("claimed") or {},
                                 "parked": planned.get("parked") or {},
                                 "resumed": planned.get("resume") or {},
                                 "scoped_reach": sorted(d.get("scoped_reach") or []),
                                 # M3.6b: why each named task did not start (the
                                 # digest's "Not started" reason), and the backlog
                                 # drafts kept out for want of a `Witness:`.
                                 "named": _named_reasons(brief, d, planned),
                                 "witness_absent": sorted(d.get("witness_absent") or [])}
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
    written_budget = _brief._nonneg_int(written.get("token-budget", {}).get("value", ""))
    if written_budget:
        # What a later shift's estimate compares: the brief's own figure, not
        # a `/cap tokens` lowered for this shift.
        counters["token_budget"] = written_budget
    # A real worker holds a reservation from its spawn until its measured
    # usage passes it, so the budget binds on the first tick (#610). A fake
    # (dry-shift) worker spends nothing.
    reserve = 0
    if getattr(spawner, "real", False):
        reserve = token_reserve if token_reserve is not None \
            else default_token_reserve(budget, max_sessions,
                                       worker_token_estimate(slot, counters, budget, mind))
    spawned, refused = [], []
    # A re-dispatch goes first (#637, item 1): a backlog dip never takes the
    # worker slot a killed task is waiting for.
    first_glance = (brief.get("first") or {}).get("value") == "glance"
    members = sorted(d["members"],
                     key=lambda m: (task_id(m["path"]) not in counters["pending_redispatch"],
                                    # `first: glance` (M3.6c): spawn order only —
                                    # the plan's selection is unchanged.
                                    not (first_glance and m.get("consequence") == "glance")))
    # The CLI login (M3.6a, #659): an expired one holds every spawn, as its
    # own event — never a worker "blocked on a person".
    login = _login_hold(counters, spawner, [] if paused else members, live, now)
    hold = paused or (login or {}).get("state") == "expired"

    def settled(task: str, member: dict) -> bool:
        """Not this tick's to start: live, done, abandoned, parked or dropped."""
        released = member.get("resume") and task in (counters.get("inshift_pending") or {})
        return bool(task in live or (task in counters["done"] and not released)
                    or task in counters["abandoned"]
                    or task in counters["parked"] or task in counters["dropped"])
    # What could still start on a later tick (M3.7c early close): a launch
    # that failed, a spend that could not be read, a login to renew. A task
    # held by a library, `max-workers` with nobody live, `max-sessions` or
    # the token budget cannot; neither can a parked or dropped one.
    startable: list[str] = []
    final: set[str] = set()
    if hold and not paused:
        startable = [task_id(m["path"]) for m in members
                     if not settled(task_id(m["path"]), m)]
    for member in [] if hold else members:
        task = task_id(member["path"])
        released = member.get("resume") and task in (counters.get("inshift_pending") or {})
        if settled(task, member):
            continue
        # Never two workers on one library (M3.6j review F2): a live, parked
        # or re-dispatch-pending task holds its library repos whatever the
        # plan's rank order made of it this tick.
        holder = _library_holder(counters, live, task, member.get("repos") or [])
        if holder:
            refused.append({"task": task, "why": f"{holder[0]} held by {holder[1]} "
                                                 "while its worker runs"})
            final.add(task)
            continue
        if len(live) >= max_workers:
            refused.append({"task": task, "why": f"max-workers {max_workers} reached"})
            final.add(task)
            continue
        # A re-dispatch may pass `max-sessions` by REDISPATCH_SESSIONS (#637,
        # item 1): after early dips used every session, a killed worker
        # stayed "awaiting re-dispatch" to the end of shift A.
        redo = task in counters["pending_redispatch"]
        limit = max_sessions + (REDISPATCH_SESSIONS if redo else 0)
        if counters["sessions"] >= limit:
            refused.append({"task": task, "why": f"max-sessions {max_sessions} reached"
                            + (f" (+{REDISPATCH_SESSIONS} for a re-dispatch)" if redo else "")})
            final.add(task)
            continue
        if counters["usage_unavailable"]:
            # Never counted as 0: a spend the watcher cannot read could be
            # anything, so nothing more starts until it can be read.
            refused.append({"task": task, "why": "token usage unavailable ("
                            + ", ".join(counters["usage_unavailable"]) + ")"})
            startable.append(task)
            continue
        if budget is not None and counters["tokens"] >= budget:
            refused.append({"task": task, "why": f"token-budget {budget} spent "
                                                f"({counters['tokens']})"})
            final.add(task)
            continue
        committed = _committed_tokens(counters)
        if budget is not None and committed + reserve > budget:
            refused.append({"task": task, "why": f"token-budget {budget}: {committed} "
                                                f"committed + {reserve} reserved per worker"})
            final.add(task)
            continue
        lease = {"task": task, "prompt": member["path"], "started": _iso(now),
                 "heartbeat": _iso(now),
                 "expires": _iso(now + _dt.timedelta(seconds=grace_s)),
                 "pid": 0, "session_id": None, "worktree": None}
        if (shift or {}).get("issue"):
            # Where a worker blocked past the grace is filed in the inbox (#645).
            lease["shift_issue"] = shift["issue"]
        lease_path = slot / "leases" / f"{task}.json"
        if not _create_exclusive(lease_path, lease):
            continue  # a lease appeared since we read them: never a second worker
        try:
            # Only a re-dispatch passes the flag, so a spawner without it
            # (a test's) is called exactly as before.
            again = {"redispatch": True} if task in counters["pending_redispatch"] else {}
            if member.get("resume"):
                again["resume"] = member["resume"]   # answered: RESUME_NOTE (#645)
            siblings = sibling_prs(counters, member.get("repos") or [])
            if siblings:
                again["siblings"] = siblings         # open on its library (M3.6j)
            lease.update(spawner.spawn(task, member["path"], slot / "leases", **again))
        except Exception as e:
            # One task's failed launch is that task's refusal, not the tick's:
            # what this tick already reaped stays written, the rest carry on.
            lease_path.unlink(missing_ok=True)
            refused.append({"task": task, "why": f"spawn failed: {str(e)[:300]}"})
            startable.append(task)
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
        if released:
            _spawned_release(counters, task, now)
        if task in counters["pending_redispatch"]:
            counters["pending_redispatch"].remove(task)
            counters["redispatched"][task] = counters["redispatched"].get(task, 0) + 1
        counters["sessions"] += 1
        _write_counters(slot, counters)
        live[task] = lease
        spawned.append({"task": task, "pid": lease["pid"]})
    _digest.note_refusals(counters, refused, _iso(now))
    _write_counters(slot, counters)
    # A re-dispatch still owed holds the shift open unless a cap refused it.
    startable += [t for t in counters["pending_redispatch"]
                  if t not in final and t not in live and t not in startable]
    out = {"action": "ticked", "reaped": reaped, "spawned": spawned,
           "refused": refused, "live": sorted(live), "ledger": ledger,
           "closeouts": closeouts}
    if startable:
        out["startable"] = sorted(set(startable))
    if mentions:
        out["mentions"] = mentions
    if login:
        out["login"] = login
    return _steered(out, commands, paused)


def _login_hold(counters: dict, spawner, members: list[dict], live: dict,
                now: _dt.datetime, probe=None) -> dict | None:
    """The CLI login as this tick sees it (M3.6a, PyAutoBrain#659), or None.

    Probed (`claude auth status --json`, local, no model call) only for a
    real spawner, and only when a member is waiting to start while the last
    probe was not `ok` — the shift's first tick, or one after an expiry — or
    when a worker shows `blocked` this tick, which an expired login looks
    like. `expired` holds every spawn until a probe passes; `unknown` holds
    nothing. Kept in `counters["login"]`, with `since` the first tick of an
    expiry (the event's key)."""
    if not getattr(spawner, "real", False):
        return None
    last = counters.get("login") or {}
    blocked = any(w.get("blocked_seen") == _iso(now) and w.get("task") not in counters["parked"]
                  for w in counters["workers"])
    held = (set(live) | set(counters["done"]) | set(counters["abandoned"])
            | set(counters["parked"]) | set(counters["dropped"]))
    wanted = any(task_id(m["path"]) not in held for m in members)
    if not (blocked or (wanted and last.get("state") != "ok")):
        return last if last.get("state") == "expired" else None
    res = (probe or _login.probe)()
    if res.get("state") == "skipped":
        return None
    rec = {**res, "at": _iso(now)}
    if res.get("state") == "expired":
        rec["since"] = (last.get("since") if last.get("state") == "expired" else None) \
            or _iso(now)
    counters["login"] = rec
    return rec


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


#: The watcher's own GitHub identity, for its own `gh` calls and nothing else
#: (then the human's account is the one an @mention notifies, #611 review):
#: its minimal GitHub App (`PYAUTO_SHIFT_APP_*`, PyAutoBrain#630), else this
#: static token as the fallback, else `gh`'s own auth. See `_app_token`.
GH_TOKEN_ENV = _app_token.GH_TOKEN_ENV
#: The identity bound for the current tick (`tick`); outside one, a fresh one.
_AUTH = None


def _auth():
    return _AUTH if _AUTH is not None else _app_token.WatcherAuth(orchestrator_home())


def _gh_env() -> dict | None:
    """The environment for one of the watcher's own `gh` calls. Raises
    `_app_token.AppTokenError` when an App is configured and no installation
    token can be had: the caller then makes no call — never one under the
    human's `gh` auth in its place."""
    return _auth().env()


def _note_auth(counters: dict, now: _dt.datetime) -> bool:
    """Record in `counters` (and so in the digest) that the watcher's App
    identity failed this tick and its GitHub writes were held; once a tick."""
    a = _AUTH
    if a is None or not a.used or not a.error:
        return False
    g = counters.get("github_auth") or {}
    if g.get("last") == _iso(now):
        return False
    counters["github_auth"] = {"error": a.error, "first": g.get("first") or _iso(now),
                               "last": _iso(now), "ticks": int(g.get("ticks") or 0) + 1}
    return True


def _note_auth_file(slot: Path, now: _dt.datetime) -> None:
    if _AUTH is not None and _AUTH.used and _AUTH.error and (slot / COUNTERS_FILE).exists():
        c = read_counters(slot)
        if _note_auth(c, now):
            _write_counters(slot, c)


def _poster_login(counters: dict, whoami=None) -> None:
    """Once per shift: who the watcher's comments post as. An App identity
    that cannot be read now is read again later, never recorded as ''."""
    if "poster_login" in counters:
        return
    who = (whoami or gh_login)()
    if who is None and _auth().mode == "app":
        return
    counters["poster_login"] = who or ""


def gh_login(run=None) -> str | None:
    """The login the watcher's comments post as; None when it cannot say. As
    the App, `<slug>[bot]` (`GET /app` with its JWT — `gh api user` does not
    answer for an installation token); else `gh api user` under the posting
    token."""
    a = _auth()
    if a.mode == "app":
        return None if a.error else a.login()
    run = run or subprocess.run
    try:
        res = run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True,
                  timeout=60, env=_gh_env())
    except (OSError, subprocess.SubprocessError, _app_token.AppTokenError):
        return None
    login = (res.stdout or "").strip()
    return login if res.returncode == 0 and login else None


def gh_comment(issue_url: str, body_file: Path, run=None) -> dict:
    """The watcher's one kind of write: a comment on the brief's `issue:`,
    posted as the watcher's own identity (`_gh_env`). `retry: False` marks a
    failure after which the comment may have landed; `unsent: True` one where
    no call was made (no App token), which costs the post no try."""
    try:
        env = _gh_env()
    except _app_token.AppTokenError as e:
        return {"posted": False, "unsent": True, "error": f"no GitHub identity: {e}"[:300]}
    run = run or subprocess.run
    try:
        res = run(["gh", "issue", "comment", issue_url, "--body-file", str(body_file)],
                  capture_output=True, text=True, timeout=120, env=env)
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
    rec = {k: v for k, v in rec.items() if k not in ("error", "retry", "unsent")}
    rec.update(res)
    if res.get("unsent"):
        # Nothing reached GitHub (no App token): this try does not count.
        rec["tries"] = max(0, int(rec.get("tries", 1)) - 1)
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
    """(task, state, reason) for each worker that needs the human's @mention
    on the shift issue. Since M3.5 (#645) none: a worker blocked on a person
    past the grace (parked) and one whose `.done` names an issue not marked
    `verdict:` both land in the questions inbox instead (`land_question`),
    and the digest's one inbox line is their notice. The mention machinery
    (markers, retries, the late sweep) stays for other triggers; a trigger is
    read from durable state (`counters.json`, the leases), never from one
    tick's events, so a tick that died before posting still mentions once."""
    # M3.5 (#645, Decision H7 a; memory `parked-questions-bulk-inbox`: never
    # ask mid-run): a parked worker and a question no longer @-mention the
    # human. Each lands in `questions.md` (`land_question`), and the digest
    # says how many at review-at. The machinery stays for other triggers.
    return []


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
                if marker.stem.startswith("event."):
                    # A needs-you event comment (#644): counted apart from pushes.
                    if rec.get("state") == "posted":
                        counters["event_comments"] = int(counters.get("event_comments") or 0) + 1
                    out.append({"event": rec.get("event"), "post": rec["state"],
                                "retry": rec["tries"]})
                    continue
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
    if login:
        # Once per shift: who the comments post as. The human's own login
        # gets no notification for its own comment (#611 review).
        _poster_login(counters, whoami)
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
#: The steering commands, read from the human's comments on the shift issue
#: (#622; `/add`, `/cap` and `/kill` from #644).
COMMANDS = ("pause", "resume", "drop", "stop", "add", "cap", "kill")
_COMMAND_RE = re.compile(
    r"^/(pause|resume|drop|stop|add|cap|kill)\b[ \t]*(\S+)?(?:[ \t]+(\S+))?[ \t]*$")
#: The one verb that takes two arguments (`/cap <what> <n>`).
_TWO_ARGS = ("cap",)
_TASK_ARG_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
#: `/add` is refused this close to `review-at:` — a worker needs longer
#: (human ruling H8, 2026-11-16).
ADD_CUTOFF_S = 1800
#: `/cap <what>` → the brief key it lowers (human ruling H6: never above the
#: brief's own value).
CAP_KEYS = {"merges": "merge-cap", "workers": "max-workers", "sessions": "max-sessions",
            "tokens": "token-budget"}
#: `/kill`'s one local act, `claude stop <id>` — not a network call.
STOP_TIMEOUT_S = 30
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
    watcher's own identity (`_gh_env`) — the only edit the watcher makes. An
    edit is idempotent, so any failure is retried next tick."""
    m = _COMMENT_API_RE.match(comment_url or "")
    if not m:
        return {"edited": False, "error": f"not a comment URL: {comment_url!r}"[:300]}
    try:
        env = _gh_env()
    except _app_token.AppTokenError as e:
        return {"edited": False, "error": f"no GitHub identity: {e}"[:300]}
    payload = Path(body_file).with_suffix(".json")
    payload.write_text(json.dumps({"body": Path(body_file).read_text(encoding="utf-8")}),
                       encoding="utf-8")
    run = run or subprocess.run
    try:
        res = run(["gh", "api", "-X", "PATCH",
                   f"repos/{m.group(1)}/{m.group(2)}/issues/comments/{m.group(3)}",
                   "--input", str(payload), "--jq", ".html_url"],
                  capture_output=True, text=True, timeout=120, env=env)
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
    try:
        env = _gh_env()
    except _app_token.AppTokenError:
        return None
    run = run or subprocess.run
    query = f"?per_page=100&since={since}" if since else "?per_page=100"
    try:
        res = run(["gh", "api", f"repos/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}"
                   f"/comments{query}"],
                  capture_output=True, text=True, timeout=60, env=env)
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
    steering command and nothing else; None otherwise. `/cap`'s two
    arguments come back as one, space-separated; every other verb takes one
    at most, as before #644."""
    first = next((ln.strip() for ln in (body or "").splitlines() if ln.strip()), "")
    m = _COMMAND_RE.match(first)
    if not m:
        return None
    one, two = (m.group(2) or "").strip("`"), (m.group(3) or "").strip("`")
    if two and m.group(1) not in _TWO_ARGS:
        return None
    return m.group(1), (f"{one} {two}" if two else one)


def _apply_command(slot: Path, counters: dict, cmd: str, arg: str, who: str,
                   at: str, known=None, ctx: dict | None = None) -> str:
    """Enact one command; returns its acknowledgement. `known(task)` says
    whether a task belongs to this shift (a pick, a lease, a brief or plan
    member). `ctx` is what `/add`, `/cap` and `/kill` judge against: the
    brief as written, `now`, `review_at` and the Mind checkout."""
    if cmd in ("add", "cap", "kill"):
        ctx = ctx or {}
        try:
            return {"add": _cmd_add, "cap": _cmd_cap, "kill": _cmd_kill}[cmd](
                slot, counters, arg, who, at, ctx)
        except Exception as e:   # one command's failure is its ack, never the tick's
            return f"refused: /{cmd} could not be judged ({str(e)[:200]})"
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
           whoami=None, known=None, ctx: dict | None = None) -> list[dict]:
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
    written by the posting identity (`gh api user`, or the App's
    `<slug>[bot]`; once per shift)."""
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
    if adopting:
        _poster_login(counters, whoami)
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
        ack = _apply_command(slot, counters, cmd, arg, c["login"], c["created_at"], known,
                             ctx=ctx)
        counters["commands"].append({"id": c["id"], "command": "/" + cmd + (f" {arg}" if arg else ""),
                                     "by": c["login"], "at": c["created_at"], "url": c["url"],
                                     "ack": ack})
        out.append({"command": cmd, "arg": arg, "ack": ack, "id": c["id"], "by": c["login"],
                    "at": c["created_at"], "url": c["url"]})
    counters["commands_seen"] = sorted(seen)
    return out


# --- `/cap`, `/add`, `/kill` (#644; human rulings H5, H6, H8 of 2026-11-16) -------------

def _cap_ceiling(brief: dict, key: str) -> int | None:
    """A cap as `brief` states it: the spawn caps with their defaults, the
    merge cap 0 when absent (as the close-out reads it), and no token
    ceiling when the brief sets no `token-budget:`."""
    if key in ("max-workers", "max-sessions"):
        return _brief.cap_of(brief, key)
    value = _brief._nonneg_int((brief.get(key) or {}).get("value", ""))
    return (value or 0) if key == "merge-cap" else value


def _cap_number(word: str, tokens: bool) -> int | None:
    if re.fullmatch(r"\d+", word or ""):
        return int(word)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM])", word or "") if tokens else None
    if m:
        return int(round(float(m.group(1)) * (1000 if m.group(2) in "kK" else 1_000_000)))
    return None


def _cmd_cap(slot: Path, counters: dict, arg: str, who: str, at: str, ctx: dict) -> str:
    """`/cap merges|workers|sessions|tokens <n>`: lower one of this shift's
    caps, or raise it back, never above the brief's own value. It never
    kills, never stops a close-out already running and never edits the
    brief; `_brief.effective` applies it from this tick on."""
    words = (arg or "").split()
    if not words or words[0] not in CAP_KEYS:
        return "ignored: /cap takes merges, workers, sessions or tokens"
    key = CAP_KEYS[words[0]]
    n = _cap_number(words[1], key == "token-budget") if len(words) == 2 else None
    if n is None:
        return "ignored: /cap needs a whole number"
    brief = ctx.get("brief") or {}
    ceiling = _cap_ceiling(brief, key)
    if ceiling is not None and n > ceiling:
        return (f"refused: /cap {words[0]} {words[1]} is above this brief's {key} {ceiling}. "
                "A higher cap needs a new brief.")
    was = _cap_ceiling(_brief.effective(brief, counters), key)
    counters.setdefault("caps", {})[key] = {"value": n, "by": who, "at": at, "was": was,
                                            "brief": ceiling}
    of = f"{ceiling}" if ceiling is not None else "none"
    if key == "merge-cap":
        # Every slot taken this shift — in-turn merges, close-outs merged and
        # close-outs still running alike (R3, #661).
        # An in-turn merge made with no slot is counted too (#661 review).
        try:
            taken = _merge_slots.used(slot)
            unslotted = len(_digest.no_slot_merges(
                {**counters, "slot_holders": _merge_slots.holders(slot)}))
        except (_merge_slots.MergeSlotError, OSError):
            return f"merge-cap now {n} of this brief's {of} (merge slots unreadable)."
        count = taken + unslotted
        tail = (": no new merge starts." if count >= n
                else f": up to {n - count} more may merge.")
        extra = f", plus {unslotted} merged with no merge slot" if unslotted else ""
        return (f"merge-cap now {n} of this brief's {of} ({taken} merge slot(s) taken so far"
                f"{extra}){tail}")
    if key == "max-workers":
        live = len(active_leases(slot))
        return f"max-workers now {n} of {of}." + (
            f" {live} still running are not stopped; no new spawn until fewer than {n}."
            if live >= n else "")
    if key == "max-sessions":
        started = int(counters.get("sessions") or 0)
        return f"max-sessions now {n} of {of} ({started} started)" + (
            ": no new spawn." if started >= n else ".")
    committed = _committed_tokens(counters)
    tail = "."
    if committed >= CLOSEOUT_BUDGET_FACTOR * n:
        tail = ": no new spawn or close-out."
    elif committed >= n:
        tail = f": no new spawn; close-outs stop at {int(CLOSEOUT_BUDGET_FACTOR * n)}."
    return f"token-budget now {n} of {of} ({committed} committed){tail}"


def _origin_prompt(mind: Path, arg: str) -> tuple[str | None, str]:
    """(Mind-relative path, '') of the draft `arg` names on Mind origin/main,
    or (None, the ignored ack). A path is read as given; a basename must name
    exactly one draft. Local git reads after the `/add` fetch."""
    if "/" in arg:
        rel = arg if arg.endswith(".md") else arg + ".md"
        if _brief.origin_text(mind, rel) is None:
            return None, f"ignored: no prompt {rel} on Mind origin/main (filed? pushed?)"
        return rel, ""
    name = arg if arg.endswith(".md") else arg + ".md"
    try:
        res = subprocess.run(["git", "-C", str(mind), "ls-tree", "-r", "-z", "--name-only",
                              "origin/main", "--", "draft/"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"ignored: Mind origin/main unreadable ({str(e)[:120]})"
    if res.returncode != 0:
        return None, "ignored: Mind origin/main unreadable: " + (res.stderr or "").strip()[:120]
    hits = sorted(p for p in res.stdout.split("\0") if p and Path(p).name == name)
    if not hits:
        return None, f"ignored: no prompt {name} on Mind origin/main (filed? pushed?)"
    if len(hits) > 1:
        return None, f"ignored: {name} names {len(hits)} drafts: give the path"
    return hits[0], ""


def _in_shift(task: str, slot: Path, counters: dict, brief: dict) -> str:
    """Why `task` is already this shift's ('' when it is not)."""
    if task in leases(slot):
        return "running"
    if task in counters.get("added", {}):
        return "added by /add"
    if task in counters["dropped"]:
        return "dropped"
    if task in counters["done"] or task in counters["outcomes"]:
        return "finished"
    if task in counters["picks"]:
        return "picked"
    if task in {task_id(p) for p in _brief.tasks_of(brief)}:
        return "named in the brief"
    return ""


def _cmd_add(slot: Path, counters: dict, arg: str, who: str, at: str, ctx: dict) -> str:
    """`/add <prompt>`: make a draft a brief-named task for the rest of this
    shift. The planner's own gates judge it as they judge a named task; it
    overrides the brief's `exclude:` and an earlier shift's parked hold (the
    human's newer word), never the organ rule (human ruling H8)."""
    if not arg or not _TASK_ARG_RE.match(arg):
        return "ignored: /add needs a prompt (draft/…/x.md, x.md or x)"
    now, review_at = ctx.get("now") or _now(), ctx.get("review_at")
    if review_at is not None and (review_at - now).total_seconds() < ADD_CUTOFF_S:
        return (f"refused: /add within {ADD_CUTOFF_S // 60} min of review-at. "
                "A worker needs longer.")
    brief = ctx.get("brief") or {}
    if _brief.is_shadow(brief):
        return "refused: shadow shift: nothing is dispatched."
    mind = Path(ctx["mind"])
    try:
        # One fetch per `/add` (AUTONOMY.md amendment 2026-11-16, #644): a
        # prompt filed mid-shift is newer than the once-per-shift fetch.
        _mind_writer.fetch(mind)
    except _mind_writer.MindWriteError as e:
        counters.setdefault("add_fetch_errors", []).append(str(e)[:200])
    rel, why = _origin_prompt(mind, arg)
    if rel is None:
        return why
    task = task_id(rel)
    state = _in_shift(task, slot, counters, brief)
    if state:
        return f"ignored: {task} is already in this shift ({state})"
    text = _brief.origin_text(mind, rel) or ""
    added_dir = slot / "added"
    added_dir.mkdir(parents=True, exist_ok=True)
    (added_dir / Path(rel).name).write_text(text, encoding="utf-8")
    import _batch  # noqa: E402 — deferred, as in `_tick_body`
    rec = _batch.grade_text(text, rel, mind)
    if (organ := _batch.self_organ_why(rec)):
        return f"refused: {task} {organ} (the organ rule: /add never overrides it)"
    if (lane := _batch.lane_absent_why(rec)):
        return f"refused: {task}: no Lane: line ({lane})"
    ex_paths, ex_keyed = _brief.excluded_of(brief)
    excluded = Path(rel).name in {Path(p).name for p in ex_paths} \
        or rec.get("epic") in ex_keyed.get("epics", []) \
        or bool(set(rec.get("themes") or []) & set(ex_keyed.get("tags", [])))
    trial = dict(counters, added={**counters.get("added", {}), task: {"prompt": rel}})
    eff = _brief.effective(brief, trial)
    d = _batch.plan([rec], session_lane="local-dev", brief=eff, queue=None)
    if not any(m.get("path") == rel for m in d["members"]):
        reason = next((w for p, w in d["rejected"] if p == rel), "not admitted by the planner")
        return f"refused: {task}: {reason}"
    kept, claimed = on_origin([rec], mind, set())
    if not kept:
        return f"refused: {task}: {claimed.get(rel) or 'claimed on Mind origin/main'}"
    # The inbox's word on earlier parks (#645): an answered park is not "was parked".
    was_parked = task in parked_elsewhere(slot, _questions.read_origin(mind))
    counters.setdefault("added", {})[task] = {"prompt": rel, "by": who, "at": at, "record": rec}
    notes = "".join([" (was excluded in the brief)" if excluded else "",
                     " (was parked)" if was_parked else ""])
    max_workers = _brief.cap_of(_brief.effective(brief, counters), "max-workers")
    live = len(active_leases(slot))
    when = ("starts this tick" if live < max_workers
            else "starts when a worker slot frees (next in line)")
    return (f"added {task} ({rec.get('consequence') or '?'}){notes}: {when}; "
            f"max-workers {max_workers}, {live} running.")


def claude_stop(agent_id: str, run=None) -> tuple[bool, str]:
    """`claude stop <id>`, the local CLI (30 s timeout): (stopped?, why not)."""
    run = run or subprocess.run
    try:
        res = run(["claude", "stop", agent_id], capture_output=True, text=True,
                  timeout=STOP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if res.returncode != 0:
        first = next((ln for ln in ((res.stderr or "") + (res.stdout or "")).splitlines()
                      if ln.strip()), f"exit {res.returncode}")
        return False, first.strip()
    return True, ""


def _cmd_kill(slot: Path, counters: dict, arg: str, who: str, at: str, ctx: dict) -> str:
    """`/kill <task>` (human ruling H5): stop that task's running worker with
    `claude stop`. The next reap sees it ended: it is `killed` (not a crash)
    and re-dispatched once by the usual rule, unless the task was dropped.
    A close-out is not killable here."""
    if not arg or not _TASK_ARG_RE.match(arg):
        return "ignored: /kill needs a task name"
    task = Path(arg).stem
    lease = leases(slot).get(task)
    if lease is None:
        return f"ignored: no running worker for {task}"
    key = _worker_key(lease, task)
    agent = lease.get("agent_id")
    if not agent:
        return (f"refused: {task}'s worker {key} is no claude session (a dry-run stub). "
                "Stop it by hand.")
    old = (counters.get("killed") or {}).get(task) or {}
    if old.get("key") == key:
        return f"ignored: {task}'s worker {key} is already stopping (/kill at {old.get('at')})"
    # A crash between this stop and the counters write leaves the comment
    # unseen: the next tick stops the same agent id again, at most — never another session.
    ok, why = (ctx.get("stop") or claude_stop)(agent)
    if not ok:
        return (f"refused: claude stop failed: {why[:160]}. Stop it by hand: "
                f"claude stop {agent}")
    counters.setdefault("killed", {})[task] = {"by": who, "at": at, "key": key}
    if task in counters["dropped"]:
        tail = f"It is not restarted: {task} was dropped."
    elif lease.get("state") == "parked":
        tail = "It stays parked for you; it is not restarted."
    elif counters["redispatched"].get(task, 0) >= REDISPATCH_LIMIT:
        tail = "It is not restarted: its one retry is spent."
    else:
        tail = f"It is restarted once, unless you /drop {task}."
    return f"stopping {task}'s worker {key} (claude stop). {tail}"


# --- the event stream's watcher side (#644) --------------------------------------------

#: Needs-you event comments a shift may post (human ruling H4b), then one
#: last one saying the rest are in the status comment.
EVENT_COMMENTS_MAX = 5
EVENT_OVERFLOW = "event.overflow"


def _event_info(brief_path: Path, slot: Path) -> dict:
    """What the record says about the shift, with this shift's `/cap`s and
    `/add`s applied — the `shift-open` and `merged` lines. Local reads."""
    try:
        rec = _brief.parse(Path(brief_path).read_text(encoding="utf-8"))
    except (OSError, _brief.BriefError):
        return {}
    top = rec["top"]
    eff = _brief.effective(rec["brief"] or {}, _safe_counters(slot) or {})
    return {"review_at": (top.get("review-at") or {}).get("value", ""),
            "issue": (top.get("issue") or {}).get("value", ""),
            "named": len(_brief.tasks_of(eff)),
            "merge_cap": _cap_ceiling(eff, "merge-cap"),
            "token_budget": (eff.get("token-budget") or {}).get("value", "")}


def shift_quiet(slot: Path) -> bool:
    """Nothing left for the late sweep: no lease, no queued Mind op, no
    close-out out, nothing unreported, no post due — the late sweep's own
    condition, negated. Local reads."""
    return not (leases(slot) or _mind_writer.pending_ops(slot) or closeouts_running(slot)
                or ledger_unreported(slot) or post_due(slot / DIGEST_MARKER)
                or post_due(slot / CORRECTION_MARKER) or mentions_due(slot))


def _record_events(slot: Path, now: _dt.datetime, result: dict, brief_path: Path,
                   poster=None) -> None:
    """Append the tick's events (inside the tick lock), then post a comment
    for each needs-you one. Never fails the tick: a fault is named on stderr
    and the tick carries on."""
    _auth_note(result)
    try:
        info = _event_info(brief_path, slot)
        quiet = shift_quiet(slot) if result.get("action") in ("digest", "late") else None
        new = _events.record_tick(slot, now, result, info=info, quiet=quiet)
    except Exception as e:
        print(f"orchestrator: events not recorded this tick ({e})", file=sys.stderr)
        return
    try:
        posted = _event_comments(slot, new, info.get("issue", ""), poster, now)
    except Exception as e:
        print(f"orchestrator: needs-you comment failed ({e})", file=sys.stderr)
        return
    if posted:
        result["event_comments"] = posted


def event_comment_body(slot_name: str, event: dict) -> str:
    """A needs-you event as a short comment: no `@`, so it notifies only those
    who already take part in the issue (the human, through their commands)."""
    return (f"Shift `{slot_name}` needs you: {event['line']}\n\n"
            f"(event {event['seq']}, `{event['kind']}`; the status comment has the rest. "
            f"At most {EVENT_COMMENTS_MAX} such comments a shift.)\n").replace("@", "@\u200b")


def _event_comments(slot: Path, events: list[dict], issue: str, poster,
                    now: _dt.datetime) -> list[dict]:
    """One comment per needs-you event on the shift issue (human ruling H4b),
    at most `EVENT_COMMENTS_MAX` a shift and then one overflow comment, each
    claimed by its marker before the post (`mentions/event.<seq>`); a post
    `gh` said failed is retried with the mentions. Each counts in
    `event_comments`, apart from the per-worker `pushes`."""
    todo = [e for e in events if e.get("needs_you")]
    if not todo or not issue.startswith("http") or (slot / STOP_FILE).exists():
        return []
    d = slot / MENTIONS_DIR
    d.mkdir(parents=True, exist_ok=True)
    sent = len([m for m in d.glob("event.*.json") if m.stem != EVENT_OVERFLOW])
    counters = read_counters(slot)
    out = []
    for e in todo:
        if sent >= EVENT_COMMENTS_MAX:
            name = EVENT_OVERFLOW
            text = (f"Shift `{slot.name}`: further needs-you events are in the status "
                    "comment (and the event stream); no more such comments this shift.\n")
        else:
            name, text = f"event.{e['seq']}", event_comment_body(slot.name, e)
        if (d / f"{name}.json").exists():
            break
        (d / f"{name}.md").write_text(text, encoding="utf-8")
        rec = post_once(d / f"{name}.json", issue, d / f"{name}.md", poster, now,
                        event=e["seq"], kind=e["kind"])
        if rec is None:
            continue
        sent += 1
        if rec.get("state") == "posted":
            # Counted apart from the per-worker pushes, whose digest finding
            # budgets about one a shift (AUTONOMY.md push test).
            counters["event_comments"] = int(counters.get("event_comments") or 0) + 1
        out.append({"event": e["seq"], "post": rec.get("state")})
        if name == EVENT_OVERFLOW:
            break
    _write_counters(slot, counters)
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
    `batch watch`, from what this tick already read — no network read of its
    own (the work-issue links are a local git read of Mind, #634).
    On the `/stop` tick only the status write runs, as the acknowledgement:
    nothing is queued or committed to Mind, exactly as under `STOP`."""
    brief_path = shift.get("brief_path")
    if brief_path is None:
        return None
    import _watch  # noqa: E402 — deferred: _watch imports this module
    issue = shift.get("issue", "")
    snap = _watch.snapshot(brief_path, slot, now, agents=agents, health=health,
                           mind=mind, issue=issue)
    out = {}
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
            out["ledger"] = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: live status",
                own_tasks=read_counters(slot)["redispatched"])
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
               tokens=transcript_usage, poster=None, pr_state=None) -> dict:
    """A closed shift whose digest is posted, with a worker still out, Mind
    ops still queued (PyAutoBrain#594: a worker finished 12 minutes after
    `review-at:` and its `.done` and ledger ops were stranded) or a failed
    post due its retry.

    Reaps as a live tick does and commits the queued ops through the one Mind
    writer, then names each late arrival in the record under `### Late
    arrivals`, amends the shift's pilot row in place (`amended: true`) and
    posts one correction comment for the shift (#610). Never a spawn, a
    re-dispatch or a close-out: the grant ended at `review-at:`, so what
    arrives late waits for `/prm`.

    A close-out still out at `review-at:` is reaped here too (#632, F1): its
    merge is counted, its stage-2 row queued and the pilot row amended, and
    the sweep runs while one is out."""
    counters = read_counters(slot)
    counters["usage_unavailable"] = []
    agents = agents or AgentsView()
    reaped = _reap(slot, counters, now, grace_s, agents, tokens, late=True)
    closed = reap_closeouts(slot, counters, now, agents, pr_state, tokens, late=True)
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
    review_at = _brief._iso((top.get("review-at") or {}).get("value", ""))
    for pr in closed["merged"] + closed["refused"]:
        co = counters["closeouts"][pr]
        gh = co.get("github")
        if gh:   # GitHub's word replaces the one read at review-at
            try:
                inside = review_at is None or not gh.get("mergedAt") \
                    or _parse_iso(gh["mergedAt"]) <= review_at
            except ValueError:
                inside = True
            counters["github"][pr] = {**gh, "in_window": gh.get("state") == "MERGED"
                                      and inside}
        what = (f"close-out merged {pr} unattended (stage-2 row written)"
                if co["state"] == "merged" else f"close-out on {pr} ended: {co.get('why', '?')}")
        lines.append(f"- late: {co['task']} — {what} (after review-at, {_iso(now)})")
        counters["late"].append(co["task"])
    # A Mind op set aside, in conflict or held after the digest was built
    # reaches the human here: a late line, the record and the correction.
    for e in ledger_unreported(slot):
        lines.append(f"- late: Mind ledger — {_digest.report_line(e)[2:]} "
                     f"(after review-at, {_iso(now)})")
        counters["late"].append(f"ledger:{e.get('file')}")
    counters["ledger_reported"] = len(_mind_writer.report(slot))
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
                slot, mind, f"shift {slot.name}: late arrivals after review-at",
                own_tasks=counters["redispatched"])
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
    _note_auth_file(slot, now)
    return out


# --- early close (M3.7c, PyAutoBrain#690) -----------------------------------------

def early_close_ready(slot: Path, counters: dict, result: dict) -> bool:
    """Whether a live tick leaves the shift with nothing to do before
    `review-at:` (M3.7c, decisions 2 and 3). All must hold: the tick ran
    (not shadow, not stopped) and the shift is not paused; nothing this
    tick read failed (the steering comments, Mind origin/main); the shift has
    started something (a worker or a carried PR), so a plan that could not be
    read never closes it; no worker holds a lease (a parked one does not
    count); no pick could still start (`startable`: a failed launch, an
    unreadable spend, an expired login, a re-dispatch no cap refused); no
    close-out or branch update is running or waiting on the updated head's
    CI; and every open PR of the shift is judged — refused, merged, or
    waiting in merge order behind an earlier PR (a wait behind a /prm-bound
    PR does not hold the shift open)."""
    if result.get("action") != "ticked" or result.get("paused") or counters.get("paused"):
        return False
    if result.get("spawned") or result.get("startable"):
        return False
    # Review round 1, finding 1: an input this tick could not read is never
    # "nothing to do" — an unread `/add` or `/resume` on the shift issue, or
    # drafts the plan dropped because Mind origin/main failed closed.
    if counters.get("commands_unread"):
        return False
    origin = (counters.get("backlog_gates") or {}).get("origin") or {}
    if any(str(w).endswith("fail closed") for w in origin.values()):
        return False
    outcomes = counters.get("outcomes") or {}
    if not (counters.get("sessions") or outcomes):
        return False
    if active_leases(slot):
        return False
    cos = counters.get("closeouts") or {}
    if any(co.get("state") in ("running", *ORDER_STATES) for co in cos.values()):
        return False
    waits = counters.get("merge_waits") or {}
    for o in outcomes.values():
        if not isinstance(o, dict):
            continue
        for pr in o.get("prs") or []:
            if "/pull/" in pr and pr not in (o.get("merged") or []) \
                    and pr not in cos and pr not in waits:
                return False      # not judged yet: CI grace, an unread label, …
    return True


def close_early(brief_path: Path, mind: Path, slot: Path, now: _dt.datetime, shift: dict, *,
                poster=None, health=None, agents=None, tokens=transcript_usage,
                grace_s: float = LEASE_GRACE_S, github=None, pr_state=None) -> dict:
    """Close the shift on this tick (M3.7c): record when, then the digest as
    at `review-at:`, with this tick's time as the shift's end — merges are
    counted up to it. Called inside the tick lock."""
    counters = read_counters(slot)
    counters["closed_early"] = _iso(now)
    counters["review_at"] = (shift or {}).get("review_at", "")
    _write_counters(slot, counters)
    result = finish_shift(brief_path, mind, slot, now, poster=poster, health=health,
                          agents=agents, tokens=tokens, grace_s=grace_s, pr_state=pr_state,
                          github=github, closed_at=now)
    _record_events(slot, now, result, brief_path, poster)
    return result


def _after_early_close(brief_path: Path, mind: Path, slot: Path, now: _dt.datetime, *,
                       spawner=None, grace_s: float = LEASE_GRACE_S, agents=None,
                       tokens=transcript_usage, poster=None, pr_state=None) -> dict:
    """A tick inside the window of a shift that closed early: the late sweep
    while something is owed, else idle. Steering is not read: the shift is
    over, as after `review-at:`."""
    if not shift_quiet(slot):
        if not _take_lock(slot, now):
            return {"action": "busy", "reason": "another tick holds the lock"}
        try:
            result = late_sweep(brief_path, mind, slot, now, grace_s=grace_s, agents=agents,
                                tokens=tokens, poster=poster,
                                pr_state=(pr_state or getattr(spawner, "pr_state", None)
                                          or _default_pr_state()))
            _record_events(slot, now, result, brief_path, poster)
        finally:
            _drop_lock(slot)
        _log(slot, now, result)
        return result
    at = (_safe_counters(slot) or {}).get("closed_early") or "?"
    return {"action": "idle", "reason": f"closed early at {at}; the digest is posted"}


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
                 grace_s: float = LEASE_GRACE_S, pr_state=None, github=None,
                 closed_at: _dt.datetime | None = None) -> dict:
    """Reap, then write the digest into the record and post it on the brief's issue.

    `closed_at` is an early close's time (M3.7c): the shift's end in place of
    `review-at:`, so merges are counted up to it.

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
    # A close-out that ended since the last tick lands in this digest (#632,
    # F1); one still out is reaped by the late sweep.
    reap_closeouts(slot, counters, now, agents, pr_state, tokens)
    counters["pending_redispatch"] = []      # the grant has ended: never re-dispatched
    if not _brief.is_shadow(brief):
        _github_merges(counters, closed_at or _brief._iso(
            (top.get("review-at") or {}).get("value", "")), pr_state)
    issue = (top.get("issue") or {}).get("value", "")
    if issue.startswith("http"):
        # The digest is about to be posted: an App identity that cannot be had
        # is named in the digest itself, which still reaches the record.
        _auth().failed()
        _note_auth(counters, now)
    # The readiness pass (M3.3, PyAutoBrain#671): every gate on the next
    # shift's queue becomes a ruling, queued for this shift's one Mind writer.
    readiness_pass(slot, counters, mind, now)
    # Everything the Mind writer reported so far is in this digest; what it
    # reports from here on reaches the human through the late sweep (#632).
    counters["ledger_reported"] = len(_mind_writer.report(slot))
    _write_counters(slot, counters)
    digest = _digest.build(_brief.effective(brief, counters), slot, counters, health=health,
                           issue=issue, mind=mind)
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
                "value": (f"closed early at {_iso(closed_at)}" if closed_at
                          else "closed at review-at") + " — the digest is below"
                         + (f" — status: {status_url(slot)}" if status_url(slot) else "")})
        try:
            result["ledger"] = _mind_writer.commit_ledger(
                slot, mind, f"shift {slot.name}: digest",
                own_tasks=counters["redispatched"])
        except _mind_writer.MindWriteError as e:
            result["ledger"] = {"committed": None, "error": str(e)}

    if top.get("packet", {}).get("value", "").lower() == "yes":
        result["packet"] = str(_write_packet(slot, digest))

    posted = post_once(slot / DIGEST_MARKER, issue, slot / DIGEST_FILE, poster, now)
    if posted is None:
        result["post"] = {"posted": False, "error": "already posted this shift"}
        return result
    result["post"] = {k: posted[k] for k in ("posted", "url", "error") if k in posted}
    closing = _close_status(brief_path, slot, issue, now, agents, github, mind=mind)
    if closing:
        result["status"] = closing
    return result


def readiness_pass(slot: Path, counters: dict, mind: Path, now: _dt.datetime) -> None:
    """Run `batch ready` at shift end (M3.3, PyAutoBrain#671): offline (the
    premise check never fetches, no gh), against the watcher's Mind, each new
    ruling queued as a `question-add` op in this shift's own ledger and noted
    in `counters["rulings"]`. A shadow shift runs it too: its digest is
    written through the same writer. A failure never breaks the close: its
    reason is recorded and the digest says so."""
    try:
        import _ready  # noqa: E402 — inside the try: an import failure is a failed pass
        res = _ready.run(mind, fetch=False, shift=Path(slot).name, now=now)
        _ready.queue(res, slot, counters)
    except Exception as e:  # noqa: BLE001 — the digest must still be written
        r = counters.setdefault("rulings", {})
        r.setdefault("new", [])
        r["error"] = f"{type(e).__name__}: {e}"[:200]


def _close_status(brief_path: Path, slot: Path, issue: str, now: _dt.datetime,
                  agents, github=None, *, mind=None) -> dict | None:
    """One last edit of the status comment at `review-at:`, saying the shift
    is closed (#622); never retried — the digest is the record from here."""
    rec = _read_json(slot / STATUS_MARKER)
    if not rec or rec.get("state") != "posted":
        return None
    import _watch  # noqa: E402
    snap = _watch.snapshot(brief_path, slot, now, agents=agents,
                           health=lambda u: "see the digest", mind=mind, issue=issue)
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

#: No close-out starts this close to `review-at:` (PyAutoBrain#632, F1): one
#: that ran past it merged outside the digest. The PR waits for `/prm`.
CLOSEOUT_CUTOFF_S = 1200
#: No close-out starts once the shift's spend reaches this multiple of its
#: `token-budget:` (AUTONOMY.md, ruling 2026-11-14, #632 F5). Below it a
#: close-out may pass the budget: it counts against it and the digest shows it.
CLOSEOUT_BUDGET_FACTOR = 1.5


def ledger_unreported(slot: Path) -> list[dict]:
    """What the Mind writer reported (set aside, conflict, held) after the
    digest was built — the late sweep's to tell the human (#632 review)."""
    if not (slot / COUNTERS_FILE).exists():
        return []
    done = int(read_counters(slot).get("ledger_reported") or 0)
    return [e for e in _mind_writer.report(slot)[done:] if e.get("kind") != "skipped"]


def closeouts_running(slot: Path) -> bool:
    """Whether a close-out session is still out — the late sweep's business."""
    return any(co.get("state") == "running"
               for co in read_counters(slot)["closeouts"].values()) \
        if (slot / COUNTERS_FILE).exists() else False


def _closeouts(slot: Path, brief: dict, counters: dict, spawner, now: _dt.datetime,
               agents: AgentsView | None, health, pr_state=None,
               tokens=transcript_usage, review_at: _dt.datetime | None = None,
               pr_files=None) -> dict:
    """Reap finished close-out sessions, then start one per newly open PR.

    The watcher's guards are the ones it can judge from its own reads (AUTONOMY
    "Unattended `glance` merges"): the recorded tier, CI by `gh pr checks` not
    red — running or green starts the close-out at PR-open (ruling S5,
    M3.7b), which waits in-turn for a green `ci-verdict`; none at all is
    refused after a grace (PyAutoHeart#343) — a free slot under the brief's
    `merge-cap:`, and never in a shadow shift. The label, Heart, the witness,
    the CI wait and the merge slot's take are the close-out session's — it is
    the independent session, and it refuses rather than merges when one fails.

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

    Two more refusals (#632): no close-out starts within `CLOSEOUT_CUTOFF_S`
    of `review-at:`, nor once the spend reaches `CLOSEOUT_BUDGET_FACTOR` × the
    `token-budget:`.
    """
    pr_state = pr_state or getattr(spawner, "pr_state", None)
    pr_files = pr_files or getattr(spawner, "pr_files", None)
    events = reap_closeouts(slot, counters, now, agents, pr_state, tokens)
    events.setdefault("started", [])
    # The cap every in-shift merge takes a slot against, worker or close-out
    # (ruling R3, #661). A shadow or paused shift publishes a pause: a
    # worker's take is refused and the PR waits for /prm.
    try:
        _merge_slots.publish(slot, _brief._nonneg_int(brief.get("merge-cap", {}).get("value", ""))
                             or 0, _brief.is_shadow(brief) or bool(counters.get("paused")))
        # Who holds which slot, for the live view and the digest's label of
        # each in-turn merge (slot or NO slot).
        counters["slot_holders"] = _merge_slots.holders(slot)
    except (_merge_slots.MergeSlotError, OSError) as e:
        events["slots_error"] = str(e)[:300]   # a take reads what is there, or cannot tell
    if _brief.is_shadow(brief) or counters.get("paused"):
        return events   # paused (#622): an open PR waits; it is not refused
    return _start_closeouts(slot, brief, counters, spawner, now, health, events,
                            review_at, pr_state=pr_state, pr_files=pr_files)


def queue_retire_op(counters: dict, task: str, pr: str, now: _dt.datetime,
                    by: str = "the unattended close-out") -> dict | None:
    """The ledger op that retires a merged task's live `queue.md` entry —
    what `lifecycle.py close` does and an unattended close-out skipped once
    (PyAutoBrain#634), as did an in-turn merge (#637). None when the pick
    recorded no prompt."""
    prompt = (counters.get("picks", {}).get(task) or {}).get("prompt") or ""
    if not prompt:
        return None
    return {"op": "queue-retire", "path": "queue.md", "prompt": Path(prompt).name,
            "shipped_as": f"{pr} (merged by {by}, {now.strftime('%Y-%m-%d')})"}


def question_retire_op(counters: dict, task: str, now: _dt.datetime,
                       by: str = "the unattended close-out") -> dict:
    """The ledger op that answers a merged task's Open and Deferred inbox
    questions as `(task completed)` (`lifecycle.questions_close_text`).
    Queued beside `queue_retire_op`, which has already checked the prompt."""
    prompt = (counters.get("picks", {}).get(task) or {}).get("prompt") or ""
    return {"op": "question-retire", "path": "questions.md", "prompt": Path(prompt).name,
            "day": now.strftime("%Y-%m-%d"), "by": by}


def reap_closeouts(slot: Path, counters: dict, now: _dt.datetime, agents, pr_state,
                   tokens=transcript_usage, *, late: bool = False) -> dict:
    """Reap every finished close-out session (the first half of `_closeouts`):
    a live tick, `finish_shift` at `review-at:` and the late sweep all call it,
    so a close-out that ends after `review-at:` still lands its merge count and
    stage-2 row (#632, F1). `late` marks the events as after `review-at:`."""
    events = {"merged": [], "refused": []}
    lease_dir = slot / "leases"
    agents = agents or AgentsView()
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
        result = (verdict or {}).get("result")
        if result in ORDER_STATES and not merged:
            # A branch-update session's word (M3.6j, #683): the branch now has
            # main in it (`updated`) or already had (`current`). Neither is a
            # merge nor a refusal: the slot stays held, and a later tick
            # starts the merge close-out once CI on the new head is not red (S5).
            co.update(state=result, updated=_iso(now))
            if result == "updated":
                co.update(head=str(verdict.get("head") or "")[:64],
                          updates=int(co.get("updates") or 0) + 1)
            co.pop("why", None)
            events.setdefault("updated", []).append(pr)
            if co.get("agent_id") in counters["usage"]:
                counters["usage"][co["agent_id"]]["final"] = True
            _write_counters(slot, counters)
            verdict_file.unlink(missing_ok=True)
            continue
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
            # What became of the task's worktree and local branch (#637, item
            # 10): the close-out removes them as /prm does, or says why not.
            co["cleanup"] = str((verdict or {}).get("cleanup") or "").strip()[:300] \
                or CLEANUP_UNREPORTED
            out = counters["outcomes"].setdefault(co["task"], {"prs": [pr], "merged": []})
            if pr not in out["merged"]:
                out["merged"].append(pr)
            tier = co.get("tier") or counters["picks"].get(co["task"], {}).get("tier", "?")
            if tier == "glance":
                # Only a `glance` close-out is a stage-2 row and an unattended
                # `glance` merge; a `notify` one (ruling R3, #661) is neither.
                counters["glance_auto_merges"] += 1
                _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, {
                    "op": "table-append", "path": STAGE2_LOG, "heading": STAGE2_HEADING,
                    # One row per PR and shift, even if a crash between this queue
                    # and the counters write below reaps the close-out twice (#632).
                    "unique": f"| {co['task']} ({pr}) | {slot.name} |",
                    "row": stage2_row(now, co["task"], pr, slot.name, co["gate"], co["model"],
                                      merged_by=(gh or {}).get("mergedBy") or "")})
            retire = queue_retire_op(counters, co["task"], pr, now)
            if retire:
                # The close-out queues this with its complete record; this is
                # the safety net when it did not (#634). A second retire of
                # the same entry finds none live and is silent.
                _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR, retire)
                # An unattended close-out never runs `lifecycle.py close`, so
                # the task's Open questions (a `blocked` one whose late `.done`
                # merged) are answered here, or `check` would drift (#645).
                _mind_writer.queue_op(slot / _mind_writer.LEDGER_DIR,
                                      question_retire_op(counters, co["task"], now))
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
        if co["state"] == "refused":
            # A refused close-out frees its PR's merge slot (R3, #661) whoever
            # holds it for this task: the watcher (taken before a branch
            # update) or the close-out session itself (its own `merge-slot
            # take` just before the merge, M3.7b decision A). A merge made
            # outside the close-out is not the shift's. A merged one keeps it.
            for by, of_task in ((_merge_slots.WATCHER, None),
                                (_merge_slots.SESSION, co["task"])):
                try:
                    _merge_slots.release(slot, pr, by, co.get("why") or "refused",
                                         task=of_task)
                except (_merge_slots.MergeSlotError, OSError):
                    pass   # the slot stays held: fails toward fewer merges
        if late:
            co["late"] = _iso(now)
        if co.get("agent_id") in counters["usage"]:
            counters["usage"][co["agent_id"]]["final"] = True   # its last read stands
        _write_counters(slot, counters)
        verdict_file.unlink(missing_ok=True)
    return events


#: How long an `updated` PR (its branch just merged `main` in) may read
#: NO-CHECKS before that is its CI verdict: room for CI to register on the new
#: head (M3.6j, PyAutoBrain#683).
UPDATE_CHECKS_GRACE_S = 600
#: Branch updates one PR may have in a shift; the next one it would need
#: refuses it, `main kept moving → your /prm` (M3.6j).
UPDATE_LIMIT = 2
#: Close-out states the watcher looks at again on later ticks (M3.6j): the
#: branch was brought up to date with `main` (or already was), its slot is
#: held, and its merge close-out has not started yet.
ORDER_STATES = ("updated", "current")


def _iso_or_none(text: str) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def _known_prs(counters: dict) -> dict[str, str]:
    """{canonical PR key: URL} for every PR this shift knows (ruling f): its
    outcomes' PRs, carried ones included, and a carried outcome's `behind`."""
    out: dict[str, str] = {}
    for o in (counters.get("outcomes") or {}).values():
        if not isinstance(o, dict):
            continue
        for u in [*(o.get("prs") or []), *(o.get("behind") or [])]:
            k = _merge_slots.pr_key(u)
            if k:
                out.setdefault(k, u)
    return out


def _earlier_prs(counters: dict, pr: str) -> list[str]:
    """This shift's known PRs that merge before `pr`, in PR order: the same
    GitHub repo, a lower number, and only on a library repo (ruling f)."""
    key = _merge_slots.pr_key(pr)
    if not key or not _library_key(pr):
        return []
    repo, n = key.rsplit("/pull/", 1)
    return sorted((u for k, u in _known_prs(counters).items()
                   if k.rsplit("/pull/", 1)[0] == repo and _pr_number(k) < int(n)),
                  key=_pr_number)


def _recorded_merged(counters: dict) -> set[str]:
    """Canonical keys of the PRs this shift recorded merged."""
    urls = [u for o in (counters.get("outcomes") or {}).values() if isinstance(o, dict)
            for u in o.get("merged") or []]
    urls += [pr for pr, co in (counters.get("closeouts") or {}).items()
             if co.get("state") == "merged"]
    return {k for k in map(_merge_slots.pr_key, urls) if k}


def _merge_blockers(counters: dict, pr: str, pr_state, cache: dict) -> list[str]:
    """The earlier PRs (`_earlier_prs`) `pr` must wait behind (M3.6j,
    PyAutoBrain#683): every one not recorded merged and not MERGED or CLOSED
    on GitHub, whatever this shift made of it — refused, dropped, red
    (ruling c). One GitHub read per PR per tick (`cache`, ruling b); a PR
    GitHub cannot say about blocks."""
    merged = _recorded_merged(counters)
    out = []
    for u in _earlier_prs(counters, pr):
        if _merge_slots.pr_key(u) in merged:
            continue
        gh = _gh_once(pr_state, cache, u)
        if (gh or {}).get("state") in ("MERGED", "CLOSED"):
            continue
        out.append(u)
    return out


def in_turn_merge_blockers(slot: Path, pr: str, pr_state=None) -> list[str]:
    """The earlier PRs of this shift a worker's in-turn merge of `pr` would
    jump (M3.6j review F1): the same rule as the close-out's wait
    (`_merge_blockers`), read from the slot's `counters.json`. `merge-slot
    take` refuses while any is open, so the PR ends at PR-open and the
    watcher's close-out merges it in order. A missing counters file (no shift
    state yet) blocks nothing; an unreadable one raises `OSError`/`ValueError`."""
    path = Path(slot) / COUNTERS_FILE
    if not path.exists():
        return []
    counters = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(counters, dict):
        raise ValueError(f"{path} is not a JSON object")
    counters.setdefault("outcomes", {})
    counters.setdefault("closeouts", {})
    return _merge_blockers(counters, pr, pr_state or gh_pr_state, {})


def _gh_once(pr_state, cache: dict, url: str) -> dict | None:
    """`pr_state(url)`, read at most once a tick; None when it cannot say."""
    if url not in cache:
        try:
            cache[url] = pr_state(url) if pr_state else None
        except Exception:   # an unreadable PR blocks, as an unknown one does
            cache[url] = None
    return cache[url]


def _merged_after_start(counters: dict, task: str, pr: str, pr_state, cache: dict,
                        carried: bool) -> list[str]:
    """The earlier PRs that merged after `task`'s first worker started (M3.6j):
    its branch was cut from a `main` without them, so it is updated before it
    merges. A carried PR's every merged earlier PR counts; so does one whose
    merge time cannot be read."""
    first = None if carried else min(
        (t for t in (_iso_or_none(w.get("spawned") or "") for w in counters.get("workers") or []
                     if w.get("task") == task) if t), default=None)
    merged = _recorded_merged(counters)
    out = []
    for u in _earlier_prs(counters, pr):
        co = (counters.get("closeouts") or {}).get(u) or {}
        at = (co.get("github") or {}).get("mergedAt") if co.get("state") == "merged" else ""
        if not at:
            gh = _gh_once(pr_state, cache, u)
            if (gh or {}).get("state") != "MERGED" and _merge_slots.pr_key(u) not in merged:
                continue   # closed unmerged: nothing of it is on main
            at = (gh or {}).get("mergedAt") or ""
        when = _iso_or_none(at) if at else None
        if first is None or when is None or when > first:
            out.append(u)
    return out


def _pr_files_once(counters: dict, pr_files, url: str) -> list[str] | None:
    """A PR's changed files, read at most once per PR per shift and kept in
    `counters["pr_files"]` (S6, M3.7b; AUTONOMY.md "The watcher's network
    surface", amendment 2026-11-19). A read that fails, raises or may be
    truncated is kept as None — unreadable, an overlap — and never read
    again. None, uncached, when there is no reader (a test spawner): that
    fails toward the branch update, as before S6."""
    cache = counters.setdefault("pr_files", {})
    if url in cache:
        return cache[url]
    if pr_files is None:
        return None
    try:
        files = pr_files(url)
    except Exception:   # unreadable: update, never assume disjoint
        files = None
    cache[url] = list(files) if isinstance(files, list) else None
    return cache[url]


#: The label a worker puts on a PR whose decision the human must take (S7).
DECISION_TAKEN = "decision-taken"
#: Why a `decision-taken` PR is refused at PR-open (S7, M3.7c, #690).
DECISION_TAKEN_WHY = "decision-taken — the human's /prm"
#: Label reads one PR may fail in a shift before it goes to the human's /prm
#: (review round 1, M3.7c): never read without bound, never assumed clean.
LABEL_READS = 3
LABELS_UNREADABLE_WHY = f"labels unreadable after {LABEL_READS} reads → your /prm"


def _pr_labels_once(counters: dict, pr_state, cache: dict, url: str) -> list[str] | None:
    """A PR's label names, read once per PR per shift and kept in
    `counters["pr_labels"]` (S7, M3.7c; AUTONOMY.md "The watcher's network
    surface", amendment 2026-11-19): the `labels` field of the `gh pr view`
    the tick already makes (`_gh_once`). None when GitHub cannot say: not
    kept, asked again next tick (each miss counted in
    `counters["pr_label_misses"]`), never assumed clean. No reader at all (a
    test spawner) reads as no labels, uncached: the close-out's own label
    check stays the second layer."""
    kept = counters.setdefault("pr_labels", {})
    if url in kept:
        return kept[url]
    if pr_state is None:
        return []
    gh = _gh_once(pr_state, cache, url)
    if not gh:
        misses = counters.setdefault("pr_label_misses", {})
        misses[url] = int(misses.get(url) or 0) + 1
        return None
    labels = gh.get("labels")
    kept[url] = [str(x) for x in labels] if isinstance(labels, list) else []
    return kept[url]


def _overlap(counters: dict, pr: str, merged_ahead: list[str], pr_state, pr_files,
             cache: dict) -> tuple[list[str], list[str]]:
    """(need, disjoint): which PRs merged ahead of `pr` its branch must be
    updated for (ruling S6, M3.7b). Every one when GitHub reports `pr`
    CONFLICTING or `pr`'s own files cannot be read; otherwise each one whose
    changed files intersect `pr`'s, or cannot be read. The rest are disjoint."""
    if not merged_ahead:
        return [], []
    if (_gh_once(pr_state, cache, pr) or {}).get("mergeable") == "CONFLICTING":
        return list(merged_ahead), []
    mine = _pr_files_once(counters, pr_files, pr)
    if mine is None:
        return list(merged_ahead), []
    need, disjoint = [], []
    for u in merged_ahead:
        theirs = _pr_files_once(counters, pr_files, u)
        (need if theirs is None or set(theirs) & set(mine) else disjoint).append(u)
    return need, disjoint


def _start_closeouts(slot: Path, brief: dict, counters: dict, spawner, now: _dt.datetime,
                     health, events: dict, review_at: _dt.datetime | None,
                     pr_state=None, pr_files=None) -> dict:
    """Start one close-out per newly open PR, under the watcher's guards.

    Ruling S5 (M3.7b, PyAutoBrain#688): a PR whose CI reads RUNNING or
    HEALTHY starts its close-out at once; the session runs the witness and
    reads the diff while CI runs, then waits in-turn (`ci-verdict --until`,
    at most CLOSEOUT_CI_WAIT_S and never past `review-at:`) and merges only on
    GREEN. FAILED or UNKNOWN refuses with no session; NO-CHECKS waits
    UPDATE_CHECKS_GRACE_S from when the watcher first saw the PR, then refuses.
    Decision A: the watcher takes no merge slot for a merge close-out; it
    refuses one when the cap has no room (`_merge_slots.room`, counting the
    close-outs already running without a slot). The session takes its slot
    itself, immediately before the merge.

    Merge order (M3.6j, PyAutoBrain#683): a library PR whose earlier PR of
    this shift on the same library is still open waits — no close-out, no
    merge slot, no refusal — in `counters["merge_waits"]`, rebuilt each tick;
    a workspace PR waits while its own task's library PR waits or is being
    closed out. Once nothing is ahead of it, a PR whose branch was cut before
    an earlier PR merged gets a branch-update session first (`gh pr
    update-branch`, ruling a) under a merge slot the watcher takes — only when
    their changed files overlap, a file list cannot be read, or GitHub reports
    this PR CONFLICTING (ruling S6). Its merge close-out starts on a later
    tick, once GitHub shows the update's head and CI there is not red."""
    lease_dir = slot / "leases"
    health = health or _digest.pr_health
    budget = _brief._nonneg_int(brief.get("token-budget", {}).get("value", ""))
    cache: dict = {}   # GitHub's word on a PR, read once this tick (ruling b)
    before_waits = counters.get("merge_waits") or {}
    waits: dict = {}
    counters["merge_waits"] = waits
    seen = counters.setdefault("pr_seen", {})   # when the watcher first saw each PR

    def refuse(pr: str, task: str, why: str, held: bool = False) -> None:
        prev = counters["closeouts"].get(pr) or {}
        counters["closeouts"][pr] = {**{k: prev[k] for k in ("after", "updates") if k in prev},
                                     "task": task, "state": "refused", "why": why}
        events["refused"].append(pr)
        if held:   # an updated PR's slot, taken before its update session
            try:
                _merge_slots.release(slot, pr, _merge_slots.WATCHER, why)
            except (_merge_slots.MergeSlotError, OSError):
                pass

    # Library PRs first, so a workspace PR sees its task's library PR's wait.
    pairs = sorted(((task, pr) for task, out in counters["outcomes"].items()
                    for pr in out["prs"]), key=lambda tp: not _library_key(tp[1]))
    for task, pr in pairs:
        out = counters["outcomes"][task]
        if "/pull/" not in pr or pr in out["merged"]:
            continue
        co = counters["closeouts"].get(pr)
        again = co is not None
        if again and co.get("state") not in ORDER_STATES:
            continue
        seen.setdefault(pr, _iso(now))
        tier = counters["picks"].get(task, {}).get("tier", "?")
        if task in counters["dropped"]:
            refuse(pr, task, "dropped by /drop — the human's /prm", held=again)
            continue
        if tier not in ("glance", "notify"):
            # Ruling R3 (2026-11-17, #661): a `notify` PR a worker left
            # open is closed out on the same terms as a `glance` one.
            refuse(pr, task, f"tier {tier} — never merged unattended → your /prm", held=again)
            continue
        if out.get("carried_from"):
            # A carried PR (M3.6c) may have been merged or closed by the
            # human since its shift: only an OPEN one is closed out, so a
            # human's merge is never counted as an unattended one.
            gh = _gh_once(pr_state, cache, pr)
            if not gh:
                continue      # GitHub unreadable: asked again next tick, never assumed
            state = gh.get("state")
            if state != "OPEN":
                refuse(pr, task, f"carried over from {out['carried_from']}, but GitHub reads "
                                 f"it {state or '?'} — not closed out", held=again)
                continue
        # S7 (M3.7c, #690): a `decision-taken` PR is the human's /prm, from
        # its label alone: no close-out session, no merge slot, no CI read.
        # It stays among the shift's known PRs, so a later PR on its library
        # still waits behind it (ruling c). After the carried check (review
        # round 1): a carried PR the human merged or closed is reported by
        # its GitHub state. Unreadable: asked again next tick, at most
        # LABEL_READS times, then the human's /prm.
        labels = _pr_labels_once(counters, pr_state, cache, pr)
        if labels is None:
            if int((counters.get("pr_label_misses") or {}).get(pr) or 0) >= LABEL_READS:
                refuse(pr, task, LABELS_UNREADABLE_WHY, held=again)
            continue
        if DECISION_TAKEN in labels:
            refuse(pr, task, DECISION_TAKEN_WHY, held=again)
            continue
        # Merge order (M3.6j): an earlier library PR of this shift still open
        # holds this one back. Waiting is not a refusal and takes no slot. An
        # earlier PR whose close-out is running (waiting in-turn on its CI,
        # S5) is still open, so this one gets no session until it merges.
        behind = _merge_blockers(counters, pr, pr_state, cache)
        if not behind and not _library_key(pr):
            behind = [u for u in out["prs"] if u != pr and _library_key(u)
                      and u not in out["merged"]
                      and (u in waits or (counters["closeouts"].get(u) or {}).get("state")
                           in ("running", *ORDER_STATES))]
        if behind:
            prev = before_waits.get(pr) or {}
            waits[pr] = {"task": task, "behind": behind,
                         "since": prev.get("since") or _iso(now)}
            if prev.get("behind") != behind:
                events.setdefault("waiting", []).append(pr)
            continue
        if again and co.get("state") == "updated" and co.get("head"):
            # CI is judged on the head the update made (review F5): until
            # GitHub shows that head, a check read may be an older head's.
            head = (_gh_once(pr_state, cache, pr) or {}).get("head") or ""
            if not head:
                continue      # GitHub cannot say yet: asked again next tick
            if head != co["head"]:
                refuse(pr, task, f"head moved after the branch update ({co['head'][:12]} → "
                                 f"{head[:12]}) → your /prm", held=True)
                continue
        verdict = health(pr)
        if verdict == "NO-CHECKS":
            # CI may not have registered yet — on a new PR or on the head a
            # branch update made: wait out the grace, then it is the verdict.
            since = _iso_or_none((co.get("updated") if again and co.get("state") == "updated"
                                  else seen.get(pr)) or "")
            if since is None or (now - since).total_seconds() < UPDATE_CHECKS_GRACE_S:
                continue
        if verdict not in ("RUNNING", "HEALTHY"):
            refuse(pr, task, f"CI {verdict} on the updated head → your /prm" if again
                   else f"CI {verdict} — never merged unattended", held=again)
            continue
        if review_at is not None \
                and (review_at - now).total_seconds() < CLOSEOUT_CUTOFF_S:
            if again:
                # An updated PR at review-at is not refused: it keeps its
                # state, the digest reports it, and the next shift carries it.
                continue
            # A close-out runs ~10-30 min; one still out at review-at
            # merged outside the digest (#632, F1). Final, like the others.
            refuse(pr, task, f"open within {CLOSEOUT_CUTOFF_S // 60} min of review-at — "
                             "no close-out starts this late")
            continue
        if budget is not None and counters["usage_unavailable"]:
            # As the spawn gate: a spend that cannot be read could be
            # anything, so nothing starts this tick; asked again next tick.
            events.setdefault("held", []).append(
                {"pr": pr, "why": "token usage unavailable ("
                 + ", ".join(counters["usage_unavailable"]) + ")"})
            continue
        spent = _committed_tokens(counters)
        # `is not None`: a `/cap tokens 0` (#644) means zero, not "no budget".
        if budget is not None and spent >= CLOSEOUT_BUDGET_FACTOR * budget:
            # The human's ruling 2026-11-14 (#632, F5): a close-out may pass
            # the budget, but none starts once spend reaches 1.5x it —
            # spend as the spawn gate counts it, reservations included.
            refuse(pr, task, f"token spend {spent} (committed) reached "
                             f"{CLOSEOUT_BUDGET_FACTOR}× token-budget {budget}", held=again)
            continue
        # Branch update (M3.6j): an earlier PR merged after this branch was
        # cut, and this PR's branch does not have it yet — needed only when
        # their changed files overlap or GitHub reports a conflict (S6).
        after = list((co or {}).get("after") or [])
        ahead = [u for u in _merged_after_start(counters, task, pr, pr_state, cache,
                                                bool(out.get("carried_from")))
                 if u not in after]
        need, disjoint = _overlap(counters, pr, ahead, pr_state, pr_files, cache)
        updates = int((co or {}).get("updates") or 0)
        if need and updates >= UPDATE_LIMIT:
            refuse(pr, task, f"main kept moving ({updates} branch updates this shift) "
                             "→ your /prm", held=again)
            continue
        if need:
            # One merge-slot count for the shift (R3, #661). The watcher
            # takes it before a branch-update session, last, so no other
            # refusal holds a slot. Idempotent: an updated PR holds its slot.
            try:
                taken, why = _merge_slots.take(slot, pr, _merge_slots.WATCHER, task)
            except (_merge_slots.MergeSlotError, OSError) as e:
                taken, why = False, f"merge slot cannot tell ({str(e)[:200]}) — left for your /prm"
        else:
            # Decision A (M3.7b): the merge close-out takes its own slot just
            # before the merge. The watcher only reads that one would be free,
            # counting the close-outs already running without one.
            pending = sum(1 for u, c in counters["closeouts"].items()
                          if c.get("state") == "running" and c.get("kind") != "update"
                          and _merge_slots.pr_key(u) not in counters.get("slot_holders", {}))
            try:
                taken, why = _merge_slots.room(slot, pr, task, pending)
            except (_merge_slots.MergeSlotError, OSError) as e:
                taken, why = False, f"merge slot cannot tell ({str(e)[:200]}) — left for your /prm"
        if not taken:
            # Final for this shift, like every refusal: the PR waits for a
            # human `/prm`, and the digest says why.
            refuse(pr, task, why, held=again)
            continue
        prompt = counters["picks"].get(task, {}).get("prompt", "")
        new = {"task": task, "state": "running", "started": _iso(now), "tier": tier}
        if need:
            kw = {"update_after": need}
            new.update(kind="update", after=after + need, updates=updates)
        else:
            # Only a PR with earlier PRs of the shift on its library is
            # told about them, so every other close-out starts as before.
            before = _earlier_prs(counters, pr)
            until = now + _dt.timedelta(seconds=CLOSEOUT_CI_WAIT_S)
            if review_at is not None:
                until = min(until, review_at
                            - _dt.timedelta(seconds=CLOSEOUT_MERGE_MARGIN_S))
            kw = {k: v for k, v in (("after", after), ("before", before),
                                    ("disjoint", disjoint)) if v}
            kw["ci_until"] = _iso(until)
            new.update({k: v for k, v in (("after", after), ("updates", updates),
                                          ("disjoint", disjoint)) if v})
        try:
            new.update(spawner.spawn_closeout(task, pr, prompt, lease_dir, **kw))
        except Exception as e:
            refuse(pr, task, f"the close-out could not start: {str(e)[:300]}")
            try:
                _merge_slots.release(slot, pr, _merge_slots.WATCHER, "the close-out could not start")
            except (_merge_slots.MergeSlotError, OSError):
                pass
            _write_counters(slot, counters)
            continue
        counters["closeouts"][pr] = new
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
    why = _brief.pick_reason(member, brief)
    if member.get("resume"):
        # An answer is not a new priority (Decision H11 a): the pick names
        # the answer, then the standing it re-entered at.
        why = (f"resumed after {', '.join(member['resume'].get('ids') or ['?'])} was "
               f"answered · {why}")
    rec = {"prompt": member["path"], "why": why,
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


# --- which brief: the one open on Mind origin/main (M3.6a, PyAutoBrain#659) -------

#: The env file's brief: now only an override, honoured inside its own window.
SHIFT_BRIEF_ENV = "PYAUTO_SHIFT_BRIEF"
ORIGIN_REF = "origin/main"


def shift_briefs(mind: Path, ref: str = ORIGIN_REF) -> list[dict] | None:
    """Every shift brief on Mind's local `ref`: {name, rel, dispatched,
    review_at} for each top-level `batches/*.md` with a `brief:` block and
    both times. None when `mind` is not its own git checkout or has no such
    ref. Local `git ls-tree` / `git show` only — never a fetch: only a pushed
    brief opens, so pushing the brief stays the launch."""
    def git(*args):
        try:
            res = subprocess.run(["git", "-C", str(mind), *args], capture_output=True,
                                 text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return res.stdout if res.returncode == 0 else None
    top = git("rev-parse", "--show-toplevel")
    if top is None or Path(top.strip()).resolve() != Path(mind).resolve():
        return None
    listing = git("ls-tree", "--name-only", ref, "batches/")
    if listing is None:
        return None
    out = []
    for rel in listing.splitlines():
        name = Path(rel).name
        if not name.endswith(".md") or name == "AGENTS.md":
            continue
        text = git("show", f"{ref}:{rel}")
        try:
            rec = _brief.parse(text or "")
        except _brief.BriefError:
            continue
        top_keys = rec["top"]
        start = _brief._iso((top_keys.get("dispatched") or {}).get("value", ""))
        end = _brief._iso((top_keys.get("review-at") or {}).get("value", ""))
        if rec["brief"] is None or start is None or end is None:
            continue
        out.append({"name": Path(rel).stem, "rel": rel, "dispatched": start, "review_at": end})
    return sorted(out, key=lambda b: b["name"])


#: How long after `review-at:` + the late window a shift whose digest is still
#: owed is caught up (the laptop was off through the late window). Bounded,
#: so an old slot is never digested days later.
CATCH_UP_S = 24 * 3600
#: Claimed in a slot the first time a tick finds it past `CATCH_UP_S` with
#: something still owed, so the "abandoned" line is printed once.
ABANDONED_MARKER = "abandoned.noted"


def _owes(slot: Path) -> str:
    """What `late_owed` found, in words, with the leases still held."""
    slot = Path(slot)
    bits = []
    if not (slot / DIGEST_MARKER).exists():
        bits.append("digest not posted")
    elif post_due(slot / DIGEST_MARKER):
        bits.append("digest post retry due")
    if post_due(slot / CORRECTION_MARKER):
        bits.append("correction post retry due")
    ops = len(_mind_writer.pending_ops(slot))
    if ops:
        bits.append(f"{ops} queued Mind op{'s' if ops != 1 else ''}")
    n = len(list((slot / "leases").glob("*.json")))
    bits.append(f"{n} lease{'s' if n != 1 else ''}")
    return "; ".join(bits)


def _override_state(path: Path, now: _dt.datetime) -> str:
    """Where an override brief (`--brief`, `$PYAUTO_SHIFT_BRIEF`) is in its own
    window: "open" (`dispatched:` <= now < `review-at:`), "late" (to
    `review-at:` + the late window), else ""."""
    try:
        top = _brief.parse(Path(path).read_text(encoding="utf-8"))["top"]
    except (OSError, _brief.BriefError):
        return ""
    start = _brief._iso((top.get("dispatched") or {}).get("value", ""))
    end = _brief._iso((top.get("review-at") or {}).get("value", ""))
    if start is None or end is None or now < start:
        return ""
    if now < end:
        return "open"
    return "late" if now < end + _dt.timedelta(seconds=_brief.LATE_WINDOW_S) else ""


def find_briefs(mind: Path, now: _dt.datetime, *, override: Path | None = None,
                ref: str = ORIGIN_REF, home: Path | None = None) -> tuple[list[Path], str]:
    """(the brief files to tick, why something is not ticked).

    The one open brief on `ref` (`dispatched:` <= now < `review-at:`), then
    every late one (`review-at:` <= now < + 45 min, for its digest and late
    sweep), then any past that window whose slot still has something owed
    (`late_owed`: the laptop was off through the late window), up to
    `CATCH_UP_S`. Two open briefs tick neither: which grant holds is the
    human's word, not the watcher's guess. A brief is ticked from Mind's
    working tree; one pushed but missing there is named, not ticked.

    An override takes the open brief's place only while it is open itself;
    in its late window it is one more late brief, ticked beside the open one
    (M3.6a review: a stale env file must never displace the next shift)."""
    state = _override_state(override, now) if override is not None else ""
    briefs = shift_briefs(mind, ref)
    if briefs is None:
        if state:
            return [Path(override)], ""
        return [], f"no {ref} in {mind} to find the shift brief on"
    home = home or orchestrator_home()
    late_s = _dt.timedelta(seconds=_brief.LATE_WINDOW_S)
    catch_s = _dt.timedelta(seconds=CATCH_UP_S)
    own = Path(override).stem if state else None
    opened = [b for b in briefs if b["dispatched"] <= now < b["review_at"]]
    late = [b for b in briefs if b["review_at"] <= now < b["review_at"] + late_s]
    owed = [b for b in briefs if b["review_at"] + late_s <= now < b["review_at"] + late_s + catch_s
            and (Path(home) / b["name"] / "leases").is_dir()
            and late_owed(Path(home) / b["name"])]
    # Past the catch-up with something still owed: never ticked again, so the
    # human is told once which slot was left and what it owes (M3.6a review).
    abandoned = []
    for b in briefs:
        slot = Path(home) / b["name"]
        if now >= b["review_at"] + late_s + catch_s and (slot / "leases").is_dir() \
                and late_owed(slot) and _create_exclusive(slot / ABANDONED_MARKER,
                                                          {"at": _iso(now)}):
            abandoned.append(f"abandoned: {b['name']} past catch-up ({_owes(slot)}) — "
                             f"run `batch digest --record {b['rel']}` and close it by hand")
    reasons: list[str] = []
    first: list[Path] = []
    if state == "open":
        first.append(Path(override))
        picks = late + owed
    else:
        if len(opened) > 1:
            count = "two" if len(opened) == 2 else str(len(opened))
            reasons.append(f"{count} open briefs on {ref} ("
                           + ", ".join(b["name"] for b in opened) + ")")
        picks = (opened if len(opened) == 1 else []) + late + owed
    paths: list[Path] = []
    for b in picks:
        if b["name"] == own:
            continue
        path = Path(mind) / b["rel"]
        if path.is_file():
            paths.append(path)
        else:
            reasons.append(f"{b['name']} is pushed, but the Mind checkout is behind "
                           f"(no {b['rel']} in {mind})")
    if state == "late":
        # After the open brief (if any), before the other late ones.
        at = 1 if opened and len(opened) == 1 and paths and paths[0].stem == opened[0]["name"] \
            else 0
        paths.insert(at, Path(override))
    paths = first + paths
    if not paths and not reasons:
        reasons.append(f"no open brief on {ref}")
    return paths, "; ".join(reasons + abandoned)


def watch(mind: Path, *, home: Path | None = None, now: _dt.datetime | None = None,
          override: Path | None = None, **kw) -> dict:
    """One timer firing (M3.6a, PyAutoBrain#659): find the brief(s) on Mind
    `origin/main` and tick each. {"action": "idle", "reason"} when there is
    none; else {"action": "watch", "ticked": {slot: tick result}} plus a
    `reason` for what was left out."""
    now = now or _now()
    paths, why = find_briefs(mind, now, override=override, home=home)
    out: dict = {"action": "watch", "ticked": {}}
    if override is not None and Path(override) not in paths:
        out["override"] = (f"{override} not honoured: outside its window "
                           "(dispatched → review-at + 45 min)")
    if not paths:
        return {"action": "idle", "reason": why, **({"override": out["override"]}
                                                    if "override" in out else {})}
    for path in paths:
        try:
            out["ticked"][path.stem] = tick(path, mind, home=home, now=now, **kw)
        except OrchestratorError as e:
            out["ticked"][path.stem] = {"action": "error", "reason": str(e)}
    if why:
        out["reason"] = why
    return out


def _result_line(res: dict) -> str:
    return f"{res['action']}: " + (res.get("reason") or
                                   f"spawned {len(res.get('spawned', []))}, "
                                   f"refused {len(res.get('refused', []))}, "
                                   f"live {len(res.get('live', []))}")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="orchestrator_watch",
        description="One shift-watcher tick (run by a systemd user timer the "
                    "human installs). Fake workers only until phase 3b.")
    ap.add_argument("--brief", type=Path, default=None,
                    help="override: tick this brief record instead of the one open "
                         "on Mind origin/main — honoured only inside its own window "
                         "(dispatched → review-at + 45 min); default "
                         f"${SHIFT_BRIEF_ENV}, else none")
    ap.add_argument("--mind", required=True, type=Path)
    ap.add_argument("--home", type=Path, default=None,
                    help=f"state directory (default ${HOME_ENV}, else "
                         ".orchestrator under the worktree root)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    env_brief = os.environ.get(SHIFT_BRIEF_ENV, "").strip()
    override = a.brief or (Path(env_brief) if env_brief else None)
    res = watch(a.mind.resolve(), home=a.home, override=override)
    ticked = res.get("ticked") or {}
    if a.as_json:
        one = len(ticked) == 1 and not res.get("reason")
        print(json.dumps(next(iter(ticked.values())) if one else res, indent=2))
    else:
        for name, r in ticked.items():
            print((f"{name}: " if len(ticked) > 1 else "") + _result_line(r))
        if res.get("reason"):
            print(f"idle: {res['reason']}")
    errors = [r["reason"] for r in ticked.values() if r.get("action") == "error"]
    for e in errors:
        print(f"orchestrator_watch: {e}", file=sys.stderr)
    return 2 if errors else 0

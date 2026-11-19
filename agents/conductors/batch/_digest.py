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

import json
import re
import subprocess
import sys
from pathlib import Path

import _brief  # noqa: E402
import _merge_slots  # noqa: E402 — slot evidence for an in-turn merge (R3, #661)
import _questions  # noqa: E402 — the inbox line (M3.5, #645)

# The one CI judgement (PyAutoBrain#628) lives in bin/, beside its CLI.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "bin"))
import ci_verdict  # noqa: E402

DIGEST_HEADING = "## Digest"
#: The tail of a watcher plan reason for a draft held because Mind
#: origin/main could not be read (`_orchestrator.on_origin`).
FAIL_CLOSED = "fail closed"
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
#: A worker whose lease is still held when the digest is built (#634, N1): it
#: was dispatched and is not done; the late sweep reports how it ends.
STILL_OUT = "still running at review time — the late sweep will report it"
#: A PR the worker merged in-turn — after taking a merge slot against the
#: shift's `merge-cap:` (AUTONOMY.md ruling R3, 2026-11-17, PyAutoBrain#661).
IN_TURN_MERGED = "merged in-turn by the worker (merge slot)"
#: A PR the worker reported merged in-turn with no merge slot held for its
#: task: past the shift's `merge-cap:` count, and the evidence ruling R3's
#: revert condition reads.
IN_TURN_NO_SLOT = "merged in-turn with NO merge slot — R3 revert-condition evidence"
#: A killed worker whose re-dispatch never started (PyAutoBrain#637, item 2):
#: never "not started" — its first worker ran.
NOT_REDISPATCHED = "crashed — not re-dispatched"
NO_PACKETS_SHADOW = "- none — shadow shift: nothing was dispatched"
#: A shadow digest's counters, in one line: every one is 0 by construction.
SHADOW_COUNTERS = "- all counters 0 — shadow shift, nothing dispatched"
#: A pick line names its task in backticks after its title (`label`).
_SLUG_RE = re.compile(r"\(`([^`]+)`")
_ISSUE_RE = re.compile(r"^(https://github\.com/[^/]+/[^/]+)/issues/\d+")
#: An issue URL on a `.done` line, wherever it is hosted.
_ISSUE_URL_RE = re.compile(r"/issues/\d+")

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

#: The `.done` words that say why a worker ended on an issue (#632, F2). Only
#: an explicit `verdict:` (its deliverable) keeps the human un-mentioned; a
#: `question:`, a bare issue URL or any other marker is a push — the push
#: test fails toward the human, never toward silence (#632 review).
DONE_QUESTION, DONE_VERDICT = "question", "verdict"
_URL_RE = re.compile(r"https?://\S+")
_MARKER_RE = re.compile(r"^\s*([A-Za-z-]*)\s*:?\s*$")


def parse_done(text: str) -> dict:
    """A worker's `.done` file: one PR or issue URL per line, `merged <url>` for
    a PR it merged in-turn under its tier, `question: <url>` for an issue it
    parked on with a question, `verdict: <url>` for a verdict it posted,
    `obsolete <why>` when its premise check stopped it. Markers are read in
    any case, with or without the colon or the space after it. An issue URL
    goes in `issues`, never in `prs`: `prs` is what CI, a close-out and the
    merge count read (PyAutoBrain#610). `verdicts` holds only the URLs an
    explicit `verdict:` marked — every other issue URL is a push (#632)."""
    prs, merged, issues, obsolete = [], [], [], None
    questions, verdicts = [], []
    for line in text.splitlines():
        words = line.split()
        if not words:
            continue
        if words[0].lower().rstrip(":") == "obsolete":
            # The worker's premise check found the task obsolete on main and
            # it stopped (worker_template.md); the rest is its evidence.
            obsolete = line.strip()[len("obsolete"):].strip(" :—-")
            continue
        m = _URL_RE.search(line)
        if not m:
            continue
        url = m.group(0)
        marker = _MARKER_RE.match(line[:m.start()])
        word = marker.group(1).lower() if marker else ""
        if word == "merged":
            merged.append(url)
            prs.append(url)
            continue
        is_issue = bool(_ISSUE_URL_RE.search(url))
        (issues if is_issue else prs).append(url)
        if word == DONE_VERDICT:
            verdicts.append(url)
        elif is_issue:
            questions.append(url)   # `question:`, bare or unrecognised: a push
    out = {"prs": prs, "merged": merged, "issues": issues}
    if questions:
        out["questions"] = questions
    if verdicts:
        out["verdicts"] = verdicts
    if obsolete is not None:
        out["obsolete"] = obsolete
    return out


def urls_of(outcome: dict | None) -> list[str]:
    """Every URL a `.done` named: its PRs, then the issues it parked on."""
    outcome = outcome or {}
    return list(outcome.get("prs") or []) + list(outcome.get("issues") or [])


def pr_health(url: str, run=None) -> str:
    """One read-only `gh pr checks --json`, judged by `bin/ci_verdict.py`
    (PyAutoBrain#628) — the one CI judgement `/prm` and the close-out run too.

    The watcher's network surface is `gh pr checks` only (AUTONOMY.md "The
    watcher's network surface"), so this keeps that read and hands its rows to
    `ci_verdict.judge` with mergeability not read; the close-out session runs
    the full `pyauto-brain ci-verdict`, which reads it. The words map from the
    verdict: GREEN is HEALTHY (at least one completed check, every completed
    check green — PyAutoHeart#343); a failed, cancelled or timed-out check is
    FAILED (`gh pr checks`' exit code counts a cancelled check as skipped, so
    the exit code alone is not the verdict); a bucket the judge does not know
    is UNKNOWN (fail closed); a pending check is RUNNING; no checks, or only
    skipped ones, is NO-CHECKS, which the close-out refuses — that PR is the
    human's merge."""
    if "/pull/" not in url:
        return "PARKED-ON-ISSUE"
    run = run or subprocess.run
    try:
        res = run(["gh", "pr", "checks", url, "--json", "name,bucket,state"],
                  capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"
    if "no checks" in ((res.stderr or "") + (res.stdout or "")).lower():
        return health_word(ci_verdict.judge([], read_mergeable=False))
    try:
        checks = json.loads(res.stdout or "")
    except ValueError:
        checks = None
    if not isinstance(checks, list):
        return "UNKNOWN"   # gh could not say (auth, network): never a pass
    return health_word(ci_verdict.judge(ci_verdict.from_pr_checks(checks),
                                        read_mergeable=False))


def health_word(verdict: dict) -> str:
    """A `ci_verdict.judge` result in the watcher's words."""
    codes = {r["code"] for r in verdict["reasons"]}
    if codes & {"check-failed", "check-cancelled", "check-timed-out"}:
        return "FAILED"
    if "check-unrecognised" in codes:
        return "UNKNOWN"
    if verdict["verdict"] == ci_verdict.PENDING:
        return "RUNNING"
    if codes & {"no-checks", "skipped-only"}:
        return "NO-CHECKS"
    return "HEALTHY" if verdict["verdict"] == ci_verdict.GREEN else "UNKNOWN"


# --- build ---------------------------------------------------------------------

def task_state(task: str, counters: dict, health, *, live: bool = False,
               lease: dict | None = None, agents=None) -> tuple[str, bool]:
    """(what a task is doing, whether its tier follows) — the one wording the
    digest and `batch watch` share, so the live view and the digest never
    disagree. Only the live view passes `live=True` (with the task's `lease`
    and the `agents` view). The digest passes a lease only for a worker still
    out at `review-at:`, which reads `STILL_OUT`, never "not started"
    (PyAutoBrain#634, N1); the late sweep reports how it ends. A task the
    human dropped by `/drop` (PyAutoBrain#622) says so first."""
    state, tiered = _task_state(task, counters, health, live=live, lease=lease,
                                agents=agents)
    if task not in (counters.get("dropped") or {}):
        return state, tiered
    if live and lease is not None:
        return f"dropped, still running — {state}", tiered
    if state == "not started":
        return "dropped by /drop — not started", False
    return f"dropped by /drop — {state}", tiered


def _task_state(task: str, counters: dict, health, *, live: bool = False,
                lease: dict | None = None, agents=None) -> tuple[str, bool]:
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
        if lease is not None:
            return STILL_OUT, True
        if task in counters.get("pending_redispatch", []):
            if live:
                word = "killed by /kill" if task in (counters.get("killed") or {}) else "crashed"
                return f"{word} — awaiting re-dispatch", True
            return f"{NOT_REDISPATCHED}: {redispatch_why(task, counters)}", False
        skipped = gate_why(task, counters)
        return ("not started — skipped: " + skipped if skipped else "not started"), False
    urls = urls_of(out)
    if not urls and "obsolete" in out:
        return ("obsolete (premise check): "
                + (out["obsolete"] or "see its proof packet")), False
    if not urls:
        return "finished, no PR or issue named in its .done", False
    parts = []
    closeouts = counters.get("closeouts", {})
    for url in urls:
        co = closeouts.get(url, {})
        if url in out.get("verdicts", []):
            state = "verdict posted"
        elif url in out.get("issues", []):
            state = "PARKED-ON-ISSUE"
        elif url in out["merged"]:
            # Which path each merge took (R3, #661): a close-out, or the
            # worker in-turn after taking a merge slot.
            if co.get("state") == "merged":
                state = "merged unattended (close-out, " + co.get("model", "?") + ")"
            else:
                state = IN_TURN_MERGED if has_slot(counters, task, url) else IN_TURN_NO_SLOT
            if co.get("state") == "merged" and co.get("cleanup"):
                state += f" — worktree: {co['cleanup']}"
        elif url in (counters.get("merge_waits") or {}):
            state = wait_state(url, counters)          # merge order (M3.6j, #683)
        elif url in (counters.get("sweep_waits") or {}):
            state = sweep_wait_state(url, counters)    # unknown sweep (M3.7e, #694)
        elif co.get("state") == "refused":
            state = f"awaiting /prm — close-out refused: {co.get('why', '?')}"
        elif co.get("state") == "running":
            state = UPDATING if co.get("kind") == "update" else "close-out running"
        elif co.get("state") == "updated":
            state = (f"{UPDATED} after {', '.join(map(pr_ref, co.get('after') or []))}, "
                     f"CI on new head {health(url)}")
        elif co.get("state") == "current":
            state = f"{CURRENT}, CI {health(url)}"
        else:
            state = health(url)
        parts.append(f"{url} — {state}")
    return "; ".join(parts), True


#: A PR's states in the merge order (M3.6j, PyAutoBrain#683).
UPDATING = "close-out updating the branch from main"
UPDATED = "branch updated from main"
CURRENT = "branch already up to date with main"
MERGE_ORDER_HEADING = "### Merge order"
_PR_REF_RE = re.compile(r"^https://github\.com/[^/\s]+/([^/\s]+)/pull/(\d+)")


def pr_ref(url: str) -> str:
    """`repo#n` for a GitHub PR URL; the URL itself otherwise."""
    m = _PR_REF_RE.match(url or "")
    return f"{m.group(1)}#{m.group(2)}" if m else (url or "?")


def _order_word(url: str, counters: dict) -> str:
    """What an earlier PR in the merge order is doing, in a few words."""
    co = (counters.get("closeouts") or {}).get(url) or {}
    if url in (counters.get("merge_waits") or {}):
        return "itself waiting"
    if co.get("state") == "refused":
        return f"needs your /prm: {refusal_class(co.get('why') or '?')}"
    if co.get("state") == "running":
        return "close-out running"
    if co.get("state") in ("updated", "current"):
        return "branch updated, CI re-running"
    return "open"


def sweep_wait_state(url: str, counters: dict) -> str:
    """A PR held while the sweep's run list is unreadable (M3.7e, #694): since
    when the sweep is unknown, from the wait's `why`."""
    wait = (counters.get("sweep_waits") or {}).get(url) or {}
    since = str(wait.get("why") or "").rpartition(" since ")[2] or wait.get("since") or "?"
    return f"waiting: workspace sweep unknown since {since}"


def wait_state(url: str, counters: dict) -> str:
    """A PR waiting in merge order: behind which PRs, what they are doing, and
    which one to merge first (M3.6j, PyAutoBrain#683)."""
    behind = ((counters.get("merge_waits") or {}).get(url) or {}).get("behind") or []
    return ("waits behind " + ", ".join(f"{pr_ref(b)} ({_order_word(b, counters)})"
                                        for b in behind)
            + f" — merge {pr_ref(behind[0]) if behind else '?'} first")


def merge_order_lines(counters: dict) -> list[str]:
    """The `### Merge order` block (M3.6j, PyAutoBrain#683): for each library
    repo where a PR of this shift waits behind an earlier one, its open PRs
    in PR-number order, ▶ on the one that needs your /prm now; and how many
    branch updates conflicted with main. Empty when nothing waits."""
    waits = counters.get("merge_waits") or {}
    if not waits:
        return []
    merged = {u for o in (counters.get("outcomes") or {}).values() if isinstance(o, dict)
              for u in o.get("merged") or []}
    known = list(dict.fromkeys(
        u for o in (counters.get("outcomes") or {}).values() if isinstance(o, dict)
        for u in [*(o.get("prs") or []), *(o.get("behind") or [])]))

    def repo(u):
        key = _merge_slots.pr_key(u)
        return key.rsplit("/pull/", 1)[0] if key else ""

    def number(u):
        key = _merge_slots.pr_key(u)
        return int(key.rsplit("/", 1)[1]) if key else 0
    repos = list(dict.fromkeys(repo(w) for w, info in waits.items()
                               if any(repo(b) == repo(w) for b in info.get("behind") or [])))
    out = ["", MERGE_ORDER_HEADING]
    for r in repos:
        prs = sorted((u for u in known if repo(u) == r and u not in merged), key=number)
        out.append(f"- **{r.rsplit('/', 1)[-1]}**, merged in this order:")
        now = next((u for u in prs if u not in waits), None)
        for u in prs:
            word = wait_state(u, counters) if u in waits else _order_word(u, counters)
            out.append(f"  - {'▶ ' if u == now else ''}{u} — {word}")
    conflicts = [u for u, co in (counters.get("closeouts") or {}).items()
                 if str(co.get("why") or "").startswith("conflicts with main")]
    if conflicts:
        out.append(f"- {len(conflicts)} branch update(s) conflicted with main — your /prm: "
                   + ", ".join(map(pr_ref, conflicts)))
    return out


#: The heading of the PRs that waited behind a /prm-bound PR (S7, M3.7c).
WAITED_HEADING = "### Waited behind your /prm"


def _hhmm(iso: str) -> str:
    """`2026-11-04T09:01Z` from an ISO time; the text itself otherwise."""
    iso = str(iso or "")
    return iso[:16] + "Z" if len(iso) >= 16 and iso[10:11] == "T" else (iso or "?")


def closed_early_lines(counters: dict) -> list[str]:
    """One line when the shift closed before `review-at:` (M3.7c, #690)."""
    at = counters.get("closed_early")
    if not at:
        return []
    return [f"Closed early at {_hhmm(at)}; review-at was {_hhmm(counters.get('review_at'))} "
            "— nothing was left to run, start or judge.", ""]


def waited_lines(counters: dict) -> list[str]:
    """The PRs that waited in merge order behind an earlier PR bound for the
    human's /prm (S7, M3.7c, PyAutoBrain#690): one line per library repo and
    set of blockers, from `merge_waits` at close and the refused close-outs —
    `autogalaxy: #8, #9 waited behind #7 (/prm-bound: decision-taken)` — after
    a count; and how many PRs were refused because their labels could not be
    read (S7). Empty when there is neither."""
    cos = counters.get("closeouts") or {}
    refused = {u: co for u, co in cos.items() if co.get("state") == "refused"}
    groups: dict[tuple, list[str]] = {}
    for url, info in (counters.get("merge_waits") or {}).items():
        bound = [b for b in info.get("behind") or [] if b in refused]
        if not bound:
            continue
        m = _PR_REF_RE.match(url)
        repo = m.group(1) if m else "?"
        groups.setdefault((repo, tuple(bound)), []).append(url)
    unread = [u for u, co in refused.items()
              if str(co.get("why") or "").startswith("labels unreadable")]
    if not groups and not unread:
        return []

    def num(u):
        m = _PR_REF_RE.match(u)
        return int(m.group(2)) if m else 0
    n = sum(len(v) for v in groups.values())
    out = ["", WAITED_HEADING] + ([f"- {n} PR(s) waited behind a /prm-bound PR"] if n else [])
    if unread:   # review round 1: label reads that never succeeded (S7)
        out.append(f"- {len(unread)} PR(s) refused: labels unreadable (at most one read a "
                   "tick, refused after 3 misses over 15 minutes) — "
                   + ", ".join(pr_ref(u) for u in unread))
    for (repo, bound), urls in groups.items():
        whys = "; ".join(dict.fromkeys(str(refused[b].get("why") or "?").split(" — ", 1)[0]
                                       for b in bound))
        out.append(f"- {repo}: " + ", ".join(f"#{num(u)}" for u in sorted(urls, key=num))
                   + " waited behind " + ", ".join(f"#{num(b)}" for b in bound)
                   + f" (/prm-bound: {whys})")
    return out


def has_slot(counters: dict, task: str, url: str) -> bool:
    """Whether the shift's merge-slot file (as last synced into `counters`
    as `slot_holders`) shows a slot for this PR held for this task."""
    held = (counters.get("slot_holders") or {}).get(_merge_slots.pr_key(url) or url)
    return bool(held) and held.get("task") == task


def no_slot_merges(counters: dict) -> list[str]:
    """In-turn merges a worker reported with no merge slot for its task —
    each one a merge `merge-cap:` did not count (R3, #661)."""
    closeouts = counters.get("closeouts", {})
    return [url for task, o in counters.get("outcomes", {}).items()
            for url in o.get("merged") or []
            if (closeouts.get(url) or {}).get("state") != "merged"
            and not has_slot(counters, task, url)]


def gate_why(task: str, counters: dict) -> str:
    """Why the watcher's last plan kept this task out — a claim or a held
    repo on Mind origin/main, a park in an earlier shift (#637), or the
    planner's own reason for a named task (M3.6b: epic, budget, Blocked-by) —
    or ""."""
    gates = counters.get("backlog_gates") or {}
    for key in ("origin", "parked", "named"):
        for path, why in (gates.get(key) or {}).items():
            if Path(path).stem == task:
                return why
    return ""


def redispatch_why(task: str, counters: dict) -> str:
    """Why a crashed task's re-dispatch never started: the last refusal the
    watcher recorded for it, else `review-at:` came first."""
    last = max((r for r in counters.get("refusals", []) if r.get("task") == task),
               key=lambda r: r.get("last") or r.get("at") or "", default=None)
    if last:
        return f"refused {last.get('why') or last.get('class') or '?'} (last {last.get('last') or last.get('at')})"
    return "review-at came before a free session"


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


# --- links and the two-line task entry (PyAutoBrain#634) ---------------------------

#: A prompt moves at most draft/ → active/ → complete/YYYY/MM/ in a shift;
#: a few more hops are tolerated, never an unbounded walk.
MAX_MOVES = 6
_GH_URL_RE = re.compile(r"^https://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/\d+$")


class MindLinks:
    """Where a task's Mind prompt and its work issue are, read at render time
    from the watcher's own Mind checkout: local git on its `origin/main` ref,
    which the watcher's one fetch and the Mind writer's pushes keep current.
    It makes no network call of its own (PyAutoBrain#634).

    A prompt moves draft/ → active/ → complete/YYYY/MM/ during a shift, often
    renamed, so the `blob/main/draft/...` link the first live shift wrote was
    dead by the time the digest was read. The prompt link here follows the
    moves and is pinned to a commit sha, so it does not go dead later. When it
    cannot read something it returns "", and the caller drops the link."""

    def __init__(self, mind=None, issue: str = "", ref: str = "origin/main", run=None):
        m = _ISSUE_RE.match(issue or "")
        self.repo = m.group(1) if m else ""
        self.mind, self.ref = (Path(mind) if mind else None), ref
        self.run = run or subprocess.run
        self._cache: dict = {}

    def _git(self, *args) -> str | None:
        """git's stdout, or None when it fails or there is no Mind checkout."""
        if self.mind is None:
            return None
        if args not in self._cache:
            try:
                res = self.run(["git", "-C", str(self.mind), *args], capture_output=True,
                               text=True, timeout=30)
                self._cache[args] = res.stdout if res.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                self._cache[args] = None
        return self._cache[args]

    def head(self) -> str:
        """The `origin/main` sha, "" when `mind` is not a checkout of its own."""
        top = self._git("rev-parse", "--show-toplevel")
        if top is None or Path(top.strip()).resolve() != self.mind.resolve():
            return ""
        return (self._git("rev-parse", "--verify", "-q", self.ref + "^{commit}") or "").strip()

    def _renamed(self, commit: str, path: str) -> str | None:
        diff = self._git("diff", "-M", "--name-status", f"{commit}^", commit) or ""
        for line in diff.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("R") and parts[1] == path:
                return parts[2]
        return None

    def prompt_url(self, prompt: str) -> str:
        """The prompt where it is now on `origin/main`, pinned to that sha.
        A prompt deleted without a detectable rename links to its last
        version (the deleting commit's parent). "" when it was never there."""
        head = self.head() if self.repo and prompt else ""
        if not head:
            return ""
        path = prompt
        for _ in range(MAX_MOVES):
            if self._git("cat-file", "-e", f"{head}:{path}") is not None:
                return f"{self.repo}/blob/{head}/{path}"
            gone = (self._git("rev-list", "-1", head, "--", path) or "").strip()
            if not gone:
                return ""
            moved = self._renamed(gone, path)
            if moved is None:
                parent = (self._git("rev-parse", "--verify", "-q", gone + "^") or "").strip()
                return f"{self.repo}/blob/{parent}/{path}" if parent else ""
            path = moved
        return ""

    def work_issue(self, task: str, prompt: str) -> str:
        """The work repo's issue for a task that has claimed itself: the
        `- issue:` of its `active.md` section on `origin/main`, matched by the
        task name or by its `- prompt:` file name (the section's slug is the
        worker's choice and often differs). "" when there is none."""
        head = self.head()
        if not head:
            return ""
        stem = Path(prompt or "").name
        for section in re.split(r"(?m)^## ", self._git("show", f"{head}:active.md") or "")[1:]:
            name, _, body = section.partition("\n")
            keys = dict(re.findall(r"(?m)^- (issue|prompt):[ \t]*(\S+)", body))
            if name.strip() == task or (stem and Path(keys.get("prompt", "")).name == stem):
                url = keys.get("issue", "")
                return url if _GH_URL_RE.match(url) else ""
        return ""


def work_link(task: str, counters: dict, links: MindLinks | None = None) -> str:
    """What a task's title links to: its PR, else the work repo's issue
    (the one its `.done` named, else the one its claim in `active.md` names),
    else "" — the title is then plain text. Never a Mind path (#634)."""
    out = counters.get("outcomes", {}).get(task) or {}
    urls = urls_of(out)
    if urls:
        return urls[0]
    pick = counters.get("picks", {}).get(task) or {}
    return links.work_issue(task, pick.get("prompt") or "") if links is not None else ""


def label(task: str, pick: dict | None, url: str = "") -> str:
    """How a pick is named in a technical list: its title (linked to `url`,
    the work itself, when there is one), the task slug in backticks, then
    size and repos. A pick recorded before titles were (or with none) falls
    back to the bare slug."""
    pick = pick or {}
    title = pick.get("title")
    if not title:
        return task
    head = f"[{title}]({url})" if url else f"**{title}**"
    details = " · ".join(x for x in (pick.get("size"), ", ".join(pick.get("repos") or [])) if x)
    return f"{head} (`{task}`" + (f"; {details}" if details else "") + ")"


#: A task's outcome in plain words (PyAutoBrain#634), read from one part of
#: its `task_state`; the first match wins. The exact state stays on the
#: entry's second line, so nothing is lost by the short form.
_PLAIN = (
    (IN_TURN_NO_SLOT, "Merged with NO merge slot — needs you"),
    ("merged", "Merged"),
    ("awaiting /prm — close-out refused: CI FAILED", "CI failed — needs you"),
    ("awaiting /prm — close-out refused: CI RED", "CI failed — needs you"),
    ("awaiting /prm", "Needs you — not merged unattended"),
    ("close-out running", "Still running — close-out checking it"),
    (UPDATING, "Still running — close-out updating the branch from main"),
    ("waits behind", "Waiting — merges after an earlier PR (your /prm first)"),
    ("waiting: workspace sweep unknown", "Waiting — workspace sweep unknown"),
    (UPDATED, "Branch updated from main — CI re-running"),
    (CURRENT, "Branch up to date — awaiting its merge close-out"),
    (STILL_OUT, "Still running at review time"),
    ("verdict posted", "Verdict posted"),
    ("PARKED-ON-ISSUE", "Needs you — question on the issue"),
    ("FAILED", "CI failed — needs you"),
    ("RUNNING", "CI running"),
    ("HEALTHY", "CI green — awaiting merge"),
    ("NO-CHECKS", "No CI checks — needs your merge"),
    ("UNKNOWN", "CI unknown — needs you"),
    ("parked", "Needs you — blocked on a person"),
    ("blocked on a person", "Needs you — blocked on a person"),
    ("abandoned", "Abandoned — crashed twice"),
    (NOT_REDISPATCHED, "Crashed — not re-dispatched"),
    ("killed by /kill", "Killed by /kill — waiting to be re-dispatched"),
    ("crashed", "Crashed — waiting to be re-dispatched"),
    ("ended", "Crashed"),
    ("obsolete", "Obsolete — nothing to do"),
    ("finished", "Finished — no PR or issue named"),
    ("running", "Still running"),
    ("not started", "Not started"),
    (PROPOSED, "Proposed (shadow)"),
)


def plain_outcome(state: str) -> str:
    """The first line's words for a `task_state`: merged, needs you, CI
    failed, still running. One word set per URL part, de-duplicated."""
    for prefix, word in (("dropped, still running — ", "Dropped, still running"),
                         ("dropped by /drop — ", "Dropped")):
        if state.startswith(prefix):
            rest = plain_outcome(state[len(prefix):])
            return word if rest in ("Not started", "Still running") or \
                word.endswith("running") else f"{word} — {rest}"
    words = []
    for part in state.split("; "):
        what = part.split(" — ", 1)[1] if part.startswith("http") and " — " in part else part
        word = next((w for p, w in _PLAIN if what.startswith(p)), "")
        word = word or (what[:1].upper() + what[1:])
        if word not in words:
            words.append(word)
    return " · ".join(words)


def entry_lines(task: str, pick: dict | None, state: str, tiered: bool, tier: str,
                link: str = "", *, why: str = "", extra=(), mind_url: str = "") -> list[str]:
    """One task as the human reads it (PyAutoBrain#634): the outcome in plain
    words and the title, linked to the work itself; then a second, smaller
    line with the slug, tier, size, repos, the exact state, any `extra`, the
    Mind prompt and, last, the `why:` (`validate` reads it from the end)."""
    pick = pick or {}
    title = pick.get("title") or task
    head = f"- **{plain_outcome(state)}** — " + (f"[{title}]({link})" if link else title)
    detail = state.replace(f"{link} — ", "", 1) if link else state
    bits = [f"`{task}`"] + ([tier] if tiered else []) \
        + [x for x in (pick.get("size"), ", ".join(pick.get("repos") or [])) if x] \
        + [detail] + list(extra) + ([f"[Mind prompt]({mind_url})"] if mind_url else []) \
        + ([f"why: {why}"] if why else [])
    return [head, "  <sub>" + " · ".join(bits) + "</sub>"]


def held_leases(slot: Path) -> dict[str, dict]:
    """The leases still held in a slot — `_orchestrator.leases`, read here
    because this module must not import the orchestrator."""
    out = {}
    for f in sorted((Path(slot) / "leases").glob("*.json")):
        try:
            out[f.stem] = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return out


def _line(task: str, counters: dict, tier: str, health, links: MindLinks | None = None,
          why: str = "", lease: dict | None = None) -> str:
    state, tiered = task_state(task, counters, health, lease=lease)
    pick = counters.get("picks", {}).get(task)
    mind_url = links.prompt_url((pick or {}).get("prompt") or "") if links else ""
    again = counters.get("redispatched", {}).get(task, 0)
    return "\n".join(entry_lines(task, pick, state, tiered, tier,
                                 work_link(task, counters, links), why=why,
                                 extra=[f"re-dispatched {again}×"] if again else [],
                                 mind_url=mind_url))


def _packet(task: str, slot: Path, counters: dict) -> str:
    proof = slot / PROOFS_DIR / f"{task}.md"
    if proof.is_file():
        return proof.read_text(encoding="utf-8").strip()
    prs = urls_of(counters.get("outcomes", {}).get(task)) or ["no PR"]
    return (f"#### {task} — {prs[0]}\n"
            "- claim: not supplied — the worker wrote no proof packet\n"
            "- not checked: everything; read the PR itself\n"
            "- revert: see the PR")


def build(brief: dict, slot: Path, counters: dict, *, tiers: dict | None = None,
          health=None, issue: str = "", mind=None) -> str:
    """The `## Digest` block for one shift, as Markdown. `mind` is the
    watcher's Mind checkout, read locally for the prompt links (#634)."""
    tiers = tiers or {}
    health = health or pr_health
    try:   # the slot file is the merge evidence; fresh at build time
        counters = {**counters, "slot_holders": _merge_slots.holders(slot)}
    except (_merge_slots.MergeSlotError, OSError):
        pass
    picks = counters.get("picks", {})
    named = [Path(p).stem for p in _brief.tasks_of(brief)]
    backlog = [t for t in picks if t not in named]

    lines = [DIGEST_HEADING, ""]
    lines += closed_early_lines(counters)
    # The one notice of the shift's parked questions (M3.5, #645, Decision
    # H7 a): no @mention mid-shift, one line here; the asks live in the inbox.
    inbox = [x for x in [_questions.inbox_line(counters, Path(slot).name, mind)]
             + _questions.unfiled_lines(counters) if x]
    lines += inbox + [""] if inbox else []
    lines += ["### Brief work"]
    links = MindLinks(mind, issue)
    # A worker still out at review-at keeps its lease (#634, N1).
    held = {t: l for t, l in held_leases(slot).items() if l.get("state") != "parked"}
    lines += [_line(t, counters, tiers.get(t, picks.get(t, {}).get("tier", "?")), health, links,
                    lease=held.get(t)) for t in named] or [NO_PICKS]
    lines += ["", "### Backlog picks"]
    lines += [_line(t, counters, tiers.get(t, picks[t].get("tier", "?")), health, links,
                    why=picks[t].get("why") or "NOT RECORDED", lease=held.get(t))
              for t in backlog] or [NO_PICKS]
    lines += backlog_gate_lines(counters)
    lines += merge_order_lines(counters)
    lines += waited_lines(counters)

    started = [t for t in named + backlog
               if t in counters.get("outcomes", {}) or t in counters.get("parked", [])
               or t in counters.get("abandoned", [])
               or t in counters.get("pending_redispatch", [])]
    lines += ["", "### Proof packets"]
    lines += ["\n\n".join(_packet(t, slot, counters) for t in started)
              or (NO_PACKETS_SHADOW if _brief.is_shadow(brief) else NO_PICKS)]

    values = counter_values(brief, counters)
    lines += ["", "### Counters"]
    if _brief.is_shadow(brief):
        lines.append(f"{SHADOW_COUNTERS} · review-minutes-planned: {values['review-minutes-planned']}")
    else:
        lines += [f"- {k}: {values[k]}" for k in COUNTERS]
        lines += cap_lines(counters)
        lines += ["", WORKERS_HEADING] + (worker_lines(counters, links) or [NO_PICKS])
        lines += ["", REFUSALS_HEADING] + (refusal_lines(counters) or [NO_PICKS])
        lines += sweep_lines(counters)
    lines += report_lines(slot)
    lines += identity_lines(counters)
    # The readiness pass's count is the digest's last line (M3.3, #671).
    try:
        import _ready  # noqa: E402 — deferred: it imports the batch conductor
        lines += _ready.digest_lines(counters)
    except Exception as e:  # noqa: BLE001 — never break the digest
        if "rulings" in counters:
            lines += ["", f"Readiness pass failed: the digest could not read it "
                          f"({type(e).__name__}: {e})"[:240]]
    return "\n".join(lines) + "\n"


SWEEP_HEADING = "### Workspace sweep"
#: The prefix of the close-out refusal a sweep block gives (M3.7e): red, or unknown.
SWEEP_RED_WHY = "workspace sweep "


def _sweep_own(sweep: dict, at: str) -> dict | None:
    """The run the shift's own dispatch started (`_sweep.own_run`)."""
    import _sweep  # noqa: E402 — deferred: the digest builds without it
    return _sweep.own_run({"runs": sweep.get("runs") or []}, at)


def sweep_lines(counters: dict) -> list[str]:
    """The shift-end cloud sweep (M3.7e, PyAutoBrain#692): the shift's own
    dispatch and its run, what the latest green sweep verified per library,
    and a red sweep's block, refusals and bug draft. The digest is never held
    for the sweep. Nothing when the sweep is off."""
    sweep, disp = counters.get("sweep") or {}, counters.get("sweep_dispatch") or {}
    if not sweep and not disp:
        return []
    out = []
    if disp:
        if not disp.get("ok"):
            out.append(f"- sweep not dispatched ({disp.get('error') or '?'}) — run it from chat")
        else:
            own = _sweep_own(sweep, disp.get("at", ""))
            if own is None:
                out.append(f"- sweep dispatched at {disp.get('at', '?')}, not yet listed")
            elif own.get("status") != "completed":
                out.append(f"- sweep running: {own.get('url')}")
            else:
                out.append(f"- this shift's sweep finished: {own.get('conclusion') or '?'} — "
                           f"{own.get('url')}")
    read = sweep.get("read") or {}
    if read.get("at") and not read.get("ok"):
        out.append(f"- sweep runs unreadable at {read['at']} ({read.get('error') or '?'}); "
                   "the last known state is below")
    if sweep.get("error"):
        out.append(f"- sweep state could not be worked out: {sweep['error']}")
    green = sweep.get("green") or {}
    run = green.get("full_sweep_run_id") or green.get("id") or "?"
    for lib, sha in (green.get("verified") or {}).items():
        out.append(f"- {lib}: workspaces verified through `{sha}` (run {run})")
    blk = sweep.get("block")
    if blk:
        repos = ", ".join((["every library, chain and workspace repo"]
                           if blk.get("everything") else [])
                          + list(blk.get("repos") or [])) or "?"
        refused = [pr_ref(pr) for pr, co in (counters.get("closeouts") or {}).items()
                   if str(co.get("why") or "").startswith(SWEEP_RED_WHY)]
        draft = f"`{blk['draft']}`" if blk.get("draft") else "not filed yet"
        if blk.get("kind") == "unknown":
            held = [pr_ref(pr) for pr in sorted(counters.get("sweep_waits") or {})]
            out.append(f"- {blk.get('why')} — blocked: {repos}; PRs waiting: "
                       f"{', '.join(held) or 'none'}; PRs refused: "
                       f"{', '.join(refused) or 'none'}")
        else:
            out.append(f"- {blk.get('why')} — blocked: {repos}; PRs refused: "
                       f"{', '.join(refused) or 'none'}; bug draft: {draft}")
    cleared = sweep.get("cleared")
    if cleared:
        out.append(f"- red sweep {cleared.get('url')} cleared by /clear-sweep "
                   f"({cleared.get('by', '?')}, {cleared.get('at', '?')})")
    if not out:
        out.append("- no sweep run known yet")
    return ["", SWEEP_HEADING] + out


_REPORT_WORDS = {
    "skipped": "note: Mind ledger op skipped",
    "set-aside": "warning: Mind ledger op set aside, not committed",
    "conflict": "warning: CONFLICT — Mind ledger op set aside, not committed",
    "held": "warning: Mind ledger op held pending, retried every tick",
    "withheld": "warning: Mind ledger op withheld with its task, not committed",
    # A set-aside whose `needs` is mechanical (#660): already true on main.
    "mechanical": "note: Mind ledger op set aside (mechanical — already true on main, "
                  "no action)",
}


def report_line(e: dict) -> str:
    """One `ledger/report.jsonl` entry as a digest or late line."""
    kind = "mechanical" if (e.get("kind") == "set-aside"
                            and e.get("needs") == "mechanical") else e.get("kind")
    head = _REPORT_WORDS.get(kind, f"warning: Mind ledger {e.get('kind')}")
    where = f" (`ledger/set_aside/{e.get('file')}`)" if e.get("kind") in (
        "set-aside", "conflict", "withheld") else ""
    note = (f" — `{e.get('task')}`'s complete record is already on main"
            if e.get("record") == "on-main" else "")
    return (f"- {head} — {e.get('op') or '?'} {e.get('path') or '?'}: {e.get('why')}"
            f"{where}{note}")


def report_lines(slot: Path) -> list[str]:
    """PyAutoBrain#632: every note, set-aside, conflict and held op the one
    Mind writer reported this shift (`ledger/report.jsonl`) — never only in
    tick.log. Nothing when there is none."""
    f = Path(slot) / "ledger" / "report.jsonl"
    out = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.is_file() else ()):
        try:
            out.append(report_line(json.loads(line)))
        except ValueError:
            continue
    return [""] + out if out else []


def identity_lines(counters: dict) -> list[str]:
    """PyAutoBrain#630: the watcher's App identity failed, so its GitHub writes
    were held — never made under the human's own gh auth instead."""
    auth = counters.get("github_auth") or {}
    if not auth.get("error"):
        return []
    return ["", f"- warning: GitHub writes held — the watcher's App token could not be "
                f"had on {auth.get('ticks', 1)} tick(s), {auth.get('first', '?')} to "
                f"{auth.get('last', '?')}: {auth['error']}"]


#: A question id in a hold's reason (`waiting on Q17 in your inbox`).
_QID_RE = re.compile(r"\bQ\d+\b")


def backlog_gate_lines(counters: dict) -> list[str]:
    """What the M2.3 gates kept out of the backlog dip (AUTONOMY.md "M2
    rulings — 2026-11-12"), as of the watcher's last tick. Not bullets: a
    `- ` line in this section is read as a pick and must carry a `why:`."""
    gates = counters.get("backlog_gates") or {}
    out = []
    if gates.get("queue_stop"):
        out.append("Backlog dip stopped: queue.md is empty, so the shift took the "
                   "brief's named tasks only.")
    origin = gates.get("origin") or {}
    closed = {p: w for p, w in origin.items() if w.endswith(FAIL_CLOSED)}
    repo_held = {p: w for p, w in origin.items() if w.startswith("repo ") and p not in closed}
    claimed = sorted(p for p in origin if p not in closed and p not in repo_held)

    def names(paths):
        return (", ".join(f"`{Path(a).stem}`" for a in paths[:SUMMARY_NAMES])
                + (f" +{len(paths) - SUMMARY_NAMES} more" if len(paths) > SUMMARY_NAMES
                   else ""))
    if claimed:
        out.append(f"Claimed on Mind origin/main: {len(claimed)} draft(s) excluded — the "
                   "canonical checkout still shows them in draft/: " + names(claimed))
    if closed:
        out.append(f"Mind origin/main could not be read: {len(closed)} draft(s) not picked "
                   f"(fail closed) — {next(iter(closed.values()))[5:]}: "
                   + names(sorted(closed)))
    if repo_held:
        out.append(f"Repo claimed on Mind origin/main: {len(repo_held)} draft(s) skipped — "
                   + "; ".join(f"`{Path(p).stem}` ({w.split(' in active.md')[0]})"
                               for p, w in sorted(repo_held.items())[:SUMMARY_NAMES]))
    parked = gates.get("parked") or {}
    if parked:
        # The inbox's word on each, by Q-id (M3.5, #645), so "why wasn't X
        # picked" answers itself; a park from before the inbox names none.
        inboxed = {p: w for p, w in parked.items() if _QID_RE.search(w)}
        out.append(f"Parked on a question by an earlier shift: {len(parked)} draft(s) not "
                   "startable until answered (name one in a brief to start it again): "
                   + ", ".join(f"`{Path(p).stem}`" + (f" ({inboxed[p]})" if p in inboxed else "")
                               for p in sorted(parked)[:SUMMARY_NAMES])
                   + (f" +{len(parked) - SUMMARY_NAMES} more" if len(parked) > SUMMARY_NAMES
                      else ""))
    resumed = gates.get("resumed") or {}
    if resumed:
        out.append(f"Released by an answer in your inbox: {len(resumed)} task(s) back at "
                   "their old standing — " + "; ".join(
                       f"`{t}` ({', '.join(v.get('ids') or [])} answered)"
                       for t, v in sorted(resumed.items())[:SUMMARY_NAMES]))
    carried = counters.get("carried_in") or {}
    if carried.get("prs"):
        out.append(f"Carried over from {carried['from']}: {len(carried['prs'])} late PR(s) "
                   "closed out under this shift's grant — " + ", ".join(carried["prs"][:SUMMARY_NAMES])
                   + (f" +{len(carried['prs']) - SUMMARY_NAMES} more"
                      if len(carried["prs"]) > SUMMARY_NAMES else ""))
    again = counters.get("inshift_released") or {}
    if again:
        out.append(f"Restarted in-shift after an answer: {len(again)} task(s) — "
                   + "; ".join(f"`{t}` ({', '.join(i for r in rs for i in r.get('ids') or [])})"
                               for t, rs in sorted(again.items())[:SUMMARY_NAMES]))
    bare = gates.get("witness_absent") or []
    if bare:
        out.append(f"No Witness: {len(bare)} draft(s) not dipped — a shift dips only "
                   "witnessed drafts; declare a Witness: to make one pickable: "
                   + names(bare))
    reach = gates.get("scoped_reach") or []
    if reach:
        out.append(f"Backlog reach (ruling 2026-11-16): {len(reach)} unqueued draft(s) not "
                   "dipped — beyond queue.md only small single-repo tasks: " + names(reach))
    absent = gates.get("lane_absent") or []
    if absent:
        out.append(f"Lane absent: {len(absent)} draft(s) excluded — no valid `Lane:`, "
                   "and an unattended pick fails closed: "
                   + ", ".join(f"`{Path(a).stem}`" for a in absent))
    return [""] + out if out else []


# --- per-worker exits, GitHub merges, tokens (PyAutoBrain#610) -----------------

WORKERS_HEADING = "### Workers"
#: A worker's exit path is these words joined by `/` — `spawned/crashed`,
#: `spawned/parked/late/finished`. `launch-failed` stands alone: no session
#: started. `ended` is a parked worker that ended without a `.done`.
EXIT_WORDS = ("spawned", "finished", "crashed", "parked", "late", "ended",
              "launch-failed", "killed")
#: `killed` is a worker the human stopped by `/kill` (#644): it is re-dispatched
#: as a crash is, but it is not a crash, so it is not in `CRASH_WORDS`.
CRASH_WORDS = ("crashed", "launch-failed")


def worker_lines(counters: dict, links: MindLinks | None = None) -> list[str]:
    """One line per worker the shift started (or failed to start)."""
    picks = counters.get("picks", {})
    out = []
    for w in counters.get("workers", []):
        url = work_link(w["task"], counters, links)
        line = f"- {label(w['task'], picks.get(w['task']), url)} ({w.get('key') or '?'}): " \
               + "/".join(w.get("exits") or ["spawned"])
        if w.get("stalled_s"):
            line += f" — blocked {round(w['stalled_s'] / 60)} min"
        for m in w.get("mentions", []):
            line += f" — mentioned ({m.get('state', '?')})"
        out.append(line)
    poster, mentioned = counters.get("poster_login") or "", counters.get("mention_login") or ""
    if poster and poster.lower() == mentioned.lower():
        out.append(f"- warning: mention will not notify: posted as the mentioned account "
                   f"({poster}) — set the watcher's App (PYAUTO_SHIFT_APP_*) or "
                   "PYAUTO_SHIFT_GH_TOKEN")
    pushes = counters.get("pushes", 0)
    if pushes > 1:
        out.append(f"- finding: {pushes} pushes this shift — the push test budgets "
                   "about one (AUTONOMY.md)")
    events = int(counters.get("event_comments") or 0)
    if events:
        # Needs-you event comments (#644) have their own cap, 5 + 1 a shift,
        # and are not pushes for the finding above.
        out.append(f"- needs-you event comments: {events} (at most 5 + 1 a shift)")
    return out


REFUSALS_HEADING = "### Refusals"
#: Refusal reasons that carry a running figure, keyed by their class so one
#: refusal is one entry however the figure moves (PyAutoBrain#632, F3).
_REFUSAL_CLASSES = (
    (re.compile(r"^(token-budget \d+) spent\b"), r"\1 spent"),
    (re.compile(r"^(token-budget \d+): \d+ committed \+ (\d+) reserved per worker"),
     r"\1: committed + \2 reserved per worker would pass it"),
    (re.compile(r"^token usage unavailable\b"), "token usage unavailable"),
    (re.compile(r"^spawn failed\b"), "spawn failed"),
    # Close-out refusals, so the event stream's `cls` is stable (#644). The
    # public-name check's wording is #641's (`bin/public_names.py` `reason`).
    (re.compile(r"^public name added/renamed\b"), "public name added or renamed: a human /prm"),
    (re.compile(r"^public-name check could not tell\b"),
     "public-name check could not tell: a human /prm"),
    (re.compile(r"^PR carries the decision-taken label\b"), "decision-taken label"),
    (re.compile(r"^token spend \d+ \(committed\) reached (\S+× token-budget \d+)"),
     r"token spend reached \1"),
)
#: Refusals whose reason is the shift's, not the task's — summarised in one
#: line for every task they held back (#632, F3 and review).
SHIFT_WIDE_RE = re.compile(r"^(max-workers \d+ reached|max-sessions \d+ reached"
                           r"|token-budget \d+|token usage unavailable)")
#: Tasks a summary line names before `+N more`.
SUMMARY_NAMES = 8


def refusal_class(why: str) -> str:
    """The stable part of a refusal reason: the reason with its running
    figure (tokens spent, committed) dropped; any other reason as it is."""
    for rx, label in _REFUSAL_CLASSES:
        m = rx.match(why or "")
        if m:
            return m.expand(label)
    return why or "?"


def note_refusals(counters: dict, refused: list[dict], at: str) -> None:
    """Record one tick's refusals: one entry per (task, reason class), with
    its count, first and last time and the latest full reason (#632, F3)."""
    index = {(r.get("task"), r.get("class") or refusal_class(r.get("why", ""))): r
             for r in counters.setdefault("refusals", [])}
    for r in refused:
        cls = refusal_class(r.get("why", ""))
        old = index.get((r.get("task"), cls))
        if old is None:
            old = {"task": r.get("task"), "class": cls, "count": 0, "at": at}
            counters["refusals"].append(old)
            index[(r.get("task"), cls)] = old
        # An entry from before #632 (no `count`) stood for one refusal.
        old.update(why=r.get("why", ""), last=at, count=int(old.get("count", 1)) + 1)


def refusal_lines(counters: dict) -> list[str]:
    """Every spawn the watcher refused: one line per task and reason class,
    with how many ticks refused it, from when to when, and the latest figure
    where the reason carries one; every `max-workers` refusal in one line
    (#610 review, #632 F3); every shift-wide reason (`max-workers`,
    `max-sessions`, a token reason) is one line for all the tasks it held
    back. A refusal recorded one entry per tick (before
    #632) folds into the same lines."""
    seen: dict[tuple[str, str], dict] = {}
    for r in counters.get("refusals", []):
        cls = r.get("class") or refusal_class(r.get("why", "?"))
        k = (r.get("task", "?"), cls)
        e = seen.setdefault(k, {"n": 0, "first": r.get("at", "?"), "last": "", "why": ""})
        e["n"] += int(r.get("count") or 1)
        e["last"] = max(e["last"], r.get("last") or r.get("at") or "")
        e["why"] = r.get("why", "") or e["why"]
    out, capped = [], {}
    for (task, cls), e in seen.items():
        if SHIFT_WIDE_RE.match(cls):
            c = capped.setdefault(cls, {"tasks": [], "n": 0, "first": e["first"], "last": "",
                                        "why": ""})
            c["tasks"].append(task)
            c["n"] += e["n"]
            c["first"] = min(c["first"], e["first"])
            if e["last"] >= c["last"]:
                c["why"] = e["why"]
            c["last"] = max(c["last"], e["last"])
            continue
        tail = f"{e['n']}× from {e['first']}" + (
            f" to {e['last']}" if e["last"] and e["last"] != e["first"] else "")
        if e["why"] and e["why"] != cls:
            tail += f" (last: {e['why']})"
        out.append(f"- {task} — {cls} — {tail}")
    for cls, c in capped.items():
        names = ", ".join(c["tasks"][:SUMMARY_NAMES]) + (
            f" +{len(c['tasks']) - SUMMARY_NAMES} more" if len(c["tasks"]) > SUMMARY_NAMES else "")
        out.append(f"- {cls} — {len(c['tasks'])} task(s) waited: {names} — "
                   f"{c['n']}× from {c['first']}"
                   + (f" to {c['last']}" if c["last"] and c["last"] != c["first"] else "")
                   + (f" (last: {c['why']})" if c["why"] and c["why"] != cls else ""))
    return out


def cap_lines(counters: dict) -> list[str]:
    """A cap the human lowered (or raised back) by `/cap` this shift (#644),
    one line each: `merge-cap 2 → 1 (/cap by <login> at 18:02Z)`. Not a
    counter column, so the pilot rows keep their shape."""
    out = []
    for key, ov in sorted((counters.get("caps") or {}).items()):
        if not isinstance(ov, dict):
            continue
        at = str(ov.get("at") or "")
        out.append(f"- cap override: {key} {ov.get('brief', '?')} → {ov.get('value', '?')} "
                   f"(/cap by {ov.get('by', '?')} at {at[11:16] + 'Z' if len(at) >= 16 else at})")
    return out


def workers_crashed(counters: dict) -> int:
    """Workers whose exit path holds a crash (or whose launch failed); a slot
    recorded before per-worker exits falls back to its crash tally."""
    workers = counters.get("workers") or []
    if not workers:
        return counters.get("crashes", 0)
    return sum(1 for w in workers if any(x in CRASH_WORDS for x in w.get("exits") or []))


def merged_prs(counters: dict) -> list[dict]:
    """The shift's PRs that are merged, with GitHub's `mergedBy` and the merge
    actor. GitHub decides where it was read at `review-at:` (`github`, with
    `in_window`: merged at or before `review-at:`); a PR it could not say
    about falls back to what the watcher recorded (`.done` / close-out)."""
    gh_all = counters.get("github", {})
    closeouts = counters.get("closeouts", {})
    out = []
    for task, o in counters.get("outcomes", {}).items():
        for url in o.get("prs") or []:
            gh = gh_all.get(url)
            recorded = url in (o.get("merged") or [])
            if not (gh.get("in_window") if gh is not None else recorded):
                continue
            co = closeouts.get(url, {})
            actor = ("unattended-watcher" if co.get("state") == "merged"
                     else "in-turn-autonomous" if recorded else "unknown")
            by = (gh or {}).get("mergedBy") or (co.get("github") or {}).get("mergedBy") or ""
            out.append({"url": url, "task": task, "mergedBy": by, "actor": actor})
    return out


def token_parts(counters: dict) -> dict:
    """The shift's tokens by component and by session kind. `measured` is what
    was read; `total` is that sum only when every session was measured, else
    None (written `null` / `unmeasured`, never 0), with the sessions named in
    `unmeasured` — never read, or `UNREADABLE_READS` failed reads in a row."""
    parts = {"total": 0, "measured": 0, "input": 0, "output": 0, "cache_creation": 0,
             "cache_read": 0, "subagents": 0, "workers": 0, "closeouts": 0,
             "unmeasured": []}
    for key, u in sorted((counters.get("usage") or {}).items()):
        if u.get("total") is None or u.get("unmeasured"):
            parts["unmeasured"].append(key)
        if u.get("total") is None:
            continue
        parts["measured"] += int(u["total"])
        for k in ("input", "output", "cache_creation", "cache_read", "subagents"):
            parts[k] += int(u.get(k) or 0)
        parts["closeouts" if u.get("kind") == "closeout" else "workers"] += int(u["total"])
    if not counters.get("usage"):
        parts["measured"] = parts["workers"] = int(counters.get("tokens", 0) or 0)
    parts["total"] = None if parts["unmeasured"] else parts["measured"]
    return parts


def counter_values(brief: dict, counters: dict) -> dict:
    """Every digest counter's value, from the brief and `counters.json`."""
    budget = brief.get("token-budget", {}).get("value", "?")
    parts = token_parts(counters)
    tokens = f"{parts['measured']} of {budget}"
    # Close-outs may pass the budget but count against it (AUTONOMY.md, ruling
    # 2026-11-14, #632 F5): their share is named, and so is an overrun.
    over = str(budget).isdigit() and parts["measured"] > int(budget)
    extra = ([f"close-outs {parts['closeouts']}"] if parts["closeouts"] else []) \
        + ([f"over budget by {parts['measured'] - int(budget)}"] if over else []) \
        + ([f"cache-read {parts['cache_read']}"] if parts["cache_read"] else []) \
        + ([f"{len(parts['unmeasured'])} session(s) unmeasured"] if parts["unmeasured"] else [])
    values = {"merges": len(merged_prs(counters)), "workers-crashed": workers_crashed(counters),
              "tokens": tokens + (f" ({'; '.join(extra)})" if extra else ""),
              "review-minutes-planned": brief.get("review-minutes", {}).get("value", "?")}
    for key, field in LATER_COUNTERS.items():
        values[key] = counters.get(field, 0)
    return values


#: The machine-readable pilot ledger: one JSON line per shift, keyed by `slot`
#: and amended in place (`amended: true`) by a late arrival — never a second
#: line. `pilot.md` is its render (`pilot_md_row`).
PILOT_JSONL = "batches/pilot/pilot.jsonl"


def pilot_record(slot_name: str, brief: dict, counters: dict, *, amended: bool = False) -> dict:
    """The shift's one `pilot.jsonl` row. Shadow merges are the human's (None)."""
    shadow = _brief.is_shadow(brief)
    v = counter_values(brief, counters)
    stall = sum(float(w.get("stalled_s") or 0) for w in counters.get("workers", []))
    cells = {k: v[k] for k in COUNTERS if k not in ("tokens", "review-minutes-planned")}
    if shadow:
        cells["merges"] = None
    return {
        "slot": slot_name, "mode": "shadow" if shadow else "live",
        "review-minutes-planned": v["review-minutes-planned"],
        "counters": cells,
        "tokens": token_parts(counters),
        "merged": [] if shadow else merged_prs(counters),
        "workers": [{"task": w["task"], "key": w.get("key"),
                     "exits": "/".join(w.get("exits") or ["spawned"]),
                     "stall_minutes": round(float(w.get("stalled_s") or 0) / 60)}
                    for w in counters.get("workers", [])],
        "stall_minutes": round(stall / 60),
        "amended": amended,
    }


def pilot_md_row(record: dict) -> str:
    """`pilot.md`'s row for one `pilot.jsonl` record; the human's cells are `?`."""
    cells = {**record["counters"], "slot": record["slot"], "mode": record["mode"],
             "review-minutes-planned": record["review-minutes-planned"],
             "tokens": record["tokens"]["total"]}
    if cells["tokens"] is None:
        cells["tokens"] = "unmeasured"
    human = PILOT_HUMAN + (PILOT_HUMAN_SHADOW if record["mode"] == "shadow" else ())
    return "| " + " | ".join("?" if c in human or cells.get(c) is None else str(cells[c])
                             for c in PILOT_COLUMNS) + " |\n"


def pilot_row(slot_name: str, brief: dict, counters: dict) -> str:
    """One `batches/pilot/pilot.md` row; the human's cells land as `?`."""
    return pilot_md_row(pilot_record(slot_name, brief, counters))


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


def _items(lines: list[str]) -> list[str]:
    """A section's bullets, each joined with its indented continuation lines
    (the second line of a #634 entry)."""
    items: list[str] = []
    for line in lines:
        if line.startswith("- "):
            items.append(line)
        elif items and line.startswith("  ") and line.strip():
            items[-1] += "\n" + line
    return items


#: A #634 entry names its task first on its second line.
_SUB_SLUG_RE = re.compile(r"(?m)^\s+<sub>`([^`]+)`")
_WHY_RE = re.compile(r"(?m)(?: — | · )why: (.*?)\s*(?:</sub>)?\s*$")


def _slug(item: str) -> str:
    """The task a digest bullet is about: the slug on a #634 entry's second
    line, else the backticked slug a titled pick carries on its one line,
    else the bullet's first word (a pick recorded without a title)."""
    m = _BULLET_RE.match(item)
    if not m:
        return ""
    sub = _SUB_SLUG_RE.search(item)
    if sub:
        return sub.group(1)
    s = _SLUG_RE.search(item.split("\n", 1)[0].split(" — ", 1)[0])
    return s.group(1) if s else m.group(1)


def validate(text: str) -> list[str]:
    """Errors in a record's `## Digest`; empty when there is none, or it is whole.
    Reads both the one-line entries of shifts before #634 and the two-line ones."""
    if DIGEST_HEADING not in text:
        return []
    errs = []
    secs = _sections(text)
    for s in SECTIONS:
        if s not in secs:
            errs.append(f"digest: {s[4:]} section missing")
    for item in _items(secs.get("### Backlog picks", [])):
        slug = _slug(item)
        if slug and item.strip() != NO_PICKS:
            why = _WHY_RE.search(item)
            if not why or not why.group(1).strip() or why.group(1).strip() == "NOT RECORDED":
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
        for item in _items(secs.get(sec, [])):
            slug = _slug(item)
            if slug and item.strip() != NO_PICKS and "not started" not in item \
                    and NOT_REDISPATCHED not in item \
                    and PROPOSED not in item and STILL_OUT not in item \
                    and f"#### {slug}" not in packets:
                errs.append(f"digest: {slug} has no proof packet")
    return errs

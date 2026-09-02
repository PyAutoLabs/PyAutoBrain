"""agents/conductors/batch/_integration.py — the batch's integration branches.

One throwaway worktree root per slot. Every member's head branch is merged into
`integration/<slot>`, per repo, off `origin/main`, so the human can *run* the
whole batch together before ruling on any of it — and so the question "how
would these resolve at the end?" is answered by a merge rather than by reading
diffs.

Three properties, deliberately:

* **It writes no remote unless `--push` is typed.** By default: `git fetch
  origin` and local merges; no push, no PR, no remote ref is created or moved.
  `--push` adds exactly one act, `push_repo` below — it publishes each
  `integration/<slot>` to `origin` as a throwaway review ref. It is never
  forced (no force flag, no lease): a branch that is not a fast-forward of what
  is already published is pushed under a new `-N` name and the earlier ref is
  left exactly where it is. Never a pull request, never a base for one.
* **It resolves nothing.** A member whose merge conflicts is left OUT of that
  repo's branch and named with the conflicting paths. That report is the
  product; it is not a failure of the collect, and it moves no exit code and no
  member's health word (a member's health is about its own delivery; a merge
  collision is a property of the *slot*).
* **It is stdlib-only and imports nothing from `_batch`.** The conductor loads
  it lazily, the way it loads the Cortex conductor, so a session that never asks
  for `--integration` never pays for it — and this module stays unit-testable
  against throwaway repos with no Mind, no record and no packet in sight.

The seam with `bin/worktree.sh`: **worktree.sh knows layout, this module knows
merges.** The value of `worktree_create` is not `git worktree add` — it is the
root (activate.sh's `PYTHONPATH`, the per-task numba/matplotlib caches, and the
symlink of every other top-level entry so relative workspace paths resolve).
Re-deriving that here would fork the definition of "a PyAuto worktree root" into
two places that would drift, so the ROOT is built by shelling to worktree.sh
with `PYAUTO_WT_BRANCH=integration/<slot>`; the MERGES are plain `git`, because
a shell helper would bury the exit code and the unmerged-path list the packet
needs.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[3]
WORKTREE_SH = BRAIN / "bin" / "worktree.sh"

#: `git` never gets to ask for a password: an unattended collect that blocks on
#: a credential prompt looks exactly like a hung merge.
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}

#: A box with no committed git identity (CI, a fresh container) cannot merge at
#: all. Supplied per-invocation with `-c`, and ONLY when the worktree has no
#: identity of its own — a human's box keeps their own name on their own merges.
FALLBACK_NAME = "PyAuto Batch"
FALLBACK_EMAIL = "batch@pyautolabs.invalid"

NOT_LOCAL = ("batch collect --integration: the integration worktree is a "
             "laptop leg (real git worktrees under $PYAUTO_WT_ROOT) — run "
             "collect from the laptop; everything else is scored anyway.")

NOT_LOCAL_PUSH = ("batch collect --integration --push: pushing an integration "
                  "ref needs the laptop's own git credential — a remote "
                  "session's GH_TOKEN is a proxy placeholder that cannot write "
                  "a ref at all (skills/GITHUB_ACCESS.md). Run it from the "
                  "laptop; everything else is scored anyway.")

#: How many publications of one slot this will name before it gives up. A slot
#: that has been re-published twenty times is not a review branch any more.
MAX_SUFFIX = 20


# ------------------------------------------------------------- where things go
def workspace_root() -> Path:
    """The directory holding the organ checkouts side by side.

    Same convention as `bin/_pyauto_root.sh`: an explicit `PYAUTO_ROOT` is the
    operator's word and always wins; otherwise it is the parent of this Brain
    checkout, which is true in every environment the organism runs in.
    """
    return Path(os.environ.get("PYAUTO_ROOT") or BRAIN.parent)


def task_name(slot: str) -> str:
    return f"integration-{slot}"


def branch_name(slot: str) -> str:
    return f"integration/{slot}"


def wt_root() -> Path:
    """Where task roots live — beside the workspace root, never inside it."""
    return Path(os.environ.get("PYAUTO_WT_ROOT") or f"{workspace_root()}-wt")


def root_for(slot: str) -> Path:
    return wt_root() / task_name(slot)


def _env() -> dict:
    """The environment every child gets: the caller's, plus the four variables
    that make worktree.sh and this module resolve the *same* paths. Deriving
    both sides from `workspace_root()` is what stops the root being built beside
    one checkout while the merges read another."""
    env = dict(os.environ)
    env.update(GIT_ENV)
    env["PYAUTO_ROOT"] = str(workspace_root())
    env["PYAUTO_MAIN"] = str(workspace_root())
    env["PYAUTO_WT_ROOT"] = str(wt_root())
    return env


def _git(*args: str, cwd=None, timeout: int = 60):
    """One git call. Captured, never interactive, and it NEVER raises on a
    non-zero return code: every git failure here is a line in the report, and a
    traceback out of a collect would lose the members that did merge."""
    try:
        return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                              env=_env(), capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:  # pragma: no cover
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=127, stdout="", stderr=str(e))


def _tail(proc) -> str:
    lines = ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()
    return lines[-1][:160] if lines else ""


# ----------------------------------------------------------------- the plan --
def plan_jobs(members: list, order: list, notes: list) -> list:
    """`[{"repo", "dir", "members": [{"member", "branch", "want_sha"}…]}…]`.

    Grouped by **repo**, not by member: the common case is one member with organ
    PRs across five repos, so a member contributes one head branch to each repo
    it touched and can be merged in one and conflicted in another. Ordered by
    the record's dispatch order (`order`), because `d["members"]` is re-sorted by
    health and merge order is a property of the record, not of the scores.

    Everything left out says so. Four reasons, and none of them is a guess:
    already merged, closed, no `head_ref` in the evidence, or a head that lives
    on a fork (whose branch is simply not on `origin` and cannot be merged from
    a local checkout at all).
    """
    by_slug = {m.get("slug"): m for m in members}
    groups: dict[str, dict] = {}
    for slug in order:
        m = by_slug.get(slug)
        if not m:
            continue
        for p in m.get("prs") or []:
            repo = str(p.get("repo") or "")
            label = f"{repo}#{p.get('number')}"
            if p.get("merged"):
                notes.append(f"{slug}: {label} is already merged — not "
                             f"re-merged")
                continue
            if str(p.get("state") or "").upper() == "CLOSED":
                notes.append(f"{slug}: {label} is CLOSED — not merged")
                continue
            head_ref = str(p.get("head_ref") or "")
            if not head_ref:
                notes.append(f"{slug}: {label} has no head_ref in the evidence "
                             f"— re-run collect --fetch (Phase 1 field "
                             f"headRefName)")
                continue
            head_repo = str(p.get("head_repo") or "")
            if head_repo and head_repo != repo:
                notes.append(f"{slug}: {label} is from a fork ({head_repo}) — "
                             f"its head is not on origin, left out")
                continue
            g = groups.setdefault(repo, {"repo": repo,
                                         "dir": repo.split("/")[-1],
                                         "members": []})
            g["members"].append({"member": slug, "branch": head_ref,
                                 "want_sha": str(p.get("head_sha") or "")})
    jobs = []
    for g in groups.values():
        if not (workspace_root() / g["dir"] / ".git").exists():
            notes.append(f"{g['repo']}: no checkout at "
                         f"{workspace_root() / g['dir']} — left out of the "
                         f"integration root")
            continue
        jobs.append(g)
    return jobs


# ----------------------------------------------------------------- the root --
def _worktree_sh(func: str, slot: str, *args: str):
    """One call into `bin/worktree.sh`, with the branch override that is the
    only thing it could not otherwise say."""
    env = _env()
    env["PYAUTO_WT_BRANCH"] = branch_name(slot)
    return subprocess.run(
        ["bash", "-c", f'set -e; . "$0"; {func} "$@"', str(WORKTREE_SH),
         task_name(slot), *args],
        env=env, capture_output=True, text=True, timeout=600)


def ensure_root(slot: str, repo_dirs: list, notes: list):
    """The worktree root, created or adopted. Idempotent by construction.

    `worktree_create` refuses an existing root — which is exactly why the two
    branches are here rather than a force: a second run of the same slot adopts
    the root it built the first time, and attaches only the repos that are still
    placeholder symlinks in it. Anything that fails returns `None`: half a root
    reported as an integration is worse than none.
    """
    root = root_for(slot)
    if not root.exists():
        proc = _worktree_sh("worktree_create", slot, *repo_dirs)
        if proc.returncode != 0:
            notes.append(f"integration root not built at {root}: "
                         f"{_tail(proc)}")
            return None
        return root
    for name in repo_dirs:
        if (root / name / ".git").exists():
            continue
        proc = _worktree_sh("worktree_add_repo", slot, name)
        if proc.returncode != 0:
            notes.append(f"{name}: could not attach to the integration root "
                         f"at {root}: {_tail(proc)}")
            return None
    return root


# --------------------------------------------------------------- the merges --
def _identity(wt: Path) -> list:
    """`-c user.name=… -c user.email=…`, or nothing at all. A box with no
    committed identity cannot make a merge commit; a box with one keeps it."""
    got = _git("-C", str(wt), "config", "user.email")
    if got.returncode == 0 and got.stdout.strip():
        return []
    return ["-c", f"user.name={FALLBACK_NAME}",
            "-c", f"user.email={FALLBACK_EMAIL}"]


def integrate_repo(job: dict, wt: Path, slot: str, notes: list) -> dict:
    """One repo's integration branch. Returns the report row; raises nothing.

    The branch is **re-cut from `origin/main` on every run** (`checkout -B`).
    The merge result is a function of the current `origin/main` and the current
    heads, so a second run that merged onto the previous run's tip would report
    a preview of a base that no longer exists — the honest refresh is a re-cut.
    That is safe because the ref is a throwaway: nothing is pushed, no PR is
    based on it and no member branch descends from it, so `-B` rewrites nothing
    anyone else holds. (`AGENTS.md`'s "never rewrite history" is about
    *published* history — which is precisely what Phase 3's never-force-push
    rule will protect once such a branch exists on GitHub.)

    The one thing a re-cut could destroy is a human's uncommitted experiment
    inside the integration worktree, so step 2 refuses a dirty worktree outright
    and says so. **That refusal, not the branch policy, is the safety property.**
    """
    branch = branch_name(slot)
    row = {"repo": job["repo"], "dir": job["dir"], "path": str(wt),
           "branch": branch, "base": "origin/main", "base_sha": "",
           "head_sha": "", "merged": [], "conflicts": [], "status": "skipped",
           "note": ""}

    # A run killed mid-merge leaves MERGE_HEAD and conflicted files behind, and
    # `checkout -B` would refuse on both. Clearing it first is what makes the
    # dirty check below mean "a human left something here", not "we did".
    _git("-C", str(wt), "merge", "--abort")

    dirty = _git("-C", str(wt), "status", "--porcelain")
    if dirty.returncode != 0:
        row["note"] = f"git status failed in {wt}: {_tail(dirty)}"
        notes.append(f"{job['repo']}: {row['note']}")
        return row
    if dirty.stdout.strip():
        row["note"] = ("the integration worktree has uncommitted changes — "
                       "left alone")
        notes.append(f"{job['repo']}: {row['note']}")
        return row

    fetched = _git("-C", str(wt), "fetch", "origin", "--quiet", timeout=300)
    if fetched.returncode != 0:
        notes.append(f"{job['repo']}: git fetch origin failed "
                     f"({_tail(fetched)}) — merged against the refs already "
                     f"here, which may be stale")

    base = _git("-C", str(wt), "rev-parse", "--verify", "origin/main")
    if base.returncode != 0:
        row["note"] = "no origin/main in this checkout — nothing to cut from"
        notes.append(f"{job['repo']}: {row['note']}")
        return row
    row["base_sha"] = base.stdout.strip()

    cut = _git("-C", str(wt), "checkout", "-B", branch, "origin/main")
    if cut.returncode != 0:
        row["note"] = f"could not cut {branch} from origin/main: {_tail(cut)}"
        notes.append(f"{job['repo']}: {row['note']}")
        return row

    ident = _identity(wt)
    for entry in job["members"]:
        ref = f"origin/{entry['branch']}"
        if _git("-C", str(wt), "rev-parse", "--verify", ref).returncode != 0:
            notes.append(f"{entry['member']}: {ref} is not in "
                         f"{job['repo']} — pushed? left out")
            continue
        got = _git("-C", str(wt), *ident, "merge", "--no-ff", "--no-edit",
                   "-m", f"integration {slot}: {entry['member']} "
                         f"({entry['branch']})", ref, timeout=300)
        if got.returncode == 0:
            row["merged"].append(entry["member"])
            continue
        # The unmerged paths exist only while the index is unmerged, so they are
        # read BEFORE the abort — afterwards there is nothing left to name.
        paths = _git("-C", str(wt), "diff", "--name-only", "--diff-filter=U")
        row["conflicts"].append({
            "member": entry["member"], "branch": entry["branch"],
            "paths": [p for p in paths.stdout.split("\n") if p.strip()]})
        _git("-C", str(wt), "merge", "--abort")

    head = _git("-C", str(wt), "rev-parse", "HEAD")
    row["head_sha"] = head.stdout.strip() if head.returncode == 0 else ""
    row["status"] = "conflicted" if row["conflicts"] else "clean"
    return row


# ---------------------------------------------------------------- the push --
def push_repo(row: dict, wt: Path, slot: str, notes: list) -> None:
    """Publish one repo's integration branch to `origin`. Mutates `row`.

    The only remote write in this module, and the only one the batch ever makes.
    It is a *throwaway review ref*: never a pull request, never a base for one,
    and it expires at the record's `sweep-after:` date.

    **Nothing already on origin is ever moved.** There is no force flag and no
    lease anywhere here; the four arms below are the whole decision, in order:

    1. the merge was skipped — there is nothing to publish;
    2. `origin/<branch>` carries the SAME TREE as HEAD — not re-pushed. This arm
       is load-bearing: `integrate_repo` re-cuts the branch every run
       (`checkout -B` plus `--no-ff` merges), so the commit SHAs differ on every
       refresh even when nothing changed. Comparing commits would make every
       refresh look non-fast-forwardable and pile up `-2 … -20`; comparing trees
       asks the question the human means, "is what is published still this?";
    3. `origin/<branch>` is an ancestor of HEAD — a genuine fast-forward, pushed
       plainly;
    4. otherwise the published ref and this one have diverged, so this one is
       published under the first free `<branch>-N` instead and the earlier ref is
       left exactly where it is. `branch -f` there only ever writes a LOCAL ref
       whose name has just been proven absent on origin, so no published history
       moves.

    A push that fails is a note and nothing more: `row["status"]` is never
    touched, because the merge verdict is a fact about the merge and a network
    failure must not turn a clean integration into a conflicted one.
    """
    row["remote_branch"] = ""
    row["pushed"] = False
    row["push_note"] = ""

    if row.get("status") == "skipped":
        row["push_note"] = "nothing was merged — nothing pushed"
        return

    # The decision below rests on what is published RIGHT NOW, so the namespace
    # is refreshed first. A failure is a note, not a stop — same shape as the
    # fetch in `integrate_repo`.
    fetched = _git("-C", str(wt), "fetch", "origin", "--quiet",
                   "+refs/heads/integration/*:refs/remotes/origin/integration/*",
                   timeout=300)
    if fetched.returncode != 0:
        notes.append(f"{row['repo']}: could not fetch the integration namespace "
                     f"({_tail(fetched)}) — the publication decision rests on "
                     f"the refs already here, which may be stale")

    base = branch_name(slot)
    remote = f"origin/{base}"
    target = base

    if _git("-C", str(wt), "rev-parse", "--verify", remote).returncode == 0:
        theirs = _git("-C", str(wt), "rev-parse", f"{remote}^{{tree}}")
        ours = _git("-C", str(wt), "rev-parse", "HEAD^{tree}")
        same = (theirs.returncode == 0 and ours.returncode == 0
                and theirs.stdout.strip() == ours.stdout.strip())
        if same:
            row["remote_branch"] = base
            row["push_note"] = (f"origin/{base} already carries this exact "
                                f"tree — not re-pushed")
            return
        ff = _git("-C", str(wt), "merge-base", "--is-ancestor", remote, "HEAD")
        if ff.returncode != 0:
            cand = ""
            for n in range(2, MAX_SUFFIX):
                probe = f"{base}-{n}"
                if _git("-C", str(wt), "rev-parse", "--verify",
                        f"origin/{probe}").returncode != 0:
                    cand = probe
                    break
            if not cand:
                row["push_note"] = (
                    f"origin/{base} is not an ancestor of this branch, and "
                    f"-2 … -{MAX_SUFFIX - 1} are all published already — not "
                    f"pushed; sweep the old refs or collect a new slot")
                notes.append(f"{row['repo']}: {row['push_note']}")
                return
            made = _git("-C", str(wt), "branch", "-f", cand, "HEAD")
            if made.returncode != 0:
                row["push_note"] = (f"could not name the local ref {cand}: "
                                    f"{_tail(made)}")
                notes.append(f"{row['repo']}: {row['push_note']}")
                return
            target = cand
            row["push_note"] = (f"origin/{base} is not an ancestor of this "
                                f"branch — never force-pushed; published as "
                                f"{cand} instead")

    proc = _git("-C", str(wt), "push", "origin",
                f"{target}:refs/heads/{target}", timeout=300)
    if proc.returncode == 0:
        row["remote_branch"] = target
        row["pushed"] = True
        return
    row["pushed"] = False
    row["remote_branch"] = ""
    row["push_note"] = f"push failed: {_tail(proc)}"
    notes.append(f"{row['repo']}: {row['push_note']}")


# ------------------------------------------------------------------- the leg --
def run(members: list, order: list, slot: str, *, lane: str,
        push: bool = False) -> tuple:
    """`(block | None, notes)` — the whole `--integration` leg.

    Refuses any lane but `local-dev` with a pointer rather than a caught error,
    exactly as `fetch_evidence` refuses a session with no `gh`: real git
    worktrees under `$PYAUTO_WT_ROOT` are a laptop thing, and a cloud session
    that tried would fail halfway rather than up front. `push=True` refuses the
    same lanes for a second reason, and says that one instead: a remote
    session's credential cannot write a ref at all.
    """
    notes: list[str] = []
    if lane != "local-dev":
        return None, [NOT_LOCAL_PUSH if push else NOT_LOCAL]
    jobs = plan_jobs(members, order, notes)
    if not jobs:
        notes.append("batch collect --integration: no member PR has a "
                     "mergeable head branch in a local checkout — nothing to "
                     "integrate")
        return None, notes
    root = ensure_root(slot, [j["dir"] for j in jobs], notes)
    if root is None:
        return None, notes
    repos = [integrate_repo(j, root / j["dir"], slot, notes) for j in jobs]
    if push:
        for j, r in zip(jobs, repos):
            push_repo(r, root / j["dir"], slot, notes)
    block = {
        "slot": slot, "root": str(root),
        "activate": str(root / "activate.sh"),
        "branch": branch_name(slot),
        "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        # `sweep_after` is filled by the conductor: it is a fact about the
        # RECORD (`review-at:` plus a week, or the human's own date), and this
        # module never reads a record.
        "pushed": bool(push), "sweep_after": "",
        "repos": repos, "notes": list(notes),
    }
    return block, notes

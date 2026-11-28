"""tests/test_worktree_conflict_guard.py — the active.md claim parser.

`worktree_check_conflict` is the start_dev step-6 guard that decides whether a
new task registers in `active.md` (can start) or `planned.md` (blocked). It
reads `worktree_list_claimed`, whose awk was written for the schema the
start_library/start_workspace references still document:

    - repos:
      - RepoA: feature/foo

Every writer drifted to the paren form instead:

    - repos:
      - RepoB (feature/foo)

which the `": "` split swallowed whole, so `repo` never equalled the requested
repo name and the guard exited 0 for every task. The parser now accepts both
forms; these tests pin that, plus the field-order independence of `worktree:`.

Drives the real bash functions against a temp PYAUTO_MAIN fixture, on the
idiom of test_worktree_claim_guard.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import hermetic_worktree_env, source_worktree

# Fixture repo names are deliberately synthetic (RepoA…RepoG): the awk in
# worktree.sh does plain string compares and validates against no repo list,
# so a real name here would be an instance fact in organ code — the tenant
# firewall's concern (PyAutoMind/scripts/repos_sync.py) — for no test value.
# Keep them synthetic.

PAREN = """# Active Tasks

## paren-task
- issue: http://x
- worktree: ~/wt/paren-task
- repos:
  - RepoB (feature/paren-task)
"""

COLON = """# Active Tasks

## colon-task
- issue: http://y
- worktree: ~/wt/colon-task
- repos:
  - RepoA: feature/colon-task
"""

# `repos:` before `worktree:` — both orderings occur in the real ledger.
REPOS_FIRST = """# Active Tasks

## rbw-task
- repos:
  - RepoC (feature/rbw-task)
- worktree: ~/wt/rbw-task
"""

# Two tasks claiming the same repo: the reproducer from the bug prompt.
TWO_CLAIMS = """# Active Tasks

## first-task
- worktree: ~/wt/first-task
- repos:
  - RepoB (feature/first-task)

## second-task
- worktree: ~/wt/second-task
- repos:
  - RepoB (feature/second-task)
"""

# Both shapes carry trailing notes in the real ledger, and some claims name no
# branch at all. Sampled from active.md history: 258 claim lines, 162 colon-form,
# 139 paren-form, plus bare names like `  - RepoG`.
ANNOTATED = """# Active Tasks

## annotated-task
- worktree: ~/wt/annotated-task
- repos:
  - RepoF: feature/howto-smoke (base 65e8fbd == origin/main)
  - RepoG
"""

# A task that claims nothing — the `repos-none-claimed:` shape live entries use.
NO_CLAIMS = """# Active Tasks

## release-drive
- issue: (no issue)
- repos-none-claimed: this entry claims NO repos — deliberately on one line.
"""


def _run(tmp_path: Path, active_body: str | None, snippet: str):
    """Source worktree.sh against a fixture PYAUTO_MAIN and run `snippet`."""
    main = tmp_path / "main"
    if active_body is None:
        main.mkdir()
    else:
        (main / "PyAutoMind").mkdir(parents=True)
        (main / "PyAutoMind" / "active.md").write_text(active_body)
    return source_worktree(snippet, hermetic_worktree_env(tmp_path))


def _claims(tmp_path: Path, active_body: str) -> list[list[str]]:
    proc = _run(tmp_path, active_body, "worktree_list_claimed")
    assert proc.returncode == 0, proc.stderr
    return [line.split("\t") for line in proc.stdout.splitlines() if line]


@pytest.mark.parametrize("body,repo,claimant", [
    # The regression: the paren form is what every writer emits.
    pytest.param(PAREN, "RepoB", "paren-task", id="paren-form"),
    # Back-compat: the documented colon form must keep working.
    pytest.param(COLON, "RepoA", "colon-task", id="colon-form"),
    # `  - RepoG` with no branch is a real shape; it must still conflict.
    pytest.param(ANNOTATED, "RepoG", "annotated-task", id="claim-without-a-branch"),
])
def test_claim_conflicts(tmp_path, body, repo, claimant):
    proc = _run(tmp_path, body, f"worktree_check_conflict new-task {repo}")
    assert proc.returncode == 1, "the claim did not register as a conflict"
    assert claimant in proc.stderr


@pytest.mark.parametrize("body,expected", [
    pytest.param(PAREN, ["RepoB", "feature/paren-task", "~/wt/paren-task"], id="paren-form"),
    pytest.param(COLON, ["RepoA", "feature/colon-task", "~/wt/colon-task"], id="colon-form"),
])
def test_claimed_repo_is_bare(tmp_path, body, expected):
    assert _claims(tmp_path, body)[0][1:] == expected


# --- field-order independence -------------------------------------------------

def test_worktree_captured_when_repos_precede_it(tmp_path):
    # The awk set `wt` on sight, so a `repos:` block above `worktree:` emitted
    # "-" and repo_cleanup lost the worktree path for that claim.
    task, repo, branch, wt = _claims(tmp_path, REPOS_FIRST)[0]
    assert repo == "RepoC"
    assert wt == "~/wt/rbw-task", "worktree: must be captured regardless of field order"


def test_worktree_does_not_leak_between_tasks(tmp_path):
    body = REPOS_FIRST + "\n## later-task\n- repos:\n  - RepoD (feature/later)\n"
    rows = {r[0]: r for r in _claims(tmp_path, body)}
    assert rows["later-task"][3] == "-", "a task with no worktree: must not inherit one"


# --- the guard's own contract -------------------------------------------------

@pytest.mark.parametrize("task,repo", [
    pytest.param("paren-task", "RepoB", id="task-does-not-conflict-with-itself"),
    pytest.param("new-task", "RepoE", id="unclaimed-repo-does-not-conflict"),
])
def test_no_conflict(tmp_path, task, repo):
    proc = _run(tmp_path, PAREN, f"worktree_check_conflict {task} {repo}")
    assert proc.returncode == 0, proc.stderr


def test_conflict_names_every_claiming_task(tmp_path):
    proc = _run(tmp_path, TWO_CLAIMS, "worktree_check_conflict new-task RepoB")
    assert proc.returncode == 1
    assert "first-task" in proc.stderr
    assert "second-task" in proc.stderr


def test_trailing_note_does_not_corrupt_repo(tmp_path):
    # `  - RepoF: feature/howto-smoke (base 65e8fbd == origin/main)` — the
    # repo name is what the guard compares, so the note must not reach it.
    rows = {r[1]: r for r in _claims(tmp_path, ANNOTATED)}
    assert set(rows) == {"RepoF", "RepoG"}
    assert rows["RepoF"][2].startswith("feature/howto-smoke")


def test_entry_claiming_no_repos_yields_no_claims(tmp_path):
    assert _claims(tmp_path, NO_CLAIMS) == []


def test_missing_active_md_reports_failure_rather_than_no_claims(tmp_path):
    """A missing registry is NOT the same as "nothing is claimed".

    This test previously asserted the opposite — `returncode == 0` with empty
    output — and that pinned behaviour turned out to BE the defect (#225).
    `worktree_check_conflict` consumes this function, so returning 0 meant a
    session whose roots are not under `$PYAUTO_MAIN` got "no conflict" from a
    guard that had read nothing. Empty output must never be mistaken for a
    clean registry, so the listing now signals the failure in its exit code.
    """
    proc = _run(tmp_path, None, "worktree_list_claimed")
    assert proc.returncode != 0
    assert proc.stdout == ""       # still emits no bogus rows


def test_conflict_guard_fails_closed_when_the_registry_is_missing(tmp_path):
    """The defect, at the level the skills actually call.

    Documented in `start_dev` step 6 and `start_library` step 1, and its answer
    decides whether a task may start — so "I could not check" has to stop the
    caller, not wave it through.
    """
    proc = _run(tmp_path, None, "worktree_check_conflict some-task RepoA")
    assert proc.returncode != 0
    assert "CANNOT VERIFY" in proc.stderr
    assert "PYAUTO_MAIN" in proc.stderr      # names what to set


def test_conflict_guard_can_be_forced_past_a_missing_registry(tmp_path):
    """The escape hatch is explicit and loud — never the default."""
    proc = _run(tmp_path, None,
                "worktree_check_conflict --allow-missing-registry t RepoA")
    assert proc.returncode == 0
    assert "UNGUARDED" in proc.stderr


# PyAutoBrain#742: a shift worker that parked on a question before its first
# edit left a `repos:` entry with no branch and no `worktree:` line. It held
# its repo for nothing and starved every draft on it.
PARKED = """# Active Tasks

## parked-task
- status: awaiting-input
- question: does the stated bug reproduce?
- repos:
  - RepoH: (no branch; parked before implementation — stated bug did not reproduce)
"""

# The same park in the paren schema, and a bare entry: neither claims.
PARKED_PAREN = """# Active Tasks

## parked-paren-task
- status: awaiting-input
- repos:
  - RepoH (no branch; parked before implementation)
  - RepoI
"""

# Parked AFTER its first edit: a real branch and worktree still hold the repo.
PARKED_WITH_BRANCH = """# Active Tasks

## parked-live-task
- status: awaiting-input
- worktree: ~/wt/parked-live-task
- repos:
  - RepoH (feature/parked-live-task)
"""

# A `(no branch …)` entry is not a claim even beside a worktree.
NO_BRANCH_WITH_WORKTREE = """# Active Tasks

## mixed-task
- worktree: ~/wt/mixed-task
- repos:
  - RepoH: (no branch yet)
  - RepoJ (feature/mixed-task)
"""


@pytest.mark.parametrize("body", [
    pytest.param(PARKED, id="parked-colon-no-branch"),
    pytest.param(PARKED_PAREN, id="parked-paren-no-branch"),
])
def test_parked_branchless_entry_is_not_a_claim(tmp_path, body):
    assert [c for c in _claims(tmp_path, body) if c[1] in ("RepoH", "RepoI")] == []
    proc = _run(tmp_path / "guard", body, "worktree_check_conflict new-task RepoH")
    assert proc.returncode == 0, proc.stderr


def test_parked_entry_with_a_real_branch_still_conflicts(tmp_path):
    proc = _run(tmp_path, PARKED_WITH_BRANCH, "worktree_check_conflict new-task RepoH")
    assert proc.returncode == 1
    assert "parked-live-task" in proc.stderr


def test_no_branch_entry_beside_a_worktree_is_not_a_claim(tmp_path):
    claims = _claims(tmp_path, NO_BRANCH_WITH_WORKTREE)
    assert [c[1] for c in claims] == ["RepoJ"]
    assert _run(tmp_path / "guard", NO_BRANCH_WITH_WORKTREE,
                "worktree_check_conflict new-task RepoH").returncode == 0

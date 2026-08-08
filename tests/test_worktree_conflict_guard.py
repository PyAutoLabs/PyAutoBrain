"""tests/test_worktree_conflict_guard.py — the active.md claim parser.

`worktree_check_conflict` is the start_dev step-6 guard that decides whether a
new task registers in `active.md` (can start) or `planned.md` (blocked). It
reads `worktree_list_claimed`, whose awk was written for the schema the
start_library/start_workspace references still document:

    - repos:
      - PyAutoFit: feature/foo

Every writer drifted to the paren form instead:

    - repos:
      - autolens_workspace (feature/foo)

which the `": "` split swallowed whole, so `repo` never equalled the requested
repo name and the guard exited 0 for every task. The parser now accepts both
forms; these tests pin that, plus the field-order independence of `worktree:`.

Drives the real bash functions against a temp PYAUTO_MAIN fixture, on the
idiom of test_worktree_claim_guard.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

WORKTREE_SH = Path(__file__).resolve().parents[1] / "bin" / "worktree.sh"

PAREN = """# Active Tasks

## paren-task
- issue: http://x
- worktree: ~/wt/paren-task
- repos:
  - autolens_workspace (feature/paren-task)
"""

COLON = """# Active Tasks

## colon-task
- issue: http://y
- worktree: ~/wt/colon-task
- repos:
  - PyAutoFit: feature/colon-task
"""

# `repos:` before `worktree:` — both orderings occur in the real ledger.
REPOS_FIRST = """# Active Tasks

## rbw-task
- repos:
  - PyAutoArray (feature/rbw-task)
- worktree: ~/wt/rbw-task
"""

# Two tasks claiming the same repo: the reproducer from the bug prompt.
TWO_CLAIMS = """# Active Tasks

## first-task
- worktree: ~/wt/first-task
- repos:
  - autolens_workspace (feature/first-task)

## second-task
- worktree: ~/wt/second-task
- repos:
  - autolens_workspace (feature/second-task)
"""

# Both shapes carry trailing notes in the real ledger, and some claims name no
# branch at all. Sampled from active.md history: 258 claim lines, 162 colon-form,
# 139 paren-form, plus bare names like `  - PyAutoReduce`.
ANNOTATED = """# Active Tasks

## annotated-task
- worktree: ~/wt/annotated-task
- repos:
  - HowToFit: feature/howto-smoke (base 65e8fbd == origin/main)
  - PyAutoReduce
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
    return subprocess.run(
        ["bash", "-c", f'source "{WORKTREE_SH}"; {snippet}'],
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYAUTO_MAIN": str(main),
            "PYAUTO_WT_ROOT": str(tmp_path / "wt"),
        },
        capture_output=True,
        text=True,
    )


def _claims(tmp_path: Path, active_body: str) -> list[list[str]]:
    proc = _run(tmp_path, active_body, "worktree_list_claimed")
    assert proc.returncode == 0, proc.stderr
    return [line.split("\t") for line in proc.stdout.splitlines() if line]


# --- the regression: the paren form is what every writer emits ----------------

def test_paren_form_claim_conflicts(tmp_path):
    proc = _run(tmp_path, PAREN, "worktree_check_conflict new-task autolens_workspace")
    assert proc.returncode == 1, "paren-form claim did not register as a conflict"
    assert "paren-task" in proc.stderr


def test_paren_form_repo_is_bare(tmp_path):
    task, repo, branch, wt = _claims(tmp_path, PAREN)[0]
    assert repo == "autolens_workspace"
    assert branch == "feature/paren-task"
    assert wt == "~/wt/paren-task"


# --- back-compat: the documented colon form must keep working -----------------

def test_colon_form_claim_conflicts(tmp_path):
    proc = _run(tmp_path, COLON, "worktree_check_conflict new-task PyAutoFit")
    assert proc.returncode == 1
    assert "colon-task" in proc.stderr


def test_colon_form_repo_is_bare(tmp_path):
    task, repo, branch, wt = _claims(tmp_path, COLON)[0]
    assert repo == "PyAutoFit"
    assert branch == "feature/colon-task"


# --- field-order independence -------------------------------------------------

def test_worktree_captured_when_repos_precede_it(tmp_path):
    # The awk set `wt` on sight, so a `repos:` block above `worktree:` emitted
    # "-" and repo_cleanup lost the worktree path for that claim.
    task, repo, branch, wt = _claims(tmp_path, REPOS_FIRST)[0]
    assert repo == "PyAutoArray"
    assert wt == "~/wt/rbw-task", "worktree: must be captured regardless of field order"


def test_worktree_does_not_leak_between_tasks(tmp_path):
    body = REPOS_FIRST + "\n## later-task\n- repos:\n  - PyAutoLens (feature/later)\n"
    rows = {r[0]: r for r in _claims(tmp_path, body)}
    assert rows["later-task"][3] == "-", "a task with no worktree: must not inherit one"


# --- the guard's own contract -------------------------------------------------

def test_task_does_not_conflict_with_itself(tmp_path):
    proc = _run(tmp_path, PAREN, "worktree_check_conflict paren-task autolens_workspace")
    assert proc.returncode == 0, proc.stderr


def test_unclaimed_repo_does_not_conflict(tmp_path):
    proc = _run(tmp_path, PAREN, "worktree_check_conflict new-task PyAutoGalaxy")
    assert proc.returncode == 0, proc.stderr


def test_conflict_names_every_claiming_task(tmp_path):
    proc = _run(tmp_path, TWO_CLAIMS, "worktree_check_conflict new-task autolens_workspace")
    assert proc.returncode == 1
    assert "first-task" in proc.stderr
    assert "second-task" in proc.stderr


def test_trailing_note_does_not_corrupt_repo(tmp_path):
    # `  - HowToFit: feature/howto-smoke (base 65e8fbd == origin/main)` — the
    # repo name is what the guard compares, so the note must not reach it.
    rows = {r[1]: r for r in _claims(tmp_path, ANNOTATED)}
    assert set(rows) == {"HowToFit", "PyAutoReduce"}
    assert rows["HowToFit"][2].startswith("feature/howto-smoke")


def test_claim_without_a_branch_still_claims(tmp_path):
    # `  - PyAutoReduce` with no branch is a real shape; it must still conflict.
    proc = _run(tmp_path, ANNOTATED, "worktree_check_conflict new-task PyAutoReduce")
    assert proc.returncode == 1
    assert "annotated-task" in proc.stderr


def test_entry_claiming_no_repos_yields_no_claims(tmp_path):
    assert _claims(tmp_path, NO_CLAIMS) == []


def test_missing_active_md_yields_no_claims(tmp_path):
    proc = _run(tmp_path, None, "worktree_list_claimed")
    assert proc.returncode == 0
    assert proc.stdout == ""

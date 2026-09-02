"""tests/test_branch_sweep.py — what the sweep REFUSES to delete.

branch_sweep.sh is the one PyAuto script whose job is irreversible from the
branch's point of view, and it runs unattended on Actions where nobody sees the
dashboard before it acts. Its value is therefore not the deletions — those are
one `git push --delete` — but the four gates that keep a branch out of the
delete set. Each gate gets a known-answer repo here, in the spirit of
test_branch_contribution.py: a gate that silently stopped working would look
exactly like a clean sweep.

The gates, and what breaking each one would cost:

  main / default branch     the repo
  archive/condemned/*       PyAutoGut's recovery path — these refs ARE the
                            backup for condemned work, so voiding one early
                            destroys the only copy
  open PR heads             someone's in-flight review
  unproven CONTRIBUTES      unmerged work, gone
  integration/*             a batch review branch whose slot is still open —
                            these can never be proven contained (a merge
                            preview is unmergeable by construction), so a date
                            on the batch record is the ONLY thing standing
                            between one and deletion

The integration gate is the inverse of the others: those keep a branch the
containment proof would clear, this one clears a branch the containment proof
never could. That makes its failure mode the loud kind — a missing records dir
must read as "keep", never as "no date, therefore expired".

`gh` is stubbed: the script refuses to run without it (it cannot rule out open
PRs blind), and these tests pin that refusal too.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "bin" / "branch_sweep.sh"

# Dates relative to the day the test runs, never literals: a fixture pinned to
# 2026-09-03 stops testing "expired" the moment the calendar passes it, and
# would then pass for the wrong reason forever.
_TODAY = dt.date.today()
EXPIRED = (_TODAY - dt.timedelta(days=30)).isoformat()
LIVE = (_TODAY + dt.timedelta(days=30)).isoformat()
TODAY = _TODAY.isoformat()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _commit(repo: Path, name: str, body: str, message: str) -> None:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", message)


@pytest.fixture
def world(tmp_path: Path):
    """An origin with one branch per verdict, and a clone that sweeps it."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _git(origin, "config", "receive.denyDeleteCurrent", "ignore")
    _commit(origin, "f", "base", "base")

    # merged: folded into main, so main contains its tip
    _git(origin, "checkout", "-q", "-b", "merged")
    _commit(origin, "m", "m", "merged work")
    _git(origin, "checkout", "-q", "main")
    _git(origin, "merge", "-q", "--no-ff", "merged", "-m", "Merge merged")

    # unmerged: unique content main has never seen
    _git(origin, "checkout", "-q", "-b", "unmerged", "main")
    _commit(origin, "u", "u", "unmerged work")

    # an open PR's head, and a Gut transit ref — both fully merged, so ONLY
    # their protection can keep them out of the delete set
    for name in ("open-pr-head", "archive/condemned/something"):
        _git(origin, "checkout", "-q", "-b", name, "main")
    _git(origin, "checkout", "-q", "main")

    # Three batch review branches, each carrying unique content main has never
    # seen — exactly what a merge preview looks like. Without the integration
    # arm all three read as CONTRIBUTES/unmerged and are kept forever; with it,
    # only the date on the record decides.
    records = tmp_path / "records"
    records.mkdir()
    for slot, after in ((EXPIRED, EXPIRED), (LIVE, LIVE), (TODAY, TODAY)):
        branch = f"integration/{slot}-pm"
        _git(origin, "checkout", "-q", "-b", branch, "main")
        _commit(origin, f"i-{slot}", slot, f"integration preview {slot}")
        _git(origin, "checkout", "-q", "main")
        # `n` is the --name this fixture sweeps under, which is the name the
        # record writes into `integration-remote:`.
        (records / f"{slot}-pm.md").write_text(
            f"# Batch {slot} pm\n"
            f"- dispatched: {slot}T17:40Z\n"
            f"- integration-remote: other-repo:integration/{slot}-pm, "
            f"n:integration/{slot}-pm\n"
            f"- sweep-after: {after}\n"
        )

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(clone)], check=True
    )
    _git(clone, "config", "user.email", "t@t")
    _git(clone, "config", "user.name", "t")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "auth" ]]; then exit 0; fi\n'
        'if [[ "$1" == "api" ]]; then exit 0; fi\n'
        'echo "open-pr-head"\n'
        "exit 0\n"
    )
    (bin_dir / "gh").chmod(0o755)
    return clone, origin, bin_dir


def _records(clone: Path) -> Path:
    """The `world` fixture's records dir. Derived rather than returned, so the
    three-value unpacking every existing test does keeps working."""
    return clone.parent / "records"


def _gh_free_path(tmp_path: Path) -> str:
    """A PATH with everything the script needs except `gh`.

    Emptying PATH would remove bash too and prove nothing, so link in the tools
    the script actually calls and leave `gh` out.
    """
    lean = tmp_path / "nogh"
    lean.mkdir(exist_ok=True)
    for tool in ("bash", "git", "sed", "awk", "grep", "sort", "head", "cut", "tr",
                 "dirname", "basename", "cat", "wc", "env", "uniq"):
        found = shutil.which(tool)
        if found and not (lean / tool).exists():
            (lean / tool).symlink_to(found)
    return str(lean)


def _sweep(clone: Path, bin_dir: Path | None, mode: str = "audit",
           records: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    else:
        env["PATH"] = _gh_free_path(clone.parent)
    cmd = ["bash", str(TOOL), "--repo", str(clone), "--owner", "o", "--name", "n",
           "--mode", mode]
    if records is not None:
        cmd += ["--records", str(records)]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def test_audit_classifies_every_branch(world):
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir).stdout
    assert "merged\tMERGED" in out
    assert "unmerged\tunmerged" in out
    assert "open-pr-head\topen-pr" in out
    assert "archive/condemned/something\tgut-transit-ref" in out


def test_symbolic_head_is_not_reported_as_a_branch(world):
    """refs/remotes/origin/HEAD must not surface as a branch called "origin".

    Git abbreviates that ref to bare `origin`, which slips past an `origin/`
    strip and a `!= HEAD` guard and then lands in KEEP with verdict UNKNOWN —
    a symbolic ref rendered as unmerged work. It was never deletable, so the
    cost is a wrong count and a reader misled about what is outstanding.
    """
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir).stdout
    assert "origin\tUNKNOWN" not in out
    assert "\n  origin\t" not in out
    # the real answer for this fixture, with nothing invented alongside it
    assert "1 unmerged" in out


def test_audit_never_deletes(world):
    clone, origin, bin_dir = world
    before = _git(origin, "for-each-ref", "--format=%(refname)", "refs/heads")
    assert _sweep(clone, bin_dir, mode="audit").returncode == 0
    assert _git(origin, "for-each-ref", "--format=%(refname)", "refs/heads") == before


def test_delete_removes_only_the_contained_branch(world):
    clone, origin, bin_dir = world
    assert _sweep(clone, bin_dir, mode="delete").returncode == 0
    remaining = _git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remaining = set(remaining.split())
    assert "merged" not in remaining, "a contained branch should have been swept"
    # every gate held
    assert {"main", "unmerged", "open-pr-head", "archive/condemned/something"} <= remaining


def test_a_legacy_trunk_is_protected_even_when_fully_merged(tmp_path):
    """`master` after a main<-master migration is not an ordinary branch.

    It is protected on NAME, not on containment: once folded into main it looks
    exactly like spent work, and deleting it breaks every stale clone, bookmark
    and doc still pointing at it. The first org-wide audit found a repo whose
    `master` survived only because it happened to carry unique content — luck,
    not a gate.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "f", "base", "base")
    # a legacy trunk fully contained in main — indistinguishable from spent work
    _git(origin, "branch", "master")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text('#!/usr/bin/env bash\nexit 0\n')
    (bin_dir / "gh").chmod(0o755)

    assert _sweep(clone, bin_dir, mode="delete").returncode == 0
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    assert "master" in remaining, "a legacy trunk must never be swept"


def _readonly_origin(tmp_path: Path):
    """A world whose origin refuses ref deletion, like a read-only credential."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _commit(origin, "f", "base", "base")
    for i in range(5):
        _git(origin, "branch", f"spent{i}")           # all contained in main
    # the closest local stand-in for "this credential may not delete refs"
    _git(origin, "config", "receive.denyDeletes", "true")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text('#!/usr/bin/env bash\nexit 0\n')
    (bin_dir / "gh").chmod(0o755)
    return clone, origin, bin_dir


def test_a_failed_delete_reports_why(tmp_path):
    """`FAILED <branch>` with no reason is barely better than silence.

    The first org-wide delete run failed 99 times and recorded nothing but the
    word FAILED, because the push was redirected to /dev/null. The error text
    is the only thing a failure carries; keep it.
    """
    clone, _, bin_dir = _readonly_origin(tmp_path)
    out = _sweep(clone, bin_dir, mode="delete").stdout
    assert "FAILED" in out
    assert "no error text returned" not in out, "the push error was swallowed"
    assert "denyDeletes" in out or "denied" in out.lower() or "error" in out.lower()


def test_repeated_delete_failures_stop_early(tmp_path):
    """Delete permission belongs to the credential, not the branch.

    Once a few in a row fail the answer is known for all of them, so grinding
    through the rest only buries the reason.
    """
    clone, origin, bin_dir = _readonly_origin(tmp_path)
    proc = _sweep(clone, bin_dir, mode="delete")
    assert proc.returncode == 2, "a run where nothing could be deleted must not report success"
    assert "Stopping:" in proc.stdout
    # stopped after the streak rather than attempting all five
    assert proc.stdout.count("FAILED") == 3
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())
    assert {f"spent{i}" for i in range(5)} <= remaining, "nothing should have been deleted"


def test_refuses_to_run_without_gh(world):
    """Blind to open PRs means blind to in-flight work: refuse, do not guess.

    The refusal must also say what to do instead. A remote session has no `gh`
    at all, so "gh not found" alone reads as a broken machine rather than the
    wrong surface — the message names the alternative and where it is mapped.
    """
    clone, _, _ = world
    proc = _sweep(clone, None)
    assert proc.returncode == 1
    assert "refusing to sweep" in proc.stderr
    assert "gh" in proc.stderr
    assert "GITHUB_ACCESS.md" in proc.stderr


def test_rejects_unknown_mode(world):
    clone, _, bin_dir = world
    proc = _sweep(clone, bin_dir, mode="purge")
    assert proc.returncode == 1
    assert "must be 'audit' or 'delete'" in proc.stderr


# --- integration/* : cleared by date, or not at all --------------------------


def test_an_expired_integration_branch_is_sweepable(world):
    """The only gate here that ever RELEASES a branch, so it has to be exact.

    An integration ref is a merge preview: cut from the base with every
    member's head merged in, it is unmergeable by construction and no
    containment proof will ever clear it. Left to the other gates it would sit
    on origin forever. Its licence is the `sweep-after:` on the batch record
    that published it, and once that date is behind us the branch is spent.
    """
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir, records=_records(clone)).stdout
    assert f"integration/{EXPIRED}-pm\tintegration-expired-{EXPIRED}" in out
    # released into the delete set, not merely reported somewhere
    assert out.index("CONTAINED IN") < out.index(f"integration/{EXPIRED}-pm\tinteg")


def test_an_unexpired_integration_branch_is_protected(world):
    """Two branches the sweep must not touch: one whose date is still ahead,
    and one whose date is TODAY.

    The same-day case is the one worth pinning. `sweep-after: <today>` is the
    day the human sits down to read the preview, and a sweep that fires that
    morning deletes the branch out from under the review it exists for. The
    comparison is strictly greater-than-today, never greater-or-equal.
    """
    clone, _, bin_dir = world
    out = _sweep(clone, bin_dir, records=_records(clone)).stdout
    protected = out.split("PROTECTED (never swept)")[1].split("\n\n")[0]
    assert f"integration/{LIVE}-pm\tintegration-until-{LIVE}" in protected
    assert f"integration/{TODAY}-pm\tintegration-until-{TODAY}" in protected


def test_an_integration_branch_with_no_record_is_protected(world):
    """No records dir means no dates, and no dates must mean KEEP.

    The whole mechanism hangs off a checkout of PyAutoMind's `batches/` that a
    workflow may simply fail to make. If a missing Mind read as "no date,
    therefore expired", one bad checkout step would delete every open slot's
    review branch across the org — the precise failure this direction exists to
    make impossible.
    """
    clone, origin, bin_dir = world
    out = _sweep(clone, bin_dir).stdout
    protected = out.split("PROTECTED (never swept)")[1].split("\n\n")[0]
    for slot in (EXPIRED, LIVE, TODAY):
        assert f"integration/{slot}-pm\tintegration-no-sweep-after" in protected

    assert _sweep(clone, bin_dir, mode="delete").returncode == 0
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)",
                         "refs/heads").split())
    assert {f"integration/{slot}-pm" for slot in (EXPIRED, LIVE, TODAY)} <= remaining


def test_delete_removes_only_the_expired_integration_branch(world):
    clone, origin, bin_dir = world
    assert _sweep(clone, bin_dir, mode="delete",
                  records=_records(clone)).returncode == 0
    remaining = set(_git(origin, "for-each-ref", "--format=%(refname:short)",
                         "refs/heads").split())
    assert f"integration/{EXPIRED}-pm" not in remaining
    assert {f"integration/{LIVE}-pm", f"integration/{TODAY}-pm"} <= remaining
    # the other gates are unmoved by the new arm
    assert {"main", "unmerged", "open-pr-head",
            "archive/condemned/something"} <= remaining


def test_a_record_naming_another_repo_does_not_answer_for_this_one(world):
    """`integration-remote:` is `<Repo>:<branch>`, comma-separated, and the repo
    half is load-bearing: one slot publishes the same branch NAME into every
    affected repo, so matching on the branch alone would let one repo's record
    expire another repo's ref.
    """
    clone, _, bin_dir = world
    records = _records(clone)
    for f in records.glob("*.md"):
        f.write_text(f.read_text().replace(f"n:integration/", "nn:integration/"))
    out = _sweep(clone, bin_dir, records=records).stdout
    assert "integration-expired" not in out
    for slot in (EXPIRED, LIVE, TODAY):
        assert f"integration/{slot}-pm\tintegration-no-sweep-after" in out

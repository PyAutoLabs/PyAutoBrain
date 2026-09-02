"""tests/test_batch_integration.py — the batch conductor's integration branches.

The Witness the task registers: *a batch-conductor test builds a temp repo with
two member branches, runs `collect --integration`, and asserts
`integration/<slot>` tree == merge of both heads plus a packet line `clean` /
`conflicted: <path>` per repo; evidence JSON carries `headRefName` for every
member PR.*

This module drives the real `bin/worktree.sh` against throwaway repos rather
than a re-implementation of it: the value of `worktree_create` is the root
layout (activate.sh's PYTHONPATH, the per-task caches, the symlink of every
other top-level entry), and a second definition of "a PyAuto worktree root"
would drift from the first.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
WORKTREE_SH = BRAIN / "bin" / "worktree.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _repo(origins: Path, main: Path, name: str) -> Path:
    """A clone of a bare origin with one commit on `main`, as `worktree_create`
    expects: it branches from `origin/<default>`, so `origin/main` must exist."""
    origin = origins / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    repo = main / name
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                   capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("base\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _create(tmp_path: Path, task: str, branch: str | None) -> tuple[Path, Path]:
    """Run the real `worktree_create` for one repo; return (root, worktree)."""
    origins = tmp_path / "origins"
    main = tmp_path / "main"
    origins.mkdir(parents=True, exist_ok=True)
    main.mkdir(parents=True, exist_ok=True)
    _repo(origins, main, "MyRepo")
    (main / "some_workspace").mkdir(exist_ok=True)  # symlinked, not a worktree

    env = {k: v for k, v in os.environ.items() if k != "PYAUTO_WT_BRANCH"}
    env.update({"HOME": str(tmp_path), "PYAUTO_ROOT": str(main),
                "PYAUTO_MAIN": str(main), "PYAUTO_WT_ROOT": str(tmp_path / "wt")})
    if branch is not None:
        env["PYAUTO_WT_BRANCH"] = branch
    proc = subprocess.run(
        ["bash", "-c", f'set -e; . "{WORKTREE_SH}"; worktree_create "$@"',
         "_", task, "MyRepo"],
        env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    root = tmp_path / "wt" / task
    return root, root / "MyRepo"


def _head(worktree: Path) -> str:
    got = subprocess.run(["git", "-C", str(worktree), "rev-parse",
                          "--abbrev-ref", "HEAD"],
                         check=True, capture_output=True, text=True)
    return got.stdout.strip()


def test_the_branch_name_override_is_honoured(tmp_path):
    """`collect --integration` builds a throwaway review root, and a root that
    calls itself `feature/<task>` masquerades as feature work — every branch
    sweep and every contribution check then has to guess. `PYAUTO_WT_BRANCH` is
    the one thing worktree.sh could not otherwise say."""
    _root, worktree = _create(tmp_path, "integration-2026-09-03-pm",
                              branch="integration/x")
    assert _head(worktree) == "integration/x"


def test_without_the_override_the_branch_is_still_feature_of_the_task(tmp_path):
    """The override is additive: unset, worktree.sh names branches exactly as
    every existing task worktree on disk is named."""
    _root, worktree = _create(tmp_path, "task-y", branch=None)
    assert _head(worktree) == "feature/task-y"


# --------------------------------------------------------- the merge engine --
import importlib.util  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

#: Loaded standalone, by file location — no `_batch`, no sizing faculty, no
#: `sys.path` surgery. That it imports at all is the first assertion: the merge
#: engine is stdlib-only and knows nothing about the conductor that calls it.
_INTEG_SPEC = importlib.util.spec_from_file_location(
    "_batch_integration_leg_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_integration.py")
INTEG = importlib.util.module_from_spec(_INTEG_SPEC)
_INTEG_SPEC.loader.exec_module(INTEG)

SLOT = "2026-09-03-pm"
STAMP = "2026-09-03T08:00Z"


def _out(repo: Path, *args: str) -> str:
    got = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True)
    return got.stdout.strip()


def _seed(origins: Path, main: Path, name: str) -> Path:
    """A repo with `main` and three pushed member heads.

    `feature/alpha` and `feature/beta` both rewrite `a.py`, so each merges
    cleanly onto `origin/main` alone and the SECOND of them collides — the
    merge-order case the whole leg exists to preview. `feature/gamma` touches
    `b.py` only, so it is the clean-alongside case.
    """
    origin = origins / f"{name}.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)],
                   check=True, capture_output=True)
    repo = main / name
    subprocess.run(["git", "clone", str(origin), str(repo)], check=True,
                   capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("base\n")
    (repo / "b.py").write_text("base\n")
    _git(repo, "add", "a.py", "b.py")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "main")
    for branch, path, body in (("feature/alpha", "a.py", "alpha"),
                               ("feature/beta", "a.py", "beta"),
                               ("feature/gamma", "b.py", "gamma")):
        _git(repo, "checkout", "-B", branch, "main")
        (repo / path).write_text(body + "\n")
        _git(repo, "add", path)
        _git(repo, "commit", "-m", branch)
        _git(repo, "push", "-u", "origin", branch)
    _git(repo, "checkout", "main")
    return repo


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A throwaway workspace root: `main/` holds the checkouts, `wt/` is where
    task roots go. Both are declared through the same environment variables the
    laptop uses, so nothing here is a special path this module invented."""
    origins, main, wt = tmp_path / "origins", tmp_path / "main", tmp_path / "wt"
    origins.mkdir()
    main.mkdir()
    (main / "some_workspace").mkdir()   # symlinked into the root, not a worktree
    monkeypatch.setenv("PYAUTO_ROOT", str(main))
    monkeypatch.setenv("PYAUTO_MAIN", str(main))
    monkeypatch.setenv("PYAUTO_WT_ROOT", str(wt))
    monkeypatch.delenv("PYAUTO_WT_BRANCH", raising=False)
    return SimpleNamespace(main=main, wt=wt, root=wt / f"integration-{SLOT}",
                           seed=lambda name: _seed(origins, main, name))


def member(slug: str, branch: str, repo: str = "MyRepo", **over) -> dict:
    """A scored member, cut down to what `plan_jobs` reads."""
    row = {"repo": f"Example/{repo}", "number": 7, "state": "OPEN",
           "merged": False, "head_ref": branch, "head_sha": "",
           "head_repo": f"Example/{repo}"}
    row.update(over)
    return {"slug": slug, "prs": [row]}


def test_two_members_merge_in_dispatch_order_and_the_conflicting_one_is_left_out(ws):
    """**The Witness.** Two members rewrote the same file. Each is green on its
    own; the batch is not. The leg answers "how would these resolve at the
    end?" by merging in DISPATCH order and naming the collision — it never
    resolves it, and it never touches the canonical checkout."""
    ws.seed("MyRepo")
    was = _out(ws.main / "MyRepo", "rev-parse", "HEAD")
    block, _notes = INTEG.run(
        [member("alpha", "feature/alpha"), member("beta", "feature/beta")],
        ["alpha", "beta"], SLOT, lane="local-dev")

    r = block["repos"][0]
    assert r["status"] == "conflicted"
    assert r["merged"] == ["alpha"]
    assert r["conflicts"] == [{"member": "beta", "branch": "feature/beta",
                               "paths": ["a.py"]}]
    assert r["branch"] == f"integration/{SLOT}"

    wt = Path(r["path"])
    assert (wt / "a.py").read_text() == "alpha\n"       # the merge of base+alpha
    assert _head(wt) == f"integration/{SLOT}"
    # The abort really aborted: no half-merge is left for the human to find.
    assert _out(wt, "status", "--porcelain") == ""
    assert subprocess.run(["git", "-C", str(wt), "rev-parse", "--verify",
                           "MERGE_HEAD"], capture_output=True).returncode != 0

    # The canonical checkout is untouched — same branch, same commit.
    assert _out(ws.main / "MyRepo", "rev-parse", "HEAD") == was
    assert _out(ws.main / "MyRepo", "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_a_clean_repo_reports_clean_and_carries_every_member(ws):
    """Two members that never touch the same file both land, and the branch
    carries one merge commit each — the case the human can actually run."""
    ws.seed("MyRepo")
    block, _notes = INTEG.run(
        [member("alpha", "feature/alpha"), member("gamma", "feature/gamma")],
        ["alpha", "gamma"], SLOT, lane="local-dev")
    r = block["repos"][0]
    assert r["status"] == "clean" and r["conflicts"] == []
    assert r["merged"] == ["alpha", "gamma"]
    wt = Path(r["path"])
    assert (wt / "a.py").read_text() == "alpha\n"
    assert (wt / "b.py").read_text() == "gamma\n"
    assert _out(wt, "rev-list", "--count", "--merges",
                "origin/main..HEAD") == "2"


def test_a_re_run_reproduces_the_branch_rather_than_stacking_on_it(ws):
    """The branch is re-cut from `origin/main` every run. The merge result is a
    function of the current base and the current heads, so a second run that
    stacked onto the first would preview a base that no longer exists."""
    ws.seed("MyRepo")
    args = ([member("alpha", "feature/alpha"), member("gamma", "feature/gamma")],
            ["alpha", "gamma"], SLOT)
    first, _n = INTEG.run(*args, lane="local-dev")
    wt = Path(first["repos"][0]["path"])
    tree = _out(wt, "rev-parse", "HEAD^{tree}")
    count = _out(wt, "rev-list", "--count", "origin/main..HEAD")

    second, _n = INTEG.run(*args, lane="local-dev")
    assert second["repos"][0]["status"] == "clean"
    assert _out(wt, "rev-parse", "HEAD^{tree}") == tree
    assert _out(wt, "rev-list", "--count", "origin/main..HEAD") == count


def test_a_dirty_integration_worktree_is_left_alone(ws):
    """The refusal that makes re-cutting the branch safe at all. The one thing
    a re-cut could destroy is a human's uncommitted experiment inside the
    review root — so it is not re-cut, and the report says why."""
    ws.seed("MyRepo")
    first, _n = INTEG.run([member("alpha", "feature/alpha")], ["alpha"], SLOT,
                          lane="local-dev")
    wt = Path(first["repos"][0]["path"])
    (wt / "scratch.py").write_text("the human was mid-experiment\n")

    block, notes = INTEG.run([member("gamma", "feature/gamma")], ["gamma"],
                             SLOT, lane="local-dev")
    r = block["repos"][0]
    assert r["status"] == "skipped"
    assert "uncommitted" in r["note"]
    assert any("uncommitted" in n for n in notes)
    assert (wt / "scratch.py").read_text() == "the human was mid-experiment\n"
    assert (wt / "b.py").read_text() == "base\n"     # gamma was NOT merged in


def test_a_fork_head_a_merged_pr_and_a_missing_head_ref_are_reported_not_merged(ws):
    """Three heads that cannot honestly be merged, three notes, zero merges. A
    fork's head is not on `origin` at all; a merged PR is history; a PR with no
    `head_ref` was scored from evidence gathered before Phase 1 widened the
    field list, and guessing a branch name is how a preview becomes a lie."""
    ws.seed("MyRepo")
    block, notes = INTEG.run(
        [member("forked", "feature/alpha", head_repo="Someone/MyRepo"),
         member("landed", "feature/beta", merged=True),
         member("blind", "")],
        ["forked", "landed", "blind"], SLOT, lane="local-dev")
    assert block is None
    joined = "\n".join(notes)
    assert "is from a fork (Someone/MyRepo)" in joined
    assert "is already merged — not re-merged" in joined
    assert "has no head_ref in the evidence" in joined
    assert not ws.root.exists()


def test_the_worktree_root_carries_activate_sh_and_the_symlinks(ws):
    """The root is built by `bin/worktree.sh`, not re-derived here: its value is
    the layout — the PYTHONPATH, the per-task caches, and the symlink of every
    other top-level entry so relative workspace paths still resolve."""
    ws.seed("MyRepo")
    block, _n = INTEG.run([member("alpha", "feature/alpha")], ["alpha"], SLOT,
                          lane="local-dev")
    root = Path(block["root"])
    assert root == ws.root
    activate = (root / "activate.sh").read_text()
    assert "PYTHONPATH" in activate and "NUMBA_CACHE_DIR" in activate
    assert f'PYAUTO_TASK="integration-{SLOT}"' in activate
    assert block["activate"] == str(root / "activate.sh")
    # A linked worktree's `.git` is a FILE; an untouched entry stays a symlink.
    assert (root / "MyRepo" / ".git").is_file()
    assert (root / "some_workspace").is_symlink()


# ---------------------------------------------------------------- the push --
def _on_origin(wt: Path, ref: str) -> str:
    """The SHA of `refs/heads/<ref>` as it really is on the origin.

    Read with `ls-remote`, never from a remote-tracking ref: the whole claim
    under test is about what is published, and a stale `origin/…` in the local
    checkout is exactly the thing that could fake it."""
    out = _out(wt, "ls-remote", "origin", f"refs/heads/{ref}")
    return out.splitlines()[0].split("\t")[0] if out else ""


def test_push_puts_the_branch_on_origin_equal_to_the_local_one(ws):
    """**Witness claim 1.** `--push` publishes exactly the branch the human just
    previewed: same commit, one real ref, under `integration/` where the sweep
    can find it. Nothing else on the remote is written."""
    ws.seed("MyRepo")
    block, _notes = INTEG.run(
        [member("alpha", "feature/alpha"), member("gamma", "feature/gamma")],
        ["alpha", "gamma"], SLOT, lane="local-dev", push=True)

    assert block["pushed"] is True
    # The conductor fills this: the date lives on the RECORD, and the merge
    # engine never reads one.
    assert block["sweep_after"] == ""
    r = block["repos"][0]
    assert r["status"] == "clean"
    assert r["pushed"] is True
    assert r["remote_branch"] == f"integration/{SLOT}"
    assert r["push_note"] == ""

    wt = Path(r["path"])
    assert _on_origin(wt, f"integration/{SLOT}") == _out(wt, "rev-parse", "HEAD")
    assert _on_origin(wt, f"integration/{SLOT}-2") == ""


def test_a_second_run_after_main_moves_never_moves_the_first_ref(ws):
    """**Witness claim 2.** `origin/main` moved, so the honest refresh re-cuts
    from the new base and the published ref is no longer an ancestor of it. A
    force push would silently destroy what a reviewer may already be reading —
    so the earlier ref is left exactly where it is and the refresh is published
    beside it as `-2`."""
    repo = ws.seed("MyRepo")
    args = ([member("alpha", "feature/alpha")], ["alpha"], SLOT)
    first, _n = INTEG.run(*args, lane="local-dev", push=True)
    wt = Path(first["repos"][0]["path"])
    was = _on_origin(wt, f"integration/{SLOT}")
    assert was

    _git(repo, "checkout", "main")
    (repo / "c.py").write_text("main moved on\n")
    _git(repo, "add", "c.py")
    _git(repo, "commit", "-m", "main moves")
    _git(repo, "push", "origin", "main")

    second, _n = INTEG.run(*args, lane="local-dev", push=True)
    r = second["repos"][0]
    assert _on_origin(wt, f"integration/{SLOT}") == was      # untouched
    assert r["pushed"] is True
    assert r["remote_branch"] == f"integration/{SLOT}-2"
    assert "never force-pushed" in r["push_note"]
    assert (_on_origin(wt, f"integration/{SLOT}-2")
            == _out(wt, "rev-parse", "HEAD"))


def test_an_unchanged_refresh_does_not_mint_a_second_branch(ws):
    """`integrate_repo` re-cuts the branch every run, so the commit SHA differs
    on every refresh even when nothing changed. Comparing commits would make
    every refresh look non-fast-forwardable and pile up `-2 … -20`; the tree
    check asks what the human means — is what is published still this?"""
    ws.seed("MyRepo")
    args = ([member("alpha", "feature/alpha")], ["alpha"], SLOT)
    first, _n = INTEG.run(*args, lane="local-dev", push=True)
    wt = Path(first["repos"][0]["path"])
    was = _on_origin(wt, f"integration/{SLOT}")

    second, _n = INTEG.run(*args, lane="local-dev", push=True)
    r = second["repos"][0]
    assert r["pushed"] is False
    assert r["remote_branch"] == f"integration/{SLOT}"
    assert "already carries this exact tree" in r["push_note"]
    assert _on_origin(wt, f"integration/{SLOT}") == was
    assert _on_origin(wt, f"integration/{SLOT}-2") == ""


def test_a_conflicted_repo_still_publishes_its_partial_branch(ws):
    """A conflict is a finding, not a failure — and the partial branch is the
    runnable thing. It is published, and the member left out of it is named."""
    ws.seed("MyRepo")
    block, _n = INTEG.run(
        [member("alpha", "feature/alpha"), member("beta", "feature/beta")],
        ["alpha", "beta"], SLOT, lane="local-dev", push=True)
    r = block["repos"][0]
    assert r["status"] == "conflicted"
    assert r["merged"] == ["alpha"]
    assert [c["member"] for c in r["conflicts"]] == ["beta"]
    assert r["pushed"] is True
    assert r["remote_branch"] == f"integration/{SLOT}"
    wt = Path(r["path"])
    assert _on_origin(wt, f"integration/{SLOT}") == _out(wt, "rev-parse", "HEAD")


def test_a_failed_push_is_a_note_and_the_merge_verdict_stands(ws, tmp_path):
    """A network failure must not turn a clean integration into a conflicted
    one: the merge verdict is a fact about the merge. The push says so in its
    own field and in the notes, and `status` is untouched."""
    ws.seed("MyRepo")
    block, _n = INTEG.run([member("alpha", "feature/alpha")], ["alpha"], SLOT,
                          lane="local-dev")
    r = block["repos"][0]
    wt = Path(r["path"])
    _git(wt, "remote", "set-url", "origin", str(tmp_path / "not-a-repo.git"))

    notes: list = []
    INTEG.push_repo(r, wt, SLOT, notes)
    assert r["status"] == "clean"
    assert r["merged"] == ["alpha"]
    assert r["pushed"] is False
    assert r["remote_branch"] == ""
    assert "push failed" in r["push_note"]
    assert any("push failed" in n for n in notes)


def test_the_push_leg_carries_no_force_flag_at_all():
    """The property the whole design rests on, asserted against the source: a
    reviewer's ref is never destroyed. The one `-f` in the module names a LOCAL
    branch whose name was just proven absent on origin."""
    src = Path(INTEG.__file__).read_text(encoding="utf-8")
    assert "--force" not in src
    assert "--force-with-lease" not in src
    assert [l.strip() for l in src.splitlines()
            if '"-f"' in l and "branch" not in l] == []


# ------------------------------------------------- the packet and the record --
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_integration_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_integration_under_test"] = _batch
_spec.loader.exec_module(_batch)


def test_the_conductor_loads_the_leg_lazily_by_file_location():
    """`batch plan` and most collects never build a worktree, so the merge
    engine is loaded the way the Cortex conductor is: by file location, cached,
    and never at module import."""
    mod = _batch.load_integration()
    assert mod.__file__ == INTEG.__file__
    assert _batch.load_integration() is mod
    assert mod.branch_name(SLOT) == f"integration/{SLOT}"


def _record(*members, keys="") -> str:
    body = [f"# Batch {SLOT}", "",
            "- dispatched: 2026-09-03T17:40Z",
            "- review-at: 2026-09-04T08:00Z",
            "- lane: any",
            "- review-minutes-planned: 3",
            "- members:"]
    body += list(members or (MEMBER,))
    if keys:
        body.append(keys)
    body += ["- notes: |", "    What actually happened."]
    return "\n".join(body) + "\n"


MEMBER = ("  - alpha: draft/bug/autofit/alpha.md — glance — 3 — "
          "session ended green")

PROMPT = """# Alpha

Type: bug
Target: autofit
Witness: a unit test pins it
"""


def mini_mind(tmp_path, *members, keys="") -> Path:
    mind = tmp_path / "mind"
    (mind / "batches" / "packets").mkdir(parents=True)
    (mind / "batches" / "reviews").mkdir(parents=True)
    (mind / "draft" / "bug" / "autofit").mkdir(parents=True)
    (mind / "batches" / f"{SLOT}.md").write_text(_record(*members, keys=keys),
                                                 encoding="utf-8")
    (mind / "draft" / "bug" / "autofit" / "alpha.md").write_text(
        PROMPT, encoding="utf-8")
    (mind / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    return mind


def block_for(root="/tmp/wt/integration-x", slug="beta") -> dict:
    return {
        "slot": SLOT, "root": root, "activate": f"{root}/activate.sh",
        "branch": f"integration/{SLOT}", "at": STAMP, "notes": [],
        "repos": [
            {"repo": "Example/MyRepo", "dir": "MyRepo", "path": f"{root}/MyRepo",
             "branch": f"integration/{SLOT}", "base": "origin/main",
             "base_sha": "aaa", "head_sha": "bbb", "merged": ["alpha"],
             "conflicts": [], "status": "clean", "note": ""},
            {"repo": "Example/Other", "dir": "Other", "path": f"{root}/Other",
             "branch": f"integration/{SLOT}", "base": "origin/main",
             "base_sha": "ccc", "head_sha": "ddd", "merged": [],
             "conflicts": [{"member": slug, "branch": "feature/beta",
                            "paths": ["a.py"]}],
             "status": "conflicted", "note": ""}]}


def collected(mind, block=None) -> dict:
    d = _batch.collect(mind, SLOT)
    d["stamp"] = STAMP
    if block is not None:
        d["integration"] = block
    return d


def region_of(page: str) -> str:
    begin = page.index("<!-- pyauto:integration:begin -->")
    return page[begin:page.index("<!-- pyauto:integration:end -->")]


def test_the_packet_carries_a_sentinel_bounded_integration_region(tmp_path):
    """The panel is a finding the human READS — no `data-*` hook, no second
    `<script>`, and every value escaped: a slug is a branch name someone typed."""
    mind = mini_mind(tmp_path)
    d = collected(mind, block_for(slug="<script>alert(1)</script>"))
    page, _notes = _batch.packet_html(d)
    assert "<!-- pyauto:integration:begin -->" in page
    assert "<!-- pyauto:integration:end -->" in page
    body = region_of(page)
    assert "clean" in body and "conflicted" in body and "a.py" in body
    assert "source /tmp/wt/integration-x/activate.sh" in body
    assert "&lt;script&gt;alert(1)" in body
    assert page.count("<script>") == 1 and page.count("</script>") == 1


def test_the_panel_says_where_a_workspace_member_has_to_be_run(tmp_path):
    """`activate.sh`'s PYTHONPATH covers the libraries only. A workspace member
    is a real worktree in the root but is not importable from outside it, and a
    human who runs its script from the canonical checkout tests the wrong tree."""
    mind = mini_mind(tmp_path)
    page, _n = _batch.packet_html(collected(mind, block_for()))
    body = region_of(page)
    assert "PYTHONPATH" in body
    assert "/tmp/wt/integration-x/&lt;workspace&gt;" in body


def test_a_refresh_without_an_integration_leaves_the_region_alone(tmp_path):
    """A plain collect must not blank the region the last `--integration`
    filled: that merge preview is still true, and the human is reading it."""
    mind = mini_mind(tmp_path)
    first, _n = _batch.packet_html(collected(mind, block_for()))
    was = region_of(first)
    assert "Example/MyRepo" in was
    second, _n = _batch.packet_html(collected(mind), first)
    assert region_of(second) == was


def test_a_cloud_session_says_run_it_from_the_laptop(tmp_path, capsys):
    """Mirrors the `--fetch` refusal: real worktrees under `$PYAUTO_WT_ROOT` are
    a laptop thing, so a cloud session is pointed at the laptop rather than
    failing halfway through building a root it cannot finish."""
    mind = mini_mind(tmp_path)
    rc = _batch.main(["collect", "--mind", str(mind), "--slot", SLOT,
                      "--integration", "--lane", "web-github"])
    out = capsys.readouterr().out
    assert rc == 1
    assert out.count("run collect from the laptop") == 1
    assert "## alpha — " in out          # the members are still scored


def _recorder(monkeypatch) -> list:
    calls: list = []

    def run(members, order, slot, *, lane):
        calls.append({"order": list(order), "slot": slot, "lane": lane})
        return None, []

    monkeypatch.setattr(_batch, "load_integration",
                        lambda: SimpleNamespace(run=run))
    return calls


def test_the_record_can_ask_for_it_at_dispatch(tmp_path, monkeypatch):
    """`- integration: yes` written at dispatch is the human saying "I will want
    to run this batch" — it must not need them to remember a flag at collect."""
    calls = _recorder(monkeypatch)
    mind = mini_mind(tmp_path, keys="- integration: yes")
    _batch.main(["collect", "--mind", str(mind), "--slot", SLOT])
    assert [c["order"] for c in calls] == [["alpha"]]

    calls.clear()
    off = mini_mind(tmp_path / "off", keys="- integration: no")
    _batch.main(["collect", "--mind", str(off), "--slot", SLOT])
    assert calls == []


def test_apply_stamps_the_integration_root_on_the_record(tmp_path):
    """A SEPARATE key. `- integration: yes` is the human's request and
    `- integration-root:` is what happened; writing the second over the first
    would erase what they asked for."""
    mind = mini_mind(tmp_path, keys="- integration: yes")
    d = collected(mind, block_for())
    before = (mind / "batches" / f"{SLOT}.md").read_text(encoding="utf-8")
    after = _batch.record_update(before, d, STAMP)
    assert _batch._rehearse_record(mind, before, after) == []
    assert "- integration: yes" in after
    assert ("- integration-root: /tmp/wt/integration-x — "
            f"integration/{SLOT}; 1 clean, 1 conflicted") in after

    _batch.apply_collect(mind, d, STAMP)
    written = (mind / "batches" / f"{SLOT}.md").read_text(encoding="utf-8")
    assert "- integration: yes" in written and "- integration-root: " in written


def test_the_report_puts_the_source_line_at_the_top(tmp_path):
    """The whole point of the leg is that the human can RUN the batch, and a
    `source …` line five screens down is a line nobody sources."""
    mind = mini_mind(tmp_path)
    body = _batch.collect_report(collected(mind, block_for()))
    assert "## Integration branches" in body
    assert "source /tmp/wt/integration-x/activate.sh" in body
    assert body.index("## Integration branches") < body.index("## alpha")
    assert ("- Example/Other — conflicted — " in body
            and "collides on a.py — left out" in body)


def test_plan_refuses_the_collect_flag(tmp_path):
    """`batch plan --integration` means something, and it is not "plan"."""
    mind = mini_mind(tmp_path)
    (mind / "draft").mkdir(exist_ok=True)
    assert _batch.main(["plan", "--mind", str(mind), "--integration"]) == 2

"""M3.7e (PyAutoBrain#692): the shift-end cloud sweep — dispatch, read, red block.

The human's rulings of 2026-11-19 (AUTONOMY.md "Shift speed — 2026-11-19", S4
and the red handling; "The watcher's network surface", amendment M3.7e):

1. A shift that merged at least one library or workspace PR dispatches the
   sweep workflow exactly once at its close; one that merged none, or a
   shadow shift, dispatches nothing; a failed dispatch is reported, never
   retried.
2. The digest names, per library, the SHA the latest green sweep verified,
   the shift's own sweep while it runs (or "not yet listed"), and a red one.
3. A red latest sweep refuses close-outs on its failing workspaces' install
   chains (`workspace sweep red: <url>`); other repos still close out; an
   unknown workspace blocks every library repo; a later green run or
   `/clear-sweep` clears it, and a newer red run blocks again; a running
   close-out on a blocked repo gets a `.sweep-red` marker it checks.
4. One bug draft per red run through the one Mind writer, with the failing
   scripts and the suspect PRs; nothing more on a second tick or shift; one
   run list a tick, artifacts once per run id.
5. No revert, bisect or forced dispatch anywhere in the watcher.
6. AUTONOMY.md records S4, the network-surface amendment and `/clear-sweep`.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "tests"))
import test_orchestrator_closeout as tc  # noqa: E402 — the 4b and M3.6j fixtures
from test_orchestrator_closeout import FIT8, GA7, Agents  # noqa: E402
from test_orchestrator_digest import _brief, _digest, orch  # noqa: E402
import _mind_writer as mw  # noqa: E402

t = tc.t
NOW = t.NOW
HEART = "example-org/example-heart"
WORKFLOW = "workspace-smoke.yml"
CFG = {"repo": HEART, "workflow": WORKFLOW,
       "siblings": {"howtofit": "autofit", "autofit_test": "autofit"}}
RUN = "https://github.com/example-org/example-heart/actions/runs/{}"
LOGIN = "the-human"
DISPATCH = ["gh", "workflow", "run", WORKFLOW, "-R", HEART]

REPOS_YAML = """\
smoke:
  workspaces:
    autofit:
      directory: example_fit_ws
      chain: [autonerves, autofit]
    autogalaxy:
      directory: example_galaxy_ws
      chain: [autonerves, autofit, autoarray, autogalaxy]
"""
VALIDATION_YML = """\
jobs:
  find_scripts:
    steps:
      - run: |
          declare -A WS=(
            [autofit]=example_fit_ws [autogalaxy]=example_galaxy_ws
            [howtofit]=example_howtofit [autofit_test]=example_fit_ws_test
          )
          for proj in "${!WS[@]}"; do
"""


def _at(minutes):
    return NOW + _dt.timedelta(minutes=minutes)


def _sha(c):
    return c * 40


def _run(rid, conclusion="success", minutes=-600, status="completed", event="schedule"):
    return {"databaseId": int(rid), "status": status, "conclusion": conclusion,
            "url": RUN.format(rid), "createdAt": orch._iso(_at(minutes)), "event": event}


def _shas(rid, fit="a", galaxy="b"):
    return {"schema": 1, "run_id": str(rid), "run_url": RUN.format(rid), "swept": True,
            "full_sweep_run_id": str(rid),
            "commit_shas": {"autofit": _sha(fit), "autogalaxy": _sha(galaxy),
                            "example_fit_ws": _sha("c")}}


def _report(*fails):
    return {"ready": False, "summary": {"failed": len(fails)},
            "failures": [{"project": p, "directory": "scripts/x", "file": f"/w/{s}",
                          "status": "failed"} for p, s in fails],
            "per_project": {}}


class FakeGH:
    """`gh` for the sweep: the run list, artifact downloads, compares and the
    dispatch, each call recorded."""

    def __init__(self, runs=None, artifacts=None, compares=None, dispatch_err=""):
        self.runs = [] if runs is None else runs
        self.artifacts = artifacts or {}
        self.compares = compares or {}
        self.dispatch_err = dispatch_err
        self.calls = []

    def __call__(self, argv, timeout=120):
        argv = list(argv)
        self.calls.append(argv)

        def done(rc=0, out="", err=""):
            return subprocess.CompletedProcess(argv, rc, out, err)
        if argv[:3] == ["gh", "workflow", "run"]:
            return done(1, "", self.dispatch_err) if self.dispatch_err else done()
        if argv[:3] == ["gh", "run", "list"]:
            if self.runs is None:
                return done(1, "", "HTTP 502")
            return done(0, json.dumps(self.runs))
        if argv[:3] == ["gh", "run", "download"]:
            rid, name = argv[3], argv[argv.index("-n") + 1]
            dest = Path(argv[argv.index("-D") + 1])
            files = self.artifacts.get((rid, name))
            if files is None:
                return done(1, "", "no artifact")
            for fname, data in files.items():
                (dest / fname).write_text(json.dumps(data))
            return done()
        if argv[:2] == ["gh", "api"]:
            got = self.compares.get(argv[2])
            return done(1, "", "404") if got is None else done(0, json.dumps(got))
        raise AssertionError(f"unexpected gh call {argv}")

    def of(self, *head):
        return [c for c in self.calls if c[:len(head)] == list(head)]


@pytest.fixture
def sweep(monkeypatch, tmp_path):
    """The sweep configured, Heart's maps in a fixture checkout, gh faked."""
    heart = tmp_path / "heart"
    (heart / "config").mkdir(parents=True)
    (heart / "config" / "repos.yaml").write_text(REPOS_YAML)
    (heart / ".github" / "workflows").mkdir(parents=True)
    (heart / ".github" / "workflows" / "workspace-validation.yml").write_text(VALIDATION_YML)
    monkeypatch.setenv("PYAUTO_HEART", str(heart))
    monkeypatch.setattr(orch, "_sweep_cfg", lambda: dict(CFG))
    gh = FakeGH()
    monkeypatch.setattr(orch._sweep, "run_gh", gh)
    return gh


# --- 1. the dispatch at close ---------------------------------------------------------

class MergeSpawner(tc.Spawner):
    def __init__(self, done):
        t.FilesSpawner.__init__(self, done=done, proofs={})
        self.closeouts = []


def _merged_shift(tmp_path, done, extra=""):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="") + extra)
    home = tmp_path / "home"
    sp = MergeSpawner(done)
    return mind, brief, home, sp


def _close(mind, brief, home, sp, states=None, poster=None):
    """Tick the shift through its end: dispatch, reap (maybe close early),
    then a tick past review-at."""
    pr_state = tc._gh_states(states or {})
    for minutes in (0, 1, 181):
        orch.tick(brief, mind, home=home, now=_at(minutes), spawner=sp, agents=Agents(),
                  health=lambda u: "FAILED", pr_state=pr_state, poster=poster or t.Poster())
    return orch.slot_dir(brief, home)


def test_a_shift_that_merged_a_library_pr_dispatches_once_at_close(tmp_path, sweep):
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + GA7 + "\n",
                                                     "picked": ""})
    slot = _close(mind, brief, home, sp, {GA7: ("MERGED", "2026-11-04T09:00:30Z")})
    assert sweep.of("gh", "workflow", "run") == [DISPATCH]          # no -f force
    assert (slot / orch._sweep.DISPATCH_MARKER).exists()
    c = orch.read_counters(slot)
    assert c["sweep_dispatch"]["ok"] is True
    # finish_shift again, retried after a lost digest: never a second dispatch.
    (slot / orch.DIGEST_MARKER).unlink()
    orch.finish_shift(brief, mind, slot, _at(182), poster=t.Poster(), agents=Agents(),
                      pr_state=tc._gh_states({GA7: ("MERGED", "2026-11-04T09:00:30Z")}))
    assert sweep.of("gh", "workflow", "run") == [DISPATCH]


def test_a_shift_that_merged_nothing_dispatches_nothing(tmp_path, sweep):
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": GA7 + "\n", "picked": ""})
    slot = _close(mind, brief, home, sp)
    assert sweep.of("gh", "workflow", "run") == []
    assert not (slot / orch._sweep.DISPATCH_MARKER).exists()


def test_a_merge_on_a_repo_neither_library_nor_workspace_dispatches_nothing(tmp_path, sweep):
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + tc.PR1 + "\n",
                                                     "picked": ""})
    _close(mind, brief, home, sp, {tc.PR1: ("MERGED", "2026-11-04T09:00:30Z")})
    assert sweep.of("gh", "workflow", "run") == []


def test_a_shadow_shift_never_dispatches_nor_reads(tmp_path, sweep):
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + GA7 + "\n"},
                                          extra="  - shadow: yes\n")
    sp.spawn = lambda *a, **k: (_ for _ in ()).throw(AssertionError("shadow spawned"))
    _close(mind, brief, home, sp, {GA7: ("MERGED", "2026-11-04T09:00:30Z")})
    assert sweep.calls == []


def test_a_failed_dispatch_is_reported_and_never_retried(tmp_path, sweep):
    sweep.dispatch_err = "HTTP 403: Resource not accessible\nmore detail"
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + GA7 + "\n",
                                                     "picked": ""})
    poster = t.Poster()
    slot = _close(mind, brief, home, sp, {GA7: ("MERGED", "2026-11-04T09:00:30Z")}, poster)
    c = orch.read_counters(slot)
    assert c["sweep_dispatch"]["ok"] is False
    d = (slot / orch.DIGEST_FILE).read_text()
    assert ("sweep not dispatched (HTTP 403: Resource not accessible) — run it from chat"
            in d)
    (slot / orch.DIGEST_MARKER).unlink()
    orch.finish_shift(brief, mind, slot, _at(182), poster=t.Poster(), agents=Agents(),
                      pr_state=tc._gh_states({GA7: ("MERGED", "2026-11-04T09:00:30Z")}))
    assert len(sweep.of("gh", "workflow", "run")) == 1


# --- 2. the digest lines --------------------------------------------------------------

def test_digest_verified_through_per_library_from_the_latest_green_run(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": GA7 + "\n", "picked": ""})
    slot = _close(mind, brief, home, sp)
    d = (slot / orch.DIGEST_FILE).read_text()
    assert "### Workspace sweep" in d
    assert "- autofit: workspaces verified through `aaaaaaaaaaaa` (run 100)" in d
    assert "- autogalaxy: workspaces verified through `bbbbbbbbbbbb` (run 100)" in d
    assert "example_fit_ws" not in d.split("### Workspace sweep")[1]   # a library line only


def test_digest_says_sweep_running_for_the_shifts_own_dispatch(tmp_path, sweep):
    # The shift closes at its review-at tick (minute 181); its run follows.
    sweep.runs = [_run(101, conclusion="", minutes=181, status="in_progress",
                       event="workflow_dispatch"), _run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + GA7 + "\n",
                                                     "picked": ""})
    slot = _close(mind, brief, home, sp, {GA7: ("MERGED", "2026-11-04T09:00:30Z")})
    d = (slot / orch.DIGEST_FILE).read_text()
    assert f"sweep running: {RUN.format(101)}" in d


def test_digest_says_not_yet_listed_when_the_dispatch_is_not_seen(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + GA7 + "\n",
                                                     "picked": ""})
    slot = _close(mind, brief, home, sp, {GA7: ("MERGED", "2026-11-04T09:00:30Z")})
    d = (slot / orch.DIGEST_FILE).read_text()
    c = orch.read_counters(slot)
    assert f"sweep dispatched at {c['sweep_dispatch']['at']}, not yet listed" in d


# --- 3. the red block -----------------------------------------------------------------

class TwoLibs(tc.Spawner):
    """`named` opens a PR on autofit, `picked` one on autogalaxy."""

    def __init__(self):
        t.FilesSpawner.__init__(self, done={"named": FIT8 + "\n", "picked": GA7 + "\n"},
                                proofs={})
        self.closeouts = []


def _red(sweep, project="autofit", rid=200, fit="d"):
    sweep.runs = [_run(rid, "failure", minutes=-60), _run(100)]
    sweep.artifacts = {
        ("100", "workspace-smoke-shas"): {"shas.json": _shas(100)},
        (str(rid), "workspace-smoke-shas"): {"shas.json": _shas(rid, fit=fit)},
        (str(rid), "workspace-validation-report"): {
            "report.json": _report((project, "start_here.py"))}}


def _libs_shift(tmp_path):
    mind = t._mind(tmp_path / "mind")
    brief = tmp_path / "shift.md"
    brief.write_text(t.BRIEF.format(issue=t.ISSUE, packet="")
                     .replace("merge-cap: 1", "merge-cap: 2"))
    return mind, brief, tmp_path / "home", TwoLibs()


def _ltick(mind, brief, home, sp, minutes, agents=None):
    return orch.tick(brief, mind, home=home, now=_at(minutes), spawner=sp,
                     agents=agents or Agents(), health=lambda u: "HEALTHY",
                     pr_state=tc._gh_states({}))


def test_a_red_sweep_refuses_a_chain_repo_pr_and_closes_out_the_others(tmp_path, sweep):
    _red(sweep, "autofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert c["closeouts"][FIT8] == {"task": "named", "state": "refused",
                                    "why": f"workspace sweep red: {RUN.format(200)}"}
    assert [pr for _, pr in sp.closeouts] == [GA7]          # the unaffected repo
    assert orch._merge_slots.pr_key(FIT8) not in tc._slots(brief, home)
    blk = c["sweep"]["block"]
    assert blk["repos"] == ["autonerves", "autofit", "example_fit_ws"]
    assert blk["everything"] is False


def test_a_sibling_project_maps_to_its_siblings_chain(tmp_path, sweep):
    _red(sweep, "howtofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    blk = orch.read_counters(orch.slot_dir(brief, home))["sweep"]["block"]
    assert blk["repos"] == ["autonerves", "autofit", "example_howtofit"]


def test_an_unknown_workspace_blocks_every_library_repo(tmp_path, sweep):
    _red(sweep, "mystery")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][FIT8]["state"] == "refused"
    assert c["closeouts"][GA7]["state"] == "refused"
    assert sp.closeouts == []
    assert c["sweep"]["block"]["everything"] is True


def test_a_later_green_run_clears_the_block(tmp_path, sweep):
    _red(sweep, "autofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    assert orch.read_counters(orch.slot_dir(brief, home))["sweep"]["block"]
    sweep.runs = [_run(201, minutes=0)] + sweep.runs
    sweep.artifacts[("201", "workspace-smoke-shas")] = {"shas.json": _shas(201, fit="d")}
    _ltick(mind, brief, home, sp, 1)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert not c["sweep"].get("block")
    assert sorted(pr for _, pr in sp.closeouts) == sorted([FIT8, GA7])


def test_clear_sweep_clears_the_latest_red_run_and_a_newer_red_blocks_again(
        tmp_path, sweep, monkeypatch):
    monkeypatch.setenv(orch.MENTION_ENV, LOGIN)
    comments = []
    monkeypatch.setattr(orch, "gh_issue_comments", lambda *a, **k: list(comments))
    _red(sweep, "autofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    comments.append({"id": "1", "login": LOGIN, "body": "/clear-sweep\nlooked at it",
                     "created_at": "2026-11-04T09:00:30Z", "url": t.ISSUE + "#issuecomment-1"})
    r = _ltick(mind, brief, home, sp, 1)
    ack = r["commands"][0]["ack"]
    assert ack.startswith(f"cleared: workspace sweep red {RUN.format(200)}")
    slot = orch.slot_dir(brief, home)
    assert "200" in json.loads((home / "sweep" / "cleared.json").read_text())
    assert sorted(pr for _, pr in sp.closeouts) == sorted([FIT8, GA7])
    # A newer red run blocks again.
    _red(sweep, "autofit", rid=300)
    _ltick(mind, brief, home, sp, 2)
    assert orch.read_counters(slot)["sweep"]["block"]["run_id"] == "300"


def test_clear_sweep_with_nothing_red_says_nothing_to_clear(tmp_path, sweep, monkeypatch):
    monkeypatch.setenv(orch.MENTION_ENV, LOGIN)
    monkeypatch.setattr(orch, "gh_issue_comments", lambda *a, **k: [
        {"id": "1", "login": LOGIN, "body": "/clear-sweep", "created_at":
         "2026-11-04T08:59:00Z", "url": t.ISSUE + "#issuecomment-1"}])
    sweep.runs = [_run(100)]
    mind, brief, home, sp = _libs_shift(tmp_path)
    r = _ltick(mind, brief, home, sp, 0)
    assert r["commands"][0]["ack"] == "nothing to clear: no red workspace sweep blocks merges"
    assert "clear-sweep" in orch.COMMANDS
    assert orch._parse_command("/clear-sweep") == ("clear-sweep", "")


@pytest.mark.usefixtures("shift_held_open")
def test_a_running_closeout_on_a_blocked_repo_gets_the_sweep_red_marker(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    assert orch.read_counters(slot)["closeouts"][FIT8]["state"] == "running"
    _red(sweep, "autofit")
    _ltick(mind, brief, home, sp, 2)
    marker = slot / "leases" / "named.sweep-red"
    assert marker.read_text().strip() == f"workspace sweep red: {RUN.format(200)}"
    assert not (slot / "leases" / "picked.sweep-red").exists()
    template = orch.closeout_prompt("named", FIT8, "x.md", brief, slot / "leases")
    assert f"{slot / 'leases'}/named.sweep-red" in template
    assert "`<the text in that file> → /prm`" in template     # verbatim: one reason line
    # A later green run lifts the block, and the marker with it.
    sweep.runs = [_run(201, minutes=2)] + sweep.runs
    sweep.artifacts[("201", "workspace-smoke-shas")] = {"shas.json": _shas(201, fit="d")}
    _ltick(mind, brief, home, sp, 3)
    assert not marker.exists()


# --- 4. the bug draft, and the reads' budget ------------------------------------------

def _draft_ops(slot):
    out = []
    for f in mw.pending_ops(slot):
        op = json.loads(f.read_text())
        if op.get("op") == "write" and "workspace_sweep_red" in op.get("path", ""):
            out.append(op)
    return out


def test_one_bug_draft_names_failing_scripts_and_suspect_prs(tmp_path, sweep):
    _red(sweep, "autofit")
    sweep.compares = {f"repos/example-org/autofit/compare/{_sha('a')}...{_sha('d')}": [
        "Merge pull request #41 from example-org/feature/x\n\nbody",
        "Fix the prior (#42)", "a plain commit"]}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    slot = orch.slot_dir(brief, home)
    ops = _draft_ops(slot)
    assert [o["path"] for o in ops] == ["draft/bug/autofit/workspace_sweep_red_200.md"]
    text = ops[0]["text"]
    for needle in ("Type: bug", "Target: autofit", "Status: draft", "Filed: 2026-11-04",
                   "Consequence: judge", RUN.format(200), "`autofit`: `scripts/x/start_here.py`",
                   "autonerves, autofit, example_fit_ws",
                   "[#41](https://github.com/example-org/autofit/pull/41)",
                   "[#42](https://github.com/example-org/autofit/pull/42)",
                   "workspace-smoke-pinned.yml", "commit_shas", "draft PRs opened for the human"):
        assert needle in text, needle
    # A second tick and a later shift file nothing more; reads stay in budget.
    _ltick(mind, brief, home, sp, 1)
    assert len(_draft_ops(slot)) == 1
    mind2 = t._mind(tmp_path / "mind2")
    brief2 = tmp_path / "shift2.md"
    brief2.write_text(t.BRIEF.format(issue=t.ISSUE, packet=""))
    orch.tick(brief2, mind2, home=home, now=_at(2), spawner=TwoLibs(), agents=Agents(),
              health=lambda u: "HEALTHY", pr_state=tc._gh_states({}))
    assert _draft_ops(orch.slot_dir(brief2, home)) == []
    assert len(sweep.of("gh", "run", "list")) == 3                     # one a tick
    downloads = [(c[3], c[c.index("-n") + 1]) for c in sweep.of("gh", "run", "download")]
    assert sorted(downloads) == sorted([("200", "workspace-smoke-shas"),
                                        ("200", "workspace-validation-report"),
                                        ("100", "workspace-smoke-shas")])
    assert len(sweep.of("gh", "api")) == 1                             # one compare


def test_no_green_baseline_says_so_and_targets_the_sweep_repo(tmp_path, sweep):
    sweep.runs = [_run(200, "failure", minutes=-60)]
    sweep.artifacts = {("200", "workspace-smoke-shas"): {"shas.json": _shas(200)},
                       ("200", "workspace-validation-report"): {
                           "report.json": _report(("autofit", "start_here.py"))}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    ops = _draft_ops(orch.slot_dir(brief, home))
    assert [o["path"] for o in ops] == ["draft/bug/example-heart/workspace_sweep_red_200.md"]
    assert "No green sweep on `main` is known to compare against" in ops[0]["text"]


def test_an_unreadable_report_is_tried_three_times_then_blocks_every_library(tmp_path, sweep):
    _red(sweep, "autofit")
    del sweep.artifacts[("200", "workspace-validation-report")]
    mind, brief, home, sp = _libs_shift(tmp_path)
    for minutes in (0, 1, 2, 3, 4):
        _ltick(mind, brief, home, sp, minutes)
    tries = [c for c in sweep.of("gh", "run", "download")
             if c[3] == "200" and "workspace-validation-report" in c]
    assert len(tries) == 3
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["sweep"]["block"]["everything"] is True
    ops = _draft_ops(orch.slot_dir(brief, home))
    assert len(ops) == 1 and "could not be read" in ops[0]["text"]


def test_the_digest_red_line_names_the_block_the_refusals_and_the_draft(tmp_path, sweep):
    _red(sweep, "autofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot,
                      orch.read_counters(slot), health=t._health)
    assert (f"- workspace sweep red: {RUN.format(200)} — blocked: autonerves, autofit, "
            "example_fit_ws; PRs refused: autofit#8; bug draft: "
            "`draft/bug/example-heart/workspace_sweep_red_200.md`") in d


def test_a_failed_run_list_keeps_the_last_known_block(tmp_path, sweep):
    _red(sweep, "autofit")
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    sweep.runs = None
    _ltick(mind, brief, home, sp, 1)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][FIT8]["state"] == "refused"


# --- 5. no revert, bisect or forced dispatch ------------------------------------------

WATCHER_CODE = [BATCH / "_orchestrator.py", BATCH / "_sweep.py"]
TEMPLATES = [BATCH / "closeout_template.md", BATCH / "closeout_update_template.md",
             BATCH / "worker_template.md"]


def _argv_lists(path):
    """Every list or tuple literal of strings that starts a `gh`/`git` call."""
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts \
                and isinstance(node.elts[0], ast.Constant) and node.elts[0].value in ("gh", "git"):
            out.append([e.value if isinstance(e, ast.Constant) else "<expr>" for e in node.elts])
    return out


def test_nothing_in_the_watcher_reverts_bisects_or_forces_a_sweep():
    calls = [argv for f in WATCHER_CODE for argv in _argv_lists(f)]
    assert ["gh", "workflow", "run", "<expr>", "-R", "<expr>"] in calls   # the one dispatch
    for argv in calls:
        words = [str(w) for w in argv]
        assert "revert" not in words, argv
        assert not any("workspace-smoke-pinned" in w for w in words), argv
        assert not any("force" in w for w in words), argv
        assert "-f" not in words and "--field" not in words and "--raw-field" not in words, argv
    policy = (BRAIN / "config" / "policy.yaml").read_text()
    assert "sweep_workflow: workspace-smoke.yml" in policy
    for f in TEMPLATES:
        text = f.read_text()
        for bad in ("git revert", "gh pr revert", "gh workflow run", "force=true"):
            assert bad not in text, (f.name, bad)


# --- 6. the doctrine ------------------------------------------------------------------

def test_autonomy_records_s4_the_network_amendment_and_clear_sweep():
    text = (BRAIN / "AUTONOMY.md").read_text()
    speed = text.split("## Shift speed — 2026-11-19", 1)[1].split("\n## ", 1)[0]
    assert "**S4, the shift-end sweep**" in speed
    assert "/clear-sweep" in speed
    assert "S4) is added to this section" not in speed
    # Review round 1: the late window can dispatch; cancelled is no verdict;
    # an unreadable run list and the fallback block every repo a merge breaks.
    for needle in ("late window", "cancelled run is no verdict", "run list unreadable",
                   "every library, chain and workspace repo"):
        assert needle in speed, needle
    net = text.split("## The watcher's network surface — 2026-11-03", 1)[1].split("\n## ", 1)[0]
    amend = net.split("**Amendment — 2026-11-19 (M3.7e, PyAutoBrain#692)", 1)[1]
    for needle in ("gh workflow run", "gh run list", "gh run download", "compare",
                   "decision b", "fake mode", "/clear-sweep"):
        assert needle in amend.split("\n\n**", 1)[0], needle
    agents = (BATCH / "AGENTS.md").read_text()
    assert "/clear-sweep" in agents and "M3.7e" in agents
    cockpit = (BRAIN / "skills" / "cockpit" / "cockpit.md").read_text()
    assert "/clear-sweep" in cockpit


# --- review round 1 (M3.7e) ---------------------------------------------------------

class Libs(tc.Spawner):
    """Workers that finished at once with the PRs the test names."""

    def __init__(self, named, picked=""):
        t.FilesSpawner.__init__(self, done={"named": named + "\n", "picked": picked + "\n"},
                                proofs={})
        self.closeouts = []


WS3 = "https://github.com/example-org/example_fit_ws/pull/3"
NERVES4 = "https://github.com/example-org/autonerves/pull/4"


def test_r1_1_the_fallback_blocks_every_chain_and_workspace_repo(tmp_path, sweep):
    _red(sweep, "mystery")
    mind, brief, home, _ = _libs_shift(tmp_path)
    sp = Libs(WS3, NERVES4)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert c["closeouts"][WS3]["state"] == "refused"
    assert c["closeouts"][NERVES4]["state"] == "refused"
    assert sp.closeouts == []


UNKNOWN = "workspace sweep unknown: run list unreadable since {}"


def test_r1_2_a_run_list_never_read_fails_closed_after_30_minutes(tmp_path, sweep):
    """Updated in review round 2: 30 minutes of failing, then a wait (not a
    refusal), named in the digest."""
    sweep.runs = None
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 31)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    why = UNKNOWN.format("2026-11-04T09:00:00Z")
    assert c["sweep_waits"][FIT8]["why"] == why and c["sweep_waits"][GA7]["why"] == why
    assert FIT8 not in c["closeouts"] and sp.closeouts == []
    d = _digest.build(_brief.parse(brief.read_text())["brief"], slot, c, health=t._health)
    assert f"- {why} — blocked:" in d and "PRs waiting: autofit#8, autogalaxy#7" in d


def test_r1_2_a_run_list_failing_for_30_minutes_fails_closed(tmp_path, sweep):
    """Updated in review round 2: measured from the first failure of the
    current streak, not from the last success."""
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    sweep.runs = None
    slot = orch.slot_dir(brief, home)
    _ltick(mind, brief, home, sp, 29)
    _ltick(mind, brief, home, sp, 58)
    assert not orch.read_counters(slot)["sweep"].get("block")
    _ltick(mind, brief, home, sp, 59)
    blk = orch.read_counters(slot)["sweep"]["block"]
    assert blk["why"] == UNKNOWN.format("2026-11-04T09:29:00Z")
    assert blk["everything"] is True


# --- review round 2 (M3.7e) ---------------------------------------------------------

def test_r2_1_one_failure_after_a_long_gap_blocks_nothing(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    sweep.runs = None
    _ltick(mind, brief, home, sp, 120)
    c = orch.read_counters(orch.slot_dir(brief, home))
    assert not c["sweep"].get("block")
    assert sorted(pr for _, pr in sp.closeouts) == sorted([FIT8, GA7])


def test_r2_1_an_unknown_sweep_holds_prs_then_a_good_read_releases_them(tmp_path, sweep):
    sweep.runs = None
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    r = _ltick(mind, brief, home, sp, 31)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert set(c["sweep_waits"]) == {FIT8, GA7}
    assert c["closeouts"] == {} and sp.closeouts == [] and tc._slots(brief, home) == {}
    assert "closed_early" not in r and not (slot / orch.DIGEST_MARKER).exists()
    r = _ltick(mind, brief, home, sp, 32)                 # still unknown: still held open
    assert "closed_early" not in r
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    _ltick(mind, brief, home, sp, 33)
    c = orch.read_counters(slot)
    assert c["sweep_waits"] == {}
    assert sorted(pr for _, pr in sp.closeouts) == sorted([FIT8, GA7])


@pytest.mark.usefixtures("shift_held_open")
def test_r2_1_a_running_closeout_under_an_unknown_sweep_gets_the_marker(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    sweep.runs = None
    _ltick(mind, brief, home, sp, 2)
    _ltick(mind, brief, home, sp, 32)
    marker = orch.slot_dir(brief, home) / "leases" / "named.sweep-red"
    assert marker.read_text().strip() == UNKNOWN.format("2026-11-04T09:02:00Z")


def test_r2_3_the_real_policy_turns_the_sweep_on_and_fake_mode_off(monkeypatch):
    monkeypatch.undo()                                  # the real `_sweep_cfg`
    monkeypatch.delenv(orch.FAKE_ENV, raising=False)
    cfg = orch._sweep_cfg()
    assert set(cfg) == {"repo", "workflow", "siblings"}
    assert cfg["workflow"] == WORKFLOW and "/" in cfg["repo"] and cfg["siblings"]
    monkeypatch.setenv(orch.FAKE_ENV, "1")
    assert orch._sweep_cfg() == {}


def test_r1_3_a_shift_whose_only_merge_is_a_chain_repo_dispatches(tmp_path, sweep):
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": "merged " + NERVES4 + "\n",
                                                     "picked": ""})
    _close(mind, brief, home, sp, {NERVES4: ("MERGED", "2026-11-04T09:00:30Z")})
    assert sweep.of("gh", "workflow", "run") == [DISPATCH]


def test_r1_3_a_chain_repo_gets_a_verified_through_line(tmp_path, sweep):
    sweep.runs = [_run(100)]
    shas = _shas(100)
    shas["commit_shas"]["autonerves"] = _sha("e")
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": shas}}
    mind, brief, home, sp = _merged_shift(tmp_path, {"named": GA7 + "\n", "picked": ""})
    slot = _close(mind, brief, home, sp)
    assert "- autonerves: workspaces verified through `eeeeeeeeeeee` (run 100)" in \
        (slot / orch.DIGEST_FILE).read_text()


def test_r1_4_scripts_are_named_from_the_real_reports_paths():
    data = json.loads((BRAIN / "tests" / "fixtures" / "sweep_report_red.json").read_text())
    rep = orch._sweep._report_of(data)
    assert rep["projects"] == ["autolens_test"]
    assert rep["failing"][0] == {"project": "autolens_test", "status": "failed",
                                 "script": "scripts/imaging/jax_likelihood/delaunay.py"}
    assert {f["script"] for f in rep["failing"]} >= {
        "scripts/interferometer/datacube/rectangular.py"}
    odd = orch._sweep._report_of({"failures": [
        {"project": "p", "directory": "elsewhere", "file": "/r/x/workspace/scripts/a/b.py"}]})
    assert odd["failing"][0]["script"] == "scripts/a/b.py"


def test_r1_5_a_cancelled_run_is_not_a_verdict(tmp_path, sweep):
    sweep.runs = [_run(201, "cancelled", minutes=-30), _run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    slot = orch.slot_dir(brief, home)
    c = orch.read_counters(slot)
    assert not c["sweep"].get("block") and c["sweep"]["latest"]["id"] == "100"
    assert _draft_ops(slot) == []
    # Behind a cancelled run, a red one still blocks.
    _red(sweep, "autofit")
    sweep.runs = [_run(201, "cancelled", minutes=-30)] + sweep.runs
    _ltick(mind, brief, home, sp, 1)
    assert orch.read_counters(slot)["sweep"]["block"]["run_id"] == "200"


def test_r1_6_a_merge_after_close_dispatches_once_from_the_late_sweep(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    assert orch.read_counters(slot)["closeouts"][FIT8]["state"] == "running"
    orch.tick(brief, mind, home=home, now=_at(181), spawner=sp, agents=Agents(),
              health=lambda u: "HEALTHY", pr_state=tc._gh_states({}), poster=t.Poster())
    assert (slot / orch.DIGEST_MARKER).exists()
    assert sweep.of("gh", "workflow", "run") == []
    tc._verdict(home, brief, "named", result="merged", pr=FIT8, gate="g", model="m")
    merged = tc._gh_states({FIT8: ("MERGED", "2026-11-04T11:35:00Z")})
    for minutes in (186, 187):
        orch.tick(brief, mind, home=home, now=_at(minutes), spawner=sp, agents=Agents(),
                  health=lambda u: "HEALTHY", pr_state=merged, poster=t.Poster())
    assert sweep.of("gh", "workflow", "run") == [DISPATCH]
    assert orch.read_counters(slot)["sweep_dispatch"]["ok"] is True


@pytest.mark.usefixtures("shift_held_open")
def test_r1_7_a_marker_the_current_block_does_not_cover_is_removed(tmp_path, sweep):
    sweep.runs = [_run(100)]
    sweep.artifacts = {("100", "workspace-smoke-shas"): {"shas.json": _shas(100)}}
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)
    _ltick(mind, brief, home, sp, 1)
    slot = orch.slot_dir(brief, home)
    _red(sweep, "autofit")                       # red A on autofit (named's repo)
    _ltick(mind, brief, home, sp, 2)
    named = slot / "leases" / "named.sweep-red"
    assert named.exists()
    orch._sweep.clear(home, LOGIN, "2026-11-04T09:02:30Z")
    # Red B (newer) fails a workspace whose chain is autogalaxy alone: not autofit.
    heart = Path(os.environ["PYAUTO_HEART"]) / "config" / "repos.yaml"
    heart.write_text(REPOS_YAML + "    galaxy_only:\n      directory: example_galaxy_ws\n"
                                  "      chain: [autogalaxy]\n")
    sweep.runs = [_run(300, "failure", minutes=2)] + sweep.runs
    sweep.artifacts[("300", "workspace-smoke-shas")] = {"shas.json": _shas(300)}
    sweep.artifacts[("300", "workspace-validation-report")] = {
        "report.json": _report(("galaxy_only", "x.py"))}
    _ltick(mind, brief, home, sp, 3)
    assert orch.read_counters(slot)["sweep"]["block"]["run_id"] == "300"
    assert not named.exists()
    assert (slot / "leases" / "picked.sweep-red").read_text().strip() == \
        f"workspace sweep red: {RUN.format(300)}"


def test_r1_8_a_clear_before_the_artifacts_are_read_still_files_the_draft(tmp_path, sweep):
    _red(sweep, "autofit")
    del sweep.artifacts[("200", "workspace-validation-report")]
    mind, brief, home, sp = _libs_shift(tmp_path)
    _ltick(mind, brief, home, sp, 0)               # report try 1 of 3: not settled
    slot = orch.slot_dir(brief, home)
    assert _draft_ops(slot) == []
    orch._sweep.clear(home, LOGIN, "2026-11-04T09:00:30Z")
    for minutes in (1, 2, 3):
        _ltick(mind, brief, home, sp, minutes)
    assert [o["path"].rsplit("/", 1)[1] for o in _draft_ops(slot)] == \
        ["workspace_sweep_red_200.md"]

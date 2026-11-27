"""Phase 14.2 maintenance prompt writer (PyAutoBrain#733).

Witness: two runs file each `draft/maintenance/<target>/maint_<key>.md`
exactly once (Source-key header, key mark and `maintain.json` dedupe); every
file passes Mind's `lifecycle.py check` and is graded by sizing; the cap
holds; queue.md and active/ dedupe; an unread, stale or partial read files
nothing and clears nothing; a fixed finding releases its key; a judge finding
is `Unattended: never`; a main git checkout is refused; and the
keep-Heart-green lane files through this writer. Placeholder repos and
fixture boards only — nothing reads a real Heart, the network or the shared
Mind.
"""

from __future__ import annotations

import ast
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from _shift_fixtures import _batch, git_as_t as _git  # noqa: E402
import _green  # noqa: E402
import _maintain  # noqa: E402
import _maintain_write as W  # noqa: E402

BRAIN = Path(__file__).resolve().parents[1]
MIND_SCRIPTS = BRAIN.parent / "PyAutoMind" / "scripts"
NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
TS = "2026-11-27T14:00:00+00:00"
OK = {"ok": True, "stale": False, "partial": False, "source": "fixture", "age_hours": 1.0}


def _f(key, source="census", repo="ws_alpha", tier="judge", lane="local-dev",
       paths=None, stale=False, summary=None):
    return _maintain.Finding(
        key=key, source=source, repo=repo, paths=paths if paths is not None else
        ["scripts/x.py", "no_run.yaml"], summary=summary or f"SLOW since 2026-07-30: {key}",
        witness="the entry is gone from the repo's no_run.yaml and the script passes "
                "under the smoke cap", tier_floor=tier, lane=lane,
        evidence={"repo": repo, "marker": "SLOW"}, stale=stale)


def _mk(m: Path) -> Path:
    for d in ("draft", "active"):
        (m / d).mkdir(parents=True, exist_ok=True)
    (m / "queue.md").write_text("# Queue\n\n## Live\n", encoding="utf-8")
    return m


@pytest.fixture
def plain_mind(tmp_path):
    """A Mind that is not a git checkout."""
    return _mk(tmp_path / "mind")


@pytest.fixture
def main_mind(tmp_path):
    """A main git checkout — what the shared canonical Mind is."""
    m = _mk(tmp_path / "main")
    _git(m, "init", "-q")
    _git(m, "add", "queue.md")
    _git(m, "commit", "-qm", "seed")
    return m


@pytest.fixture
def wt_mind(main_mind, tmp_path):
    wt = tmp_path / "wt"
    _git(main_mind, "worktree", "add", "-q", "--detach", str(wt))
    return _mk(wt)


@pytest.fixture(params=["plain", "wt"])
def mind(request):
    return request.getfixturevalue(f"{request.param}_mind")


def _file(mind, findings, reads=None, cap=3, **kw):
    reads = reads if reads is not None else {"census": OK, "monitoring": OK, "release": OK}
    return W.file_findings(findings, reads, mind, cap=cap,
                           state_path=mind.parent / "home" / W.STATE_NAME, now=NOW, **kw)


def _state(mind):
    return json.loads((mind.parent / "home" / W.STATE_NAME).read_text())["keys"]


FINDINGS = [_f("no_run:ws_alpha/imaging/slow_one"),
            _f("no_run:ws_beta/graphical/ep.py", repo="ws_beta"),
            _f("ci:OrganA:tests", source="monitoring", repo="OrganA", tier="glance",
               lane="any", paths=[".github/workflows/tests.yml"],
               summary="[red] ci_status: OrganA/workflows/tests — failure")]


# --- filing and dedupe --------------------------------------------------------

def test_two_runs_file_each_prompt_exactly_once(mind):
    first = _file(mind, FINDINGS)
    assert [r["key"] for r in first["filed"]] == [f.key for f in FINDINGS]
    for r in first["filed"]:
        assert r["path"].startswith("draft/maintenance/") and "/maint_" in r["path"]
        text = (mind / r["path"]).read_text()
        for need in (f"Source-key: {r['key']}", f"<!-- maint-key: {r['key']} -->",
                     "Re-check first", "Autonomy: supervised", "Status: draft",
                     "Filed: 2026-11-27", "Witness: ", "Review-minutes: ", "Lane: ",
                     "Tier rule", "raise `Consequence:` to `judge`"):
            assert need in text, (need, r["path"])
    census = (mind / first["filed"][0]["path"]).read_text()
    assert "anything other than `no_run.yaml` in ws_alpha" in census and "Consequence: judge" in census
    second = _file(mind, FINDINGS)
    assert second["filed"] == []
    assert all(s["reason"].startswith("existing draft/maintenance/")
               for s in second["skipped"])
    assert len(list(mind.glob("draft/maintenance/*/maint_*.md"))) == 3
    rows = _state(mind)
    assert {k: rows[k]["filed"] for k in rows} == {r["key"]: r["path"] for r in first["filed"]}


def test_state_stops_a_refile_after_the_prompt_left_the_backlog(plain_mind):
    rel = _file(plain_mind, FINDINGS[:1])["filed"][0]["path"]
    (plain_mind / rel).unlink()
    again = _file(plain_mind, FINDINGS[:1])
    assert again["filed"] == [] and "since left the backlog" in again["skipped"][0]["reason"]


@pytest.mark.skipif(not (MIND_SCRIPTS / "lifecycle.py").is_file(),
                    reason="sibling PyAutoMind with lifecycle.py not checked out")
def test_filed_prompts_pass_lifecycle_check_and_are_graded_by_sizing(plain_mind):
    res = _file(plain_mind, FINDINGS)
    (plain_mind / "scripts").mkdir()
    shutil.copy(MIND_SCRIPTS / "lifecycle.py", plain_mind / "scripts" / "lifecycle.py")
    paths = [r["path"] for r in res["filed"]]
    chk = subprocess.run([sys.executable, "scripts/lifecycle.py", "check", "--paths", *paths],
                         cwd=plain_mind, env=dict(os.environ, LIFECYCLE_NO_GH="1"),
                         capture_output=True, text=True)
    assert chk.returncode == 0 and "lifecycle check: OK" in chk.stdout, chk.stdout + chk.stderr
    for r in res["filed"]:
        p = _batch.parse_prompt(plain_mind / r["path"], plain_mind)
        level, _s, factors, derived = _batch.effective_difficulty(p)
        assert p["work_type"] == "maintenance"
        assert level == derived == r["difficulty"], "Difficulty is sizing's own grade"
        grade = _batch.effective_unattended(p, level, factors, derived)[0]
        assert grade == r["unattended"]
        assert p["declared_consequence"] == r["tier"]


def test_judge_is_unattended_never_even_when_sizing_says_ready(plain_mind):
    res = _file(plain_mind, FINDINGS)
    by = {r["key"]: r for r in res["filed"]}
    judge = by["no_run:ws_alpha/imaging/slow_one"]
    p = _batch.parse_prompt(plain_mind / judge["path"], plain_mind)
    p["declared_unattended"] = None
    level, _s, factors, derived = _batch.effective_difficulty(p)
    assert _batch.effective_unattended(p, level, factors, derived)[0] == "ready", \
        "the fixture must be one sizing alone would grade ready"
    assert judge["unattended"] == "never"
    assert "Unattended: never" in (plain_mind / judge["path"]).read_text()
    glance = by["ci:OrganA:tests"]
    assert glance["tier"] == "glance" and glance["unattended"] == "ready"


def test_the_cap_holds_and_the_rest_file_next_run(plain_mind):
    many = [_f(f"no_run:ws_alpha/s{i}.py") for i in range(5)]
    first = _file(plain_mind, many, cap=2)
    assert len(first["filed"]) == 2
    assert sum("cap 2 reached" in s["reason"] for s in first["skipped"]) == 3
    assert len(_file(plain_mind, many, cap=2)["filed"]) == 2
    assert len(_file(plain_mind, many, cap=2)["filed"]) == 1
    assert _file(plain_mind, many, cap=2)["filed"] == []


def test_queue_md_and_active_dedupe(plain_mind):
    a, b, c = FINDINGS
    (plain_mind / "queue.md").write_text(f"# Queue\n\n## 1. fix {a.key}\n")
    (plain_mind / "active" / "task.md").write_text(f"# Task\n\nSource-key: {b.key}\n")
    (plain_mind / "draft" / "maintenance" / "x").mkdir(parents=True)
    (plain_mind / "draft/maintenance/x/human.md").write_text(f"# Human\n\nSee {c.key}.\n")
    res = _file(plain_mind, FINDINGS)
    assert res["filed"] == []
    why = {s["key"]: s["reason"] for s in res["skipped"]}
    assert why[a.key].startswith("already named in queue.md")
    assert why[b.key] == "existing active/task.md"
    assert why[c.key].startswith("mentioned by draft/maintenance/x/human.md")


def test_legacy_heart_green_mark_counts_as_existing(plain_mind):
    rel = plain_mind / "draft/bug/x/old.md"
    rel.parent.mkdir(parents=True)
    rel.write_text(f"# Old\n\n{_green.KEY_MARK.format('ci:OrganA:tests')}\n")
    res = _file(plain_mind, FINDINGS[2:])
    assert res["filed"] == [] and res["skipped"][0]["reason"] == "existing draft/bug/x/old.md"


# --- read gating and clearing -------------------------------------------------

@pytest.mark.parametrize("read,why", [
    ({"ok": False, "stale": True, "partial": False, "why": "board unreachable"}, "read failed"),
    (dict(OK, stale=True), "stale read"),
    (dict(OK, partial=True, why="board census rows not read"), "partial read"),
    (None, "not read"),
])
def test_an_unread_stale_or_partial_read_files_nothing_and_clears_nothing(plain_mind,
                                                                         read, why):
    _file(plain_mind, FINDINGS[:1])
    (plain_mind / _state_rel(plain_mind, FINDINGS[0].key)).unlink()
    reads = {"census": read} if read is not None else {}
    res = _file(plain_mind, [], reads=reads)  # the source lists nothing
    assert res["cleared"] == [] and FINDINGS[0].key in _state(plain_mind)
    res = _file(plain_mind, [_f("no_run:ws_alpha/new.py")], reads=reads)
    assert res["filed"] == [] and why in res["skipped"][0]["reason"]


def _state_rel(mind, key):
    return _state(mind)[key]["filed"]


def test_a_stale_finding_is_never_filed(plain_mind):
    res = _file(plain_mind, [_f("no_run:ws_alpha/x.py", stale=True)])
    assert res["filed"] == [] and "stale finding" in res["skipped"][0]["reason"]


def test_a_fixed_finding_clears_its_key_so_a_recurrence_files_again(plain_mind):
    gone = FINDINGS[0]
    rel = _file(plain_mind, FINDINGS)["filed"][0]["path"]
    res = _file(plain_mind, FINDINGS[1:])  # fresh ok read without it
    assert res["cleared"] == [gone.key] and gone.key not in _state(plain_mind)
    assert FINDINGS[2].key in _state(plain_mind)
    (plain_mind / rel).unlink()  # the fix shipped and its prompt closed
    assert [r["key"] for r in _file(plain_mind, FINDINGS)["filed"]] == [gone.key]


def test_only_the_freshly_read_source_clears(plain_mind):
    _file(plain_mind, FINDINGS)
    res = _file(plain_mind, [], reads={"census": OK})  # monitoring not read
    assert sorted(res["cleared"]) == sorted(f.key for f in FINDINGS[:2])
    assert list(_state(plain_mind)) == [FINDINGS[2].key]


def test_heart_green_state_is_migrated_once(plain_mind):
    home = plain_mind.parent / "home"
    home.mkdir()
    (home / W.LEGACY_STATE_NAME).write_text(json.dumps(
        {"version": 1, "reasons": {"ci:RepoX": {"first_seen": "t", "filed": "draft/a.md",
                                                "filed_at": "2026-11-20"}}}))
    _file(plain_mind, [], reads={"census": OK})
    assert _state(plain_mind)["ci:RepoX"]["source"] == "release"
    _file(plain_mind, [], reads={"release": OK})  # a fresh verdict without it
    _file(plain_mind, [], reads={"census": OK})
    assert "ci:RepoX" not in _state(plain_mind), "a cleared legacy key never comes back"


# --- classification ---------------------------------------------------------------

def test_an_intake_lane_refusal_is_skipped_never_filed(plain_mind):
    res = _file(plain_mind, [_f("no_run:ws_alpha/lane_less.py", lane="")])
    assert res["filed"] == [] and "lane refusal" in res["skipped"][0]["reason"]


# --- the write guard ------------------------------------------------------------

def test_a_main_git_checkout_is_refused(main_mind):
    res = _file(main_mind, FINDINGS)
    assert res["filed"] == [] and "main git checkout" in res["hold"]
    assert not list(main_mind.glob("draft/maintenance/**/*.md"))
    assert not (main_mind.parent / "home").exists(), "no state written either"


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _batch.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _board(rows):
    return {"ts": TS, "monitoring": {"findings": [
        {"id": f"no_run_census:{r['repo']}/{r['entry']}", "family": "no_run_census",
         "subject": f"{r['repo']}/{r['entry']}", "status": "yellow", "summary": "parked",
         "observed_at": TS, "fresh": True, "source": "snapshot", "evidence": r}
        for r in rows]}}


ROWS = [{"repo": "ws_alpha", "entry": "imaging/slow_one", "marker": "SLOW",
         "date": "2026-07-30", "reason": "slow"},
        {"repo": "ws_beta", "entry": "graphical/ep.py", "marker": "NEEDS_FIX",
         "date": "2026-08-03", "reason": "EP parked"}]


def _cli_args(tmp_path, mind, *extra):
    board = tmp_path / "board.json"
    board.write_text(json.dumps(_board(ROWS)))
    return ["maintain", "--file", "--mind", str(mind), "--sources", "census,monitoring",
            "--board-json", str(board), "--census-json", str(tmp_path / "absent.json"),
            "--home", str(tmp_path / "home"), "--at", NOW.isoformat(), *extra]


def test_cli_files_once_then_nothing(plain_mind, tmp_path):
    rc, out, err = _cli(_cli_args(tmp_path, plain_mind))
    assert rc == 0, err
    assert "Filed (2, cap 3)" in out and "maint_no_run_ws_alpha_imaging_slow_one.md" in out
    rc, out, _ = _cli(_cli_args(tmp_path, plain_mind, "--json"))
    doc = json.loads(out)
    assert rc == 0 and doc["write"]["filed"] == []
    assert len(list(plain_mind.glob("draft/maintenance/*/maint_*.md"))) == 2


def test_cli_refuses_a_main_checkout_and_a_missing_mind(main_mind, tmp_path):
    rc, out, err = _cli(_cli_args(tmp_path, main_mind))
    assert rc == 2 and "main git checkout" in err and not out
    assert not (tmp_path / "home").exists()
    rc, _, err = _cli(["maintain", "--file"])
    assert rc == 2 and "--mind" in err


def test_cli_exits_3_when_a_source_is_unread(plain_mind, tmp_path):
    args = _cli_args(tmp_path, plain_mind)
    args[args.index("--board-json") + 1] = str(tmp_path / "missing_board.json")
    rc, out, err = _cli(args)
    assert rc == 3 and "not read" in err
    assert not list(plain_mind.glob("draft/maintenance/**/*.md"))


# --- one filing path --------------------------------------------------------------

def test_green_file_mode_goes_through_the_writer(plain_mind, monkeypatch):
    calls = []
    real = W.file_findings

    def spy(findings, reads, mind, **kw):
        calls.append(([f.key for f in findings], dict(reads), kw.get("only")))
        return real(findings, reads, mind, **kw)

    monkeypatch.setattr(W, "file_findings", spy)
    heart = _green.from_doc({"verdict": "red", "ts": TS, "repository_reasons": [],
                             "red_reasons": ["RepoX: CI failure"]})
    heart.update(source="fixture", why="", age_hours=1.0)
    res = _green.run(plain_mind, heart, mode="file", state_path=plain_mind.parent / "home"
                     / W.STATE_NAME, now=NOW)
    assert calls and calls[0][0] == ["ci:RepoX"] and calls[0][2] == {"ci:RepoX"}
    assert calls[0][1]["release"]["ok"] and not calls[0][1]["release"]["stale"]
    assert res["filed"] == ["draft/maintenance/repox/maint_ci_repox.md"]
    text = (plain_mind / res["filed"][0]).read_text()
    assert "Source-key: ci:RepoX" in text and "Consequence: judge" in text \
        and "Unattended: never" in text
    assert _state(plain_mind)["ci:RepoX"]["source"] == "release"


def test_writer_imports_no_network_module():
    tree = ast.parse((BRAIN / "agents/conductors/batch/_maintain_write.py").read_text())
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"urllib", "urllib.request", "http.client", "socket", "subprocess"}, mods
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"load_board", "fetch_board", "load_census", "load_release",
                        "read_heart", "urlopen"}

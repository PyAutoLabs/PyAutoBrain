"""Phase 14.3 maintenance brief (PyAutoBrain#737).

Witness: `batch brief --new <slot> --maintenance --out F --mind M` reads the
boards (14.1), files through the writer (14.2) into a Mind that is a linked
worktree or not a git checkout, and writes a `shadow: yes` brief whose
`tasks:` are only generated prompts (a `Source-key:`), each with a Witness and
a tier; read flags, cap and tiers hold; claimed and blocked prompts are passed
over; `backlog: scoped` gains `sources:`; `--live` is refused without
`--gate-open`; `brief --check` validates the `maintenance:` block; a main
git checkout is refused. Placeholder repos and fixture boards only — nothing
reads a real Heart, the network or the shared Mind.
"""

from __future__ import annotations

import datetime as dt
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from _shift_fixtures import _batch, git_as_t as _git  # noqa: E402
import _brief  # noqa: E402
import _digest  # noqa: E402
import _maintain  # noqa: E402
import _maintain_write as W  # noqa: E402

NOW = dt.datetime(2026, 11, 27, 15, 0, tzinfo=dt.timezone.utc)
TS = "2026-11-27T14:00:00+00:00"
SLOT = "2026-11-28-am"
REVIEW_AT = "2026-11-28T12:00Z"
ISSUE = "https://github.com/example-org/ExampleMind/issues/7"


def _row(i: int, repo: str, glance: bool) -> dict:
    row = {"repo": repo, "entry": f"scripts/s{i}.py", "date": "2026-07-30",
           "reason": "slow"}
    row.update({"marker": "SLOW", "passed": True, "seconds": 10, "cap_s": 60} if glance
               else {"marker": "NEEDS_FIX"})
    return row


#: Seven census rows: four glance (a proven SLOW removal), three judge.
ROWS = [_row(i, f"ws_{c}", glance=i % 2 == 0) for i, c in enumerate("abcdefg")]


def _board(rows=ROWS, ts=TS) -> dict:
    return {"ts": ts, "monitoring": {"findings": [
        {"id": f"no_run_census:{r['repo']}/{r['entry']}", "family": "no_run_census",
         "subject": f"{r['repo']}/{r['entry']}", "status": "yellow", "summary": "parked",
         "observed_at": ts, "fresh": True, "source": "snapshot", "evidence": r}
        for r in rows]}}


def _mk(m: Path) -> Path:
    for d in ("draft", "active"):
        (m / d).mkdir(parents=True, exist_ok=True)
    (m / "queue.md").write_text("# Queue\n\n## Live\n", encoding="utf-8")
    return m


@pytest.fixture
def plain_mind(tmp_path):
    return _mk(tmp_path / "mind")


@pytest.fixture
def main_mind(tmp_path):
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


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = _batch.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _inputs(tmp_path, board=None, heart_verdict="GREEN", heart_ts=TS):
    b = tmp_path / "board.json"
    b.write_text(json.dumps(board if board is not None else _board()))
    h = tmp_path / "heart.json"
    h.write_text(json.dumps({"verdict": heart_verdict, "ts": heart_ts,
                             "repository_reasons": [], "red_reasons": []}))
    return b, h


def _new(tmp_path, mind, *extra, board=None, out="brief.md", mind_arg=True):
    b, h = _inputs(tmp_path, board)
    args = ["brief", "--new", SLOT, "--maintenance", "--review-at", REVIEW_AT,
            "--board-json", str(b), "--census-json", str(tmp_path / "absent.json"),
            "--heart-json", str(h), "--home", str(tmp_path / "home"),
            "--at", NOW.isoformat()]
    if out:
        args += ["--out", str(tmp_path / out)]
    if mind_arg:
        args += ["--mind", str(mind)]
    return _cli(args + list(extra))


def _parsed(path: Path) -> dict:
    return _brief.parse(path.read_text(encoding="utf-8"))["brief"]


def _check(tmp_path, brief: Path, mind: Path):
    _b, h = _inputs(tmp_path)
    return _cli(["brief", "--check", str(brief), "--mind", str(mind), "--heart-json", str(h),
                 "--no-premise", "--at", NOW.isoformat(), "--json"])


def _generated(mind: Path, rows=ROWS, cap=10) -> list[str]:
    """File generated prompts with the writer directly (an earlier run)."""
    raw = {"census": _maintain.census_findings({"rows": rows})}
    reads = {"census": {"ok": True, "stale": False, "partial": False,
                        "source": "fixture", "age_hours": 1.0}}
    res = W.file_findings(raw["census"], reads, mind, cap=cap,
                          state_path=mind.parent / "earlier" / W.STATE_NAME, now=NOW)
    return [r["path"] for r in res["filed"]]


HAND = """\
# A hand-written task

Type: feature
Target: ws_a
Repos:
- ws_a
Difficulty: small
Consequence: glance
Witness: a unit test
Review-minutes: 3
Unattended: ready

Body.
"""


# --- the witness ------------------------------------------------------------------

def test_maintenance_brief_is_shadow_and_names_only_generated_prompts(mind, tmp_path):
    hand = mind / "draft" / "feature" / "ws_a" / "hand.md"
    hand.parent.mkdir(parents=True)
    hand.write_text(HAND, encoding="utf-8")
    rc, out, err = _new(tmp_path, mind)
    assert rc == 0, err
    brief = _parsed(tmp_path / "brief.md")
    assert _brief.is_shadow(brief)
    assert "maintenance" in brief and _brief.maintenance_goal(brief).startswith("maintenance:")
    tasks = _brief.tasks_of(brief)
    assert len(tasks) >= 5
    assert not any("hand.md" in t for t in tasks)          # none named by hand
    for t in tasks:
        text = (mind / t).read_text()
        assert _brief.source_key(text)
        g = _batch.grade(mind / t, mind)
        assert g["witness"] and g["consequence"] in ("glance", "judge")
    # Cheapest tier first.
    tiers = [_batch.grade(mind / t, mind)["consequence"] for t in tasks]
    assert tiers == sorted(tiers, key=("notify", "glance", "judge").index)
    # The backlog stays within generated prompts.
    assert _brief.scoped_of(brief)["sources"] == ["maintenance"]
    assert "## Maintenance" in (tmp_path / "brief.md").read_text()
    # brief --check accepts it and lists each named task with tier and Witness.
    rc, out, err = _check(tmp_path, tmp_path / "brief.md", mind)
    res = json.loads(out)
    assert rc == 0 and res["ok"], res["errors"]
    assert [m["path"] for m in res["maintenance"]] == tasks
    assert all(m["witness"] and m["tier"] in ("glance", "judge") and m["source_key"]
               for m in res["maintenance"])
    assert any(n.startswith("Maintenance shift") for n in res["notes"])
    assert not any("goal 1 of goals.md" in w for w in res["warnings"])


def test_a_shadow_maintenance_brief_makes_no_shift_issue(plain_mind, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(_batch, "create_shift_issue", lambda *a, **k: called.append(a))
    rc, _, err = _new(tmp_path, plain_mind)
    assert rc == 0, err
    assert called == []
    assert "issue" not in _brief.parse((tmp_path / "brief.md").read_text())["top"]


def test_existing_generated_prompts_are_named_too(plain_mind, tmp_path):
    earlier = _generated(plain_mind, ROWS[:2])
    rc, _, err = _new(tmp_path, plain_mind, "--maintenance-cap", "7")
    assert rc == 0, err
    tasks = _brief.tasks_of(_parsed(tmp_path / "brief.md"))
    # The two filed earlier (not re-filed) and the five filed now.
    assert len(tasks) == 7 and set(earlier) <= set(tasks)
    assert len(list(plain_mind.glob("draft/maintenance/**/*.md"))) == 7


# --- read flags ---------------------------------------------------------------------

def test_a_stale_source_files_and_names_nothing(plain_mind, tmp_path):
    earlier = _generated(plain_mind, ROWS[:2])
    old = (NOW - dt.timedelta(hours=10)).isoformat()
    rc, _, err = _new(tmp_path, plain_mind, board=_board(ts=old))
    assert rc == 0, err
    assert "nothing filed or named from census" in err
    brief = _parsed(tmp_path / "brief.md")
    assert _brief.tasks_of(brief) == []
    assert sorted(str(p.relative_to(plain_mind)) for p in
                  plain_mind.glob("draft/**/*.md")) == sorted(earlier)   # nothing new
    text = (tmp_path / "brief.md").read_text()
    assert "stale read" in text and all(e in text for e in earlier)  # passed over, said


def test_a_key_the_fresh_read_no_longer_lists_is_not_named(plain_mind, tmp_path):
    gone = _generated(plain_mind, [_row(9, "ws_z", glance=True)])
    rc, _, err = _new(tmp_path, plain_mind)
    assert rc == 0, err
    assert gone[0] not in _brief.tasks_of(_parsed(tmp_path / "brief.md"))
    assert "no longer lists" in (tmp_path / "brief.md").read_text()


# --- cap and tiers ------------------------------------------------------------------

def test_the_cap_holds(plain_mind, tmp_path):
    rc, _, err = _new(tmp_path, plain_mind, "--maintenance-cap", "2")
    assert rc == 0, err
    brief = _parsed(tmp_path / "brief.md")
    assert len(_brief.tasks_of(brief)) == 2
    assert _brief.maintenance_of(brief)["cap"] == 2
    assert len(list(plain_mind.glob("draft/maintenance/**/*.md"))) == 2


def test_tiers_filter_what_is_named(plain_mind, tmp_path):
    rc, _, err = _new(tmp_path, plain_mind, "--maintenance-tiers", "glance",
                      "--maintenance-cap", "7")
    assert rc == 0, err
    tasks = _brief.tasks_of(_parsed(tmp_path / "brief.md"))
    assert len(tasks) == 4
    assert {_batch.grade(plain_mind / t, plain_mind)["consequence"] for t in tasks} == {"glance"}
    assert "not in the brief's tiers" in (tmp_path / "brief.md").read_text()


# --- claimed and blocked ------------------------------------------------------------

def test_claimed_and_blocked_prompts_are_passed_over(plain_mind, tmp_path):
    earlier = _generated(plain_mind, ROWS[:3])
    claimed, blocked = Path(earlier[0]), plain_mind / earlier[1]
    (plain_mind / "active.md").write_text(
        f"# Active\n\n## {claimed.stem}\n- issue: none\n- status: started\n",
        encoding="utf-8")
    blocked.write_text(blocked.read_text().replace(
        "Unattended:", "Blocked-by: ExampleOrg#1\nUnattended:", 1), encoding="utf-8")
    rc, _, err = _new(tmp_path, plain_mind)
    assert rc == 0, err
    tasks = _brief.tasks_of(_parsed(tmp_path / "brief.md"))
    assert earlier[0] not in tasks and earlier[1] not in tasks and earlier[2] in tasks
    text = (tmp_path / "brief.md").read_text()
    assert "claimed in active.md" in text and "blocked (ExampleOrg#1)" in text


# --- backlog: scoped + sources ------------------------------------------------------

def _rec(name, *, key="", tier="glance", epic=""):
    return {"path": f"draft/x/{name}.md", "source_key": key, "consequence": tier,
            "epic": epic, "themes": [], "lane": "any"}


def _scoped_brief(scoped: str, exclude: str = "") -> dict:
    text = ("- dispatched: 2026-11-28T00:00Z\n- review-at: 2026-11-28T12:00Z\n- brief:\n"
            "  - goals:\n    - 1. g\n  - backlog: scoped\n  - scoped:\n" + scoped
            + ("  - exclude:\n" + exclude if exclude else "") + "  - lanes: any\n")
    return _brief.parse(text)["brief"]


def test_scoped_sources_admit_only_generated_prompts():
    recs = [_rec("gen", key="no_run:r/a"), _rec("hand"), _rec("gen_judge", key="k2",
                                                              tier="judge")]
    kept, rejected, _ = _brief.scope(recs, _scoped_brief("    - sources: maintenance\n"))
    assert [Path(r["path"]).stem for r in kept] == ["gen", "gen_judge"]
    assert dict(rejected)["draft/x/hand.md"] == "outside the brief's scoped backlog"
    # sources narrows tiers: a generated judge prompt is out under tiers: glance.
    kept, _, _ = _brief.scope(recs, _scoped_brief("    - sources: maintenance\n"
                                                  "    - tiers: glance\n"))
    assert [Path(r["path"]).stem for r in kept] == ["gen"]
    assert _brief._scoped_match(recs[0], {"sources": ["maintenance"], "tiers": ["glance"]}) \
        == "scoped tier glance · source maintenance"
    # Without sources, tiers alone admit a hand-written prompt as before.
    kept, _, _ = _brief.scope(recs, _scoped_brief("    - tiers: glance\n"))
    assert {Path(r["path"]).stem for r in kept} == {"gen", "hand"}
    # exclude: sources keeps generated prompts out.
    kept, _, _ = _brief.scope(recs, _scoped_brief("    - tiers: glance\n",
                                                  "    - sources: maintenance\n"))
    assert [Path(r["path"]).stem for r in kept] == ["hand"]


def test_survey_records_carry_the_source_key(plain_mind):
    paths = _generated(plain_mind, ROWS[:1])
    rec = next(r for r in _batch.survey(plain_mind) if r["path"] == paths[0])
    assert rec["source_key"] == "no_run:ws_a/scripts/s0.py"


# --- --live --------------------------------------------------------------------------

def test_live_is_refused_without_gate_open(plain_mind, tmp_path):
    rc, out, err = _new(tmp_path, plain_mind, "--live")
    assert rc == 1 and "PyAutoBrain#574" in err and "--gate-open" in err
    assert not (tmp_path / "brief.md").exists()
    assert not list(plain_mind.glob("draft/**/*.md"))
    assert not (tmp_path / "home").exists()


def test_gate_open_alone_and_live_without_maintenance_are_usage_errors(plain_mind, tmp_path):
    assert _new(tmp_path, plain_mind, "--gate-open")[0] == 2
    rc, _, err = _cli(["brief", "--new", SLOT, "--review-at", REVIEW_AT, "--live"])
    assert rc == 2 and "--maintenance" in err


def test_live_with_gate_open_writes_the_gate_and_check_holds_it(plain_mind, tmp_path):
    rc, _, err = _new(tmp_path, plain_mind, "--live", "--gate-open", "--issue", ISSUE)
    assert rc == 0, err
    path = tmp_path / "brief.md"
    brief = _parsed(path)
    assert not _brief.is_shadow(brief)
    assert _brief.maintenance_of(brief)["gate_open"] == "PyAutoBrain#574"
    assert _brief.check(path, plain_mind)["ok"]
    # A shadow brief hand-edited to live without the gate is refused.
    shadow = tmp_path / "shadow.md"
    _new(tmp_path, plain_mind, out="shadow.md")
    shadow.write_text(shadow.read_text().replace("shadow: yes", "shadow: no"))
    res = _brief.check(shadow, plain_mind)
    assert not res["ok"] and any("gate-open" in e for e in res["errors"])


# --- brief --check validates the block -----------------------------------------------

@pytest.mark.parametrize("line, needle", [
    ("    - sources: census, gossip\n", "brief.maintenance.sources"),
    ("    - tiers: glance, urgent\n", "brief.maintenance.tiers"),
    ("    - cap: many\n", "brief.maintenance.cap"),
    ("    - colour: blue\n", "brief.maintenance.colour: unknown"),
])
def test_check_validates_the_maintenance_block(plain_mind, tmp_path, line, needle):
    rc, _, err = _new(tmp_path, plain_mind)
    assert rc == 0, err
    path = tmp_path / "brief.md"
    path.write_text(path.read_text().replace("  - maintenance:\n",
                                             "  - maintenance:\n" + line, 1))
    res = _brief.check(path, plain_mind)
    assert not res["ok"] and any(needle in e for e in res["errors"]), res["errors"]


def test_check_wants_the_maintenance_goal_and_flags_a_hand_task(plain_mind, tmp_path):
    hand = plain_mind / "draft" / "feature" / "ws_a" / "hand.md"
    hand.parent.mkdir(parents=True)
    hand.write_text(HAND, encoding="utf-8")
    _new(tmp_path, plain_mind)
    path = tmp_path / "brief.md"
    text = path.read_text().replace("1. maintenance: board", "1. tidy the board")
    text = text.replace("  - tasks:", "  - tasks:\n    - draft/feature/ws_a/hand.md", 1)
    path.write_text(text)
    res = _brief.check(path, plain_mind)
    assert any("maintenance brief names its goal" in e for e in res["errors"])
    assert any("hand.md has no `Source-key:`" in w for w in res["warnings"])


def test_check_refuses_an_unknown_scoped_source(plain_mind, tmp_path):
    _new(tmp_path, plain_mind)
    path = tmp_path / "brief.md"
    path.write_text(path.read_text().replace("- sources: maintenance", "- sources: rumours"))
    res = _brief.check(path, plain_mind)
    assert any("brief.scoped.sources: rumours" in e for e in res["errors"])


# --- the write guard -----------------------------------------------------------------

def test_a_main_checkout_mind_is_refused(main_mind, tmp_path):
    rc, out, err = _new(tmp_path, main_mind)
    assert rc == 2 and "main git checkout" in err
    assert not (tmp_path / "brief.md").exists()
    assert not list(main_mind.glob("draft/**/*.md"))
    assert not (tmp_path / "home").exists()


def test_an_implicit_mind_is_refused_with_out(plain_mind, tmp_path):
    rc, _, err = _new(tmp_path, plain_mind, mind_arg=False)
    assert rc == 2 and "--mind is required" in err
    assert not (tmp_path / "brief.md").exists()


def test_a_preview_files_nothing(plain_mind, tmp_path):
    earlier = _generated(plain_mind, ROWS[:1])
    rc, out, err = _new(tmp_path, plain_mind, out="")
    assert rc == 0, err
    assert "a preview (no --out) writes nothing" in out
    assert [str(p.relative_to(plain_mind)) for p in
            plain_mind.glob("draft/**/*.md")] == earlier
    assert earlier[0] in _brief.tasks_of(_brief.parse(out)["brief"])


# --- the digest names it ---------------------------------------------------------------

def test_the_digest_names_a_maintenance_shift(plain_mind, tmp_path):
    _new(tmp_path, plain_mind)
    brief = _parsed(tmp_path / "brief.md")
    line = _brief.maintenance_line(brief)
    assert line.startswith("Maintenance shift — goal: maintenance: board findings")
    slot = tmp_path / "slot"
    slot.mkdir()
    digest = _digest.build(brief, slot, {}, health=lambda url: {}, mind=plain_mind)
    assert line in digest
    assert _brief.maintenance_line({"goals": brief["goals"]}) == ""

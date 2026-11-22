"""`batch brief --new` — a shift brief whose goals come from the Mind's goals.md.

PyAutoMind#565: the human writes goals once (by hand or in chat) and every
brief starts from them. The witness: `--new` prefills
`brief.goals:` from goals.md in order, and `batch brief --check` passes on the
result. Fictional fixtures only.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


from _shift_fixtures import _batch  # noqa: E402
_brief = _batch._brief

GOALS = """# Goals

Prose header; the schema example below is not a goal.

```markdown
## <n>. <goal>
- epics: <slug>
```

## 1. Land the flywheel rework
- epics: flywheel-rework
- tags: gears

## 2. Clear review-ready PRs
- tags: gears, review
- note: the second wish
"""


def _git(mind, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_AUTHOR_DATE="2026-11-10T09:00:00Z",
               GIT_COMMITTER_DATE="2026-11-10T09:00:00Z")
    subprocess.run(["git", "-C", str(mind), *args], check=True, env=env,
                   capture_output=True)


def _mind(tmp_path: Path, goals: str | None = GOALS, git: bool = True) -> Path:
    """A Mind whose goals.md was committed by hand."""
    mind = tmp_path / "mind"
    (mind / "draft" / "feature" / "x").mkdir(parents=True)
    (mind / "batches").mkdir()
    if goals is not None:
        (mind / "goals.md").write_text(goals, encoding="utf-8")
        if git:
            _git(mind, "init", "-q")
            _git(mind, "add", "goals.md")
            _git(mind, "commit", "-qm", "goals by hand")
    return mind


def test_read_goals_reads_the_numbered_list_in_order(tmp_path):
    goals = _batch.read_goals(_mind(tmp_path))
    assert [g["text"] for g in goals] == ["Land the flywheel rework",
                                          "Clear review-ready PRs"]
    assert goals[0]["epics"] == ["flywheel-rework"]
    assert goals[1]["tags"] == ["gears", "review"]
    assert goals[1]["note"] == "the second wish"
    assert _batch.read_goals(tmp_path / "nowhere") == []


def test_new_prefills_goals_and_passes_check(tmp_path, capsys):
    mind = _mind(tmp_path)
    out = tmp_path / "brief.md"
    rc = _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                      "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out),
                      "--issue", "https://github.com/example-org/PyAutoMind/issues/1"])
    assert rc == 0
    text = out.read_text()
    # A live brief needs its shift issue (M3.6a, PyAutoBrain#659).
    assert "- issue: https://github.com/example-org/PyAutoMind/issues/1\n" in text
    assert ("  - goals:" in text and "    - 1. Land the flywheel rework\n"
            "    - 2. Clear review-ready PRs\n" in text)
    assert "  - backlog: scoped" in text
    assert "    - epics: flywheel-rework\n    - tags: gears, review\n" in text
    assert "  - merge-cap: 0" in text, "nothing merges unattended by default"
    brief = _brief.parse(text)["brief"]
    assert [c["text"] for c in brief["goals"]["children"]] == [
        "1. Land the flywheel rework", "2. Clear review-ready PRs"]
    res = _brief.check(out, mind)
    assert res["ok"], res["errors"]
    capsys.readouterr()
    assert _batch.main(["brief", "--check", str(out), "--mind", str(mind),
                        "--no-premise"]) == 0
    assert "goal 1 of goals.md" not in capsys.readouterr().out


def test_new_prints_to_stdout_by_default_and_never_writes_a_record(tmp_path, capsys):
    mind = _mind(tmp_path)
    assert _batch.main(["brief", "--new", "2026-11-14-pm", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Batch 2026-11-14 pm\n") and "- shift: afternoon" in out
    assert list((mind / "batches").iterdir()) == [], \
        "writing a record is the dispatch — the human's act, not this verb's"


def test_new_writes_the_5m_token_budget_and_leaves_the_caps_to_the_code(tmp_path, capsys):
    """PyAutoBrain#656 Witness: `brief --new` carries `token-budget: 5000000`
    and no `max-workers:` line, so a new shift gets the code default of 4."""
    mind = _mind(tmp_path)
    assert _batch.main(["brief", "--new", "2026-11-14-pm", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind)]) == 0
    out = capsys.readouterr().out
    assert "  - token-budget: 5000000\n" in out
    assert "max-workers:" not in out and "max-sessions:" not in out


def test_no_goals_still_composes_but_check_refuses(tmp_path, capsys):
    mind = _mind(tmp_path, None)
    out = tmp_path / "brief.md"
    assert _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out)]) == 0
    assert "goals.md has no goals" in capsys.readouterr().err
    res = _brief.check(out, mind)
    assert not res["ok"] and any(e.startswith("brief.goals:") for e in res["errors"])


def test_new_needs_a_slot_and_a_review_at(tmp_path):
    mind = _mind(tmp_path)
    assert _batch.main(["brief", "--new", "tomorrow", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind)]) == _batch.RC_USAGE
    assert _batch.main(["brief", "--new", "2026-11-14-am",
                        "--mind", str(mind)]) == _batch.RC_USAGE


def test_check_warns_when_goal_one_is_missing_from_the_brief(tmp_path, capsys):
    mind = _mind(tmp_path)
    out = tmp_path / "brief.md"
    text = _batch.new_brief(mind, "2026-11-14-am", "2099-01-01T12:00Z",
                            issue="https://github.com/example-org/PyAutoMind/issues/1")
    out.write_text(text.replace("1. Land the flywheel rework", "1. Something else"))
    assert _batch.main(["brief", "--check", str(out), "--mind", str(mind),
                        "--no-premise"]) == 0
    assert "goal 1 of goals.md" in capsys.readouterr().out


# --- the goal diff since the newest brief ---------------------------------

def test_new_reports_the_goal_diff_since_the_last_brief(tmp_path, capsys):
    mind = _mind(tmp_path, GOALS.replace(
        "## 2. Clear review-ready PRs\n- tags: gears, review\n- note: the second wish\n",
        "## 2. Tidy the review queue\n- tags: review\n\n## 3. Clear review-ready PRs\n"))
    (mind / "batches" / "2026-11-13-am.md").write_text(
        "# Batch\n- dispatched: 2026-11-13T08:00Z\n- review-at: 2026-11-13T11:00Z\n"
        "- brief:\n  - goals:\n    - 1. Clear review-ready PRs\n"
        "    - 2. Land the flywheel rework\n    - 3. Retire the old gearbox\n")
    assert _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind)]) == 0
    err = capsys.readouterr().err
    assert "goals since 2026-11-13-am.md:" in err
    assert "  + Tidy the review queue" in err
    assert "  - Retire the old gearbox" in err
    assert "  ~ Land the flywheel rework (2 → 1)" in err


def test_goals_are_copied_as_written_with_or_without_git(tmp_path):
    """The human is goals.md's only writer (the dashboard input path was
    removed, PyAutoBrain#640), so no goal is held back on provenance."""
    mind = _mind(tmp_path, git=False)
    text = _batch.new_brief(mind, "2026-11-14-am", "2099-01-01T12:00Z")
    assert [c["text"] for c in _brief.parse(text)["brief"]["goals"]["children"]] == [
        "1. Land the flywheel rework", "2. Clear review-ready PRs"]
    assert "# - " not in text


# --- RAL by default, and queued epics in scope (PyAutoBrain#696) ------------

LEDGER_TEXT = """# Widgets epic

Type: feature
Target: widgets
Difficulty: too-large
Autonomy: human-required
Status: campaign map — phases route one at a time
Epic: widgets
Lane: local-dev
"""
QUEUE_TEXT = """# Queue

## 1. Widgets epic
- kind: prompt
- ref: draft/feature/x/widgets_epic.md
"""


def test_an_unedited_new_brief_allows_ral_and_passes_check(tmp_path, capsys):
    """The Witness, part (a): `brief --new` writes `ral` into `lanes:` with a
    `ral-allowance:` block, and `brief --check` passes it as written."""
    mind = _mind(tmp_path, "# Goals\n\n## 1. Ship it\n")
    out = tmp_path / "brief.md"
    assert _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out),
                        "--issue", "https://github.com/example-org/PyAutoMind/issues/1"]) == 0
    text = out.read_text()
    brief = _brief.parse(text)["brief"]
    assert "ral" in _brief.lanes_of(brief)
    allow = _brief._keyed(brief["ral-allowance"]["children"])
    assert {k: v["value"] for k, v in allow.items()} == {
        "packets": "2", "partition": "ral", "cpu-hours": "64"}
    assert _brief.check(out, mind)["ok"]
    capsys.readouterr()
    assert _batch.main(["brief", "--check", str(out), "--mind", str(mind),
                        "--no-premise"]) == 0


def test_new_puts_queued_epics_in_scope_and_check_says_why_one_is_idle(tmp_path, capsys):
    """A queued epic ledger queues its phases, so `brief --new` scopes the
    brief to its epic beside the default tiers, and `brief --check` warns,
    one line per queued epic, why nothing of it starts."""
    mind = _mind(tmp_path, "# Goals\n\n## 1. Ship it\n")
    (mind / "draft" / "feature" / "x" / "widgets_epic.md").write_text(LEDGER_TEXT)
    (mind / "queue.md").write_text(QUEUE_TEXT)
    text = _batch.new_brief(mind, "2026-11-14-am", "2099-01-01T12:00Z",
                            issue="https://github.com/example-org/PyAutoMind/issues/1")
    scoped = _brief.scoped_of(_brief.parse(text)["brief"])
    assert scoped == {"tiers": ["notify", "glance"], "epics": ["widgets"]}
    out = tmp_path / "brief.md"
    out.write_text(text)
    assert _batch.main(["brief", "--check", str(out), "--mind", str(mind),
                        "--no-premise"]) == 0
    printed = capsys.readouterr().out
    assert ("! queued epic widgets (q1): nothing — no draft prompt for its next "
            "phase") in printed

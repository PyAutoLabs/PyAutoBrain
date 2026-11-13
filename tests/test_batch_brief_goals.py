"""`batch brief --new` — a shift brief whose goals come from the Mind's goals.md.

PyAutoMind#565: the human writes goals once (by hand or from the dashboard's
Goals box) and every brief starts from them. The witness: `--new` prefills
`brief.goals:` from goals.md in order, and `batch brief --check` passes on the
result. Fictional fixtures only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_goals", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_batch)
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


def _mind(tmp_path: Path, goals: str | None = GOALS) -> Path:
    mind = tmp_path / "mind"
    (mind / "draft" / "feature" / "x").mkdir(parents=True)
    (mind / "batches").mkdir()
    if goals is not None:
        (mind / "goals.md").write_text(goals, encoding="utf-8")
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
                      "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out)])
    assert rc == 0
    text = out.read_text()
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


def test_goals_without_epics_or_tags_fill_idle(tmp_path):
    mind = _mind(tmp_path, "# Goals\n\n## 1. Ship it\n")
    text = _batch.new_brief(mind, "2026-11-14-am", "2099-01-01T12:00Z")
    assert "  - backlog: fill-idle" in text and "scoped:" not in text


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
    text = _batch.new_brief(mind, "2026-11-14-am", "2099-01-01T12:00Z")
    out.write_text(text.replace("1. Land the flywheel rework", "1. Something else"))
    assert _batch.main(["brief", "--check", str(out), "--mind", str(mind),
                        "--no-premise"]) == 0
    assert "goal 1 of goals.md" in capsys.readouterr().out

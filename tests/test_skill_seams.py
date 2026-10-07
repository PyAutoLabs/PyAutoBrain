"""Skill seams for the Heart at the door (PyAutoBrain#423).

The development entry skills must name the step, and start_dev must point at
the AUTONOMY.md override by its section title rather than restating the rule —
so a rename of either side fails here instead of leaving a dangling pointer.
"""

from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
SKILLS = BRAIN_HOME / "skills"
STEP = "Heart at the door"
OVERRIDE = "Human override for Heart RED (development only)"


def _read(rel):
    return (SKILLS / rel).read_text(encoding="utf-8")


def test_entry_skills_name_the_step():
    for rel in ("start_dev/start_dev.md",
                "route/route.md"):
        assert STEP in _read(rel), rel


def test_start_dev_step_runs_the_helper_before_the_resume_check():
    text = _read("start_dev/start_dev.md")
    door, resume = text.index(f"### 0a. {STEP}"), text.index("### 0. Sync + resume")
    assert door < resume
    assert "bin/heart_feed.py" in text[door:resume]
    assert (BRAIN_HOME / "bin" / "heart_feed.py").is_file()


def test_start_dev_points_at_the_autonomy_override_by_title():
    assert OVERRIDE in _read("start_dev/start_dev.md")
    assert f"## {OVERRIDE}" in (BRAIN_HOME / "AUTONOMY.md").read_text(encoding="utf-8")


def test_workflow_heart_gate_mentions_the_door():
    text = _read("WORKFLOW.md")
    section = text[text.index("## Heart gate"):]
    section = section[:section.index("\n## ", 1)]
    assert STEP in section and "heart_feed.py" in section

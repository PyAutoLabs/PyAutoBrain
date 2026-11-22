"""tests/test_conductor_discovery.py — conductor discovery vs the Mind lifecycle layout.

The companion to `test_sizing_paths.py`. That file locks how a prompt path is
*read*; this one locks how prompts are *found* — the half the 2026-07-16 sweep
missed, which left `feature` / `bug` / `refactor` selection silently returning
"no prompts found" against a live backlog for as long as the split had been in
place (all three rooted discovery at the pre-#71 `mind/<work-type>/`).

The end-to-end cases at the bottom are the real regression guard: they assert
each conductor's selection surface is non-empty on a draft/-layout Mind, which
is the exact assertion that would have caught the original bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "feature"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "bug"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "refactor"))

from _sizing import discover_prompts, empty_discovery_reason  # noqa: E402
import _feature  # noqa: E402
import _bug  # noqa: E402
import _refactor  # noqa: E402


def _write(mind: Path, rel: str, work_type: str = "bug", target: str = "PyAutoHands") -> Path:
    p = mind / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"# A task\n\n"
        f"Type: {work_type}\n"
        f"Target: {target}\n"
        f"Repos:\n- {target}\n"
        f"Difficulty: small\nAutonomy: safe\nPriority: normal\nStatus: formalised\n\n"
        f"Body mentioning @{target}.\n"
    )
    return p


def _rel(mind: Path, paths) -> set[str]:
    return {str(p.relative_to(mind)) for p in paths}


# --- discover_prompts: the layout regimes -------------------------------------
@pytest.mark.parametrize("prompts", [
    pytest.param(["draft/bug/pyautohands/one.md", "draft/bug/pyautofit/two.md"],
                 id="draft-layout-is-discovered"),
    # Pre-migration paths keep working, mirroring parse_prompt's third regime.
    pytest.param(["bug/pyautohands/legacy.md"], id="legacy-flat-layout-still-resolves"),
])
def test_layout_is_discovered(tmp_path, prompts):
    for rel in prompts:
        _write(tmp_path, rel)
    assert _rel(tmp_path, discover_prompts(tmp_path, "bug")) == set(prompts)


def test_both_layouts_coexist_without_duplicates(tmp_path):
    _write(tmp_path, "draft/bug/pyautohands/one.md")
    _write(tmp_path, "bug/pyautohands/legacy.md")
    found = discover_prompts(tmp_path, "bug")
    assert _rel(tmp_path, found) == {"draft/bug/pyautohands/one.md", "bug/pyautohands/legacy.md"}
    assert len(found) == len(set(found))


def test_work_types_do_not_bleed_into_each_other(tmp_path):
    _write(tmp_path, "draft/bug/pyautohands/a_bug.md", work_type="bug")
    _write(tmp_path, "draft/feature/pyautohands/a_feature.md", work_type="feature")
    assert _rel(tmp_path, discover_prompts(tmp_path, "bug")) == {"draft/bug/pyautohands/a_bug.md"}
    assert _rel(tmp_path, discover_prompts(tmp_path, "feature")) == {
        "draft/feature/pyautohands/a_feature.md"
    }


# --- discover_prompts: what must stay out -------------------------------------
def test_readme_is_not_a_task(tmp_path):
    _write(tmp_path, "draft/bug/health_fixes/one.md")
    (tmp_path / "draft/bug/health_fixes/README.md").write_text("# documents the folder\n")
    assert _rel(tmp_path, discover_prompts(tmp_path, "bug")) == {"draft/bug/health_fixes/one.md"}


@pytest.mark.parametrize("elsewhere", [
    # complete/ holds shipped records; selection must never resurface them.
    pytest.param(["complete/2026/07/bug/shipped.md", "complete/archive/shelved/bug/old.md"],
                 id="complete-records-are-not-backlog"),
    # active/ is issued, in-flight work; selection answers 'what next'.
    pytest.param(["active/issued.md"], id="active-is-not-discovered"),
])
def test_only_the_backlog_is_discovered(tmp_path, elsewhere):
    _write(tmp_path, "draft/bug/pyautohands/live.md")
    for rel in elsewhere:
        _write(tmp_path, rel)
    assert _rel(tmp_path, discover_prompts(tmp_path, "bug")) == {"draft/bug/pyautohands/live.md"}


def test_missing_roots_are_not_an_error(tmp_path):
    assert discover_prompts(tmp_path, "refactor") == []


# --- end-to-end: the assertion that would have caught the original bug --------
def _populated(tmp_path) -> Path:
    _write(tmp_path, "draft/feature/pyautohands/feat.md", work_type="feature")
    _write(tmp_path, "draft/bug/pyautohands/bug.md", work_type="bug")
    _write(tmp_path, "draft/refactor/pyautohands/ref.md", work_type="refactor")
    return tmp_path


def _ranked(selection):
    """(paths, total) from a ranking conductor's `(ranked, total)`."""
    ranked, total = selection
    return [r["path"] for r in ranked], total


@pytest.mark.parametrize("select,expected", [
    pytest.param(lambda mind: _ranked(_feature.select(mind, {}, 5)),
                 (["draft/feature/pyautohands/feat.md"], 1), id="feature-selection"),
    pytest.param(lambda mind: _ranked(_bug.select_bug(mind, {}, 5)),
                 (["draft/bug/pyautohands/bug.md"], 1), id="bug-selection"),
    pytest.param(lambda mind: _refactor.candidates(mind)["backlog"],
                 ["draft/refactor/pyautohands/ref.md"], id="refactor-backlog"),
])
def test_selection_is_non_empty_on_draft_layout(tmp_path, select, expected):
    assert select(_populated(tmp_path)) == expected


# --- empty_discovery_reason: an empty result must say WHICH empty it is -------
# A flat "no prompts found" reads the same whether the backlog is bare or the
# root is wrong. That ambiguity is what let the original bug survive four weeks,
# so the three cases below must stay mutually distinguishable.
def test_reason_flags_a_path_that_is_not_a_directory(tmp_path):
    reason = empty_discovery_reason(tmp_path / "nope", "bug")
    assert "not a directory" in reason


def test_reason_flags_a_directory_that_is_not_a_mind(tmp_path):
    (tmp_path / "random").mkdir()
    reason = empty_discovery_reason(tmp_path / "random", "bug")
    assert "does not look like a PyAutoMind checkout" in reason
    assert "PYAUTO_MIND" in reason


def test_reason_names_the_missing_work_type_and_lists_those_present(tmp_path):
    _write(tmp_path, "draft/bug/pyautohands/one.md")
    _write(tmp_path, "draft/feature/pyautohands/two.md", work_type="feature")
    (tmp_path / "active.md").write_text("# Active Tasks\n")
    reason = empty_discovery_reason(tmp_path, "refactor")
    assert "no 'refactor' work-type folder" in reason
    assert "work-types present: bug, feature" in reason


def test_reason_reports_a_genuinely_empty_backlog(tmp_path):
    (tmp_path / "draft" / "bug").mkdir(parents=True)
    (tmp_path / "active.md").write_text("# Active Tasks\n")
    reason = empty_discovery_reason(tmp_path, "bug")
    assert "holds no prompts" in reason
    assert "backlog genuinely empty" in reason


def test_the_three_empty_causes_are_mutually_distinguishable(tmp_path):
    not_a_mind = tmp_path / "random"
    not_a_mind.mkdir()

    missing_type = tmp_path / "mind_a"
    _write(missing_type, "draft/bug/pyautohands/one.md")
    (missing_type / "active.md").write_text("# Active Tasks\n")

    bare = tmp_path / "mind_b"
    (bare / "draft" / "bug").mkdir(parents=True)
    (bare / "active.md").write_text("# Active Tasks\n")

    reasons = {
        empty_discovery_reason(not_a_mind, "bug"),
        empty_discovery_reason(missing_type, "refactor"),
        empty_discovery_reason(bare, "bug"),
    }
    assert len(reasons) == 3


def test_a_freshly_spawned_mind_without_draft_is_still_a_mind(tmp_path):
    """A Mind that has taken no work yet has active.md but no draft/ — that is
    an empty backlog, not a bad path."""
    (tmp_path / "active.md").write_text("# Active Tasks\n")
    reason = empty_discovery_reason(tmp_path, "bug")
    assert "does not look like a PyAutoMind checkout" not in reason
    assert "no 'bug' work-type folder" in reason

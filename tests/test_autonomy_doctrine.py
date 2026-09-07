"""Doc-contract tests for the 2026-09-07 decide-and-flag extension
(PyAutoBrain#363).

Under an explicit `--auto` launch an effective-`supervised` run's ship
checkpoint no longer parks: it resolves to decide-and-flag and the run ends at
PR-open, where the PR review is the human approval the level exists to provide.
That is doctrine, not code, so it is pinned against the canonical text of
AUTONOMY.md — an edit that quietly drops the scope sentence or the revert
condition fails loudly here rather than leaving the planner admitting work the
contract no longer covers.
"""

from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
AUTONOMY = (BRAIN_HOME / "AUTONOMY.md").read_text()

SECTION_HEADER = "### Decide-and-flag"


def _norm(text):
    """Lowercase, strip markdown emphasis, and collapse whitespace so assertions
    ignore ``**``/``` ` ``` and line wrapping."""
    return " ".join(text.replace("*", "").replace("`", "").lower().split())


def _heading():
    """The decide-and-flag heading line, verbatim."""
    for line in AUTONOMY.splitlines():
        if line.startswith(SECTION_HEADER):
            return line
    raise AssertionError("decide-and-flag heading not found in AUTONOMY.md")


def _section():
    """The decide-and-flag section body (header line to the next ``## ``)."""
    head = _heading()
    start = AUTONOMY.index(head)
    rest = AUTONOMY[start + len(head):]
    end = rest.find("\n## ")
    return _norm(rest if end == -1 else rest[:end])


def test_heading_records_the_extension_date():
    # The heading is the dated audit trail: the rule was born 2026-08-30 for
    # batch launches and widened 2026-09-07 to every explicit --auto launch.
    head = _norm(_heading())
    assert "extended 2026-09-07" in head
    assert "--auto launches" in head


def test_section_carries_the_dated_extension_paragraph():
    sec = _section()
    assert "extended 2026-09-07" in sec
    assert "ship checkpoint" in sec


def test_extension_is_scoped_to_auto_launches_only():
    # Interactive supervised runs keep park-and-ask, and the levels that never
    # run unattended are untouched.
    sec = _section()
    assert "explicit --auto launches only" in sec
    for untouched in ("human-required", "unattended: never", "blocked-by:"):
        assert untouched in sec, untouched


def test_the_judge_tier_limit_survives_the_extension():
    # The extension changes WHERE the ship checkpoint lands, never a limit.
    sec = _section()
    assert "never for a judge-tier task" in sec


def test_levels_table_supervised_ship_cell_names_decide_and_flag():
    row = next(line for line in AUTONOMY.splitlines()
               if line.startswith("| Ship PR sign-off |"))
    supervised = _norm(row.split("|")[3])
    assert "decide-and-flag" in supervised
    assert "--auto" in supervised
    assert "2026-09-07" in supervised


def test_revert_condition_returns_the_ship_checkpoint_to_park_and_ask():
    sec = _section()
    assert "revert condition:" in sec
    assert "park-and-ask" in sec
    # the second, 2026-09-07 condition: one unwanted PR retires the extension
    assert "would have wanted stopped before it existed" in sec

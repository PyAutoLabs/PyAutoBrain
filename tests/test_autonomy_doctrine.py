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


# --- Shift briefs and unattended glance (2026-11-03, PyAutoBrain#551) -------

SHIFT_HEADER = "## Shift briefs and unattended `glance` — 2026-11-03"
SHIFT_SUBRULES = (
    "### Shift brief = launch — 2026-11-03",
    "### Unattended `glance` merges — 2026-11-03",
    "### One Mind writer per shift — 2026-11-03",
    "### Goal decomposition files drafts only — 2026-11-03",
    "### The push-notification test — 2026-11-03",
)


def _shift_section():
    """The shift-brief H2 body, raw (header line to the next ``## ``)."""
    assert AUTONOMY.count(SHIFT_HEADER) == 1, "shift-brief heading missing or duplicated"
    rest = AUTONOMY[AUTONOMY.index(SHIFT_HEADER) + len(SHIFT_HEADER):]
    return rest[:rest.find("\n## ")]


def test_shift_section_sits_after_merge_authority():
    # It extends the 2026-10-02 section, so it is read after it.
    assert AUTONOMY.index("## Merge authority follows Consequence — 2026-10-02") \
        < AUTONOMY.index(SHIFT_HEADER)


def test_shift_section_has_five_dated_subrules_each_with_a_revert_condition():
    sec = _shift_section()
    for head in SHIFT_SUBRULES:
        assert head in sec, head
    assert _norm(sec).count("revert condition:") == len(SHIFT_SUBRULES)


def test_unattended_glance_never_reaches_judge_or_decision_taken():
    sec = _norm(_shift_section())
    assert "never judge" in sec
    assert "never a decision-taken pr" in sec
    assert "never a release" in sec
    assert "merge-cap:" in sec
    assert "independent session" in sec


def test_brief_is_the_launch_and_no_brief_dispatches_nothing():
    sec = _norm(_shift_section())
    assert "is the launch act" in sec
    assert "no open brief dispatches nothing" in sec


def test_consumers_and_invariant_name_the_shift_section():
    consumers = AUTONOMY[AUTONOMY.index("## Consumers"):]
    assert "Shift briefs and unattended `glance`" in consumers
    invariants = _norm(AUTONOMY[AUTONOMY.index("## Hard invariants"):])
    assert "\"shift briefs and unattended glance\" (2026-11-03) grant them" in invariants


# --- The watcher's network surface (2026-11-03, PyAutoBrain#555) -------------

WATCHER_HEADER = "## The watcher's network surface — 2026-11-03"


def _watcher_section():
    assert AUTONOMY.count(WATCHER_HEADER) == 1
    rest = AUTONOMY[AUTONOMY.index(WATCHER_HEADER) + len(WATCHER_HEADER):]
    return _norm(rest[:rest.find("\n## ")])


def test_watcher_section_names_exactly_its_surface_and_a_revert_condition():
    sec = _watcher_section()
    for surface in ("gh pr checks", "claude agents --json", "one comment per shift"):
        assert surface in sec, surface
    assert "revert condition:" in sec
    assert "laptop-only" in sec and "never" in sec


def test_the_network_invariant_points_at_the_watcher_section():
    invariants = AUTONOMY[AUTONOMY.index("## Hard invariants"):]
    assert "A third exception, added 2026-11-03" in invariants
    assert "The watcher's network surface — 2026-11-03" in invariants
    assert "Any *further* network surface in the Brain is a new decision" in invariants


def test_watcher_section_is_a_consumer_entry():
    consumers = AUTONOMY[AUTONOMY.index("## Consumers"):]
    assert "The watcher's network surface" in consumers


# --- The `glance` Shadow-window ruling (2026-11-04, PyAutoBrain#566) --------

RULING_HEADER = "## The `glance` Shadow-window ruling — 2026-11-04"


def _ruling_section():
    assert AUTONOMY.count(RULING_HEADER) == 1, "ruling heading missing or duplicated"
    rest = AUTONOMY[AUTONOMY.index(RULING_HEADER) + len(RULING_HEADER):]
    return _norm(rest[:rest.find("\n## ")])


def test_ruling_sits_between_merge_authority_and_shift_briefs():
    assert AUTONOMY.index("## Merge authority follows Consequence — 2026-10-02") \
        < AUTONOMY.index(RULING_HEADER) < AUTONOMY.index(SHIFT_HEADER)


def test_a_witness_that_did_not_pass_never_auto_merges():
    sec = _ruling_section()
    assert "a witness: that did not pass means a human /prm" in sec
    for form in ("none", "n/a", "partial", "waived"):
        assert form in sec, form


def test_ruling_records_the_audit_outcome():
    sec = _ruling_section()
    assert "confirmed, narrowed" in sec
    assert "8 of 8 ok" in sec
    assert "69 counted rows" in sec
    # The tier-drift narrowing was conditional on a `minded` row; none was.
    assert "not adopted" in sec
    assert "the declared consequence: stays the authority" in sec


def test_unattended_glance_counts_in_its_own_stage_two_sub_window():
    sec = _ruling_section()
    assert "stage-2 sub-window" in sec
    assert "first 10 needs the independent different-model adversary leg actually run" in sec
    assert "counted apart from the stage-1 rows" in sec
    # The shift section's unattended sub-rule points back at the ruling.
    assert "The `glance` Shadow-window ruling — 2026-11-04" in AUTONOMY[AUTONOMY.index(SHIFT_HEADER):]


def test_ruling_keeps_the_revert_condition_and_is_a_consumer_entry():
    sec = _ruling_section()
    assert sec.count("revert condition:") == 1
    assert "any reverted row demotes glance" in sec
    consumers = AUTONOMY[AUTONOMY.index("## Consumers"):]
    assert "Shadow-window ruling" in consumers

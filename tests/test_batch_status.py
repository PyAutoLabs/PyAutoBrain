"""tests/test_batch_status.py — the batch-status box's one reading.

`agents/conductors/batch/_status.py` is imported by both dashboards
(`_cortex.py`, `_intake.py`) and by `_batch.py` for its shared vocabulary.
This file exercises the module directly, against constructed records rather
than a live checkout: the box's own rules are organ-agnostic (dev is a
dispatch-and-review sitting, science is a rolling board) and belong to
`_status.py` alone, not to either organ's fixture.

Three things this file defends, because getting any of them wrong makes the
box lie about what a human still has to do:

- The **dev** rule: the button waits for `collected:`, and the box itself
  disappears once the slot has been reviewed (`reviewed-at:` OR a review file
  on disk — either says the sitting is over).
- The **cortex** rule: the board is rolling — a slot stays open while any
  member is still `submitted`/`running`/`pulled`/`awaiting-ruling`, the
  button appears as soon as ONE member is `awaiting-ruling`, and a member
  named on a `- carried:` line does not hold its OWN slot open (it belongs to
  the next one).
- `pick_slot` reads `- dispatched:`, never the record's file name — two slots
  dispatched on the same date sort by clock time, not by the slot label.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_status_under_test", BRAIN / "agents" / "conductors" / "batch" / "_status.py")
_status = importlib.util.module_from_spec(_spec)
sys.modules["_status_under_test"] = _status
_spec.loader.exec_module(_status)

PAGES = "https://pyautolabs.github.io/PyAutoMind/"


# ------------------------------------------------------------------- dev ---
def test_dev_in_flight_member_reads_as_in_progress_with_no_button():
    keys = {"dispatched": ["2026-09-03T18:00Z"]}
    members = [{"slug": "autofit-resampling-info", "outcome": "RUNNING"}]
    st = _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                            pages=PAGES)
    assert st is not None
    assert st["reviewable"] is False
    assert st["url"] == ""
    assert st["members"][0]["state"] == _status.IN_PROGRESS
    assert "Nothing to review yet" in _status.render_md(st)
    assert 'class="go"' not in _status.render_html(st)


def test_dev_collected_slot_gets_the_button():
    keys = {"dispatched": ["2026-09-03T18:00Z"], "collected": ["2026-09-03T20:00Z"]}
    members = [{"slug": "autofit-resampling-info",
                "outcome": "DELIVERED (PyAutoFit#1554)"}]
    st = _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                            pages=PAGES)
    assert st is not None
    assert st["reviewable"] is True
    assert st["url"] == f"{PAGES}packets/2026-09-03-pm.html"
    assert 'class="go"' in _status.render_html(st)
    assert "[Review this batch →]" in _status.render_md(st)


def test_dev_slot_closes_on_reviewed_at_key():
    keys = {"dispatched": ["2026-09-03T18:00Z"], "collected": ["2026-09-03T20:00Z"],
            "reviewed-at": ["2026-09-03T21:00Z"]}
    members = [{"slug": "autofit-resampling-info", "outcome": "DELIVERED"}]
    assert _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                              pages=PAGES) is None


def test_dev_slot_closes_when_a_review_file_exists_even_without_the_key():
    # `_intake.py`'s adapter passes `review_exists` from the reviews/ folder —
    # a record transcribed or migrated in may carry no `reviewed-at:` line at
    # all, and the box must still treat the sitting as over.
    keys = {"dispatched": ["2026-09-03T18:00Z"], "collected": ["2026-09-03T20:00Z"]}
    members = [{"slug": "autofit-resampling-info", "outcome": "DELIVERED"}]
    assert _status.dev_status("2026-09-03-pm", keys, members, review_exists=True,
                              pages=PAGES) is None


def test_dev_member_with_no_outcome_is_not_delivered():
    keys = {"dispatched": ["2026-09-03T18:00Z"]}
    members = [{"slug": "silent-member", "outcome": ""}]
    st = _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                            pages=PAGES)
    assert st["members"][0]["state"] == _status.NOT_DELIVERED


# --------------------------------------------------------------- cortex ---
def _cortex_member(slug, state):
    return {"slug": slug, "state": state}


def test_cortex_mixed_board_is_open_and_reviewable_with_no_per_member_control():
    keys = {"dispatched": ["2026-09-01T09:00Z"]}
    members = [_cortex_member("05_running_array", "running"),
               _cortex_member("07_awaiting_ruling", "awaiting-ruling")]
    states = {"05_running_array": "running", "07_awaiting_ruling": "awaiting-ruling"}
    live = {"05_running_array": "wall 3:10 of 8:00 (40%)"}
    st = _status.cortex_status("2026-09-01-pm", keys, members, states, live, PAGES)
    assert st is not None
    assert st["reviewable"] is True
    assert st["url"] == f"{PAGES}packets/2026-09-01-pm.html"
    rows = {r["slug"]: r for r in st["members"]}
    assert rows["05_running_array"]["state"] == _status.IN_PROGRESS
    assert rows["07_awaiting_ruling"]["state"] == _status.AWAITING
    # Exactly one button for the whole box, never a per-member review control.
    html = _status.render_html(st)
    assert html.count('class="go"') == 1


def test_cortex_all_ruled_slot_is_closed():
    keys = {"dispatched": ["2026-09-01T09:00Z"]}
    members = [_cortex_member("08_accepted", "accepted"),
               _cortex_member("09_rerun", "rerun"),
               _cortex_member("10_dropped", "dropped")]
    states = {"08_accepted": "accepted", "09_rerun": "rerun",
              "10_dropped": "dropped"}
    assert _status.cortex_status("2026-09-01-pm", keys, members, states, {},
                                 PAGES) is None


def test_cortex_carried_member_does_not_reopen_its_own_slot():
    # The member is CURRENTLY awaiting-ruling (per the phase file's own
    # `State:`), but the record hands it to the next slot — it must not hold
    # THIS one open, or a closed batch would render as still in flight.
    keys = {"dispatched": ["2026-09-02T17:51Z"],
            "carried": ["refs_v1_positions_on_completion — still submitted "
                        "at review"]}
    members = [_cortex_member("phase2_nss_mainline_gate_a_reuse", "awaiting-ruling"),
               _cortex_member("refs_v1_positions_on_completion", "submitted")]
    states = {"phase2_nss_mainline_gate_a_reuse": "accepted",
              "refs_v1_positions_on_completion": "awaiting-ruling"}
    assert _status.cortex_status("2026-09-02-pm", keys, members, states, {},
                                 PAGES) is None


def test_cortex_carried_line_reads_the_double_hyphen_typed_em_dash():
    keys = {"dispatched": ["2026-09-02T17:51Z"],
            "carried": ["refs_v1_positions_on_completion -- still submitted "
                        "at review"]}
    members = [_cortex_member("refs_v1_positions_on_completion", "submitted")]
    states = {"refs_v1_positions_on_completion": "awaiting-ruling"}
    assert _status.cortex_status("2026-09-02-pm", keys, members, states, {},
                                 PAGES) is None


# ------------------------------------------------------------- pick_slot ---
def _dev_reading(slot, dispatched):
    members = [{"slug": "m", "outcome": "RUNNING"}]
    return _status.dev_status(slot, {"dispatched": [dispatched]}, members,
                              review_exists=False, pages=PAGES)


def test_pick_slot_reads_dispatched_not_the_lexical_slot_name():
    # "night" < "pm" lexically, so a slot-name pick would choose the earlier
    # afternoon slot even though the evening one dispatched later the same day.
    pm = _dev_reading("2026-09-01-pm", "2026-09-01T13:00Z")
    night = _dev_reading("2026-09-01-night", "2026-09-01T23:00Z")
    assert _status.pick_slot([pm, night]) is night
    assert _status.pick_slot([night, pm]) is night


def test_pick_slot_ignores_closed_records_and_returns_none_when_all_are():
    assert _status.pick_slot([None, None]) is None
    pm = _dev_reading("2026-09-01-pm", "2026-09-01T13:00Z")
    assert _status.pick_slot([None, pm]) is pm


# --------------------------------------------------------- md/html parity ---
def test_md_and_html_agree_on_every_slug_and_the_review_url():
    keys = {"dispatched": ["2026-09-03T18:00Z"], "collected": ["2026-09-03T20:00Z"]}
    members = [{"slug": "autofit-resampling-info", "outcome": "DELIVERED"},
               {"slug": "autonerves-colab-silence", "outcome": "MERGED"}]
    st = _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                            pages=PAGES)
    md, html = _status.render_md(st), _status.render_html(st)
    for m in members:
        assert m["slug"] in md
        assert m["slug"] in html
    assert st["url"] in md
    assert st["url"] in html


def test_fixture_when_nothing_is_open():
    assert _status.render_md(None) == "> **No batch in flight.**"
    assert _status.render_html(None) == (
        '<div class="verdict ok"><b>No batch in flight.</b></div>')

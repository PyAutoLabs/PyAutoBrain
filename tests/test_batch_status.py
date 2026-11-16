"""tests/test_batch_status.py — the batch-status box's one reading.

`agents/conductors/batch/_status.py` is imported by the Mind's dashboard
(`_intake.py`) and by `_batch.py` for its shared vocabulary. This file
exercises the module directly, against constructed records rather than a live
checkout: the box's own rules belong to `_status.py` alone, not to the Mind's
fixture.

Two things this file defends, because getting either wrong makes the box lie
about what a human still has to do:

- The **dev** rule: the button waits for `collected:`, and the box itself
  disappears once the slot has been reviewed (`reviewed-at:` OR a review file
  on disk — either says the sitting is over).
- `pick_slot` reads `- dispatched:`, never the record's file name — two slots
  dispatched on the same date sort by clock time, not by the slot label.

(A second reading, for the Cortex's rolling science board, lived here until
2026-09-03; the science review slot was retired with it.)
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

PAGES = "https://exampleorg.github.io/PyAutoMind/"


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
    assert "_(nothing to review yet)_" in _status.render_md(st)
    assert _status.is_live(st) and _status.badge(st) == "LIVE · 1 in progress"
    assert 'class="go"' not in _status.render_html(st)


def test_dev_collected_slot_gets_the_button():
    keys = {"dispatched": ["2026-09-03T18:00Z"], "collected": ["2026-09-03T20:00Z"]}
    members = [{"slug": "autofit-resampling-info",
                "outcome": "DELIVERED (Widgets#1554)"}]
    st = _status.dev_status("2026-09-03-pm", keys, members, review_exists=False,
                            pages=PAGES)
    assert st is not None
    assert st["reviewable"] is True
    assert st["url"] == f"{PAGES}packets/2026-09-03-pm.html"
    assert 'class="go"' in _status.render_html(st)
    assert "[Review this batch →]" in _status.render_md(st)
    assert not _status.is_live(st) and _status.badge(st) == "1 to review"


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


def test_fixture_when_there_is_no_shift_at_all():
    assert _status.render_md(None) == "**Shift**\n\n_(no shift yet)_"
    assert _status.render_html(None) == (
        '<h3 id="shift">Shift</h3>\n<p class="muted">(no shift yet)</p>')
    assert _status.badge(None) == ""


def test_a_live_shift_shows_its_detail_and_links_the_shift_issue_tidily():
    """PyAutoBrain#650: the Shift part of the Autopilot block. The watcher's
    raw `— status: <url>` becomes a link named by the shift issue's number."""
    url = "https://github.com/o/PyAutoMind/issues/571#issuecomment-6883569285"
    keys = {"dispatched": ["2026-11-14T18:00Z"],
            "issue": ["https://github.com/o/PyAutoMind/issues/571   # the digest lands here"],
            "live": [f"LIVE · 1 running · review-at 21:20 — status: {url}"]}
    st = _status.dev_status("2026-11-14-pm3", keys,
                            [{"slug": "gears", "outcome": "RUNNING"}],
                            review_exists=False, pages=PAGES)
    assert st["issue"] == "https://github.com/o/PyAutoMind/issues/571"
    assert _status.badge(st) == "LIVE · 1 in progress"
    html = _status.render_html(st)
    assert html.startswith('<h3 id="shift">Shift <span class="facets">(2026-11-14-pm3 — '
                           "1 in progress · 0 awaiting review)</span></h3>")
    assert (f'<p class="facets">Live: LIVE · 1 running · review-at 21:20 · '
            f'<a href="{url}">shift issue #571</a></p>') in html
    assert "<li><code>gears</code>" in html
    assert f">{url}<" not in html and "status: http" not in html
    assert 'class="verdict' not in html and "<h2" not in html
    md = _status.render_md(st)
    assert f"Live: LIVE · 1 running · review-at 21:20 · [shift issue #571]({url})" in md


def test_an_idle_or_reviewed_shift_is_one_quiet_line_linking_its_issue():
    issue = "https://github.com/o/PyAutoMind/issues/571"
    keys = {"dispatched": ["2026-11-14T18:00Z"], "issue": [issue],
            "live": [f"closed at review-at — the digest is below — status: {issue}#c"]}
    st = _status.dev_status("2026-11-14-pm3", keys, [], review_exists=False, pages=PAGES)
    assert not _status.active(st) and _status.badge(st) == ""
    assert _status.render_html(st) == (
        '<h3 id="shift">Shift</h3>\n<p class="muted">(last shift 2026-11-14-pm3 — closed, '
        f'nothing to review · <a href="{issue}">shift issue #571</a>)</p>')
    # Every shift reviewed: the last one, from `last_shift`, says so.
    last = _status.last_shift([("2026-11-14-pm2", {"dispatched": ["2026-11-14T13:00Z"]}),
                               ("2026-11-14-pm3", keys), ("AGENTS", {})])
    assert last == {"slot": "2026-11-14-pm3", "issue": issue}
    assert _status.render_md(None, last) == (
        f"**Shift**\n\n_(last shift 2026-11-14-pm3 — reviewed · [shift issue #571]({issue}))_")
    assert "(last shift 2026-11-14-pm3 — reviewed · <a" in _status.render_html(None, last)

"""tests/test_batch_freeze.py — the Heart freeze flag, as Brain reads it.

PyAutoHeart owns the flag (`PyAutoHeart/heart/freeze.py`); everything here is a
**read**. What these tests defend is that the read agrees with Heart on the two
things a wrong answer would cost something:

- **expiry is re-derived, never trusted.** A window that has passed reads as
  thawed even though nobody cleared the file, so a forgotten `--set` cannot
  block merges indefinitely.
- **the box only carries the line when a caller supplies it.** The flag lives
  in the dev box's `~/.pyauto-heart/`, which no checkout contains; a surface
  that renders a *committed* artifact (the Mind dashboard, regenerated in CI)
  must render byte-identically with and without it, or every freeze reads as
  dashboard drift.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_status_under_freeze_test",
    BRAIN / "agents" / "conductors" / "batch" / "_status.py")
_status = importlib.util.module_from_spec(_spec)
sys.modules["_status_under_freeze_test"] = _status
_spec.loader.exec_module(_status)

sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_bspec = importlib.util.spec_from_file_location(
    "_batch_under_freeze_test",
    BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_bspec)
sys.modules["_batch_under_freeze_test"] = _batch
_bspec.loader.exec_module(_batch)

PAGES = "https://exampleorg.github.io/ExampleMind/"
ACTIVE_REC = {"state": "active", "reason": "release validation",
              "until": "2026-09-03T19:30:00+00:00"}


def _write_flag(tmp_path: Path, until: str, reason: str = "release validation"):
    (tmp_path / "freeze.json").write_text(json.dumps({
        "reason": reason, "set_at": "2026-09-03T18:00:00+00:00",
        "until": until, "set_by": "pre-build"}), encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------ the wording ---
def test_the_line_is_heart_s_sentence_verbatim():
    assert _status.freeze_line(ACTIVE_REC) == (
        "FROZEN: release validation until 2026-09-03T19:30:00+00:00")


def test_nothing_frozen_is_the_empty_string_so_callers_can_just_test_it():
    assert _status.freeze_line(None) == ""
    assert _status.freeze_line({}) == ""
    assert _status.freeze_line({"state": "clear"}) == ""
    # Expired reads as thawed — the same reading Heart gives it.
    assert _status.freeze_line({**ACTIVE_REC, "state": "expired"}) == ""


# ---------------------------------------------------------------- the read ---
def test_an_unexpired_flag_reads_active(tmp_path):
    _write_flag(tmp_path, "2026-09-03T19:30:00+00:00")
    now = dt.datetime(2026, 9, 3, 18, 30, tzinfo=dt.timezone.utc)
    assert _batch.heart_freeze(now=now, state_dir=tmp_path)["state"] == "active"


def test_expiry_is_re_derived_not_trusted(tmp_path):
    """Nobody cleared it; the window still ended. The file says nothing about
    its own state, so a stale flag cannot go on blocking merges."""
    _write_flag(tmp_path, "2026-09-03T19:30:00+00:00")
    now = dt.datetime(2026, 9, 3, 21, 0, tzinfo=dt.timezone.utc)
    rec = _batch.heart_freeze(now=now, state_dir=tmp_path)
    assert rec["state"] == "expired"
    assert _status.freeze_line(rec) == ""


def test_absent_or_unreadable_state_reads_as_clear(tmp_path):
    # No Heart on this box at all (CI, a web container) — collect still runs.
    assert _batch.heart_freeze(state_dir=tmp_path)["state"] == "clear"
    (tmp_path / "freeze.json").write_text("{not json", encoding="utf-8")
    assert _batch.heart_freeze(state_dir=tmp_path)["state"] == "clear"
    (tmp_path / "freeze.json").write_text(json.dumps({"reason": "x"}),
                                          encoding="utf-8")
    assert _batch.heart_freeze(state_dir=tmp_path)["state"] == "clear"
    _write_flag(tmp_path, "whenever")
    assert _batch.heart_freeze(state_dir=tmp_path)["state"] == "clear"


def test_a_zoneless_until_is_read_as_utc(tmp_path):
    _write_flag(tmp_path, "2026-09-03T19:30:00")
    before = dt.datetime(2026, 9, 3, 18, 30, tzinfo=dt.timezone.utc)
    after = dt.datetime(2026, 9, 3, 20, 30, tzinfo=dt.timezone.utc)
    assert _batch.heart_freeze(now=before, state_dir=tmp_path)["state"] == "active"
    assert _batch.heart_freeze(now=after, state_dir=tmp_path)["state"] == "expired"


# ----------------------------------------------------------------- the box ---
def _box(freeze=""):
    return _status.dev_status(
        "2026-09-03-pm", {"dispatched": ["2026-09-03T18:00Z"]},
        [{"slug": "resampling-info", "outcome": "RUNNING"}],
        review_exists=False, pages=PAGES, freeze=freeze)


def test_the_box_is_byte_identical_when_no_caller_supplies_a_freeze():
    """The committed-artifact invariant: a dashboard regenerated in CI, where
    Heart's state does not exist, must match one regenerated on the dev box."""
    st = _box()
    assert st["freeze"] == ""
    assert "FROZEN" not in _status.render_md(st)
    assert "FROZEN" not in _status.render_html(st)


def test_the_box_carries_one_line_when_it_is_supplied():
    st = _box(_status.freeze_line(ACTIVE_REC))
    md, html = _status.render_md(st), _status.render_html(st)
    line = "FROZEN: release validation until 2026-09-03T19:30:00+00:00"
    assert f"> {line}" in md
    assert line in html
    # One line, and above the members — a human reading the box is deciding
    # what to merge.
    assert md.count("FROZEN") == 1
    assert md.index("FROZEN") < md.index("resampling-info")


def test_the_science_box_carries_it_too():
    st = _status.cortex_status(
        "2026-09-03-night", {"dispatched": ["2026-09-03T18:00Z"]},
        [{"slug": "a-phase"}], states={"a-phase": "running"}, live={},
        pages=PAGES, freeze=_status.freeze_line(ACTIVE_REC))
    assert "FROZEN" in _status.render_md(st)


# ------------------------------------------------------------- the packet ---
def test_the_collect_packet_says_what_the_freeze_means_for_merging():
    d = {"slot": "2026-09-03-pm", "not_delivered": [], "members": [],
         "delivered": (0, 0), "review": None, "notes": [],
         "freeze": _status.freeze_line(ACTIVE_REC)}
    body = _batch.collect_report(d)
    assert "FROZEN: release validation" in body
    assert "/prm" in body and "--thaw" in body


def test_the_collect_packet_says_nothing_when_nothing_is_frozen():
    d = {"slot": "2026-09-03-pm", "not_delivered": [], "members": [],
         "delivered": (0, 0), "review": None, "notes": [], "freeze": ""}
    assert "FROZEN" not in _batch.collect_report(d)


def test_the_collect_summary_line(capsys):
    d = {"slot": "2026-09-03-pm", "not_delivered": [], "members": [],
         "delivered": (0, 0), "review": None, "notes": [],
         "freeze": _status.freeze_line(ACTIVE_REC)}
    _batch.emit_collect(d)
    out = capsys.readouterr().out
    assert out.splitlines()[1] == (
        "FROZEN: release validation until 2026-09-03T19:30:00+00:00")

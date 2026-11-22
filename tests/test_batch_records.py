"""The batch records the planner still reads: the newest slot and what it
carried forward. (The `batch collect` verb that wrote these was retired.)"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_records_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_records_under_test"] = _batch
_spec.loader.exec_module(_batch)

RECORD = """# Batch 2026-09-03-pm

- dispatched: 2026-09-03T17:00Z
- members:
  - resampling: draft/bug/autofit/resampling.md — glance — 3 — session ended green
- outcomes:
  - resampling: carried
  - other: merged
- notes: |
  free text
"""


def _mind(tmp_path) -> Path:
    mind = tmp_path / "mind"
    (mind / "batches").mkdir(parents=True)
    (mind / "draft").mkdir()
    (mind / "batches" / "2026-09-03-am.md").write_text("# Batch\n", encoding="utf-8")
    (mind / "batches" / "2026-09-03-pm.md").write_text(RECORD, encoding="utf-8")
    return mind


def test_flags_of_other_verbs_are_refused_on_plan(tmp_path):
    assert _batch.main(["plan", "--mind", str(_mind(tmp_path)), "--apply"]) == 2


def test_collect_is_no_longer_a_verb(tmp_path):
    import pytest
    with pytest.raises(SystemExit) as e:
        _batch.main(["collect", "--mind", str(_mind(tmp_path))])
    assert e.value.code == 2


def test_the_newest_slot_sort_is_lexical(tmp_path):
    mind = _mind(tmp_path)
    assert _batch.newest_slot(mind) == "2026-09-03-pm"
    (mind / "batches" / "2026-09-03-night.md").write_text(RECORD, encoding="utf-8")
    assert _batch.newest_slot(mind) == "2026-09-03-pm"


def test_previous_carried_reads_the_newest_records_outcomes(tmp_path):
    assert _batch.previous_carried(_mind(tmp_path)) == ("2026-09-03-pm", ["resampling"])

"""Records written by the retired `batch collect` verb (`members:`,
`- outcomes:`) still sit in the Mind; the planner runs past them and no
longer reads anything forward from them."""
from __future__ import annotations

import json
from pathlib import Path

from _shift_fixtures import _batch  # noqa: E402

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


def test_an_old_record_with_outcomes_plans_without_a_carried_line(tmp_path, capsys):
    """The newest record carries a collect-era `- outcomes:` block with a
    `carried` member: plan runs, and reads nothing forward from it."""
    mind = _mind(tmp_path)
    assert _batch.main(["plan", "--mind", str(mind), "--lane", "local-dev"]) == 0
    out = capsys.readouterr().out
    assert "== BatchDecision ==" in out and "Carried in" not in out
    assert _batch.main(["plan", "--mind", str(mind), "--lane", "local-dev", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert "carried" not in d and "carried_from" not in d

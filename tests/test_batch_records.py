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


def test_collect_is_no_longer_a_verb(tmp_path, capsys):
    """Retired, it scores nothing: with no record to read it says the digest
    is the review surface (exit 2), never "0 members"."""
    assert _batch.main(["collect", "--mind", str(_mind(tmp_path))]) == 2
    out = capsys.readouterr()
    assert "the digest is the review surface" in out.err
    assert "0 members" not in out.out + out.err


# The shape of a brief-form shift record (2026-11-16-pm): top-level keys, a
# `brief:` block and no `members:`, then `## Heart` and `## Digest` with its
# subsections. Placeholders only.
BRIEF_RECORD = """# Batch 2026-11-16 pm
- dispatched: 2026-11-16T17:48Z
- review-at: 2026-11-16T19:18Z
- live: closed at review-at — the digest is below
- heart-ack:
  - acknowledged by the human: RED on local-checkout rows
- expected-effects:
  - task_a: example-lib library PR (judge; PR-open, human /prm)
- brief:
  - goals:
    - 1. Fix 3 bugs in the dashboard
  - tasks:
    - draft/bug/example/task_a.md
  - backlog: scoped
  - scoped:
    - tiers: notify, glance
  - review-minutes: 45
  - lanes: any local-dev
  - merge-cap: 1
  - token-budget: 5000000

## Heart

Read 2026-11-16T17:11Z from local readiness: **RED**.

### local-checkout (1)
- [red] example-lib: 1 commit(s) behind origin — rule `behind` → report only

## Digest

Inbox: 1 question added to your inbox this shift (Q3).

### Brief work
- task_a — PR open https://github.com/o/r/pull/70 (judge)

### Counters
- merges 1 of merge-cap 1

### Late arrivals
- late: task_b — https://github.com/o/r/pull/720 (after review-at)
"""


def test_collect_on_a_brief_shift_prints_its_digest(tmp_path, capsys):
    """M3.6g (PyAutoBrain#728): `batch collect --slot 2026-11-16-pm` on a
    brief-form record prints the digest, says it is the review surface, and
    never reports "0 members"."""
    mind = _mind(tmp_path)
    (mind / "batches" / "2026-11-16-pm.md").write_text(BRIEF_RECORD, encoding="utf-8")
    rc = _batch.main(["collect", "--slot", "2026-11-16-pm", "--mind", str(mind)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert out.out.startswith("## Digest\n")
    assert "### Late arrivals" in out.out and "pull/720" in out.out
    assert "## Heart" not in out.out and "- brief:" not in out.out
    assert "is the review surface" in out.out
    assert "0 members" not in out.out + out.err


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

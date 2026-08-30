"""tests/test_intake_review_cost.py — intake writes the review-cost model.

Two things are locked here. First, the header round-trip: what `analyse` derives
is what `_render_header` writes and what `parse_header` reads back, with
`Witness:` written **only** when the author supplied one. Second, the
2026-08-30 change to `infer_autonomy` — including the variant that was measured
and reverted, so nobody re-proposes it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "intake"))
from _intake import (  # noqa: E402
    HEADER_FIELDS, analyse, infer_autonomy, parse_header,
)

RAW = "Tidy the @PyAutoBrain board copy so a 403 reads as an egress block.\n"
WITNESSED = RAW + "Witness: the degraded row renders and a test pins its text.\n"


def test_header_round_trips_through_parse_header():
    header = analyse(WITNESSED, "test")["header"]
    got = parse_header(header)
    assert got["consequence"] == "notify"
    assert got["witness"].startswith("the degraded row renders")
    assert got["review-minutes"] == "0"
    assert got["unattended"] == "ready"


def test_witness_is_written_only_when_supplied():
    """It is the one field that cannot be derived. An invented one would be
    plausible prose with nothing behind it — strictly worse than none, because
    the whole value of the field is that its absence is informative."""
    assert "Witness:" in analyse(WITNESSED, "test")["header"]
    bare = analyse(RAW, "test")
    assert "Witness:" not in bare["header"]
    assert bare["consequence"] == "judge"
    assert any("No Witness" in r for r in bare["risks"])


def test_witness_stays_out_of_the_hygiene_set():
    """`intake formalise` writes every field in HEADER_FIELDS that a prompt is
    missing. A `Witness:` in there would be auto-invented across the backlog."""
    assert "witness" not in HEADER_FIELDS
    assert "unattended" not in HEADER_FIELDS
    assert "consequence" in HEADER_FIELDS
    assert "review-minutes" in HEADER_FIELDS


def _factors(**over):
    base = {"repos_affected": 1, "architectural_risk": [], "human_judgement": [],
            "library_repos": [], "workspace_repos": [], "organism_repos": [],
            "library_and_workspace": False, "size_words": 100,
            "scientific_complexity": [], "test_burden": [],
            "memory_context_required": False}
    base.update(over)
    return base


def test_multi_repo_alone_no_longer_forces_supervised():
    """The 2026-08-30 change. Repo count is blast radius, which
    `estimate_difficulty` already prices at +2 per repo; this field is about
    whether a human's judgement is needed."""
    assert infer_autonomy("medium", _factors(repos_affected=4)) == "safe"


def test_real_judgement_signals_still_force_supervised():
    assert infer_autonomy("medium", _factors(architectural_risk=["api"])) == "supervised"
    assert infer_autonomy("large", _factors()) == "supervised"
    assert infer_autonomy("too-large", _factors()) == "supervised"


def test_ambiguity_alone_does_not_force_supervised():
    """The variant that was measured and REVERTED: adding `human_judgement` as a
    supervised trigger took `safe` from 30 to 24 across the backlog, because the
    ambiguity keywords fire on 63% of prompts and catch well-written ones
    indiscriminately — the same mistake as the rule it replaced. Locked so it is
    not re-introduced by someone reasoning from first principles."""
    assert infer_autonomy("medium", _factors(human_judgement=["investigate"])) == "safe"


def test_unscoped_ambiguity_is_still_human_required():
    """The one place `human_judgement` legitimately fires: nothing to scope
    against, so nobody can size or gate the work."""
    assert infer_autonomy(
        "medium", _factors(repos_affected=0, human_judgement=["unclear"])
    ) == "human-required"

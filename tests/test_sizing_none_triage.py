"""None witnesses and unclassified work must retain visible review reasons."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    declared_header,
    effective_consequence,
    effective_difficulty,
    effective_unattended,
    estimate_consequence,
    estimate_unattended,
    parse_prompt,
)


def _prompt(tmp_path, header, work_type="bug", body="Repair the short-chain crash."):
    path = tmp_path / "draft" / work_type / "samplelib" / "task.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# Short-chain repair\n\n{header}\n\n{body}\n")
    return parse_prompt(path, tmp_path)


@pytest.mark.parametrize("value, reason", [
    ("none", ""),
    ("NONE", ""),
    ("None — human judgement needed", "human judgement needed"),
    ("none - human judgement needed", "human judgement needed"),
    ("none human judgement needed", "human judgement needed"),
])
def test_none_witness_is_absent_with_an_explanatory_reason(tmp_path, value, reason):
    p = _prompt(tmp_path, f"Witness: {value}")
    assert p["witness"] is None
    assert p["witness_none_reason"] == reason
    expected = "Witness: none declared" + (f" — {reason}" if reason else "")
    assert estimate_consequence(p) == ("judge", [expected])


def test_none_header_preserves_first_declaration_and_raw_reason():
    p = declared_header("Witness: none — inspect PR #123\nWitness: tests pass")
    assert p["witness"] is None
    assert p["witness_none_reason"] == "inspect PR #123"
    p = declared_header("Witness: tests pass\nWitness: none")
    assert p["witness"] == "tests pass"
    assert p["witness_none_reason"] is None


def test_none_is_a_word_and_fenced_headers_are_not_declarations(tmp_path):
    p = _prompt(tmp_path, "```\nWitness: none\n```\nWitness: nonetheless tests pass")
    assert p["witness"] == "nonetheless tests pass"
    assert estimate_consequence(p)[0] == "glance"


def test_absent_witness_keeps_the_existing_reason(tmp_path):
    assert estimate_consequence(_prompt(tmp_path, "")) == (
        "judge", ["no Witness: declared — nothing to check but the diff"])


@pytest.mark.parametrize("header", ["", "Witness: tests pass", "Witness: none"])
def test_triage_requires_classification_before_unattended_work(tmp_path, header):
    p = _prompt(tmp_path, header, work_type="triage")
    assert p["work_type"] == "triage"
    assert estimate_consequence(p) == (
        "judge", ["work-type triage: classification still open"])
    assert estimate_unattended(p, "small") == (
        "never", ["work-type triage: classification still open"])


def test_declared_tiers_still_win_and_derived_triage_is_visible(tmp_path):
    p = _prompt(tmp_path, "Witness: tests pass\nConsequence: glance\nUnattended: ready",
                work_type="triage")
    assert effective_consequence(p)[::2] == ("glance", "judge")
    assert effective_unattended(p, "small")[::2] == ("ready", "never")


def test_unknown_unattended_value_is_reported_without_inventing_a_grade(tmp_path):
    p = _prompt(tmp_path, "Unattended: needs-decision # awaiting classification")
    assert p["declared_unattended"] is None
    assert p["unknown_unattended"] == "needs-decision"
    level, _, factors, derived_level = effective_difficulty(p)
    grade, reasons, derived = effective_unattended(p, level, factors, derived_level)
    assert grade == derived == "ready"
    assert reasons == ["fits one unattended run",
                       "unknown Unattended: needs-decision — expected ready, needs-slicing, never"]


def test_unknown_unattended_reason_survives_a_never_rule(tmp_path):
    p = _prompt(tmp_path, "Unattended: needs-decision", work_type="triage")
    grade, reasons, derived = effective_unattended(p, "small")
    assert grade == derived == "never"
    assert "triage" in reasons[0]
    assert "needs-decision" in reasons[1]


@pytest.mark.parametrize("exception", ["`IndexError`", "IndexError"])
def test_exception_symptoms_no_longer_imply_a_judged_surface(tmp_path, exception):
    p = _prompt(tmp_path, "Witness: short-chain regression passes",
                body=f"A short chain raises {exception}. Repair the slice.")
    assert estimate_consequence(p)[0] == "glance"


def test_error_contract_still_requires_judgement(tmp_path):
    p = _prompt(tmp_path, "Witness: regression passes",
                body="Change the error contract for an invalid chain.")
    tier, reasons = estimate_consequence(p)
    assert tier == "judge"
    assert "error contract" in reasons[0]

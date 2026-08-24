"""tests/test_intake_declared_difficulty.py — a human declaration outranks the estimate.

The Intake Agent sizes every idea with the shared sizing heuristic, but raw
input often states its own scope already (the ideas.md house style ends a
bullet with "Difficulty large, supervised."). Before this, that declaration was
silently overwritten by the keyword estimate — and, being prose, was also
swallowed by the derived title and so leaked into the filename.

Locked here: the declaration wins, its provenance is reported, code spans are
not read as declarations, and ordinary prose still sizes by heuristic.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "conductors" / "intake"))
from _intake import (  # noqa: E402
    _declared_fields, _derive_fields, _strip_declarations, analyse,
)


def test_declared_difficulty_beats_the_heuristic():
    d = analyse("Fix the typo in the @PyAutoHands docstring for Mask2D. "
                "Difficulty: large.", "test")
    assert d["difficulty"] == "large"
    assert d["difficulty_source"] == "declared"
    assert d["difficulty_estimated"] == "small"
    assert "Difficulty: large" in d["header"]


def test_declaration_is_kept_out_of_the_title_and_slug():
    d = analyse("Fix the typo in the @PyAutoHands docstring for Mask2D. "
                "Difficulty: large. Autonomy: supervised.", "test")
    assert d["title"] == "Fix the typo in the @PyAutoHands docstring for Mask2D"
    assert "large" not in d["proposed_path"]
    assert "supervised" not in d["proposed_path"]


def test_ideas_house_style_trailing_autonomy():
    # `ideas.md` bullets end "Difficulty large, supervised." — one clause, two fields.
    fields, spans = _declared_fields("Rework the grid. Difficulty large, supervised.")
    assert fields == {"difficulty": "large", "autonomy": "supervised"}
    assert spans


def test_declared_autonomy_and_priority_are_taken_as_written():
    d = analyse("Rework the @PyAutoHands grid API. Autonomy: human-required. "
                "Priority: high.", "test")
    assert d["autonomy"] == "human-required"
    assert d["autonomy_source"] == "declared"
    assert d["priority"] == "high"
    assert d["priority_source"] == "declared"


def test_spelling_variants_normalise_to_header_values():
    fields, _ = _declared_fields("Difficulty is Too Large, human required.")
    assert fields == {"difficulty": "too-large", "autonomy": "human-required"}


def test_code_spans_are_not_declarations():
    text = ("Intake drops the declaration. Repro:\n\n"
            "```\nintake \"a task. Difficulty: large.\"\n```\n\n"
            "Observed `Difficulty: too-large` in the header.\n")
    fields, _ = _declared_fields(text)
    assert fields == {}


def test_prose_without_a_declaration_still_sizes_by_heuristic():
    d = analyse("The @PyAutoHands mask is large and the difficulty of lensing "
                "is well known.", "test")
    assert d["difficulty_source"] == "estimated"
    assert d["autonomy_source"] == "inferred"
    assert d["priority_source"] == "inferred"


def test_strip_declarations_leaves_prose_alone_when_nothing_declared():
    text = "Just a sentence."
    assert _strip_declarations(text, []) == text


def test_declaration_only_text_keeps_a_title_to_derive_from():
    d = analyse("Difficulty: large.", "test")
    assert d["title"] != "Untitled"


def test_formalise_derives_the_declared_difficulty():
    body = ("# A backlog prompt\n\nRework the grid in @PyAutoHands.\n"
            "Difficulty large, supervised.\n")
    fields = _derive_fields(body, "refactor", "autoarray")
    assert fields["difficulty"] == "large"
    assert fields["autonomy"] == "supervised"

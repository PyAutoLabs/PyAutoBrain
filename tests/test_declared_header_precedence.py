"""tests/test_declared_header_precedence.py — declared header keys outrank prose.

One family of bug, three instances: a conductor derives a value from prose and
ignores the header key the author declared. (1) the Feature Agent's ranker
(fixed, PyAutoBrain#217); (2) the Bug Agent re-homing a prompt that declares
`Type: bug`; (3) the Intake Agent persisting its derived `Difficulty:` over the
declared one (PyAutoBrain#274).

The precedence rule therefore lives in the sizing faculty — `effective_difficulty`,
the one place every conductor already calls — rather than being re-implemented
per conductor. Locked here: declared wins, the derived level is still reported so
a disagreement stays visible, declarations are read from prose *and* header lines
but never from code fences, and a declaration never leaks into the derived title.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "feature"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "bug"))
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "intake"))
from _sizing import (  # noqa: E402
    declared_header, declared_inline, effective_difficulty, estimate_difficulty,
    strip_declarations,
)
import _bug  # noqa: E402
from _intake import _derive_fields, analyse  # noqa: E402


# --- the faculty: one precedence rule ----------------------------------------

def test_effective_difficulty_prefers_the_declared_level():
    p = {"text": "x " * 900, "repos": ["autofit", "autoarray"], "words": 900,
         "target": "autofit", "work_type": "feature",
         "declared_difficulty": "medium"}
    level, _score, _factors, derived = effective_difficulty(p)
    assert level == "medium"
    assert derived == estimate_difficulty(p)[0] != "medium"


def test_effective_difficulty_falls_back_to_the_estimate():
    p = {"text": "a short one", "repos": [], "words": 3, "target": "?",
         "work_type": "bug"}
    level, _score, _factors, derived = effective_difficulty(p)
    assert level == derived == "small"


def test_declared_inline_reads_the_ideas_house_style():
    # `ideas.md` bullets end "Difficulty large, supervised." — one clause, two keys.
    fields, spans = declared_inline("Rework the grid. Difficulty large, supervised.")
    assert fields == {"difficulty": "large", "autonomy": "supervised"}
    assert spans


def test_declared_inline_normalises_spelling_variants():
    fields, _ = declared_inline("Difficulty is Too Large, human required.")
    assert fields == {"difficulty": "too-large", "autonomy": "human-required"}


def test_code_spans_are_documentation_not_declarations():
    text = ("Intake drops the declaration. Repro:\n\n"
            "```\nintake \"a task. Difficulty: large.\"\n```\n\n"
            "Observed `Difficulty: too-large` in the header.\n")
    assert declared_inline(text)[0] == {}
    assert declared_header(text)["declared_difficulty"] is None


def test_declared_header_reads_type_and_autonomy():
    h = declared_header("Type: bug\nTarget: pyautobrain\nDifficulty: medium\n"
                        "Autonomy: safe\nPriority: high\n")
    assert h["declared_type"] == "bug"
    assert h["declared_difficulty"] == "medium"
    assert h["declared_autonomy"] == "safe"
    assert h["priority"] == "high"


def test_strip_declarations_is_a_no_op_without_declarations():
    assert strip_declarations("Just a sentence.", []) == "Just a sentence."


# --- intake: conception ------------------------------------------------------

def test_intake_persists_the_declared_difficulty_not_its_own():
    # The reported case: a long prompt (length drives the score) declaring medium.
    text = ("Add an arXiv inbox tier to @PyAutoHands, @PyAutoHeart and "
            "@PyAutoMind. It changes the public API and the architecture of the "
            "release path, and needs new tests. " + "context " * 800 +
            " Difficulty: medium.")
    d = analyse(text, "test")
    assert d["difficulty"] == "medium"
    assert d["difficulty_derived"] == "too-large"
    assert d["difficulty_disagreement"] is True
    assert "Difficulty: medium" in d["header"]


def test_intake_honours_a_prepended_header_block():
    text = ("# A task\n\nType: bug\nTarget: pyautohands\nDifficulty: medium\n"
            "Autonomy: supervised\nPriority: high\n\n"
            "Something in @PyAutoHands is broken. " + "detail " * 800)
    d = analyse(text, "test")
    assert (d["difficulty"], d["autonomy"], d["priority"]) == (
        "medium", "supervised", "high")


def test_intake_declaration_stays_out_of_the_title_and_slug():
    d = analyse("Fix the typo in the @PyAutoHands docstring. "
                "Difficulty: large. Autonomy: supervised.", "test")
    assert d["title"] == "Fix the typo in the @PyAutoHands docstring"
    assert "large" not in d["proposed_path"]
    assert "supervised" not in d["proposed_path"]


def test_intake_declared_type_beats_prose_classification():
    # The filing note's case: prose full of feature verbs, `Type: bug` declared.
    text = ("Type: bug\n\nAdd support for a new capability that implements a new "
            "@PyAutoHands surface — except it is a crash report.")
    assert analyse(text, "test")["work_type"] == "bug"
    assert analyse(text, "test")["work_type_source"] == "declared"


def test_intake_without_declarations_still_derives():
    d = analyse("The @PyAutoHands mask is large and the difficulty of the "
                "problem is well known.", "test")
    assert d["difficulty_source"] == "estimated"
    assert d["work_type_source"] == "inferred"
    assert d["autonomy_source"] == "inferred"


def test_formalise_derives_the_declared_difficulty():
    body = ("# A backlog prompt\n\nRework the grid in @PyAutoHands.\n"
            "Difficulty large, supervised.\n")
    fields = _derive_fields(body, "refactor", "pyautohands")
    assert fields["difficulty"] == "large"
    assert fields["autonomy"] == "supervised"


# --- the bug conductor -------------------------------------------------------

def _bug_prompt(text: str, **extra):
    p = {"path": "draft/bug/pyautohands/x.md", "work_type": "bug",
         "target": "pyautohands", "repos": ["pyautohands"], "text": text,
         "lines": text.count("\n") + 1, "words": len(text.split()),
         "declared_difficulty": None, "declared_type": None,
         "declared_autonomy": None, "status": None, "priority": None,
         "blocked_by": [], "closes_when": []}
    p.update(extra)
    return p


def test_bug_agent_does_not_rehome_a_declared_bug_on_prose():
    # Prose a defect report legitimately contains; no "bug"/"crash" word in it,
    # so the prose classifier would re-home it to docs/.
    text = ("The documentation build emits a docstring typo — a design decision "
            "is needed on the tutorial layout.")
    assert _bug.re_home_check(_bug_prompt(text)) == "docs"
    assert _bug.re_home_check(_bug_prompt(text, declared_type="bug")) is None


def test_bug_decision_reports_the_declared_difficulty():
    d = _bug.analyse_bug(_bug_prompt("It crashes. " + "detail " * 900,
                                     declared_difficulty="small"))
    assert d["difficulty"] == "small"
    assert d["difficulty_declared"] == "small"
    assert d["difficulty_derived"] != "small"
    assert d["difficulty_disagreement"] is True

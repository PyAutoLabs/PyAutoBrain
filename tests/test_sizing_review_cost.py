"""tests/test_sizing_review_cost.py — the review-cost model (batch epic 0a).

`Difficulty:` measures blast radius. These four outputs measure what a task
costs the HUMAN, which is the only quantity a batch can be planned against.

Two rules carry the whole model and each gets its own test:

  * **no `Witness:` means `judge`** — without it a prompt could claim a cheap
    tier while offering the reviewer nothing but the diff, and the field would
    be aspirational rather than load-bearing;
  * **declared beats derived** — the module's standing precedence rule, which
    three conductors re-implemented and two got wrong (PyAutoBrain#217, #274).

The golden file pins the grade for a fixed sample so a change to the heuristic
has to be seen and accepted rather than absorbed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "faculties" / "sizing"))
from _sizing import (  # noqa: E402
    CONSEQUENCE_TIERS,
    UNATTENDED_LEVELS,
    effective_consequence,
    effective_difficulty,
    effective_review_minutes,
    effective_unattended,
    estimate_review_minutes,
    parse_prompt,
)

GOLDEN = Path(__file__).parent / "data" / "sizing_review_cost_golden.json"


def _prompt(tmp_path: Path, body: str, rel: str = "draft/feature/pyautobrain/t.md"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return parse_prompt(path, tmp_path)


def _grade(p):
    level, _score, factors, derived_level = effective_difficulty(p)
    tier, tier_why, derived_tier = effective_consequence(p, factors)
    grade, _why, _dg = effective_unattended(p, level, factors, derived_level)
    minutes, _dm = effective_review_minutes(p, tier, level)
    return {"difficulty": level, "consequence": tier, "derived_consequence": derived_tier,
            "review_minutes": minutes, "unattended": grade, "why": tier_why[0]}


HEADERLESS_DOC = """# Tidy the Brain README

Type: docs
Target: PyAutoBrain
Repos:
- PyAutoBrain
Difficulty: small
Priority: normal
Status: draft

Rewrite two paragraphs. Nothing else.
"""


def test_no_witness_grades_judge(tmp_path):
    """The load-bearing default. A docs change to an organ repo is about as
    consequence-free as work gets — and it still costs a PI's hour, because
    nothing was promised that a reviewer could check."""
    g = _grade(_prompt(tmp_path, HEADERLESS_DOC))
    assert g["consequence"] == "judge"
    assert "no Witness" in g["why"]
    assert g["review_minutes"] == 20


def test_witness_unlocks_the_cheap_tier(tmp_path):
    """The same prompt, with a witness, is the same work — but now reviewable
    in the time it takes to read one line, so it grades `notify`."""
    body = HEADERLESS_DOC.replace(
        "Status: draft",
        "Status: draft\nWitness: every link in the file resolves; docs build clean")
    g = _grade(_prompt(tmp_path, body))
    assert g["consequence"] == "notify"
    assert g["review_minutes"] == 0


def test_judged_surface_beats_a_witness(tmp_path):
    """A witness makes work checkable; it does not make an API decision
    somebody else's to make. Surface outranks evidence."""
    body = HEADERLESS_DOC.replace(
        "Status: draft",
        "Status: draft\nWitness: byte-identical output on the full suite"
    ).replace("Rewrite two paragraphs. Nothing else.",
              "Change the default value of over_sample_size.")
    assert _grade(_prompt(tmp_path, body))["consequence"] == "judge"


def test_declared_beats_derived_and_reports_the_split(tmp_path):
    """Precedence, and the reason the derived value is returned at all: the
    disagreement is evidence about the heuristic and has to stay visible."""
    body = HEADERLESS_DOC.replace(
        "Status: draft", "Status: draft\nConsequence: judge")
    g = _grade(_prompt(tmp_path, body))
    assert g["consequence"] == "judge"          # declared wins
    assert g["derived_consequence"] == "judge"  # no witness -> judge anyway

    body2 = HEADERLESS_DOC.replace(
        "Status: draft",
        "Status: draft\nConsequence: judge\nWitness: docs build clean")
    g2 = _grade(_prompt(tmp_path, body2))
    assert g2["consequence"] == "judge"           # declared still wins
    assert g2["derived_consequence"] == "notify"  # and the split is reported


def test_prose_describing_a_surface_is_not_touching_one(tmp_path):
    """A prompt quoting a judged surface inside a code fence is documenting it.
    Same rule, same reason, as `declared_header`'s fenced-block skip."""
    body = HEADERLESS_DOC.replace(
        "Rewrite two paragraphs. Nothing else.",
        "Document the guard:\n\n```\nraises ValueError on a bad default value\n```\n"
    ).replace("Status: draft", "Status: draft\nWitness: docs build clean")
    assert _grade(_prompt(tmp_path, body))["consequence"] == "notify"


def test_unattended_is_not_difficulty_renamed(tmp_path):
    """`needs-slicing` keys off the compaction rule, not off size alone: a
    single-repo `large` task still fits one run."""
    body = HEADERLESS_DOC.replace("Difficulty: small", "Difficulty: large")
    assert _grade(_prompt(tmp_path, body))["unattended"] == "ready"

    wide = HEADERLESS_DOC.replace("Difficulty: small", "Difficulty: large").replace(
        "Repos:\n- PyAutoBrain",
        "Repos:\n- PyAutoBrain\n- PyAutoMind\n- PyAutoHeart\n- PyAutoHands")
    assert _grade(_prompt(tmp_path, wide))["unattended"] == "needs-slicing"


def test_human_required_is_never_unattended(tmp_path):
    body = HEADERLESS_DOC.replace("Priority: normal",
                                  "Autonomy: human-required\nPriority: normal")
    assert _grade(_prompt(tmp_path, body))["unattended"] == "never"


def test_review_minutes_are_a_seed_not_a_measurement():
    """Documented as a seed, and shaped like one: tier-driven, with a single
    nudge for size. Anything more precise would be inventing certainty."""
    assert estimate_review_minutes("notify", "small") == 0
    assert estimate_review_minutes("glance", "small") == 3
    assert estimate_review_minutes("judge", "small") == 20
    assert estimate_review_minutes("judge", "too-large") == 25


def test_vocabularies_are_closed():
    assert CONSEQUENCE_TIERS == ("notify", "glance", "judge")
    assert UNATTENDED_LEVELS == ("ready", "needs-slicing", "never")


def test_golden_sample_is_unchanged(tmp_path):
    """Pins the grade for a fixed sample. A heuristic change that moves these
    is not necessarily wrong — but it has to be looked at and re-accepted,
    which is the entire job of a golden file."""
    samples = {
        "doc_no_witness": HEADERLESS_DOC,
        "doc_with_witness": HEADERLESS_DOC.replace(
            "Status: draft", "Status: draft\nWitness: docs build clean"),
        "api_change": HEADERLESS_DOC.replace(
            "Rewrite two paragraphs. Nothing else.",
            "Change the public API of Grid2D.").replace(
            "Status: draft", "Status: draft\nWitness: 900 tests pass"),
        "refactor_byte_equal": HEADERLESS_DOC.replace("Type: docs", "Type: refactor").replace(
            "Status: draft", "Status: draft\nWitness: ids bit-identical, 62 -> 9.7 ms"),
    }
    got = {k: _grade(_prompt(tmp_path, v, f"draft/feature/pyautobrain/{k}.md"))
           for k, v in samples.items()}
    for g in got.values():
        g.pop("why")
    if not GOLDEN.exists():                       # first run writes the pin
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())

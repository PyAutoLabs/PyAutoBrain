"""tests/test_review_adversary.py — the independent-adversary leg (gate leg 5).

Step 2a was already adversarial in procedure and was still run, in practice, by
the branch's own author. This leg's only new content is *independence* plus
*ordering* — the task's witness is falsified before anything else — so those are
what is pinned here.

Hermetic, and deliberately so after the first version was not: driving the CLI
against this checkout passed locally and failed in CI, where there is no
`origin/main` to diff and the surface comes back empty. A test whose subject is
a block of contract text must not depend on the environment having a diff.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import load_module

BRAIN = Path(__file__).resolve().parents[1]
_review = load_module("_review_adversary_under_test", "agents/faculties/review/_review.py")

WITNESS = "ids bit-identical, 62 -> 9.7 ms"
# Mirrors `repo_surface`'s return shape exactly — a fixture that drifts from the
# producer is a test of the fixture.
SURFACE = [{
    "repo": "PyAutoBrain", "path": "/tmp/PyAutoBrain", "branch": "feature/x",
    "base": "abc123456789", "commits_ahead": 2,
    "commits": ["do the thing"], "shortstat": "3 files changed",
    "files": ["a.py"], "risk_flags": [],
    "claims_to_falsify": ["This change is a no-op for CI."],
}]


def _emit(capsys, **kw):
    _review.emit_human(SURFACE, **kw)
    return capsys.readouterr().out


def test_the_witness_is_lifted_and_falsified_first(capsys):
    """It is the claim the task was scoped around: if it does not hold, the work
    did not do what it promised and nothing else on the surface matters."""
    out = _emit(capsys, witness=WITNESS)
    assert WITNESS in out
    assert "THE WITNESS" in out
    assert out.index("THE WITNESS") < out.index("A load-bearing claim above")
    assert "Falsify it first" in out


def test_adversary_mode_states_who_may_not_run_it(capsys):
    """The independence rule is the leg. A surface that omits it invites the
    exact failure the leg exists to close."""
    out = _emit(capsys, adversary=True)
    assert "NOT the session that wrote the branch" in out
    assert "A self-run adversary leg is not a weaker version" in out


@pytest.mark.parametrize("section", [
    # A task with no witness grades `judge` and is reviewed by a human; the
    # surface must not imply a claim that was never made.
    pytest.param("THE WITNESS", id="no-witness-section-when-none-is-declared"),
    pytest.param("INDEPENDENT ADVERSARY MODE", id="contract-is-absent-unless-asked-for"),
])
def test_a_plain_surface_carries_neither_optional_section(capsys, section):
    assert section not in _emit(capsys)


def test_payload_carries_witness_and_mode():
    p = _review.surface_payload(SURFACE, WITNESS, True)
    assert p["witness"] == WITNESS
    assert p["mode"] == "independent-adversary"
    assert "contract" in p
    assert p["review_surface"] == SURFACE


def test_payload_omits_them_when_not_asked():
    p = _review.surface_payload(SURFACE)
    assert "witness" not in p and "mode" not in p and "contract" not in p


def test_the_surface_is_assembled_without_touching_git():
    """`surface_payload` is pure: the CLI resolves repos and reads diffs, this
    only shapes what was found. That split is what makes the tests above
    hermetic."""
    assert _review.surface_payload([])["review_surface"] == []

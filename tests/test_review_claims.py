"""tests/test_review_claims.py — the adversarial-claim surfacing (item 6).

docs/agent_failure_modes.md item 6: the review faculty routes the reviewing
agent to the branch's load-bearing empirical claims so the "what would make
this false?" pass fires by construction, not by the author's memory. These pin
what is surfaced (dangerous effect-claims) vs skipped (idle phrasing).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "faculties" / "review"))
from _review import load_bearing_claims  # noqa: E402


def test_surfaces_effect_claims():
    text = (
        "Proven byte-identical on the mega-run CI env.\n"
        "This change is a no-op for CI.\n"
        "The scrub does not affect infra vars.\n"
        "behaviour-preserving where behaviour is correct.\n"
    )
    claims = load_bearing_claims(text)
    joined = " ".join(claims).lower()
    assert "byte-identical" in joined
    assert "no-op" in joined
    assert "does not affect" in joined
    assert "behaviour-preserving" in joined


def test_skips_idle_phrasing():
    text = (
        "Add a helper to parse the config.\n"
        "Rename the variable for clarity.\n"
        "Update the changelog and bump the docs.\n"
    )
    assert load_bearing_claims(text) == []


def test_dedupes_and_caps():
    text = "\n".join(["This is a no-op."] * 5 + [f"claim {i} is proven" for i in range(20)])
    claims = load_bearing_claims(text, limit=12)
    assert len(claims) <= 12
    assert sum("no-op" in c.lower() for c in claims) == 1  # deduped


def test_short_fragment_and_blank_lines_ignored():
    # "no-op" (5 chars) is below the min length and dropped; blank lines too.
    # "identical" (9 chars) clears the bar and is surfaced — a claim is a claim.
    claims = load_bearing_claims("no-op\n\n   \nidentical")
    assert claims == ["identical"]


def test_verified_and_safe_to_delete_are_claims():
    text = "verified against the real stack.\nsafe to delete this branch.\nzero diff observed."
    claims = load_bearing_claims(text)
    j = " ".join(claims).lower()
    assert "verified" in j and "safe to delete" in j and "zero diff" in j

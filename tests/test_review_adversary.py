"""tests/test_review_adversary.py — the independent-adversary leg (gate leg 5).

Step 2a was already adversarial in procedure and was still run, in practice, by
the branch's own author. This leg's only new content is *independence* plus
*ordering* — the task's witness is falsified before anything else — so those are
what is pinned here.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_review_adversary_under_test",
    BRAIN / "agents" / "faculties" / "review" / "_review.py")
_review = importlib.util.module_from_spec(_spec)
sys.modules["_review_adversary_under_test"] = _review
_spec.loader.exec_module(_review)

WITNESS = "ids bit-identical, 62 -> 9.7 ms"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(BRAIN / "agents" / "faculties" / "review" / "_review.py"),
         "--repo", str(BRAIN), *args],
        capture_output=True, text=True)


def test_the_witness_is_lifted_and_falsified_first():
    out = _run("--witness", WITNESS).stdout
    assert WITNESS in out
    assert "THE WITNESS" in out
    assert "Falsify it first" in out


def test_no_witness_section_when_none_is_declared():
    """A task with no witness grades `judge` and is reviewed by a human; the
    surface must not imply a claim that was never made."""
    assert "THE WITNESS" not in _run().stdout


def test_adversary_mode_states_who_may_not_run_it():
    """The independence rule is the leg. A surface that omits it invites the
    exact failure the leg exists to close."""
    out = _run("--adversary").stdout
    assert "NOT the session or model that wrote the branch" in out
    assert "A self-run adversary leg is not a weaker version" in _review.ADVERSARY_CONTRACT


def test_contract_is_absent_unless_asked_for():
    assert "INDEPENDENT ADVERSARY MODE" not in _run().stdout


def test_json_surface_carries_witness_and_mode():
    payload = json.loads(_run("--json", "--witness", WITNESS, "--adversary").stdout)
    assert payload["witness"] == WITNESS
    assert payload["mode"] == "independent-adversary"
    assert "contract" in payload


def test_json_surface_omits_them_when_not_asked():
    payload = json.loads(_run("--json").stdout)
    assert "witness" not in payload and "mode" not in payload

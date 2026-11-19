"""The shift worker runs the chat loop (M3.7a, PyAutoBrain#686).

Rulings S1 and S3 of AUTONOMY.md "Shift speed — 2026-11-19": inside a shift
the worker runs the test modules its diff changes or that cover the changed
code, plus the `Witness:`, not the full suite (PR CI is the full-suite
verdict); the dependants' full suites still run on a public API change; one
independent review and the targeted smoke, then the PR opens; no adversary
pass (the close-out session or the human at `/prm` is the adversary).
"""

from __future__ import annotations

import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _orchestrator as orch  # noqa: E402

SECTION = "## Shift speed — 2026-11-19"


def _flat(text: str) -> str:
    """Prose wraps anywhere; compare phrases with whitespace collapsed."""
    return " ".join(text.split())


def _prompt() -> str:
    return _flat(orch.worker_prompt("t1", "draft/feature/widgetlib/t1.md", Path("b.md"), Path("leases")))


def _autonomy() -> str:
    return (BRAIN / "AUTONOMY.md").read_text(encoding="utf-8")


def test_the_worker_runs_the_changed_test_modules_and_the_witness_not_the_full_suite():
    prompt = _prompt()
    assert "test modules your diff changes or that cover the changed code" in prompt
    assert "the task's `Witness:`" in prompt
    assert "not the full suite" in prompt
    assert "PR CI is the full-suite verdict" in prompt
    assert "-n 4" in prompt
    # Only legs 1 and 5 change; the Heart leg is unchanged.
    assert "Only legs 1 (tests) and 5 (adversary) of the autonomous-ship gate change in a shift" in prompt
    assert "the Heart verdict (leg 4) apply as before" in prompt
    assert "not the full gate" not in prompt
    assert "S1" in prompt and "Shift speed — 2026-11-19" in prompt


def test_the_worker_runs_no_adversary_pass():
    prompt = _prompt()
    assert "--adversary" not in prompt
    assert "no adversary pass" in prompt
    assert "S3" in prompt


def test_the_worker_still_runs_one_independent_review_and_the_targeted_smoke():
    prompt = _prompt()
    assert "one independent review" in prompt
    assert "verdict CLEAN" in prompt
    assert "--targeted --changed-files" in prompt
    # The review starts beside the tests and the smoke; the PR opens once all pass.
    assert "beside the tests and the targeted smoke" in prompt
    assert "Open the PR as soon as" in prompt


def test_the_worker_runs_the_dependants_suites_on_a_public_api_change():
    prompt = _prompt()
    assert "dependants' full suites" in prompt
    assert "public API change" in prompt


def test_autonomy_records_s1_and_s3_and_legs_1_and_5_point_to_them():
    text = _autonomy()
    assert SECTION in text
    sec = _flat(text.split(SECTION, 1)[1].split("\n## ", 1)[0])
    assert "**S1, leg 1 in a shift.**" in sec
    assert "**S3, leg 5 in a shift.**" in sec
    assert "PR CI is the full-suite verdict" in sec
    assert "Outside a shift (an `--auto` chat) nothing changes." in sec
    gate = text.split("## The autonomous-ship gate", 1)[1].split("\n### ", 1)[0]
    leg1 = gate.split("1. **Tests**", 1)[1].split("\n2. **Smoke**", 1)[0]
    leg5 = gate.split("5. **Independent adversary**", 1)[1].split("\nA failed leg", 1)[0]
    leg1, leg5 = _flat(leg1), _flat(leg5)
    assert "Shift speed — 2026-11-19" in leg1 and "S1" in leg1
    assert "Shift speed — 2026-11-19" in leg5 and "S3" in leg5


def test_ship_library_follows_the_shift_rule():
    skill = _flat((BRAIN / "skills" / "ship_library" / "ship_library.md").read_text(encoding="utf-8"))
    # Outside a shift a batch launch still needs leg 5; the shift worker is the exception.
    assert "five under a batch launch" in skill
    assert "a shift worker runs no adversary pass (ruling S3" in skill
    assert "Shift speed — 2026-11-19" in skill
    assert "Shift worker tests: ruling S1, see [`reference.md`]" in skill
    ref = (BRAIN / "skills" / "ship_library" / "reference.md").read_text(encoding="utf-8")
    step1 = _flat(ref.split("## Execution contract", 1)[1].split("\n2. ", 1)[0])
    assert "shift worker" in step1 and "-n 4" in step1
    assert "Shift speed — 2026-11-19" in step1
    assert "beside these tests and the targeted smoke" in step1
    assert "no adversary pass (ruling S3)" in step1

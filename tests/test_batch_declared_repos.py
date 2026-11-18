"""`declared_repos` and the batch claim gate (PyAutoBrain#675).

A prompt's `Target:` is often only an epic label: a prompt with
`Target: pyautoeyes` whose `Repos:` lists only PyAutoCortex never touches
PyAutoEyes, so a claim on PyAutoEyes must not hold it.
"""

from __future__ import annotations

import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _batch  # noqa: E402
import _orchestrator as orch  # noqa: E402
from _sizing import normalise_repo  # noqa: E402

ACTIVE = ("# Active\n\n## eyes-work\n- prompt: active/feature/pyautoeyes/eyes-work.md\n"
          "- session: claude-code desktop (WSL)\n- repos:\n  - PyAutoEyes\n")


def _prompt(target: str, repos: list[str] | None) -> dict:
    text = f"Target: {target}\n"
    if repos is not None:
        text += "Repos:\n" + "".join(f"- {r}\n" for r in repos)
    return {"target": target, "text": text + "\nBody.\n", "repos": ["survey_only"]}


def test_repos_block_wins_over_an_epic_label_target():
    p = _prompt("pyautoeyes", ["PyAutoCortex"])
    assert _batch.declared_repos(p) == [normalise_repo("PyAutoCortex")]


def test_claim_on_the_target_does_not_hold_a_prompt_that_never_touches_it():
    sections = orch.claim_sections(ACTIVE)
    cortex_only = _batch.declared_repos(_prompt("pyautoeyes", ["PyAutoCortex"]))
    assert orch._held_for(sections, "cortex-ledger", cortex_only) is None
    touches_eyes = _batch.declared_repos(_prompt("pyautoeyes", ["PyAutoEyes", "PyAutoCortex"]))
    assert orch._held_for(sections, "eyes-follow-up", touches_eyes) == ("PyAutoEyes", "eyes-work")


def test_no_repos_block_falls_back_to_target():
    assert _batch.declared_repos(_prompt("pyautoeyes", None)) == [normalise_repo("pyautoeyes")]


def test_repos_block_of_unknown_names_falls_back_to_target():
    p = _prompt("pyautoeyes", ["not_a_repo", "another_unknown"])
    assert _batch.declared_repos(p) == [normalise_repo("pyautoeyes")]


def test_unknown_target_and_no_repos_falls_back_to_survey():
    assert _batch.declared_repos(_prompt("epic-label", None)) == ["survey_only"]

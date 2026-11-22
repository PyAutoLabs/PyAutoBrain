"""`declared_repos` and the batch claim gate (PyAutoBrain#675).

A prompt's `Target:` is often only an epic label: a prompt with
`Target: pyautoeyes` whose `Repos:` lists only PyAutoCortex never touches
PyAutoEyes, so a claim on PyAutoEyes must not hold it.
"""

from __future__ import annotations

import pytest

from _shift_fixtures import _batch
import _orchestrator as orch  # noqa: E402
from _sizing import normalise_repo  # noqa: E402

ACTIVE = ("# Active\n\n## eyes-work\n- prompt: active/feature/pyautoeyes/eyes-work.md\n"
          "- session: claude-code desktop (WSL)\n- repos:\n  - PyAutoEyes\n")


def _prompt(target: str, repos: list[str] | None) -> dict:
    text = f"Target: {target}\n"
    if repos is not None:
        text += "Repos:\n" + "".join(f"- {r}\n" for r in repos)
    return {"target": target, "text": text + "\nBody.\n", "repos": ["survey_only"]}


def test_claim_on_the_target_does_not_hold_a_prompt_that_never_touches_it():
    sections = orch.claim_sections(ACTIVE)
    cortex_only = _batch.declared_repos(_prompt("pyautoeyes", ["PyAutoCortex"]))
    assert orch._held_for(sections, "cortex-ledger", cortex_only) is None
    touches_eyes = _batch.declared_repos(_prompt("pyautoeyes", ["PyAutoEyes", "PyAutoCortex"]))
    assert orch._held_for(sections, "eyes-follow-up", touches_eyes) == ("PyAutoEyes", "eyes-work")


@pytest.mark.parametrize("target, repos, expected", [
    pytest.param("pyautoeyes", ["PyAutoCortex"], [normalise_repo("PyAutoCortex")],
                 id="repos-block-wins-over-an-epic-label-target"),
    pytest.param("pyautoeyes", None, [normalise_repo("pyautoeyes")],
                 id="no-repos-block-falls-back-to-target"),
    pytest.param("pyautoeyes", ["not_a_repo", "another_unknown"], [normalise_repo("pyautoeyes")],
                 id="repos-block-of-unknown-names-falls-back-to-target"),
    pytest.param("epic-label", None, ["survey_only"],
                 id="unknown-target-and-no-repos-falls-back-to-survey"),
])
def test_declared_repos(target, repos, expected):
    assert _batch.declared_repos(_prompt(target, repos)) == expected

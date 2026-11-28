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


# PyAutoBrain#742: a worker parked on a question before its first edit holds
# no repo; one parked after it (real branch, worktree) still does.
PARKED = ("# Active\n\n## parked-task\n- status: awaiting-input\n- question: q?\n"
          "- repos:\n  - RepoH: (no branch; parked before implementation)\n")
PARKED_PAREN = ("# Active\n\n## parked-task\n- status: awaiting-input\n"
                "- repos:\n  - RepoH (no branch; parked)\n  - RepoI\n")
PARKED_INLINE = "# Active\n\n## parked-task\n- status: awaiting-input\n- repos: RepoH\n"
PARKED_LIVE = ("# Active\n\n## parked-task\n- status: awaiting-input\n"
               "- worktree: ~/wt/parked-task\n- repos:\n  - RepoH (feature/parked-task)\n")
NO_BRANCH_WITH_WT = ("# Active\n\n## mixed\n- worktree: ~/wt/mixed\n- repos:\n"
                     "  - RepoH: (no branch yet)\n  - RepoI (feature/mixed)\n  - RepoJ\n")


@pytest.mark.parametrize("active", [
    pytest.param(PARKED, id="colon-schema"),
    pytest.param(PARKED_PAREN, id="paren-schema-and-bare"),
    pytest.param(PARKED_INLINE, id="inline-repos"),
])
def test_parked_branchless_entry_is_not_a_claim(active):
    sections = orch.claim_sections(active)
    assert sections["parked-task"]["repos"] == []
    assert normalise_repo("RepoH") not in orch.claimed_repos(sections)


def test_parked_entry_with_a_real_branch_still_claims():
    sections = orch.claim_sections(PARKED_LIVE)
    assert sections["parked-task"]["repos"] == ["RepoH"]
    assert orch.claimed_repos(sections)[normalise_repo("RepoH")][1] == "parked-task"


def test_no_branch_entry_is_dropped_but_bare_and_branched_entries_claim():
    assert orch.claim_sections(NO_BRANCH_WITH_WT)["mixed"]["repos"] == ["RepoI", "RepoJ"]

"""The shift's smoke split (AUTONOMY.md leg 2, 2026-11-19, PyAutoHeart#352).

A shift worker runs a targeted smoke only; the full affected smoke, three
workspaces at a time, runs in the close-out before an unattended merge, and
not at all for a PR bound for the human's /prm (the close-out refuses those
before it reaches the smoke step).
"""

from __future__ import annotations

import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _orchestrator as orch  # noqa: E402

PR = "https://github.com/ExampleOrg/WidgetLib/pull/7"


def _closeout(pr_url=PR, tmp=Path("t")):
    return orch.closeout_prompt("t1", pr_url, "draft/x/t1.md", tmp / "b.md", tmp / "leases")


def _step(text: str, n: int) -> str:
    return text.split(f"\n{n}. ", 1)[1].split(f"\n{n + 1}. ", 1)[0]


def test_the_worker_runs_a_targeted_smoke_and_says_so_in_the_pr_body():
    prompt = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"))
    assert "pyauto-heart smoke" in prompt and "--targeted --changed-files" in prompt
    assert "never the full workspace sweep" in prompt
    assert "PR body which smoke ran" in prompt
    assert "PyAutoHeart#352" in prompt


def test_a_notify_worker_runs_the_affected_smoke_before_an_in_turn_merge():
    prompt = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"))
    merge = prompt.split("merge-slot take", 1)[1].split("If it refuses", 1)[0]
    assert "--affected-by <repo> --jobs 3" in merge


def test_the_closeout_runs_the_affected_parallel_smoke_before_the_merge():
    text = _closeout()
    smoke = _step(text, 5)
    assert "--affected-by WidgetLib --jobs 3" in smoke
    assert "resolve_heart" in smoke and '--root "$PWD"' in smoke
    assert "headRefOid" in smoke and "--ff-only" in smoke
    assert "smoke FAILED" in smoke and "/prm" in smoke
    # The smoke comes after the refusal steps (tier, decision-taken, Heart, CI),
    # so a PR bound for the human's /prm never reaches a full sweep...
    assert text.index("decision-taken") < text.index("full affected smoke")
    # ...and before the merge itself.
    assert text.index("full affected smoke") < text.index("use the prm skill")
    assert "/smoke …" in text  # the verdict's gate field names it


def test_the_closeout_smoke_cannot_be_scoped_without_a_pr_repo():
    assert orch.smoke_command("") == ""
    assert "not a GitHub PR URL — refuse" in _step(_closeout("not-a-pr"), 5)


def test_autonomy_leg_2_records_the_split():
    leg = (BRAIN / "AUTONOMY.md").read_text().split("2. **Smoke**", 1)[1].split("\n3. **Review**", 1)[0]
    assert "2026-11-19" in leg and "PyAutoHeart#352" in leg and "approve C" in leg
    assert "--targeted" in leg and "--affected-by" in leg and "--jobs 3" in leg
    assert "/prm" in leg

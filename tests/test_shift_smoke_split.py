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


def test_a_notify_worker_ends_at_pr_open_and_never_merges_in_turn():
    """Ruling "ii" (2026-11-19, PyAutoHeart#352): a shift `notify` worker ends
    at PR-open like `glance`; the close-out merges after the affected smoke.
    The watcher side is unchanged: test_orchestrator_closeout.py
    test_a_notify_pr_left_open_is_closed_out_like_glance."""
    prompt = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"))
    assert "`Consequence: glance` or `notify`, end at PR-open" in prompt
    # No in-turn merge commands are handed to the worker any more.
    assert "merge-slot take <pr-url>" not in prompt
    assert "merge-slot release" not in prompt
    assert "a bare `gh pr merge`" not in prompt
    assert "merged in-turn under its tier" not in prompt
    sib = orch.worker_prompt("t1", "draft/x/t1.md", Path("b.md"), Path("leases"),
                             siblings=["https://github.com/o/r/pull/1"])
    assert "Never merge in-turn ahead" not in sib and "End at PR-open" in sib


def test_the_watcher_still_closes_out_both_unattended_tiers():
    src = (BATCH / "_orchestrator.py").read_text()
    gate = src.split("def _start_closeouts", 1)[1]
    assert 'if tier not in ("glance", "notify"):' in gate


def test_autonomy_records_the_notify_ruling():
    text = (BRAIN / "AUTONOMY.md").read_text()
    sec = text.split("### Shift `notify` workers end at PR-open — 2026-11-19", 1)[1].split("\n## ", 1)[0]
    assert "notify workers no longer merge in-turn" in sec
    assert '"ii"' in sec and "PyAutoHeart#352" in sec
    agents = (BATCH / "AGENTS.md").read_text()
    assert "Shift workers no\nlonger merge in-turn" in agents


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

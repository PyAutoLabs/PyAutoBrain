"""`pyauto-brain ci-verdict` — the one CI judgement (PyAutoBrain#628).

Every case runs against a fake `gh` (the `run` seam), so the suite is offline.
The Witness cases: all green; one red leg; a skipped-only check; zero checks;
pending; an empty head sha refused; mergeable BEHIND or CONFLICTING.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "bin"))

import ci_verdict as cv  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"
REF = "ExampleOrg/WidgetLib#7"


def wf(rid, jobs, *, name="Tests", event="pull_request", status="completed",
       conclusion=None):
    """A workflow run with its jobs: `jobs` are (name, status, conclusion)."""
    js = [{"id": rid * 100 + i, "name": n, "status": s, "conclusion": c}
          for i, (n, s, c) in enumerate(jobs)]
    if conclusion is None and status == "completed":
        concl = [j["conclusion"] for j in js]
        conclusion = next((c for c in concl if c not in ("success", "skipped")), "success")
    return {"id": rid, "name": name, "event": event, "head_sha": SHA,
            "status": status, "conclusion": conclusion}, js


class FakeGh:
    """`gh api` by path. `prs` is one PR object or a list of successive reads."""

    def __init__(self, runs=(), *, pr=None, prs=None, extra_checks=(), statuses=(),
                 fail_on=None):
        base = {"sha": SHA, "state": "open", "merged": False, "mergeable": True,
                "mergeable_state": "clean", "draft": False, "url": "https://x/pull/7"}
        self.prs = [dict(base, **p) for p in (prs or [pr or {}])]
        self.runs = [r for r, _ in runs]
        self.jobs = {r["id"]: js for r, js in runs}
        # Every job is also a check-run with the same id (as on GitHub).
        self.check_runs = [dict(j, app={"slug": "github-actions"})
                           for js in self.jobs.values() for j in js] + list(extra_checks)
        self.statuses = list(statuses)
        self.fail_on = fail_on
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        assert argv[:2] == ["gh", "api"]
        self.calls.append(argv)
        path = next(a for a in argv[2:] if a.startswith("repos/"))
        if self.fail_on and self.fail_on in path:
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 502: Bad Gateway")
        if "/pulls/" in path:
            out = [self.prs.pop(0) if len(self.prs) > 1 else self.prs[0]]
        elif "/check-runs" in path:
            out = self.check_runs
        elif "/status?" in path:
            out = self.statuses
        elif "/jobs" in path:
            out = self.jobs[int(path.split("/runs/")[1].split("/")[0])]
        elif "/actions/runs?" in path:
            assert f"head_sha={SHA}" in path
            out = self.runs
        else:
            raise AssertionError(path)
        # `--paginate --jq '.x[]'` prints one compact JSON value per line.
        return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps(o) for o in out), "")


def verdict(gh):
    return cv.verdict_for(REF, run=gh, sleep=lambda s: None)


def codes(v):
    return [r["code"] for r in v["reasons"]]


GREEN_RUNS = [wf(1, [("pytest (3.12)", "completed", "success"),
                     ("pytest (3.13)", "completed", "success")]),
              wf(2, [("pytest (3.12)", "completed", "success"),
                     ("pytest (3.13)", "completed", "success")], event="push")]


# --- the Witness cases -------------------------------------------------------------

def test_all_green_every_run_and_leg():
    v = verdict(FakeGh(GREEN_RUNS))
    assert v["verdict"] == cv.GREEN and v["reasons"] == []
    assert v["counts"]["checks"] == 4          # jobs and check-runs deduplicated
    assert v["sha"] == SHA and v["mergeable_state"] == "clean"
    assert "Tests [push] / pytest (3.13)" in [c["name"] for c in v["checks"]]


def test_one_red_leg_is_red_and_named():
    runs = GREEN_RUNS[:1] + [wf(2, [("pytest (3.12)", "completed", "success"),
                                    ("pytest (3.13)", "completed", "failure")], event="push")]
    v = verdict(FakeGh(runs))
    assert v["verdict"] == cv.RED and codes(v) == ["check-failed"]
    assert "Tests [push] / pytest (3.13) (failure)" in v["reasons"][0]["detail"]


@pytest.mark.parametrize("conclusion,code", [("cancelled", "check-cancelled"),
                                             ("timed_out", "check-timed-out")])
def test_cancelled_or_timed_out_is_red(conclusion, code):
    v = verdict(FakeGh([wf(1, [("a", "completed", "success"),
                               ("b", "completed", conclusion)])]))
    assert v["verdict"] == cv.RED and code in codes(v)


def test_skipped_only_is_red():
    v = verdict(FakeGh([wf(1, [("smoke", "completed", "skipped")])]))
    assert v["verdict"] == cv.RED and codes(v) == ["skipped-only"]
    assert v["skipped"] == ["Tests [pull_request] / smoke"]


def test_a_skipped_leg_beside_a_green_one_is_green_and_named():
    v = verdict(FakeGh([wf(1, [("pytest", "completed", "success"),
                               ("docs", "completed", "skipped")])]))
    assert v["verdict"] == cv.GREEN
    assert v["skipped"] == ["Tests [pull_request] / docs"]
    assert "skipped: Tests [pull_request] / docs" in cv.summary(v)


def test_zero_checks_is_red():
    v = verdict(FakeGh([]))
    assert v["verdict"] == cv.RED and codes(v) == ["no-checks"]


def test_pending_leg_is_pending():
    runs = [wf(1, [("pytest (3.12)", "completed", "success"),
                   ("pytest (3.13)", "in_progress", None)], status="in_progress")]
    v = verdict(FakeGh(runs))
    assert v["verdict"] == cv.PENDING and codes(v) == ["checks-pending"]
    assert "1 of 2 not completed" in v["reasons"][0]["detail"]


def test_a_queued_run_with_no_jobs_yet_is_pending():
    runs = GREEN_RUNS[:1] + [wf(3, [], name="Lint", status="queued")]
    v = verdict(FakeGh(runs))
    assert v["verdict"] == cv.PENDING and "Lint [pull_request] (queued)" in v["reasons"][0]["detail"]


def test_a_run_that_failed_before_any_job_is_red():
    runs = GREEN_RUNS[:1] + [wf(3, [], name="Lint", conclusion="startup_failure")]
    v = verdict(FakeGh(runs))
    assert v["verdict"] == cv.RED and "Lint [pull_request] (startup_failure)" in v["reasons"][0]["detail"]


@pytest.mark.parametrize("sha", ["", None, "   "])
def test_an_empty_head_sha_is_refused_before_any_run_query(sha):
    gh = FakeGh(GREEN_RUNS, pr={"sha": sha})
    v = verdict(gh)
    assert v["verdict"] == cv.RED and codes(v) == ["empty-sha"]
    assert all("/pulls/" in " ".join(c) for c in gh.calls)   # never asked for runs


@pytest.mark.parametrize("pr,code", [
    ({"mergeable_state": "behind"}, "behind"),
    ({"mergeable_state": "dirty", "mergeable": False}, "conflicting"),
    ({"mergeable_state": "unknown", "mergeable": False}, "conflicting"),
    ({"mergeable_state": "blocked"}, "blocked"),
    ({"mergeable_state": "draft", "draft": True}, "draft"),
    ({"mergeable_state": "has_hooks"}, "not-clean"),
])
def test_mergeable_states_that_stop_a_merge_are_red(pr, code):
    v = verdict(FakeGh(GREEN_RUNS, pr=pr))
    assert v["verdict"] == cv.RED and code in codes(v)


def test_conflicting_is_red_even_while_checks_run():
    runs = [wf(1, [("pytest", "queued", None)], status="queued")]
    v = verdict(FakeGh(runs, pr={"mergeable_state": "dirty", "mergeable": False}))
    assert v["verdict"] == cv.RED and set(codes(v)) == {"conflicting", "checks-pending"}


def test_blocked_while_checks_run_is_pending_not_red():
    """GitHub reads `blocked` while required checks are still running."""
    runs = [wf(1, [("pytest", "in_progress", None)], status="in_progress")]
    v = verdict(FakeGh(runs, pr={"mergeable_state": "blocked"}))
    assert v["verdict"] == cv.PENDING and codes(v) == ["checks-pending"]


def test_mergeability_not_yet_computed_is_asked_once_more_then_pending():
    gh = FakeGh(GREEN_RUNS, prs=[{"mergeable": None, "mergeable_state": "unknown"}] * 2)
    v = verdict(gh)
    assert v["verdict"] == cv.PENDING and codes(v) == ["mergeable-unknown"]
    assert sum("/pulls/" in " ".join(c) for c in gh.calls) == 2


def test_mergeability_computed_on_the_second_read_is_used():
    gh = FakeGh(GREEN_RUNS, prs=[{"mergeable": None, "mergeable_state": "unknown"}, {}])
    assert verdict(gh)["verdict"] == cv.GREEN


def test_a_merged_pr_is_judged_on_its_checks_alone():
    v = verdict(FakeGh(GREEN_RUNS, pr={"state": "closed", "merged": True,
                                       "mergeable": None, "mergeable_state": "unknown"}))
    assert v["verdict"] == cv.GREEN and "already merged" in v["note"]


def test_a_closed_unmerged_pr_is_red():
    v = verdict(FakeGh(GREEN_RUNS, pr={"state": "closed", "mergeable": None}))
    assert v["verdict"] == cv.RED and "closed" in codes(v)


# --- other check sources ---------------------------------------------------------------

def test_a_third_party_check_run_and_a_commit_status_are_judged():
    extra = [{"id": 999, "name": "codecov/patch", "status": "completed",
              "conclusion": "failure", "app": {"slug": "codecov"}}]
    v = verdict(FakeGh(GREEN_RUNS, extra_checks=extra))
    assert v["verdict"] == cv.RED and "codecov/patch (codecov) (failure)" in v["reasons"][0]["detail"]
    v = verdict(FakeGh(GREEN_RUNS, statuses=[{"context": "docs/rtd", "state": "pending"}]))
    assert v["verdict"] == cv.PENDING
    v = verdict(FakeGh(GREEN_RUNS, statuses=[{"context": "docs/rtd", "state": "error"}]))
    assert v["verdict"] == cv.RED


def test_an_unknown_conclusion_fails_closed():
    v = verdict(FakeGh([wf(1, [("a", "completed", "success"), ("b", "completed", "mystery")],
                           conclusion="success")]))
    assert v["verdict"] == cv.RED and codes(v) == ["check-unrecognised"]


def test_an_unreadable_gh_reply_is_red_never_green():
    v = verdict(FakeGh(GREEN_RUNS, fail_on="/check-runs"))
    assert v["verdict"] == cv.RED and codes(v) == ["unreadable"]
    assert "502" in v["reasons"][0]["detail"]


def test_paginated_output_of_several_pages_is_read_whole():
    out = '{"a": 1}\n{"a": 2}\n{\n "a": 3\n}\n'
    got = cv._gh(lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, ""), "x")
    assert got == [{"a": 1}, {"a": 2}, {"a": 3}]


# --- the CLI ---------------------------------------------------------------------------

@pytest.mark.parametrize("ref", ["ExampleOrg/WidgetLib#7", "ExampleOrg/WidgetLib/pull/7",
                                 "https://github.com/ExampleOrg/WidgetLib/pull/7"])
def test_parse_ref_forms(ref):
    assert cv.parse_ref(ref) == ("ExampleOrg/WidgetLib", 7)


@pytest.mark.parametrize("gh,code,word", [
    (FakeGh(GREEN_RUNS), 0, "GREEN"),
    (FakeGh([]), 1, "RED"),
    (FakeGh([wf(1, [("a", "queued", None)], status="queued")]), 2, "PENDING"),
])
def test_cli_exit_codes_summary_and_json(gh, code, word, capsys):
    assert cv.main([REF], run=gh, sleep=lambda s: None) == code
    assert capsys.readouterr().out.splitlines()[0].endswith(f"— {word}")
    assert cv.main([REF, "--json"], run=gh, sleep=lambda s: None) == code
    assert json.loads(capsys.readouterr().out)["verdict"] == word


def test_the_brain_cli_dispatches_the_verb():
    r = subprocess.run([str(BRAIN_HOME / "bin" / "pyauto-brain"), "ci-verdict", "not-a-ref"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == cv.EXIT_USAGE and "not a PR reference" in r.stderr


# --- the three call sites ------------------------------------------------------------

def test_the_merge_paths_name_the_script():
    prm = (BRAIN_HOME / "skills" / "prm" / "prm.md").read_text(encoding="utf-8")
    step2 = prm.split("## 2.", 1)[1].split("## 3.", 1)[0]
    assert "pyauto-brain ci-verdict" in step2
    tmpl = (BRAIN_HOME / "agents" / "conductors" / "batch" / "closeout_template.md")
    assert "{ci_verdict_cmd}" in tmpl.read_text(encoding="utf-8")
    digest = (BRAIN_HOME / "agents" / "conductors" / "batch" / "_digest.py")
    assert "ci_verdict.judge(" in digest.read_text(encoding="utf-8")

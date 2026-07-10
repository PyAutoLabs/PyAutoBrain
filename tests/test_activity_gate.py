"""tests/test_activity_gate.py — the nightly activity gate's decision logic.

Pins the pipeline self-commit contract (design §4 of
PyAutoBuild/docs/nightly_release_design.md): both exclusion signals are
pipeline-controlled, so a drift in release.yml's git identity or commit
message prefix fails here instead of silently re-counting releases as
activity.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "agents" / "conductors" / "release" / "activity_gate.py"
)
spec = importlib.util.spec_from_file_location("activity_gate", MODULE_PATH)
activity_gate = importlib.util.module_from_spec(spec)
sys.modules["activity_gate"] = activity_gate
spec.loader.exec_module(activity_gate)


def commit(message="fix: a real change", name="Jam", email="dev@example.com"):
    """A minimal GitHub `GET /repos/{o}/{r}/commits` list item."""
    return {
        "sha": "a" * 40,
        "commit": {
            "message": message,
            "author": {"name": name, "email": email},
            "committer": {"name": name, "email": email},
        },
    }


def test_normal_commit_counts():
    assert not activity_gate.is_pipeline_commit(commit())
    v = activity_gate.judge({"PyAutoLens": [commit()]})
    assert v["active"] is True
    assert v["counts"] == {"PyAutoLens": 1}


def test_release_message_prefix_is_excluded():
    c = commit(message="Release 2026.7.9.1: update notebooks and version")
    assert activity_gate.is_pipeline_commit(c)
    v = activity_gate.judge({"autolens_workspace": [c]})
    assert v["active"] is False
    assert v["excluded"] == 1
    assert "self-commit" in v["summary"]


def test_bot_identity_is_excluded_regardless_of_message():
    for name, email in [
        ("GitHub Actions bot", "dev@example.com"),
        ("github-actions[bot]", "dev@example.com"),
        ("Someone", "richard@rghsoftware.co.uk"),
    ]:
        c = commit(message="regenerate notebooks", name=name, email=email)
        assert activity_gate.is_pipeline_commit(c), (name, email)


def test_release_like_but_human_message_counts():
    # "Release notes" prose, not the pipeline's "Release <YYYY.…>:" stamp.
    c = commit(message="Release notes cleanup for the docs page")
    assert not activity_gate.is_pipeline_commit(c)


def test_mixed_repo_night():
    v = activity_gate.judge({
        "PyAutoFit": [commit(), commit(message="Release 2026.7.8.1: bump Colab URL tag refs")],
        "HowToLens": [],
        "PyAutoArray": [commit(message="perf: faster kernels")],
    })
    assert v["active"] is True
    assert v["counts"] == {"PyAutoArray": 1, "PyAutoFit": 1}
    assert v["excluded"] == 1
    assert "PyAutoArray (1)" in v["summary"] and "PyAutoFit (1)" in v["summary"]


def test_empty_window_is_quiet():
    v = activity_gate.judge({r: [] for r in activity_gate.RELEASE_RELEVANT_REPOS})
    assert v["active"] is False
    assert v["counts"] == {}
    assert v["summary"] == "no qualifying activity"


def test_malformed_entries_never_crash_or_count():
    v = activity_gate.judge({"PyAutoLens": [None, "junk", {}], "bad": "not-a-list"})
    # {} is a well-formed-enough commit dict (not pipeline) — it counts;
    # non-dicts never do, and a non-list repo value is a FETCH ERROR (#67),
    # counted rather than ignored.
    assert v["counts"] == {"PyAutoLens": 1}
    assert v["fetch_errors"] == 1
    assert v["fetched"] == 1
    assert v["all_failed"] is False


def test_fetch_error_is_not_a_quiet_repo():
    # The 2026-07-10 06:05 incident (#67, hole 1): every fetch failed and the
    # old '[]' fallback read as a quiet night. `null` per repo must instead
    # produce all_failed=True so the driver pages, never 💤-skips.
    v = activity_gate.judge({r: None for r in activity_gate.RELEASE_RELEVANT_REPOS})
    assert v["active"] is False
    assert v["fetch_errors"] == len(activity_gate.RELEASE_RELEVANT_REPOS)
    assert v["fetched"] == 0
    assert v["all_failed"] is True
    assert "UNREADABLE" in v["summary"]


def test_partial_fetch_errors_still_qualify_on_readable_activity():
    v = activity_gate.judge({"PyAutoLens": [commit()], "PyAutoFit": None})
    assert v["active"] is True
    assert v["all_failed"] is False
    assert v["fetch_errors"] == 1
    assert "UNREADABLE" in v["summary"]


def test_quiet_night_with_no_errors_is_clean():
    v = activity_gate.judge({r: [] for r in activity_gate.RELEASE_RELEVANT_REPOS})
    assert v["fetch_errors"] == 0
    assert v["all_failed"] is False
    assert "UNREADABLE" not in v["summary"]


def test_anchor_validator():
    # The 2026-07-10 08:03 incident (#67, hole 2): a 404 JSON body reached the
    # `since=` parameter because the empty-string check couldn't catch it.
    assert activity_gate.valid_anchor("2026-07-09T06:05:39Z")
    assert not activity_gate.valid_anchor("")
    assert not activity_gate.valid_anchor(None)
    assert not activity_gate.valid_anchor(
        '{"message":"Not Found","documentation_url":"...","status":"404"}'
    )
    assert not activity_gate.valid_anchor("2026-07-09T06:05:39Z\n")
    assert not activity_gate.valid_anchor("2026-07-09T06:05:39+00:00")


def test_release_relevant_set_is_the_design_set():
    # Design §4: 5 libraries + 3 workspaces + 3 HowTo repos.
    assert len(activity_gate.RELEASE_RELEVANT_REPOS) == 11
    for repo in ("PyAutoConf", "autolens_workspace", "HowToFit"):
        assert repo in activity_gate.RELEASE_RELEVANT_REPOS

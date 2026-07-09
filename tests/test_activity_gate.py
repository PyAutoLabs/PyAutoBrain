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
    # non-dicts never do, and a non-list repo value is ignored.
    assert v["counts"] == {"PyAutoLens": 1}


def test_release_relevant_set_is_the_design_set():
    # Design §4: 5 libraries + 3 workspaces + 3 HowTo repos.
    assert len(activity_gate.RELEASE_RELEVANT_REPOS) == 11
    for repo in ("PyAutoConf", "autolens_workspace", "HowToFit"):
        assert repo in activity_gate.RELEASE_RELEVANT_REPOS

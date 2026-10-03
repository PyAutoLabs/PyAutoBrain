"""Contract tests for the community conductor's CLI footing.

Hermetic: PYAUTO_ROOT points at a fabricated PyAutoMind/repos.yaml and
COMMUNITY_GH at a stub `gh` that serves fixture JSON, so scan/triage surfaces
are asserted structurally with no network and no real checkouts. The conductor
is read-only — it never posts to GitHub (the stub records every call so the
tests can prove no mutating endpoint is ever hit) and never writes files.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

SCAN_KEYS = {
    "self_logins", "org", "hub", "extra_repos", "open_discussions",
    "open_external_issues", "open_external_prs", "awaiting_review",
    "awaiting_response", "counts", "degraded", "next_action",
}
TRIAGE_KEYS = {
    "type", "pr", "repo", "number", "url", "title", "author",
    "author_is_external", "state", "labels", "body", "signals_present",
    "signals_missing", "comment_tail", "awaiting_response", "route",
    "reminders", "comment_coverage",
}

REPOS_YAML = """\
repos:
  PyAutoLens:
    github: PyAutoLabs/PyAutoLens
    category: library
  admin_jammy:
    github: Jammy2211/admin_jammy
    category: admin
"""

EMPTY_SEARCHES = {
    "search_org_issues.json": {"items": []},
    "search_org_prs.json": {"items": []},
    "search_org_review.json": {"items": []},
    "search_extra.json": {"items": []},
    "comments.json": [],
    "discussions.json": [],
    "discussion_comments.json": [],
}


def _discussion(hub, number, login, title, comments=0, answered=False,
                category="Help & Questions", state="open", locked=False):
    return {
        "number": number,
        "title": title,
        "user": {"login": login, "type": "User"},
        "html_url": f"https://github.com/{hub}/discussions/{number}",
        "category": {"name": category, "slug": category.lower(), "is_answerable": True},
        "answer_chosen_at": "2026-07-11T00:00:00Z" if answered else None,
        "labels": [],
        "comments": comments,
        "state": state,
        "locked": locked,
        "body": "",
        "updated_at": "2026-07-10T00:00:00Z",
        "repository_url": f"https://api.github.com/repos/{hub}",
    }


def _item(repo, number, login, title, comments=0, user_type="User"):
    return {
        "number": number,
        "title": title,
        "user": {"login": login, "type": user_type},
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "labels": [],
        "comments": comments,
        "updated_at": "2026-07-10T00:00:00Z",
        "repository_url": f"https://api.github.com/repos/{repo}",
    }


def _fabricate(tmp_path, fixtures):
    """A PYAUTO_ROOT with a body map, plus a stub gh serving per-endpoint
    fixture JSON and logging every invocation to gh_calls.log."""
    mind = tmp_path / "PyAutoMind"
    mind.mkdir()
    (mind / "repos.yaml").write_text(REPOS_YAML)

    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    for name, payload in fixtures.items():
        (fixture_dir / name).write_text(json.dumps(payload))

    stub = tmp_path / "gh"
    stub.write_text(f"""#!/usr/bin/env bash
echo "$@" >> "{tmp_path}/gh_calls.log"
for arg in "$@"; do
  case "$arg" in
    q=org:*review-requested*)  cat "{fixture_dir}/search_org_review.json"; exit 0 ;;
    q=org:*is:issue*)          cat "{fixture_dir}/search_org_issues.json"; exit 0 ;;
    q=org:*is:pr*)             cat "{fixture_dir}/search_org_prs.json"; exit 0 ;;
    q=repo:*)                  cat "{fixture_dir}/search_extra.json"; exit 0 ;;
    repos/*/discussions/*/comments) cat "{fixture_dir}/discussion_comments.json"; exit 0 ;;
    repos/*/discussions/*)     cat "{fixture_dir}/discussion.json"; exit 0 ;;
    repos/*/discussions)       cat "{fixture_dir}/discussions.json"; exit 0 ;;
    */comments)                cat "{fixture_dir}/comments.json"; exit 0 ;;
    repos/*/pulls/*)           cat "{fixture_dir}/pull.json"; exit 0 ;;
    repos/*/issues/*)          cat "{fixture_dir}/issue.json"; exit 0 ;;
  esac
done
exit 1
""")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def _run(args, tmp_path, stub):
    env = {
        **os.environ,
        "PYAUTO_ROOT": str(tmp_path),
        "COMMUNITY_GH": str(stub),
        "COMMUNITY_SEARCH_PAUSE": "0",
    }
    return subprocess.run(
        [str(BRAIN), "community", *args],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )








def test_triage_issue_signals_and_missing_asks(tmp_path):
    body = "```python\nfit = al.FitImaging(...)\n```\nTraceback (most recent call last):\nboom"
    stub = _fabricate(tmp_path, {
        **EMPTY_SEARCHES,
        "issue.json": {
            "number": 7, "title": "crash", "state": "open", "body": body,
            "user": {"login": "some_user", "type": "User"},
            "html_url": "https://github.com/PyAutoLabs/PyAutoLens/issues/7",
            "labels": [{"name": "bug"}],
        },
    })
    r = _run(["triage", "PyAutoLabs/PyAutoLens#7", "--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    t = json.loads(r.stdout)
    assert set(t) == TRIAGE_KEYS
    assert t["type"] == "issue" and t["pr"] is None
    assert t["author_is_external"] is True
    assert t["signals_present"]["code_block"] is True
    assert t["signals_present"]["traceback"] is True
    missing = {m["signal"] for m in t["signals_missing"]}
    assert "version" in missing and "data_pointer" in missing
    assert t["route"].startswith("/start_dev_for_user ")


def test_triage_pr_ref_carries_the_change_shape_block(tmp_path):
    stub = _fabricate(tmp_path, {
        **EMPTY_SEARCHES,
        "issue.json": {
            "number": 40, "title": "add cored profile", "state": "open",
            "body": "adds a cored isothermal profile",
            "user": {"login": "contributor", "type": "User"},
            "html_url": "https://github.com/PyAutoLabs/PyAutoLens/pull/40",
            "labels": [],
            "pull_request": {"url": "https://api.github.com/repos/PyAutoLabs/PyAutoLens/pulls/40"},
        },
        "pull.json": {
            "draft": False, "changed_files": 3, "additions": 120, "deletions": 4,
            "mergeable_state": "clean",
            "requested_reviewers": [{"login": "Jammy2211"}],
            "base": {"ref": "main"}, "head": {"ref": "feature/cored-profile"},
        },
    })
    r = _run(["triage", "https://github.com/PyAutoLabs/PyAutoLens/pull/40", "--json"],
             tmp_path, stub)
    assert r.returncode == 0, r.stderr
    t = json.loads(r.stdout)
    assert t["type"] == "pr"
    assert t["pr"]["changed_files"] == 3
    assert t["pr"]["requested_reviewers"] == ["Jammy2211"]
    assert t["pr"]["head"] == "feature/cored-profile"
    assert "human review" in t["route"] and "/start_dev_for_user" not in t["route"]




def test_bad_ref_and_unknown_mode_fail_loudly(tmp_path):
    stub = _fabricate(tmp_path, EMPTY_SEARCHES)
    assert _run(["triage", "not-a-ref"], tmp_path, stub).returncode == 5
    assert _run(["triage"], tmp_path, stub).returncode == 5
    assert _run(["gossip"], tmp_path, stub).returncode == 5




HUB = "PyAutoLabs/.github"




@pytest.mark.parametrize("category,answered,awaiting", [
    ("Announcements", False, False),
    ("Show and tell", False, False),
    ("Help & Questions", False, None),
    ("Help & Questions", True, False),
    ("Ideas & Proposals", False, None),
    ("Ideas & Proposals", True, False),
    ("Bugs & Errors", False, None),
    ("Bugs & Errors", True, False),
])
def test_discussion_category_and_answer_control_response(
    tmp_path, category, answered, awaiting,
):
    discussion = _discussion(
        HUB, 21, "Jammy2211", "a community thread", comments=1,
        category=category, answered=answered,
    )
    discussion["body"] = "Context remains available for manual triage."
    stub = _fabricate(tmp_path, {
        **EMPTY_SEARCHES,
        "discussions.json": [discussion],
        "discussion.json": discussion,
        "discussion_comments.json": [
            {"user": {"login": "visitor"}, "created_at": "2026-07-10T01:00:00Z",
             "body": "an outside comment"},
        ],
    })
    triage = _run(["triage", f"{HUB}/discussions/21", "--json"], tmp_path, stub)
    assert triage.returncode == 0, triage.stderr
    context = json.loads(triage.stdout)
    assert context["awaiting_response"] is awaiting
    assert context["category"] == category
    assert context["body"] == discussion["body"]
    assert context["comment_tail"][0]["author"] == "visitor"
    assert bool(context["signals_missing"]) is (category not in {"Announcements", "Show and tell"})
    assert "answer in the thread" in context["route"]
    assert "accepted proposal" in context["route"]
    assert "in an answerable category" in context["route"]



def test_triage_discussion_ref_routes_to_the_thread(tmp_path):
    stub = _fabricate(tmp_path, {
        **EMPTY_SEARCHES,
        "discussion.json": _discussion(
            HUB, 11, "asker", "how do I mask my data?", comments=1),
        "discussion_comments.json": [
            {"user": {"login": "asker"}, "created_at": "2026-07-10T01:00:00Z",
             "body": "still stuck"},
        ],
    })
    for ref in (f"https://github.com/{HUB}/discussions/11", f"{HUB}/discussions/11"):
        r = _run(["triage", ref, "--json"], tmp_path, stub)
        assert r.returncode == 0, r.stderr
        t = json.loads(r.stdout)
        assert set(t) >= TRIAGE_KEYS | {"category", "answered"}
        assert t["type"] == "discussion" and t["pr"] is None
        assert t["repo"] == HUB and t["number"] == 11
        assert t["author_is_external"] and t["awaiting_response"] is None
        assert t["category"] == "Help & Questions" and t["answered"] is False
        assert "answer in the thread" in t["route"]
        assert "/start_dev_for_user" in t["route"]
        # Nothing in the run hit the issues endpoints for a discussion ref.
    calls = (tmp_path / "gh_calls.log").read_text()
    assert "/issues/" not in calls
    text = _run(["triage", f"{HUB}/discussions/11"], tmp_path, stub).stdout
    assert "(discussion)" in text and "Category:             Help & Questions" in text


@pytest.mark.parametrize("category,keys", [
    ("Help & Questions", {"assumptions", "data_pointer", "inference_goal"}),
    ("Bugs & Errors", {"code_block", "traceback", "version", "expected_vs_actual", "data_pointer"}),
    ("Ideas & Proposals", {"use_case", "desired_outcome"}),
    ("Announcements", set()), ("Show and tell", set()),
])
def test_category_sensitive_clarifying_questions(tmp_path, category, keys):
    discussion = _discussion(HUB, 5, "visitor", "question", category=category)
    stub = _fabricate(tmp_path, {**EMPTY_SEARCHES, "discussion.json": discussion})
    result = _run(["triage", f"{HUB}/discussions/5", "--json"], tmp_path, stub)
    context = json.loads(result.stdout)
    assert {s["signal"] for s in context["signals_missing"]} == keys
    assert "delivery" in context["route"]
    assert context["delivery_state"] == "unknown"


@pytest.mark.parametrize("comments,reported,author,expected,status", [
    ([], 0, "visitor", True, "complete"),
    ([{"user": {"login": "jammy2211"}}], 1, "visitor", False, "complete"),
    ([], 0, None, None, "partial"),
    ([{"user": None}], 1, "visitor", None, "partial"),
    (None, 0, "visitor", None, "unavailable"),
    ({"message": "failure"}, 0, "visitor", None, "unavailable"),
    ([], 3, "visitor", None, "partial"),
    ([{"user": {"login": "Jammy2211"}}] * 100, 101, "visitor", None, "partial"),
])
def test_bounded_comments_never_invent_response_state(
    tmp_path, comments, reported, author, expected, status,
):
    issue = _item("PyAutoLabs/PyAutoLens", 4, author, "test", comments=reported)
    stub = _fabricate(tmp_path, {**EMPTY_SEARCHES, "issue.json": issue,
                                 "comments.json": comments})
    result = _run(["triage", "PyAutoLabs/PyAutoLens#4", "--json"], tmp_path, stub)
    assert result.returncode == 0, result.stderr
    context = json.loads(result.stdout)
    assert context["awaiting_response"] is expected
    assert context["comment_coverage"]["status"] == status
    assert len(context["comment_tail"]) <= 3
    assert "-X GET -f per_page=100" in (tmp_path / "gh_calls.log").read_text()
    if author is None:
        assert context["author_is_external"] is None


def test_comment_endpoint_failure_keeps_context_but_unknown(tmp_path):
    issue = _item("PyAutoLabs/PyAutoLens", 4, "visitor", "test")
    fixtures = {**EMPTY_SEARCHES, "issue.json": issue}
    del fixtures["comments.json"]
    stub = _fabricate(tmp_path, fixtures)
    result = _run(["triage", "PyAutoLabs/PyAutoLens#4", "--json"], tmp_path, stub)
    assert result.returncode == 0
    context = json.loads(result.stdout)
    assert context["comment_coverage"]["status"] == "unavailable"
    assert context["awaiting_response"] is None


def test_scientific_help_does_not_request_traceback_for_sufficient_context(tmp_path):
    discussion = _discussion(HUB, 5, "visitor", "scientific help")
    discussion["body"] = "My model assumes an SIE lens. The dataset is imaging; I want to infer the slope."
    stub = _fabricate(tmp_path, {**EMPTY_SEARCHES, "discussion.json": discussion})
    result = _run(["triage", f"{HUB}/discussions/5", "--json"], tmp_path, stub)
    context = json.loads(result.stdout)
    assert context["signals_missing"] == []
    assert "traceback" not in context["signals_present"]
    assert context["awaiting_response"] is None

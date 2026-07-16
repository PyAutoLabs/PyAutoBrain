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

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

SCAN_KEYS = {
    "self_logins", "org", "extra_repos", "open_external_issues",
    "awaiting_response", "counts", "degraded", "next_action",
}
TRIAGE_KEYS = {
    "repo", "number", "url", "title", "author", "author_is_external", "state",
    "labels", "body", "signals_present", "signals_missing", "comment_tail",
    "awaiting_response", "route", "reminders",
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


def _issue(repo, number, login, title, comments=0, user_type="User"):
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
    q=org:*)        cat "{fixture_dir}/search_org.json"; exit 0 ;;
    q=repo:*)       cat "{fixture_dir}/search_extra.json"; exit 0 ;;
    */comments)     cat "{fixture_dir}/comments.json"; exit 0 ;;
    repos/*/issues/*) cat "{fixture_dir}/issue.json"; exit 0 ;;
  esac
done
exit 1
""")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def _run(args, tmp_path, stub):
    env = {**os.environ, "PYAUTO_ROOT": str(tmp_path), "COMMUNITY_GH": str(stub)}
    return subprocess.run(
        [str(BRAIN), "community", *args],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )


def test_scan_json_is_a_complete_surface_and_filters_bots(tmp_path):
    stub = _fabricate(tmp_path, {
        "search_org.json": {"items": [
            _issue("PyAutoLabs/PyAutoLens", 1, "some_user", "lens model crashes"),
            _issue("PyAutoLabs/PyAutoLens", 2, "dependabot[bot]", "bump", user_type="Bot"),
        ]},
        "search_extra.json": {"items": []},
        "comments.json": [],
    })
    r = _run(["scan", "--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert set(s) == SCAN_KEYS
    assert s["org"] == "PyAutoLabs"
    assert s["extra_repos"] == ["Jammy2211/admin_jammy"]
    assert [e["author"] for e in s["open_external_issues"]] == ["some_user"]
    assert s["counts"] == {"open_external": 1, "awaiting_response": 1}
    # Uncommented external issue: the author had the last word -> awaiting us.
    assert s["awaiting_response"][0]["last_actor"] == "some_user"


def test_scan_last_word_ours_is_not_awaiting(tmp_path):
    stub = _fabricate(tmp_path, {
        "search_org.json": {"items": [
            _issue("PyAutoLabs/PyAutoLens", 3, "some_user", "feature request", comments=2),
        ]},
        "search_extra.json": {"items": []},
        "comments.json": [
            {"user": {"login": "some_user"}, "created_at": "t1", "body": "ping"},
            {"user": {"login": "Jammy2211"}, "created_at": "t2", "body": "on it"},
        ],
    })
    s = json.loads(_run(["scan", "--json"], tmp_path, stub).stdout)
    assert s["counts"]["awaiting_response"] == 0
    assert s["open_external_issues"][0]["awaiting_response"] is False
    assert s["open_external_issues"][0]["last_actor"] == "Jammy2211"


def test_triage_surface_signals_and_missing_asks(tmp_path):
    body = "```python\nfit = al.FitImaging(...)\n```\nTraceback (most recent call last):\nboom"
    stub = _fabricate(tmp_path, {
        "search_org.json": {"items": []},
        "search_extra.json": {"items": []},
        "issue.json": {
            "number": 7, "title": "crash", "state": "open", "body": body,
            "user": {"login": "some_user", "type": "User"},
            "html_url": "https://github.com/PyAutoLabs/PyAutoLens/issues/7",
            "labels": [{"name": "bug"}],
        },
        "comments.json": [],
    })
    r = _run(["triage", "PyAutoLabs/PyAutoLens#7", "--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    t = json.loads(r.stdout)
    assert set(t) == TRIAGE_KEYS
    assert t["author_is_external"] is True
    assert t["signals_present"]["code_block"] is True
    assert t["signals_present"]["traceback"] is True
    missing = {m["signal"] for m in t["signals_missing"]}
    assert "version" in missing and "data_pointer" in missing
    assert t["route"].startswith("/start_dev_for_user ")


def test_never_writes_and_never_mutates_github(tmp_path):
    stub = _fabricate(tmp_path, {
        "search_org.json": {"items": []},
        "search_extra.json": {"items": []},
        "comments.json": [],
    })
    before = {p for p in tmp_path.rglob("*")}
    r = _run(["scan", "--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    after = {p for p in tmp_path.rglob("*")}
    assert after - before == {tmp_path / "gh_calls.log"}
    calls = (tmp_path / "gh_calls.log").read_text()
    assert "-X POST" not in calls and "-X PATCH" not in calls and "-X DELETE" not in calls
    # Every call is `gh api` reads driven through the one entry point.
    assert all(line.startswith("api ") for line in calls.strip().splitlines())


def test_bad_ref_and_unknown_mode_fail_loudly(tmp_path):
    stub = _fabricate(tmp_path, {
        "search_org.json": {"items": []},
        "search_extra.json": {"items": []},
        "comments.json": [],
    })
    assert _run(["triage", "not-a-ref"], tmp_path, stub).returncode == 5
    assert _run(["triage"], tmp_path, stub).returncode == 5
    assert _run(["gossip"], tmp_path, stub).returncode == 5


def test_scan_degrades_honestly_when_search_fails(tmp_path):
    stub = _fabricate(tmp_path, {"comments.json": []})  # no search fixtures -> stub exits 1
    r = _run(["scan", "--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["counts"]["open_external"] == 0
    assert len(s["degraded"]) == 2

"""Published evidence compatibility, freshness and safe links; no live network."""
import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from ears_fixtures import evidence, row, write_feed

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents/conductors/community"))
import _ears_feed


def adapt(snapshot, state):
    return _ears_feed.adapt(snapshot, state, ["maintainer"], "ExampleOrg", "ExampleOrg/.github")


def test_scan_preserves_source_decisions_and_unknowns():
    rows = [row(), row("discussion", 2, awaiting=None, coverage="partial"),
            row("pr", 3, awaiting=False, review_requested=True, author="maintainer")]
    snapshot, state = evidence(rows)
    s = adapt(snapshot, state)
    assert s["counts"] == {"open_discussions": 1, "open_external": 1,
                           "open_external_prs": 0, "awaiting_review": 1,
                           "awaiting_response": 1, "unknown": 1}
    assert s["open_discussions"][0]["awaiting_response"] is None
    assert s["open_external_issues"][0]["last_actor"] is None
    assert s["awaiting_review"][0]["url"].endswith("/pull/3")
    assert s["degraded"]


@pytest.mark.parametrize("age", [-1, 7])
def test_stale_or_future_evidence_cannot_claim_current_response_state(age):
    snapshot, state = evidence([row(awaiting=False)], generated=datetime.now(timezone.utc) - timedelta(hours=age))
    s = adapt(snapshot, state)
    assert s["stale"] and s["degraded"] and s["counts"]["unknown"] == 1
    assert s["open_external_issues"][0]["awaiting_response"] is None
    assert s["open_external_issues"][0]["observed_awaiting_response"] is False


def test_empty_checked_sources_and_no_coverage_differ():
    assert not adapt(*evidence())["degraded"]
    assert adapt(*evidence(receipts=[]))["degraded"]


def test_partial_and_unavailable_sources_are_not_empty_success():
    snapshot, state = evidence()
    snapshot["receipts"][0].update(status="unavailable", public_verified=False, gaps=["permission unavailable"])
    assert any("unavailable" in gap for gap in adapt(snapshot, state)["degraded"])


@pytest.mark.parametrize("mutation", [
    lambda s, t: s.update(schema_version=2),
    lambda s, t: t.update(updated="2025-01-01T00:00:00Z"),
    lambda s, t: s["conversations"][0].update(url="javascript:alert(1)"),
    lambda s, t: s["conversations"][0].update(number=True),
    lambda s, t: s["receipts"][0].update(public_verified=False),
    lambda s, t: s["conversations"].append(copy.deepcopy(s["conversations"][0])),
])
def test_invalid_published_evidence_fails_closed(mutation):
    snapshot, state = evidence([row()])
    mutation(snapshot, state)
    with pytest.raises(ValueError):
        adapt(snapshot, state)


def test_cli_reads_feed_without_gh_or_writes(tmp_path):
    base = write_feed(tmp_path / "feed", [row("discussion", awaiting=None)])
    before = set(tmp_path.rglob("*"))
    result = subprocess.run([str(BRAIN / "bin/pyauto-brain"), "community", "scan", "--json"],
        env={**os.environ, "COMMUNITY_EARS_URL": base, "COMMUNITY_GH": "/missing/gh"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["counts"]["unknown"] == 1
    assert set(tmp_path.rglob("*")) == before


def test_unavailable_feed_does_not_fallback_to_github(tmp_path):
    result = subprocess.run([str(BRAIN / "bin/pyauto-brain"), "community", "scan", "--json"],
        env={**os.environ, "COMMUNITY_EARS_URL": (tmp_path / "missing").as_uri(), "COMMUNITY_GH": "/missing/gh"},
        capture_output=True, text=True)
    assert result.returncode == 4 and "Ears published evidence unavailable" in result.stderr


def test_excluded_only_sources_are_not_checked_clear():
    snapshot, state = evidence()
    snapshot["receipts"][0].update(status="excluded", public_verified=False)
    state["status"] = "grey"
    assert adapt(snapshot, state)["degraded"]


def test_maintainer_case_matches_producer_identity():
    snapshot, state = evidence([row("pr", author="Maintainer", review_requested=True)])
    surface = adapt(snapshot, state)
    assert surface["counts"]["open_external_prs"] == 0
    assert surface["counts"]["awaiting_review"] == 1

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


def delivery_fixture():
    discussion = row('discussion', closed=True, awaiting=False)
    snapshot, state = evidence([discussion])
    refs = [{'kind': k, 'repo': 'ExampleOrg/RepoA', 'url': 'https://github.com/ExampleOrg/RepoA/' + suffix}
            for k, suffix in [('issue', 'issues/2'), ('PR', 'pull/3'), ('release', 'releases/tag/v1')]]
    snapshot['follow_through'] = [{'discussion': discussion['url'], 'state': 'available',
                                   'update_owed': True, 'evidence': refs, 'gaps': []}]
    return snapshot, state


def test_delivery_preserves_settlement_and_stale_projection():
    snapshot, state = delivery_fixture()
    result = adapt(snapshot, state)
    assert not result['open_discussions'] and not result['awaiting_response']
    assert result['follow_through'][0]['update_owed'] is True
    result = _ears_feed.adapt(snapshot, state, [], 'ExampleOrg', 'ExampleOrg/RepoA',
                             current=datetime.now(timezone.utc) + timedelta(days=1))
    assert result['follow_through'][0]['state'] == 'unknown'
    assert result['follow_through'][0]['observed_state'] == 'available'
    assert result['follow_through'][0]['update_owed'] is None


@pytest.mark.parametrize('change', ['link', 'extra_body', 'state', 'missing_release', 'unknown_update'])
def test_invalid_delivery_rejected(change):
    snapshot, state = delivery_fixture()
    d = snapshot['follow_through'][0]
    if change == 'link': d['evidence'][0]['url'] = 'javascript:alert(1)'
    elif change == 'extra_body': d['body'] = 'RAW TRANSCRIPT'
    elif change == 'state': d['state'] = 'guaranteed'
    elif change == 'missing_release': d['evidence'].pop()
    else: d['state'] = 'unknown'
    with pytest.raises(ValueError): adapt(snapshot, state)


def followup_row(kind='discussion', **extra):
    r = row(kind, closed=True, answered=kind == 'discussion', **extra)
    anchor = 'discussioncomment' if kind == 'discussion' else 'issuecomment'
    r['follow_up'] = {'review_needed': True, 'since': r['waiting_since'],
                      'url': r['url'] + f'#{anchor}-42'}
    return r


@pytest.mark.parametrize('kind', ['discussion', 'issue'])
def test_closed_followups_are_attention_not_open_conversations(kind):
    s = adapt(*evidence([followup_row(kind)]))
    assert s['counts']['open_discussions'] == s['counts']['open_external'] == 0
    assert s['counts']['awaiting_response'] == 1
    assert s['follow_up_review'][0]['follow_up']['review_needed'] is True


@pytest.mark.parametrize('cached,stale', [(True, False), (False, True)])
def test_expired_followup_retains_observation_without_current_claim(cached, stale):
    snapshot, state = evidence([followup_row(cached=cached)])
    if stale: state['status'] = 'stale'
    s = adapt(snapshot, state)
    candidate = s['follow_up_review'][0]
    assert candidate['follow_up']['review_needed'] is None
    assert candidate['observed_follow_up']['review_needed'] is True
    assert not s['awaiting_response']


@pytest.mark.parametrize('field,value', [('url', 'javascript:alert(1)'), ('since', None),
                                        ('review_needed', 1), ('body', 'not allowed')])
def test_invalid_followup_fails_closed(field, value):
    r = followup_row(); r['follow_up'][field] = value
    with pytest.raises((ValueError, TypeError, AttributeError)):
        adapt(*evidence([r]))


def historical_row(kind='issue', number=5, **extra):
    r = row(kind, number, closed=True, awaiting=False, waiting_since=None,
            answered=kind == 'discussion', category='Help & Questions' if kind == 'discussion' else '',
            **extra)
    r['follow_up'] = {'review_needed': False, 'since': None, 'url': None}
    r['historical_follow_up_at'] = '2019-06-01T00:00:00Z'
    return r


@pytest.mark.parametrize('cached,stale', [(False, False), (True, False), (False, True)])
def test_stale_or_cached_history_stays_quiet(cached, stale):
    rows = [historical_row(cached=cached), historical_row('discussion', 6, cached=cached)]
    rows[1].pop('historical_follow_up_at')  # settled, inactive, not yet historical
    snapshot, state = evidence(rows)
    if stale: state['status'] = 'stale'
    s = adapt(snapshot, state)
    assert s['follow_up_review'] == []
    assert s['historical_follow_up'] == 1
    assert s['counts']['unknown'] == 0


def test_stale_scan_prints_history_as_a_count_only(tmp_path):
    feed = tmp_path / 'feed'
    base = write_feed(feed, [historical_row(), followup_row('issue', number=9)])
    state = json.loads((feed / 'state.json').read_text()); state['status'] = 'stale'
    (feed / 'state.json').write_text(json.dumps(state))
    result = subprocess.run([str(BRAIN / "bin/pyauto-brain"), "community", "scan"],
        env={**os.environ, "COMMUNITY_EARS_URL": base, "COMMUNITY_GH": "/missing/gh"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Historical follow-ups: 1 (settled, >30 days; not listed)' in result.stdout
    assert result.stdout.count('Follow-up:') == 1  # the active candidate, now unknown
    assert 'RepoA#5' not in result.stdout


@pytest.mark.parametrize('category,kept', [('Announcements', False), ('Show and tell', False),
                                           ('Ideas & Proposals', True)])
def test_broadcast_unknown_delivery_is_filtered(category, kept):
    discussion = row('discussion', awaiting=False, category=category)
    snapshot, state = evidence([discussion])
    snapshot['follow_through'] = [{'discussion': discussion['url'], 'state': 'unknown',
                                   'update_owed': None, 'evidence': [], 'gaps': ['no link']}]
    s = adapt(snapshot, state)
    assert bool(s['follow_through']) is kept
    assert any('Delivery evidence' in d for d in s['degraded']) is kept


def close_due_row(kind='discussion', number=7, due=True, since='2026-01-01T00:00:00Z'):
    return row(kind, number, awaiting=False, waiting_since=None, category='Help & Questions',
               close_due=due, awaiting_contributor_since=since)


def test_close_due_passes_through_with_the_standard_message(tmp_path):
    rows = [close_due_row(), close_due_row('issue', 8), close_due_row('issue', 9, due=False)]
    s = adapt(*evidence(rows))
    assert [r['number'] for r in s['close_due']] == [7, 8]
    base = write_feed(tmp_path / 'feed', rows)
    result = subprocess.run([str(BRAIN / "bin/pyauto-brain"), "community", "scan", "--json"],
        env={**os.environ, "COMMUNITY_EARS_URL": base, "COMMUNITY_GH": "/missing/gh"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    due = json.loads(result.stdout)['close_due']
    assert due[0]['close_message'].startswith("Hi @visitor, we're closing this for now")
    assert 'reopen this discussion or just reply here' in due[0]['close_message']
    assert "reply here <with what we asked for> and we'll reopen it." in due[1]['close_message']
    assert due[0]['days_silent'] > 21


def test_snapshots_without_close_due_have_an_empty_section():
    s = adapt(*evidence([row()]))
    assert s['close_due'] == [] and s['historical_follow_up'] == 0


@pytest.mark.parametrize('change', [{'close_due': 'yes'}, {'awaiting_contributor_since': 'soon'},
                                    {'awaiting_contributor_since': None}])
def test_invalid_close_due_fails_closed(change):
    r = close_due_row(); r.update(change)
    with pytest.raises(ValueError):
        adapt(*evidence([r]))

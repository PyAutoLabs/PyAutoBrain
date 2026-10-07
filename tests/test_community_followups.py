"""Permission-aware source triage stays read only and does not invent rights."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents/conductors/community'))
import _community as community


@pytest.mark.parametrize('kind', ['discussion', 'issue'])
@pytest.mark.parametrize('permission', [True, False, None])
def test_settled_triage_does_not_require_contributor_reopen(monkeypatch, kind, permission):
    calls = []
    raw = {'state': 'closed', 'title': 'Follow-up', 'user': {'login': 'Reporter'},
           'comments': 1, 'answer_chosen_at': '2026-09-30T00:00:00Z',
           'category': {'name': 'Ideas & Proposals'}, 'body': 'Original request',
           'html_url': f'https://github.com/example/hub/{kind}s/13'}
    def read(args):
        calls.append(args)
        if args[0] == 'graphql':
            return {'data': {'repository': {kind: {'viewerCanReopen': permission}}}}
        if args[0].endswith('/comments'):
            return [{'user': {'login': 'Reporter'}, 'created_at': '2026-10-04T00:00:00Z',
                     'body': 'Please add analytic components; I cannot reopen this.'}]
        return raw
    monkeypatch.setattr(community, 'gh_json', read)
    t = community.build_triage(f'https://github.com/example/hub/{kind}s/13')
    assert t['awaiting_response'] is None  # bounded direct read cannot clear it
    assert t['viewer_can_reopen'] is permission
    assert 'a comment is enough' in t['follow_up_review']
    assert 'acknowledgement' in t['follow_up_review']
    assert 'maintainer with permission' in t['follow_up_review']
    assert 'cannot reopen' in t['comment_tail'][0]['excerpt']
    assert all('mutation' not in ' '.join(args) for args in calls)
    assert any(args[0] == 'graphql' for args in calls)


@pytest.mark.parametrize('result', [None, {}, {'errors': ['denied']},
    {'data': {'repository': {'discussion': {'viewerCanReopen': 'true'}}}}])
def test_unknown_reopen_permission_never_becomes_true(monkeypatch, result):
    monkeypatch.setattr(community, 'gh_json', lambda args: result)
    assert community.reopen_capability('example/hub', 13, 'discussion') is None

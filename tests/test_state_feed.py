"""Contract tests for the organ cockpit feed (board/_state.py, state.json v1).

state.json is the one shape every organ board publishes for the cockpit and
the phone. These tests pin the contract from both ends: the validator accepts
the realistic fixtures and refuses each way a feed can break, the CLI works
from any cwd (sibling organ workflows run it from their own checkout), and the
Brain board's own render_state output passes the same validator.

Hermetic: the board legs reuse test_board.py's fabricated workspace and stub
`gh` — no network, no real checkouts, fake org names per the tenant firewall.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
STATE_CLI = BRAIN_HOME / "board" / "_state.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "state"
sys.path.insert(0, str(BRAIN_HOME / "board"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _state  # noqa: E402
from test_board import (  # noqa: E402
    HEART_BOARD_JSON, _default_fixtures, _fabricate, _run,
)


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ------------------------------------------------------------- validator ----


@pytest.mark.parametrize("name", ["brain", "heart", "mind", "cortex"])
def test_the_fixtures_satisfy_the_contract(name):
    assert _state.validate_state(_fixture(name)) == []


def test_the_schema_example_satisfies_the_contract():
    schema = json.loads((BRAIN_HOME / "board" / "state_schema.json").read_text())
    assert schema["schema_version"] == _state.SCHEMA_VERSION
    assert tuple(schema["required"]) == _state.REQUIRED
    assert _state.validate_state(schema["example"]) == []


def test_the_heart_fixture_carries_linked_rows_with_a_bug_prompt():
    heart = _fixture("heart")
    assert (heart["organ"], heart["repo"], heart["status"]) == \
        ("heart", "PyAutoHeart", "red")
    assert len(heart["items"]) == 2
    for item in heart["items"]:
        assert item["url"].startswith("https://github.com/")
        assert "/actions/runs/" in item["url"]
        assert item["prompt"].startswith("/bug ")


def _broken(mutate):
    state = copy.deepcopy(_fixture("brain"))
    mutate(state)
    return _state.validate_state(state)


def test_an_unknown_status_is_refused():
    errors = _broken(lambda s: s.update(status="amber"))
    assert any("status" in e for e in errors)


def test_a_missing_required_key_is_refused():
    errors = _broken(lambda s: s.pop("pages_url"))
    assert "missing required key: pages_url" in errors


@pytest.mark.parametrize("updated", [
    "2026-09-26T05:31:00",          # naive — which clock?
    "2026-09-26T06:31:00+01:00",    # a real instant, but not UTC
    "yesterday morning",            # not a timestamp at all
    "2026-13-40T99:00:00Z",         # UTC-shaped but unparseable
])
def test_updated_must_be_parseable_utc(updated):
    errors = _broken(lambda s: s.update(updated=updated))
    assert any(e.startswith("updated") for e in errors), updated


def test_an_item_with_an_unknown_severity_is_refused():
    errors = _broken(lambda s: s["items"][0].update(severity="critical"))
    assert any("items[0].severity" in e for e in errors)


def test_a_multi_line_headline_is_refused():
    errors = _broken(lambda s: s.update(headline="2 need you\nand more"))
    assert any("headline" in e for e in errors)


def test_a_wrong_schema_version_is_refused():
    errors = _broken(lambda s: s.update(schema_version=2))
    assert any("schema_version" in e for e in errors)


def test_build_state_round_trips():
    src = _fixture("heart")
    built = _state.build_state(
        src["organ"], src["repo"], src["status"], src["headline"],
        src["updated"], src["pages_url"], src["items"])
    assert built == src
    assert json.loads(json.dumps(built)) == src


def test_build_state_refuses_what_it_cannot_publish():
    with pytest.raises(ValueError) as exc:
        _state.build_state("brain", "PyAutoBrain", "purple", "x",
                           "2026-09-26T05:31:00Z", "https://example.invalid/")
    assert "status" in str(exc.value)


# ------------------------------------------------------------------- CLI ----


def _cli(arg, cwd, stdin=None):
    return subprocess.run([sys.executable, str(STATE_CLI), arg], cwd=cwd,
                          capture_output=True, text=True, input=stdin)


def test_cli_accepts_the_fixture_from_any_cwd(tmp_path):
    r = _cli(str(FIXTURES / "heart.json"), tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == "state: ok"


def test_cli_reads_stdin(tmp_path):
    r = _cli("-", tmp_path, stdin=(FIXTURES / "brain.json").read_text())
    assert r.returncode == 0 and r.stdout.strip() == "state: ok"


def test_cli_names_every_break_and_exits_1(tmp_path):
    broken = _fixture("brain")
    broken["status"] = "amber"
    del broken["updated"]
    path = tmp_path / "state.json"
    path.write_text(json.dumps(broken))
    r = _cli("state.json", tmp_path)
    assert r.returncode == 1
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 2 and all(line.startswith("state: ") for line in lines)
    assert "ok" not in r.stdout


def test_cli_refuses_unreadable_json(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    r = _cli("state.json", tmp_path)
    assert r.returncode == 1 and r.stdout.startswith("state: unreadable")


# ------------------------------------------------------ the Brain's feed ----


def test_the_brain_board_state_satisfies_the_contract(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    r = _run(["--state"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    state = json.loads(r.stdout)
    assert _state.validate_state(state) == []
    assert state["organ"] == "brain"
    # The feed agrees with the badge beside it — one verdict, two shapes.
    badge = json.loads(_run(["--badge"], tmp_path, stub).stdout)
    assert state["headline"] == badge["message"]
    assert state["status"] == {"red": "red", "orange": "yellow",
                               "lightgrey": "grey",
                               "brightgreen": "green"}[badge["color"]]


def test_a_red_heart_blocker_is_a_red_item_with_its_link_and_prompt(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    state = json.loads(_run(["--state"], tmp_path, stub).stdout)
    blocker = HEART_BOARD_JSON["blockers"][0]
    matches = [i for i in state["items"] if blocker["text"] in i["text"]]
    assert matches, state["items"]
    item = matches[0]
    assert item["severity"] == "red"
    assert item["url"] == blocker["run_url"]
    assert item["prompt"] == blocker["prompt"]  # verbatim, never re-derived
    assert state["items"][0]["severity"] == "red"  # most urgent first


def test_a_failed_overnight_run_is_a_red_item_with_its_run_url(tmp_path):
    from test_board import _run_json
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "runs.json": _run_json("failure")}))
    state = json.loads(_run(["--state"], tmp_path, stub).stdout)
    assert _state.validate_state(state) == []
    assert state["status"] == "red"
    overnight = [i for i in state["items"] if i["text"].startswith("overnight:")]
    assert overnight and all(i["severity"] == "red" for i in overnight)
    assert overnight[0]["url"] == "https://example.invalid/run/1"
    # The page's own 📋 payload for the row, not a second phrasing of it.
    page = _run(["--html"], tmp_path, stub).stdout
    assert f'data-cmd="{overnight[0]["prompt"]}"' in page


def test_apply_writes_a_valid_state_json_beside_the_badge(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    out = tmp_path / "site"
    r = _run(["--apply", "--out", str(out)], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    assert "state.json" in r.stdout
    assert (out / "badge.json").is_file()
    state = json.loads((out / "state.json").read_text())
    assert _state.validate_state(state) == []
    cli = _cli(str(out / "state.json"), tmp_path)
    assert cli.returncode == 0 and cli.stdout.strip() == "state: ok"


@pytest.mark.parametrize('metadata', [
    {'state': 'purple'}, {'id': ''}, {'reason': 'two\nlines'},
    {'requires_human_decision': 'yes'}, {'requires_human_decision': True},
    {'actions': None}, {'actions': [None]},
    {'actions': [{'id': 'x', 'label': 'Run', 'kind': 'shell', 'target': 'echo x'}]},
    {'actions': [{'id': 'x', 'label': 'Run', 'kind': 'prompt', 'target': 'x', 'safety': True}]},
    {'actions': [{'id': 'x', 'label': 'Run', 'kind': 'link', 'target': 'javascript:alert(1)'}]},
    {'recommended_action_id': 'missing'},
])
def test_optional_metadata_is_validated_when_present(metadata):
    assert _broken(lambda s: s['items'][0].update(metadata))


def test_decision_and_action_round_trip_without_invented_safety():
    s = _fixture('brain')
    s['items'][0].update(id='decision:strategy', state='action_required',
        requires_human_decision=True, decision='Which strategy should we use?',
        actions=[{'id': 'context', 'label': 'Read context', 'kind': 'link',
                  'target': 'https://example.invalid/context'}], recommended_action_id='context')
    assert _state.validate_state(s) == []
    assert 'safety' not in s['items'][0]['actions'][0]
    s['items'].append(copy.deepcopy(s['items'][0]))
    assert any('unique within the feed' in e for e in _state.validate_state(s))
    s['items'].pop()
    s['items'][0]['actions'] *= 2
    assert any('unique within the item' in e for e in _state.validate_state(s))


def test_producer_declared_freshness_deadline():
    s = _fixture('brain')
    s['valid_until'] = '2026-10-01T00:00:00Z'
    assert _state.validate_state(s) == []
    s['valid_until'] = '2020-01-01T00:00:00Z'
    assert any('precede' in e for e in _state.validate_state(s))
    s['valid_until'] = 'not a time'
    assert any('valid_until' in e for e in _state.validate_state(s))


@pytest.mark.parametrize('conclusion,blocked,unreadable,expected', [
    ('failure', False, False, 'failed'), ('timed_out', False, False, 'failed'),
    ('success', True, False, 'blocked'), (None, False, True, 'unknown'),
    ('cancelled', False, False, 'unknown'), ('in_progress', False, False, 'active'),
    ('queued', False, False, 'active'), ('action_required', False, False, 'action_required'),
])
def test_overnight_state_preserves_evidence_and_distinguishes_outcomes(conclusion, blocked, unreadable, expected):
    import _board
    row = dict(repo='Example/Engine', workflow='nightly.yml', conclusion=conclusion,
               blocked=blocked, unreadable=unreadable, blocked_reason='Gate blocked: approval missing',
               url=None if unreadable else 'https://example.invalid/runs/1')
    item = _board._overnight_state_item(row)
    assert item['state'] == expected
    assert item['url'] == row['url']
    assert item['reason']
    assert 'requires_human_decision' not in item
    state = _fixture('brain')
    state['items'] = [item]
    assert _state.validate_state(state) == []
    if blocked:
        assert item['reason'] == row['blocked_reason']
        assert item['recommended_action_id'] == 'view-run'
    if expected == 'failed':
        action = item['actions'][0]
        assert action['kind'] == 'prompt' and action['target'] == item['prompt']
        assert action['safety'] == 'requires_approval'
    row['url'] = 'https://example.invalid/runs/2'
    assert _board._overnight_state_item(row)['id'] == item['id']


def test_successful_overnight_work_adds_no_attention_noise():
    import _board
    assert _board._overnight_state_item(dict(repo='Example/Engine', workflow='nightly.yml', conclusion='success')) is None

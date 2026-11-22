"""Codex backend contract and real local supervisor tests; no model/network calls."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import test_orchestrator_dispatch as d
from test_orchestrator_dispatch import orch
import _brief
import _codex


def wait_for(check, seconds=8):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(.03)
    pytest.fail("supervisor did not reach expected state")


def fake_codex(tmp_path, monkeypatch, body=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    path = bindir / "codex"
    path.write_text(f"#!{sys.executable}\n" + (body or '''import json, os, sys
if sys.argv[1:] == ['login', 'status']:
    print('Logged in using ChatGPT')
    raise SystemExit(0)
prompt = sys.stdin.read()
assert 'OPENAI_API_KEY' not in os.environ
assert 'CODEX_API_KEY' not in os.environ
print(json.dumps({'type': 'thread.started', 'thread_id': 'test-thread'}), flush=True)
print(json.dumps({'type': 'turn.completed', 'usage': {
    'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 20}}), flush=True)
'''))
    path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    return path


def launch(tmp_path, monkeypatch, body=None):
    fake_codex(tmp_path, monkeypatch, body)
    env = dict(os.environ, OPENAI_API_KEY="must-not-reach-child", CODEX_API_KEY="nor-this")
    home = tmp_path / "home"
    lease = _codex.launch("test prompt", home=home, cwd=tmp_path, write_root=tmp_path,
                          model="test-model", effort="medium", mode="dontAsk", env=env)
    return lease["agent_id"], home


def test_supervisor_completion_restart_and_usage(tmp_path, monkeypatch):
    sid, home = launch(tmp_path, monkeypatch)
    wait_for(lambda: _codex.state(sid, home) == "done")
    # A new watcher instance needs no in-memory Popen or Claude session list.
    view = orch.AgentsView(home=home, run=lambda *a, **k: pytest.fail("called Claude"))
    assert view.known_for(sid) and view.state(sid) == "done"
    assert view.session_of(sid) == sid
    assert orch.transcript_usage(sid, root=home) == dict(
        input=60, output=20, cache_creation=0, cache_read=40, total=80, subagents=0)
    assert _codex.stop(sid, home) == (True, "")
    request = json.loads((_codex.session_dir(sid, home) / "request.json").read_text())
    assert '--dangerously-bypass-approvals-and-sandbox' not in request['argv']
    assert 'forced_login_method="chatgpt"' in request['argv']


def test_stop_terminates_owned_child_and_records_killed(tmp_path, monkeypatch):
    sid, home = launch(tmp_path, monkeypatch, 'import time\ntime.sleep(30)\n')
    rec = wait_for(lambda: (r if (r := _codex.read_record(sid, home)).get("child_pid") else None))
    try:
        assert _codex.stop(sid, home) == (True, "")
        wait_for(lambda: _codex.state(sid, home) == "killed")
        assert _codex.process_identity(rec["child_pid"]) is None
    finally:
        _codex.stop(sid, home)


def test_pid_reuse_never_targets_unrelated_process(tmp_path):
    sid = "codex:" + "a" * 32
    path = _codex.session_dir(sid, tmp_path)
    path.mkdir(parents=True)
    _codex.write_json(path / "state.json", dict(agent_id=sid, state="working",
                                               pid=os.getpid(), identity="another-process"))
    assert _codex.state(sid, tmp_path) is None
    assert not _codex.stop(sid, tmp_path)[0]
    assert not (path / "STOP").exists()


def test_bad_records_hold_liveness_and_missing_usage(tmp_path):
    sid = "codex:" + "b" * 32
    view = orch.AgentsView(home=tmp_path)
    assert not view.known_for(sid)
    assert view.state(sid) is None
    assert _codex.usage(sid, tmp_path) is None
    path = _codex.session_dir(sid, tmp_path)
    path.mkdir(parents=True)
    (path / "state.json").write_text('{broken')
    assert not view.known_for(sid)
    (path / "events.jsonl").write_text('{"type":"turn.started"}\n{"type":')
    assert _codex.usage(sid, tmp_path) is None
    with pytest.raises(ValueError):
        _codex.session_dir("codex:../../other", tmp_path)


@pytest.mark.parametrize("code,out,expected", [
    (0, "Logged in using ChatGPT", "ok"),
    (0, "Logged in using an API key: secret", "expired"),
    (1, "Not logged in", "expired"),
    (0, "unexpected", "expired"),
])
def test_auth_is_subscription_only(code, out, expected):
    result = _codex.probe(run=lambda *a, **k: SimpleNamespace(returncode=code, stdout=out, stderr=""))
    assert result["state"] == expected
    assert "secret" not in result["detail"]


@pytest.mark.parametrize("mode", ["auto", "dontAsk"])
def test_command_preserves_sandbox_and_model(mode, tmp_path):
    argv = _codex.command("selected-model", "high", mode, tmp_path, tmp_path / "worktrees")
    assert argv[:3] == ["codex", "exec", "--json"]
    assert argv[argv.index("--model") + 1] == "selected-model"
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert "features.multi_agent=false" in argv
    assert ("--approve-for-me" in argv) == (mode == "auto")
    assert "--trust" not in argv and "--dangerously-bypass-hook-trust" not in argv


def test_brief_schema_rejects_incompatible_settings(tmp_path):
    mind, brief, home = d._shift(tmp_path, extra="  - worker-backend: codex\n")
    assert any("codex-model" in e for e in _brief.check(brief, mind)["errors"])
    with brief.open("a") as f:
        f.write("  - codex-model: selected-model\n  - worker-mode: acceptEdits\n")
    assert any("acceptEdits" in e for e in _brief.check(brief, mind)["errors"])
    brief.write_text(brief.read_text().replace("acceptEdits", "dontAsk"))
    assert _brief.check(brief, mind)["ok"]
    brief.write_text(brief.read_text().replace("worker-backend: codex", "worker-backend: typo"))
    assert any("worker-backend" in e for e in _brief.check(brief, mind)["errors"])


def test_default_remains_claude_and_closeout_remains_opus(tmp_path, monkeypatch):
    monkeypatch.delenv(orch.FAKE_ENV, raising=False)
    assert type(orch.default_spawner(tmp_path / "brief.md", {})) is orch.RealSpawner
    brief = _brief.parse("- brief:\n  - worker-backend: codex\n  - codex-model: selected-model\n")["brief"]
    spawner = orch.default_spawner(tmp_path / "brief.md", brief)
    assert isinstance(spawner, orch.CodexSpawner)
    assert spawner.spawn_closeout.__func__ is orch.RealSpawner.spawn_closeout
    argv = orch.closeout_command("t", "https://github.com/a/b/pull/1", "draft/t.md",
                                 tmp_path / "brief.md", tmp_path, "auto")
    assert argv[0] == "claude" and argv[argv.index("--model") + 1] == "opus"


def test_watcher_reaps_codex_with_claude_unavailable(tmp_path, monkeypatch):
    fake_codex(tmp_path, monkeypatch)
    mind, brief, home = d._shift(tmp_path, extra="  - worker-backend: codex\n  - codex-model: selected-model\n")
    spawner = orch.CodexSpawner(brief, _brief.parse(brief.read_text())["brief"], cwd=tmp_path)
    monkeypatch.setattr(orch, 'scope_command', lambda argv, *a, **kw: argv)
    first = orch.tick(brief, mind, home=home, now=d.NOW, spawner=spawner, grace_s=0)
    assert len(first["spawned"]) == 1
    slot = orch.slot_dir(brief, home)
    lease = orch.leases(slot)["t1"]
    assert lease["backend"] == "codex"
    wait_for(lambda: _codex.state(lease["agent_id"], home) == "done")
    # A worker's proof marker and successful CLI exit are separate evidence.
    (slot / "leases" / "t1.done").write_text("obsolete: sandbox task\n")
    second = orch.tick(brief, mind, home=home, now=d.NOW + dt.timedelta(minutes=1),
                       spawner=spawner, grace_s=0)
    assert "t1" in orch.read_counters(slot)["done"]
    assert not orch.leases(slot)
    assert not second.get("spawned")
    assert orch.read_counters(slot)["usage"][lease["agent_id"]]["total"] == 80


def test_nonzero_child_exit_is_error_not_success(tmp_path, monkeypatch):
    sid, home = launch(tmp_path, monkeypatch, 'raise SystemExit(7)\n')
    wait_for(lambda: _codex.state(sid, home) == "error")
    assert _codex.read_record(sid, home)["returncode"] == 7
    assert _codex.usage(sid, home) is None


@pytest.mark.parametrize('pid', ['broken', {}, [], True, -1])
def test_malformed_process_identity_is_unknown(tmp_path, pid):
    sid = 'codex:' + 'c' * 32
    directory = _codex.session_dir(sid, tmp_path)
    directory.mkdir(parents=True)
    _codex.write_json(directory / 'state.json', dict(agent_id=sid, state='working', pid=pid, identity='x'))
    assert _codex.state(sid, tmp_path) is None
    assert not _codex.stop(sid, tmp_path)[0]


def test_supervisor_child_handshake_gap_is_unknown(tmp_path):
    sid = 'codex:' + 'd' * 32
    directory = _codex.session_dir(sid, tmp_path)
    directory.mkdir(parents=True)
    _codex.write_json(directory / 'state.json', dict(agent_id=sid, state='working', pid=999999999, identity='gone'))
    assert _codex.state(sid, tmp_path) is None


def test_identity_is_reserved_before_process_start(tmp_path, monkeypatch):
    lease_path = tmp_path / 'lease.json'
    lease_path.write_text('{"task": "t"}')
    def die_after_reservation(*args, **kw):
        lease = json.loads(lease_path.read_text())
        assert lease['agent_id'].startswith('codex:')
        assert lease['backend'] == 'codex'
        raise KeyboardInterrupt('simulated watcher death')
    monkeypatch.setattr(_codex.subprocess, 'Popen', die_after_reservation)
    with pytest.raises(KeyboardInterrupt):
        _codex.launch('test', home=tmp_path / 'home', cwd=tmp_path, write_root=tmp_path,
                      model='selected', effort='medium', mode='auto', env=dict(os.environ),
                      lease_path=lease_path)
    sid = json.loads(lease_path.read_text())['agent_id']
    assert _codex.state(sid, tmp_path / 'home') is None


def test_reap_recovers_accounting_idempotently_after_launch_crash(tmp_path):
    mind, brief, home = d._shift(tmp_path)
    slot = orch.slot_dir(brief, home)
    (slot / 'leases').mkdir(parents=True)
    sid = 'codex:' + 'e' * 32
    lease = dict(task='t1', agent_id=sid, session_id=sid, pid=0, backend='codex',
                 started=orch._iso(d.NOW), expires=orch._iso(d.NOW),
                 launch=dict(reserve=12345, pick={'path': 'draft/t1.md'}, redispatch=True))
    (slot / 'leases' / 't1.json').write_text(json.dumps(lease))
    counters = orch.read_counters(slot)
    counters['pending_redispatch'] = ['t1']
    for _ in range(2):
        orch._reap(slot, counters, d.NOW, 0, tokens=lambda _: None)
    assert counters['sessions'] == 1
    assert counters['redispatched']['t1'] == 1
    assert counters['pending_redispatch'] == []
    assert counters['picks']['t1'] == {'path': 'draft/t1.md'}
    assert orch._committed_tokens(counters) == 12345
    assert (slot / 'leases' / 't1.json').exists()


def test_stop_cleans_descendants_when_leader_exits(tmp_path, monkeypatch):
    child_path = tmp_path / 'grandchild'
    body = '''import os, signal, time
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
else:
    open(%r, 'w').write(str(pid))
    time.sleep(30)
''' % str(child_path)
    sid, home = launch(tmp_path, monkeypatch, body)
    wait_for(child_path.exists)
    child = int(child_path.read_text())
    try:
        assert _codex.stop(sid, home)[0]
        wait_for(lambda: _codex.state(sid, home) == 'killed')
        wait_for(lambda: _codex.process_identity(child) is None)
    finally:
        try:
            os.kill(child, 9)
        except ProcessLookupError:
            pass


def test_accounted_opus_review_requires_structured_clean_and_adds_usage(tmp_path, monkeypatch):
    import _codex_review
    sid, home = launch(tmp_path, monkeypatch)
    wait_for(lambda: _codex.state(sid, home) == 'done')
    directory = _codex.session_dir(sid, home)
    rec = _codex.read_record(sid, home)
    rec['state'] = 'working'  # helper fixture: owner is still doing development
    _codex.write_json(directory / 'state.json', rec)
    monkeypatch.setenv('PYAUTO_CODEX_SESSION_DIR', str(directory))
    monkeypatch.setenv('PYAUTO_SHIFT_WORKER', '1')
    calls = []
    def reviewer(argv, **kw):
        calls.append(argv)
        assert argv[argv.index('--model') + 1] == 'opus'
        assert '--session-id' in argv and '--resume' not in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'structured_output': {'verdict': 'CLEAN', 'report': 'verified'},
            'usage': {'input_tokens': 15, 'output_tokens': 5,
                      'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 50}}))
    result = _codex_review.review('task', [tmp_path], run=reviewer)
    assert result['verdict'] == 'CLEAN' and len(calls) == 1
    u = _codex.usage(sid, home)
    assert u['total'] == 110 and u['subagents'] == 30 and u['cache_read'] == 90
    # An interrupted review attempt is unknown spend, not zero.
    (directory / 'review-incomplete.request.json').write_text('{}')
    assert _codex.usage(sid, home) is None


def test_preflight_requires_opus_even_without_merges(tmp_path, monkeypatch):
    import _batch
    monkeypatch.setattr(_codex, 'probe', lambda: {'state': 'ok', 'detail': 'ok', 'expires_at': ''})
    monkeypatch.setattr(_batch._login, 'probe', lambda: {'state': 'unknown', 'detail': 'missing'})
    for merge in ('', 'bad', '0'):
        brief = _brief.parse('- brief:\n  - worker-backend: codex\n  - codex-model: selected\n'
                             f'  - merge-cap: {merge}\n')['brief']
        login, errors, warnings = _batch.login_findings({}, brief)
        assert errors and 'Opus' in errors[0]


def test_fast_exit_without_child_identity_is_terminal(tmp_path, monkeypatch):
    import _codex_runner
    sid = 'codex:' + 'f' * 32
    directory = _codex.session_dir(sid, tmp_path)
    directory.mkdir(parents=True)
    _codex.write_json(directory / 'state.json', {'agent_id': sid, 'state': 'starting'})
    _codex.write_json(directory / 'request.json', {'argv': [sys.executable, '-c', 'pass'], 'cwd': str(tmp_path)})
    (directory / 'prompt.txt').write_text('')
    original = _codex_runner.process_identity
    monkeypatch.setattr(_codex_runner, 'process_identity', lambda pid: original(pid) if pid == os.getpid() else None)
    assert _codex_runner.run(directory) == 0
    assert _codex.state(sid, tmp_path) == 'done'


def test_check_default_does_not_launch_a_worker(tmp_path, monkeypatch):
    import importlib.util
    path = Path(orch.__file__).resolve().parents[3] / 'bin' / 'codex_orchestrator_check.py'
    spec = importlib.util.spec_from_file_location('codex_check_test', path)
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    monkeypatch.setattr(check._codex, 'launch', lambda *a, **kw: pytest.fail('default check launched a model'))
    monkeypatch.setattr(check._codex, 'probe', lambda: {'state': 'ok', 'detail': 'ok'})
    monkeypatch.setattr(check._login, 'probe', lambda: {'state': 'ok'})
    monkeypatch.setattr(check.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout='--json --sandbox --add-dir --approve-for-me'))
    assert check.check()['ok']

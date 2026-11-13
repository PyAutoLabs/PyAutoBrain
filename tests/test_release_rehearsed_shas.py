"""M2.4 callers (PyAutoHands#337 "Caller contract"): a release publishes the
REHEARSED commits.

The nightly reads `commit_shas` and the run id from the rehearsal's own
`rehearsal.json` (never `main` re-read), feeds the same file to Heart, and the
live dispatch carries `rehearsal_run_id`; the manual door forwards the run id
to `autohands pre_build` and refuses without one. Offline throughout: fake
`gh`, `pyauto-heart` and `autohands` on PATH, fictional repo names.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
REL = BRAIN_HOME / "agents" / "conductors" / "release"
LIB = REL / "_nightly_lib.sh"
NIGHTLY = (REL / "nightly.sh").read_text()
BUILD = BRAIN_HOME / "agents" / "conductors" / "build" / "build.sh"
RELEASE = REL / "release.sh"
REHEARSE = REL / "rehearse.sh"

SHAS = {"WidgetLib": "a" * 40, "GadgetLib": "b" * 40}
RECORD = {"mode": "rehearsal", "index": "testpypi", "version": "2026.11.12.1.dev1",
          "run_id": "12345", "run_attempt": "1", "commit_shas": SHAS}


def _bin(tmp_path, name, body):
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/usr/bin/env bash\n" + body)
    f.chmod(0o755)
    return d


def _env(tmp_path, **extra):
    empty = tmp_path / "empty"
    empty.mkdir(exist_ok=True)
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
               PYAUTO_HEART=str(empty), PYAUTO_HANDS=str(empty),
               HEART_STATE_DIR=str(tmp_path / "heart-state"),
               NIGHTLY_POLL_SECONDS="0", TMPDIR=str(tmp_path))
    env.pop("REHEARSAL_RUN_ID", None)
    env.update(extra)
    return env


def _lib(tmp_path, body, env=None):
    return subprocess.run(["bash", "-c", f'set -uo pipefail; source "{LIB}"; {body}'],
                          capture_output=True, text=True, env=env or _env(tmp_path),
                          timeout=60)


# --- the rehearsal record -------------------------------------------------------------

def test_commit_shas_and_run_id_come_from_rehearsal_json(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "rehearsal.json").write_text(json.dumps(RECORD))
    r = _lib(tmp_path, f'rehearsal_record "{art}" "{art}/commit_shas.json"')
    assert r.returncode == 0 and r.stdout.strip() == "12345"
    assert json.loads((art / "commit_shas.json").read_text()) == SHAS


@pytest.mark.parametrize("record", [None, {k: v for k, v in RECORD.items()
                                           if k != "commit_shas"},
                                    dict(RECORD, run_id="")])
def test_no_usable_record_refuses(tmp_path, record):
    art = tmp_path / "art"
    art.mkdir()
    if record is not None:
        (art / "rehearsal.json").write_text(json.dumps(record))
    r = _lib(tmp_path, f'rehearsal_record "{art}" "{art}/commit_shas.json"')
    assert r.returncode == 1 and "no rehearsal record" in r.stderr
    assert not (art / "commit_shas.json").exists()


def test_live_dispatch_payload_carries_the_run_id_and_the_record(tmp_path):
    """dispatch_and_await turns the inputs into `gh workflow run -f k=v`: the
    live release carries rehearsal_run_id and the record's commit_shas."""
    shas = tmp_path / "commit_shas.json"
    shas.write_text(json.dumps(SHAS))
    log = tmp_path / "gh.log"
    _bin(tmp_path, "gh", f'''echo "$@" >> "{log}"
case "$1 $2" in
  "run list") echo 777 ;;
  "run view") echo '{{"status":"completed","conclusion":"success"}}' ;;
esac
''')
    _bin(tmp_path, "sleep", "exit 0\n")
    r = _lib(tmp_path, f'inputs="$(live_release_inputs 1 12345 "{shas}")" && '
                       'dispatch_and_await Org/Hands release.yml "$inputs" && echo "$LAST_RUN_ID"')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().endswith("777")
    run = next(l for l in log.read_text().splitlines() if l.startswith("workflow run"))
    assert "-f rehearsal=false" in run and "-f minor_version=1" in run
    assert "-f rehearsal_run_id=12345" in run
    compact = json.dumps(SHAS, separators=(",", ":"), sort_keys=True)
    assert f"-f commit_shas={compact}" in run


def test_a_missing_run_id_refuses_to_compose_the_live_inputs(tmp_path):
    shas = tmp_path / "commit_shas.json"
    shas.write_text(json.dumps(SHAS))
    r = _lib(tmp_path, f'live_release_inputs 1 "" "{shas}"')
    assert r.returncode != 0 and not r.stdout.strip()


def test_nightly_uses_the_record_not_main_heads():
    assert "commits/main" not in NIGHTLY
    assert "capture-heads" not in NIGHTLY
    assert 'rehearsal_record "$ART_DIR" "$ART_DIR/commit_shas.json"' in NIGHTLY
    assert '--commit-shas "$ART_DIR/commit_shas.json"' in NIGHTLY
    assert 'live_release_inputs 1 "$rehearsal_run_id"' in NIGHTLY
    # The pre-#337 payload a merged release.yml would refuse.
    assert '{"rehearsal": "false", "minor_version": "1"}' not in NIGHTLY


# --- rehearse.sh ingest: the record is the commit_shas authority -----------------------

def _fake_heart(tmp_path, log):
    _bin(tmp_path, "pyauto-heart", f'''echo "$@" >> "{log}"
case "$1" in
  readiness) echo '{{"verdict":"green","red_reasons":[]}}' ;;
esac
exit 0
''')


def test_ingest_writes_commit_shas_from_the_record(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "rehearsal.json").write_text(json.dumps(RECORD))
    log = tmp_path / "heart.log"
    _fake_heart(tmp_path, log)
    r = subprocess.run(["bash", str(REHEARSE), "--ingest", str(art), "--json"],
                       capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode == 0, r.stderr
    assert json.loads((art / "commit_shas.json").read_text()) == SHAS
    assert f"validate --ingest {art} --commit-shas {art}/commit_shas.json" in log.read_text()


def test_ingest_refuses_a_commit_shas_file_that_disagrees(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "rehearsal.json").write_text(json.dumps(RECORD))
    other = tmp_path / "heads.json"
    other.write_text(json.dumps(dict(SHAS, WidgetLib="c" * 40)))
    _fake_heart(tmp_path, tmp_path / "heart.log")
    r = subprocess.run(["bash", str(REHEARSE), "--ingest", str(art),
                        "--commit-shas", str(other), "--json"],
                       capture_output=True, text=True, env=_env(tmp_path), timeout=120)
    assert r.returncode == 1 and "disagrees with rehearsal.json" in r.stderr


# --- the manual door ----------------------------------------------------------------

def _door(tmp_path, argv, **env):
    log = tmp_path / "hands.log"
    _bin(tmp_path, "autohands", f'echo "$@" >> "{log}"\n')
    _fake_heart(tmp_path, tmp_path / "heart.log")
    r = subprocess.run(["bash", *argv], capture_output=True, text=True,
                       env=_env(tmp_path, **env), timeout=120)
    return r, (log.read_text().strip() if log.exists() else "")


def test_the_door_refuses_without_a_rehearsal_run_id(tmp_path):
    r, hands = _door(tmp_path, [str(BUILD), "--mode", "release", "pre_build"])
    assert r.returncode == 5
    assert "--rehearsal-run-id" in r.stderr and "PyAutoHands#337" in r.stderr
    assert hands == ""
    assert not (tmp_path / "heart.log").exists()   # refused before any gate


def test_the_door_forwards_the_run_id_to_pre_build(tmp_path):
    r, hands = _door(tmp_path, [str(BUILD), "--mode", "release",
                                "--rehearsal-run-id", "4242", "pre_build", "--", "2"])
    assert r.returncode == 0, r.stderr
    assert hands == "pre_build 2 4242"


def test_release_conductor_forwards_the_run_id(tmp_path):
    r, hands = _door(tmp_path, [str(RELEASE), "--rehearsal-run-id=31337"])
    assert r.returncode == 0, r.stderr
    assert hands == "pre_build 1 31337"


def test_the_door_takes_hearts_validated_rehearsal_run_id(tmp_path):
    state = tmp_path / "heart-state"
    state.mkdir()
    (state / "validation_report.json").write_text(json.dumps(
        {"stages": {"rehearse": {"run_id": "9001", "status": "pass"}}}))
    r, hands = _door(tmp_path, [str(RELEASE)])
    assert r.returncode == 0, r.stderr
    assert hands == "pre_build 1 9001"
    assert "stages.rehearse.run_id" in r.stdout


def _heart_validated(tmp_path, run_id):
    state = tmp_path / "heart-state"
    state.mkdir(exist_ok=True)
    (state / "validation_report.json").write_text(json.dumps(
        {"stages": {"rehearse": {"run_id": run_id, "status": "pass"}}}))


def test_a_stale_env_run_id_that_heart_never_validated_refuses(tmp_path):
    _heart_validated(tmp_path, "9001")
    r, hands = _door(tmp_path, [str(RELEASE)], REHEARSAL_RUN_ID="111")
    assert r.returncode == 5 and hands == ""
    assert "111" in r.stderr and "9001" in r.stderr


def test_a_given_run_id_matching_hearts_proceeds(tmp_path):
    _heart_validated(tmp_path, "9001")
    r, hands = _door(tmp_path, [str(RELEASE), "--rehearsal-run-id", "9001"])
    assert r.returncode == 0, r.stderr
    assert hands == "pre_build 1 9001"
    r, hands = _door(tmp_path, [str(RELEASE), "--rehearsal-run-id", "9002"])
    assert r.returncode == 5 and "9002" in r.stderr and "9001" in r.stderr

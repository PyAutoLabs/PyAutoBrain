"""The scoped development-ship gate's Brain callers (PyAutoHeart#340, M2.1).

`consult_vitals_verdict --repos A,B` asks `pyauto-heart readiness --dev --repos
A,B --json`; only GREEN passes and STALE never does. `active_task_repos` reads
the scope from the task's `repos:` in PyAutoMind/active.md. `heart_feed.py`
gains the 6 h maximum age and an optional `--repos` scope. Offline: a fake
`pyauto-heart` first on PATH; fictional repo names only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
COMMON = BRAIN_HOME / "agents" / "_common.sh"
sys.path.insert(0, str(BRAIN_HOME / "bin"))
import heart_feed  # noqa: E402


def _iso(hours_ago):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dev(verdict="stale", **kw):
    d = {"gate": "dev-ship", "verdict": verdict, "pass": verdict == "green",
         "red_reasons": [], "yellow_reasons": [],
         "stale_reasons": ["Heart snapshot 7.0 h old, over the 6 h maximum"],
         "shown_reasons": ["WidgetWorkspace: smoke failing"],
         "feed_ts": _iso(7), "ts": _iso(0)}
    d.update(kw)
    return d


@pytest.fixture
def heart(tmp_path):
    """A fake pyauto-heart answering `readiness` with the JSON in a file, and
    logging every argument line."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    payload, log = tmp_path / "readiness.json", tmp_path / "heart.log"
    cli = bindir / "pyauto-heart"
    cli.write_text("#!/usr/bin/env bash\n"
                   f'echo "$@" >> "{log}"\n'
                   f'if [[ "$1" == readiness ]]; then cat "{payload}"; fi\n')
    cli.chmod(0o755)
    empty = tmp_path / "no_heart_checkout"
    empty.mkdir()
    env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}",
               PYAUTO_HEART=str(empty))

    def answer(obj):
        payload.write_text(json.dumps(obj))
        return env, log
    return answer


def _sh(env, body):
    r = subprocess.run(["bash", "-c", f'source "{COMMON}"; {body}'],
                       capture_output=True, text=True, env=env, timeout=60)
    return r.stdout.strip()


# --- agents/_common.sh ------------------------------------------------------------

def test_scoped_verdict_asks_the_dev_gate_and_stale_comes_back_stale(heart):
    env, log = heart(_dev("stale"))
    assert _sh(env, "consult_vitals_verdict --repos WidgetLib,GadgetLib") == "stale"
    assert "readiness --dev --repos WidgetLib,GadgetLib --json" in log.read_text()


def test_unscoped_verdict_is_unchanged_for_release_callers(heart):
    env, log = heart({"verdict": "green", "red_reasons": []})
    assert _sh(env, "consult_vitals_verdict") == "green"
    assert _sh(env, "consult_vitals_verdict --profile release-ci") == "green"
    lines = log.read_text().splitlines()
    assert lines == ["readiness --json", "readiness --json --profile release-ci"]


def test_a_scoped_read_without_the_dev_gate_is_unknown_never_a_pass(heart):
    """A Heart without `--dev` (or the published, organism-wide board) cannot
    judge the scope: unknown parks, it does not pass."""
    env, _ = heart({"verdict": "green", "red_reasons": []})
    assert _sh(env, "consult_vitals_verdict --repos WidgetLib") == "unknown"


def test_scoped_reasons_by_field(heart):
    env, _ = heart(_dev("red", red_reasons=["WidgetLib: main CI failing"]))
    assert _sh(env, "consult_vitals_red_reasons --repos WidgetLib") \
        == "WidgetLib: main CI failing"
    assert _sh(env, "consult_vitals_red_reasons --repos WidgetLib --field shown_reasons") \
        == "WidgetWorkspace: smoke failing"


ACTIVE = """\
# Active

## other-task
- repos:
  - GadgetLib: feature/other-task

## widget-polish
- status: library-dev
- repos:
  - WidgetLib: feature/widget-polish
  - widget_workspace: feature/widget-polish
- prompt: active/widget_polish.md

## no-repos
- status: library-dev
"""


def test_active_task_repos_reads_the_tasks_repos_block(tmp_path):
    ledger = tmp_path / "active.md"
    ledger.write_text(ACTIVE)
    env = dict(os.environ)
    assert _sh(env, f'active_task_repos widget-polish "{ledger}"') \
        == "WidgetLib,widget_workspace"
    r = subprocess.run(["bash", "-c", f'source "{COMMON}"; active_task_repos no-repos "{ledger}"'],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and r.stdout == ""


# --- bin/heart_feed.py ------------------------------------------------------------------

def _feed(status, hours):
    return {"status": status, "headline": "h", "updated": _iso(hours), "items": []}


def test_a_green_feed_over_six_hours_is_stale_and_never_passes():
    s = heart_feed.summarise(_feed("green", 7), "published")
    assert s["status"] == "stale" and s["pass"] is False and s["exit"] == 1
    assert "over the 6 h maximum" in s["items"][0]["text"]
    fresh = heart_feed.summarise(_feed("green", 1), "published")
    assert fresh["status"] == "green" and fresh["pass"] is True


def test_age_never_makes_a_feed_greener():
    s = heart_feed.summarise(_feed("red", 9), "published")
    assert s["status"] == "red" and s["pass"] is False
    undated = heart_feed.summarise({"status": "green", "headline": "h", "items": []},
                                   "published")
    assert undated["status"] == "stale"


def test_repos_asks_the_local_dev_gate(heart, monkeypatch, capsys):
    env, log = heart(_dev("green", stale_reasons=[], feed_ts=_iso(1)))
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setattr(heart_feed, "fetch_feed",
                        lambda *a, **k: pytest.fail("a scoped read fetched the feed"))
    assert heart_feed.main(["--repos", "WidgetLib", "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["scope_applied"] is True and s["pass"] is True
    assert s["repos"] == ["WidgetLib"]
    assert "readiness --dev --repos WidgetLib --json" in log.read_text()


def test_repos_without_a_local_gate_reads_the_feed_unscoped_and_says_so(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(heart_feed, "resolve_heart_cli", lambda: None)
    url = tmp_path / "state.json"
    url.write_text(json.dumps(_feed("green", 1)))
    assert heart_feed.main(["--url", url.as_uri(), "--repos", "WidgetLib"]) == 0
    out = capsys.readouterr().out
    assert "scope WidgetLib NOT applied" in out


# --- the watcher's close-out: the same scoped gate for the PR's repo ------------------

def _closeout_heart_cmd(pr_url, tmp_path):
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "faculties" / "sizing"))
    sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "batch"))
    import _orchestrator  # noqa: PLC0415
    text = _orchestrator.closeout_prompt("t", pr_url, "draft/x/t.md",
                                         tmp_path / "brief.md", tmp_path / "leases")
    step = text.split("\n3. ", 1)[1].split("\n4. ", 1)[0]
    cmd = next((l.strip() for l in step.splitlines() if l.strip().startswith("bash -c")), "")
    return step, cmd


@pytest.mark.parametrize("reply,printed", [
    (_dev("green", stale_reasons=[]), "green"),
    (_dev("stale"), "stale"),
    ({"verdict": "green", "red_reasons": []}, "unknown"),   # not the dev-ship gate
])
def test_closeout_asks_the_scoped_gate_for_the_prs_repo(heart, tmp_path, reply, printed):
    step, cmd = _closeout_heart_cmd("https://github.com/ExampleOrg/WidgetLib/pull/7", tmp_path)
    assert "heart_feed.py" not in step
    assert "Only `green` passes" in step and "(WidgetLib)" in step
    env, log = heart(reply)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env, timeout=60)
    assert r.stdout.strip() == printed
    assert "readiness --dev --repos WidgetLib --json" in log.read_text()


def test_closeout_without_a_pr_repo_cannot_be_scoped(tmp_path):
    step, cmd = _closeout_heart_cmd("not-a-pr-url", tmp_path)
    assert cmd == "" and "cannot be scoped — refuse" in step


# --- review items: an empty scope, and the no-Heart-CLI fallback -------------------------

def test_an_empty_scope_is_unknown_never_an_unscoped_read(heart):
    env, log = heart({"verdict": "green", "red_reasons": ["x"]})
    assert _sh(env, 'consult_vitals_verdict --repos ""') == "unknown"
    assert _sh(env, "consult_vitals_verdict --repos=") == "unknown"
    assert _sh(env, 'consult_vitals_red_reasons --repos ""') == ""
    assert not log.exists()          # Heart was never asked the unscoped question


def _no_heart_env(tmp_path, feed):
    """No pyauto-heart anywhere; the published feed is a file:// fixture."""
    path = [d for d in os.environ["PATH"].split(os.pathsep)
            if d and not (Path(d) / "pyauto-heart").exists()]
    empty = tmp_path / "no_heart_checkout"
    empty.mkdir(exist_ok=True)
    pages = tmp_path / "pages" / heart_feed.heart_board_repo()
    pages.mkdir(parents=True)
    if feed is not None:
        (pages / "state.json").write_text(json.dumps(
            {"schema_version": 1, "organ": "heart", "items": [], "headline": "h", **feed}))
    return dict(os.environ, PATH=os.pathsep.join(path), PYAUTO_HEART=str(empty),
                PYAUTO_ROOT=str(empty), BOARD_PAGES_BASE=(tmp_path / "pages").as_uri())


@pytest.mark.parametrize("feed,printed", [
    ({"status": "green", "updated": _iso(1)}, "green"),     # fresh organism GREEN
    ({"status": "green", "updated": _iso(7)}, "unknown"),   # over 6 h
    ({"status": "stale", "updated": _iso(1)}, "unknown"),
    ({"status": "red", "updated": _iso(1)}, "unknown"),
    (None, "unknown"),                                      # nothing published
])
def test_without_a_heart_cli_only_a_fresh_published_green_passes(tmp_path, feed, printed):
    env = _no_heart_env(tmp_path, feed)
    assert _sh(env, "consult_vitals_verdict --repos WidgetLib") == printed

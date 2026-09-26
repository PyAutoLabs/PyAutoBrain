"""bin/heart_feed.py — the Heart at the door (PyAutoBrain#423).

Fixture feeds only: every published read is a `file://` URL in tmp_path, and
the local fallback is a fake `pyauto-heart` placed first on PATH. Nothing here
reaches the network or a real Heart, and no test runs a tick.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
SCRIPT = BRAIN_HOME / "bin" / "heart_feed.py"
sys.path.insert(0, str(BRAIN_HOME / "bin"))

import heart_feed  # noqa: E402


def _iso(hours_ago=2):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago, minutes=1)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _feed(status, headline, items):
    return {"schema_version": 1, "organ": "heart", "repo": "HeartRepo",
            "status": status, "headline": headline, "updated": _iso(),
            "pages_url": "https://example.invalid/HeartRepo/", "items": items}


FEEDS = {
    "green": _feed("green", "all checks green", []),
    "yellow": _feed("yellow", "2 yellow reasons", [
        {"severity": "yellow", "text": "manifest drift: 3 mismatches"},
        {"severity": "info", "text": "install verification not run"},
    ]),
    "red": _feed("red", "workspace smoke failing", [
        {"severity": "info", "text": "install verification not run"},
        {"severity": "red", "text": "smoke: example_script.py failed",
         "url": "https://example.invalid/run/1"},
        {"severity": "yellow", "text": "manifest drift: 1 mismatch"},
    ]),
    "stale": _feed("stale", "no release validation for current source", [
        {"severity": "info", "text": "no release validation for current source"},
    ]),
    "grey": _feed("grey", "heart has never ticked", []),
}


def _write(tmp_path, name, payload):
    path = tmp_path / f"{name}.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return path.as_uri()


@pytest.fixture
def no_local_heart(tmp_path, monkeypatch):
    """PATH without pyauto-heart and no sibling checkout to fall back on."""
    monkeypatch.setattr(heart_feed, "resolve_heart_cli", lambda: None)


@pytest.fixture
def fake_heart(tmp_path, monkeypatch):
    """A fake `pyauto-heart` first on PATH answering `readiness --json`."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    log = tmp_path / "calls.log"

    def install(readiness):
        cli = bindir / "pyauto-heart"
        cli.write_text(
            "#!/usr/bin/env bash\n"
            f"echo \"$@\" >> {log}\n"
            "if [ \"$1\" = readiness ]; then cat <<'EOF'\n"
            f"{json.dumps(readiness)}\nEOF\nfi\n")
        cli.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        return log

    return install


@pytest.mark.parametrize("status,code", [
    ("green", 0), ("yellow", 1), ("stale", 1), ("red", 2), ("grey", 3)])
def test_exit_code_per_status(tmp_path, no_local_heart, status, code):
    url = _write(tmp_path, status, FEEDS[status])
    assert heart_feed.main(["--url", url]) == code


def test_red_prints_headline_then_reasons_worst_first(tmp_path, no_local_heart, capsys):
    url = _write(tmp_path, "red", FEEDS["red"])
    assert heart_feed.main(["--url", url]) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Heart: RED — workspace smoke failing (updated 2h ago)"
    assert lines[1] == ("  [red] smoke: example_script.py failed — "
                        "https://example.invalid/run/1")
    assert lines[2] == "  [yellow] manifest drift: 1 mismatch"
    # info rows are not printed when louder rows exist
    assert not any("install verification" in ln for ln in lines)


def test_stale_prints_its_info_rows(tmp_path, no_local_heart, capsys):
    url = _write(tmp_path, "stale", FEEDS["stale"])
    heart_feed.main(["--url", url])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("Heart: STALE — no release validation")
    assert out[1] == "  [info] no release validation for current source"


def test_green_prints_one_line(tmp_path, no_local_heart, capsys):
    url = _write(tmp_path, "green", FEEDS["green"])
    heart_feed.main(["--url", url])
    assert capsys.readouterr().out.splitlines() == [
        "Heart: GREEN — all checks green (updated 2h ago)"]


def test_json_output_is_the_summary(tmp_path, no_local_heart, capsys):
    url = _write(tmp_path, "red", FEEDS["red"])
    assert heart_feed.main(["--url", url, "--json"]) == 2
    s = json.loads(capsys.readouterr().out)
    assert s["status"] == "red" and s["exit"] == 2 and s["source"] == "published"
    assert [i["severity"] for i in s["items"]] == ["red", "yellow"]
    assert s["url"] == url


@pytest.mark.parametrize("payload", [
    "{not json", json.dumps([1, 2]), json.dumps({"status": "purple", "items": []}),
    json.dumps({"status": "red", "items": "nope"})])
def test_malformed_feed_without_fallback_is_grey(tmp_path, no_local_heart, capsys, payload):
    url = _write(tmp_path, "bad", payload)
    assert heart_feed.main(["--url", url]) == 3
    assert capsys.readouterr().out.startswith("Heart: GREY — unreachable (")


def test_unreachable_feed_without_fallback_is_grey(tmp_path, no_local_heart, capsys):
    url = (tmp_path / "missing.json").as_uri()
    assert heart_feed.main(["--url", url]) == 3
    out = capsys.readouterr().out
    assert out.startswith("Heart: GREY — unreachable (")
    assert "no pyauto-heart" in out  # the reason names both legs that failed


def test_unreachable_feed_falls_back_to_local_readiness(tmp_path, fake_heart, capsys):
    log = fake_heart({"verdict": "red", "red_reasons": ["smoke failing: a.py"],
                      "yellow_reasons": ["drift"], "stale_reasons": ["old"],
                      "ts": _iso(3)})
    url = (tmp_path / "missing.json").as_uri()
    assert heart_feed.main(["--url", url]) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Heart: RED — smoke failing: a.py (updated 3h ago)"
    assert lines[1] == "  [red] smoke failing: a.py"
    assert lines[2] == "  [yellow] drift"
    assert "local `pyauto-heart readiness`" in lines[-1]
    # read-only: the fallback asks for the verdict, never a tick
    assert log.read_text().split("\n")[0] == "readiness --json"
    assert "tick" not in log.read_text()


def test_offline_skips_the_feed(tmp_path, fake_heart, monkeypatch, capsys):
    fake_heart({"verdict": "green", "red_reasons": [], "yellow_reasons": [],
                "stale_reasons": [], "ts": _iso(1)})
    monkeypatch.setattr(heart_feed, "fetch_feed",
                        lambda *a, **k: pytest.fail("--offline fetched the feed"))
    assert heart_feed.main(["--offline"]) == 0
    assert capsys.readouterr().out.startswith(
        "Heart: GREEN — all checks green (updated 1h ago)")


def test_readiness_mapping_shape():
    s = heart_feed.from_readiness({"verdict": "stale", "stale_reasons": ["x"],
                                   "ts": "2026-01-01T00:00:00+00:00"})
    assert s == {"status": "stale", "headline": "x",
                 "updated": "2026-01-01T00:00:00+00:00",
                 "items": [{"severity": "info", "text": "x"}]}
    assert heart_feed.from_readiness({"verdict": "??"})["status"] == "grey"


def test_url_derives_from_policy_and_pages_base(monkeypatch):
    monkeypatch.setenv("BOARD_PAGES_BASE", "https://pages.example.invalid/")
    url, why = heart_feed.feed_url()
    assert why is None
    assert url == (f"https://pages.example.invalid/"
                   f"{heart_feed.heart_board_repo()}/state.json")


def test_cli_exit_code_end_to_end(tmp_path):
    url = _write(tmp_path, "red", FEEDS["red"])
    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(SCRIPT), "--url", url],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2
    assert r.stdout.splitlines()[0].startswith("Heart: RED — workspace smoke failing")

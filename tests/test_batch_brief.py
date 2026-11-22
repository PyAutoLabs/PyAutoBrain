"""Shift launch preflight (M3.6a, PyAutoBrain#659): `batch brief --new` makes
the shift issue, and `batch brief --check` refuses a live brief that has no
issue or whose CLI login has expired.

`gh` and `claude` are fakes on PATH: no issue is created and no model is
called. Fictional fixtures only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
BATCH = BRAIN / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
sys.path.insert(0, str(BATCH))
import _batch  # noqa: E402

ISSUE = "https://github.com/example-org/PyAutoMind/issues/42"
GOALS = "# Goals\n\n## 1. Land the flywheel rework\n- epics: flywheel-rework\n"
EXPIRED = "CLI login expired: run `claude /login`"

BRIEF = """\
# Batch 2026-11-17 pm
- dispatched: 2026-11-17T13:00Z
- review-at: 2099-01-01T12:00Z
{issue}- brief:
  - goals:
    - 1. Land the flywheel rework
  - backlog: fill-idle
  - review-minutes: 45
  - lanes: any
  - merge-cap: 0
  - token-budget: 5000000
{extra}"""


def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    subprocess.run(["git", "-C", str(cwd), *args], check=True, env=env, capture_output=True)


def _mind(tmp_path: Path) -> Path:
    """A Mind checkout whose origin is a (fictional) GitHub PyAutoMind."""
    mind = tmp_path / "mind"
    (mind / "draft" / "feature" / "x").mkdir(parents=True)
    (mind / "batches").mkdir()
    (mind / "goals.md").write_text(GOALS, encoding="utf-8")
    _git(mind, "init", "-q")
    _git(mind, "remote", "add", "origin", "https://github.com/example-org/PyAutoMind.git")
    return mind


def _fake(tmp_path: Path, monkeypatch, name: str, out: str, rc: int = 0) -> Path:
    """A fake `name` on PATH that logs its argv and prints `out` (from a file,
    so a test can change it between calls)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log, text, code = (tmp_path / f"{name}.log", tmp_path / f"{name}.out",
                       tmp_path / f"{name}.rc")
    text.write_text(out)
    code.write_text(str(rc))
    (bindir / name).write_text(f"#!/bin/sh\necho \"$@\" >> {log}\ncat {text}\n"
                               f"exit $(cat {code})\n")
    (bindir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return log


def _calls(log: Path) -> list[str]:
    """One entry per `gh` call (the issue body spans lines)."""
    return [ln for ln in log.read_text().splitlines() if ln.startswith("issue create")]


def _brief(tmp_path: Path, issue: str = ISSUE, extra: str = "") -> Path:
    f = tmp_path / "brief.md"
    f.write_text(BRIEF.format(issue=f"- issue: {issue}\n" if issue else "", extra=extra))
    return f


def _check(brief: Path, mind: Path, capsys, *more) -> tuple[int, str]:
    capsys.readouterr()
    rc = _batch.main(["brief", "--check", str(brief), "--mind", str(mind),
                      "--no-premise", *more])
    return rc, capsys.readouterr().out


# --- Witness 1: `--new` creates one shift issue and writes it --------------------

def test_new_creates_one_shift_issue_and_writes_it(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PYAUTO_BRIEF_ISSUE", raising=False)
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "gh", ISSUE + "\n")
    out = tmp_path / "2026-11-17-pm.md"
    argv = ["brief", "--new", "2026-11-17-pm", "--review-at", "2099-01-01T12:00Z",
            "--mind", str(mind), "--out", str(out)]
    assert _batch.main(argv) == 0
    assert f"- issue: {ISSUE}\n" in out.read_text()
    calls = _calls(log)
    assert len(calls) == 1, calls
    assert calls[0].startswith("issue create --repo example-org/PyAutoMind --title Shift "
                               "2026-11-17-pm")
    # Run again on the same file: the issue it names is reused, never a second.
    assert _batch.main(argv) == 0
    assert len(_calls(log)) == 1
    assert out.read_text().count("- issue: ") == 1
    # The written brief passes the launch check (login probe off in tests).
    assert _check(out, mind, capsys)[0] == 0


def test_new_writes_nothing_when_gh_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PYAUTO_BRIEF_ISSUE", raising=False)
    mind = _mind(tmp_path)
    _fake(tmp_path, monkeypatch, "gh", "", rc=1)
    out = tmp_path / "2026-11-17-pm.md"
    rc = _batch.main(["brief", "--new", "2026-11-17-pm", "--review-at",
                      "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out)])
    assert rc == _batch.RC_FINDINGS and not out.exists()
    assert "shift issue" in capsys.readouterr().err


def test_new_takes_a_given_issue_and_makes_none(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_BRIEF_ISSUE", raising=False)
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "gh", "")
    out = tmp_path / "2026-11-17-pm.md"
    assert _batch.main(["brief", "--new", "2026-11-17-pm", "--review-at",
                        "2099-01-01T12:00Z", "--mind", str(mind), "--out", str(out),
                        "--issue", ISSUE]) == 0
    assert f"- issue: {ISSUE}\n" in out.read_text() and not log.exists()


# --- Witness 2: a live brief without `issue:` is refused ---------------------------

def test_check_refuses_a_live_brief_without_issue(tmp_path, capsys):
    mind = _mind(tmp_path)
    rc, out = _check(_brief(tmp_path, issue=""), mind, capsys)
    assert rc == _batch.RC_FINDINGS
    assert ("issue: missing — a live brief needs its shift issue "
            "(batch brief --new creates it)") in out
    # A shadow shift spawns nothing and posts nothing: no issue needed.
    rc, out = _check(_brief(tmp_path, issue="", extra="  - shadow: yes\n"), mind, capsys)
    assert rc == 0, out


# --- Witness 3: an expired CLI login refuses the launch ------------------------------

def test_check_refuses_on_expired_login(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PYAUTO_LOGIN_PROBE", raising=False)
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "claude",
                "Login reached its time limit. Run /login to sign in again.\n", rc=1)
    brief = _brief(tmp_path)
    rc, out = _check(brief, mind, capsys)
    assert rc == _batch.RC_FINDINGS
    assert f"login: {EXPIRED}" in out
    assert log.read_text().splitlines() == ["auth status --json"]   # no model call

    # Logged in, but the login lapses before review-at: refused, naming the expiry.
    (tmp_path / "claude.out").write_text(
        '{"loggedIn": true, "loginExpiresAt": "2098-06-01T00:00:00.000Z"}\n')
    (tmp_path / "claude.rc").write_text("0")
    rc, out = _check(brief, mind, capsys)
    assert rc == _batch.RC_FINDINGS and "2098-06-01T00:00:00.000Z" in out

    # Logged in past review-at: the launch passes.
    (tmp_path / "claude.out").write_text(
        '{"loggedIn": true, "loginExpiresAt": "2099-06-01T00:00:00.000Z"}\n')
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out


def test_a_write_failure_after_the_issue_names_it_for_a_rerun(tmp_path, monkeypatch, capsys):
    """The issue is made just before the write; if the write still fails, its
    URL is printed so a re-run reuses it rather than making a second."""
    monkeypatch.delenv("PYAUTO_BRIEF_ISSUE", raising=False)
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "gh", ISSUE + "\n")
    out = tmp_path / "no-such-dir" / "2026-11-17-pm.md"
    rc = _batch.main(["brief", "--new", "2026-11-17-pm", "--review-at", "2099-01-01T12:00Z",
                      "--mind", str(mind), "--out", str(out)])
    assert rc == _batch.RC_FINDINGS and not out.exists()
    err = capsys.readouterr().err
    assert ISSUE in err and f"--issue {ISSUE}" in err
    assert len(_calls(log)) == 1


# --- the RAL probe: a granted `ral` lane a worker cannot reach (2026-11-20-am) -----

RAL = ("  - lanes: any ral\n", "  - lanes: any ral\n  - ral-allowance:\n    - packets: 2\n"
       "    - partition: ral\n    - cpu-hours: 64\n")


def _ral_brief(tmp_path: Path, extra: str = "") -> Path:
    f = _brief(tmp_path, extra=extra)
    f.write_text(f.read_text().replace("  - lanes: any\n", RAL[1]))
    return f


def test_check_warns_when_unattended_ssh_to_ral_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PYAUTO_RAL_PROBE", raising=False)
    monkeypatch.delenv("PYAUTO_RAL_SSH_HOST", raising=False)
    mind = _mind(tmp_path)
    (mind / "policy").mkdir()
    (mind / "policy" / "hpc_ral.md").write_text(
        "- Cluster: connect via SSH alias `example_jump` (→ hpc.example.invalid).\n")
    log = _fake(tmp_path, monkeypatch, "ssh",
                "Received disconnect: Too many authentication failures\n", rc=255)
    brief = _ral_brief(tmp_path)
    rc, out = _check(brief, mind, capsys)
    assert rc == 0, out                                    # a warning, never a refusal
    warn = [ln for ln in out.splitlines() if "ral is granted" in ln]
    assert len(warn) == 1 and "`example_jump`" in warn[0]
    assert "Too many authentication failures" in warn[0]
    assert log.read_text().splitlines() == [
        "-o BatchMode=yes -o ConnectTimeout=10 example_jump true"]

    # The host answers: no warning. The environment names the host first.
    (tmp_path / "ssh.rc").write_text("0")
    monkeypatch.setenv("PYAUTO_RAL_SSH_HOST", "other_jump")
    rc, out = _check(brief, mind, capsys)
    assert rc == 0 and "ral is granted" not in out
    assert log.read_text().splitlines()[-1].endswith("other_jump true")


def test_check_runs_no_ssh_without_the_ral_lane_or_for_a_shadow_brief(tmp_path, monkeypatch,
                                                                     capsys):
    monkeypatch.delenv("PYAUTO_RAL_PROBE", raising=False)
    monkeypatch.setenv("PYAUTO_RAL_SSH_HOST", "example_jump")
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "ssh", "denied\n", rc=255)
    rc, out = _check(_brief(tmp_path), mind, capsys)                  # lanes: any
    assert rc == 0 and "ral is granted" not in out and not log.exists()
    rc, out = _check(_ral_brief(tmp_path, extra="  - shadow: yes\n"), mind, capsys)
    assert "ral is granted" not in out and not log.exists()


def test_the_ral_probe_names_no_host_of_its_own(tmp_path, monkeypatch, capsys):
    """No host named anywhere: one warning that it could not be checked, and
    no ssh call. A value that would read as an ssh option is not a host."""
    import _ral
    monkeypatch.delenv("PYAUTO_RAL_PROBE", raising=False)
    monkeypatch.delenv("PYAUTO_RAL_SSH_HOST", raising=False)
    mind = _mind(tmp_path)
    log = _fake(tmp_path, monkeypatch, "ssh", "", rc=0)
    rc, out = _check(_ral_brief(tmp_path), mind, capsys)
    assert rc == 0 and "unattended ssh could not be checked (no host named" in out
    assert not log.exists()
    monkeypatch.setenv("PYAUTO_RAL_SSH_HOST", "-oProxyCommand=evil")
    assert _ral.host_of(mind) == ""
    res, warns = _ral.findings(["any", "ral"], mind)
    assert res["state"] == "unknown" and len(warns) == 1 and not log.exists()

"""Shift launch preflight (M3.6a, PyAutoBrain#659): `batch brief --new` makes
the shift issue, and `batch brief --check` refuses a live brief that has no
issue or whose CLI login has expired.

`gh` and `claude` are fakes on PATH: no issue is created and no model is
called. Fictional fixtures only.
"""

from __future__ import annotations

import os
from pathlib import Path

from _shift_fixtures import BATCH, BRAIN, _batch, git_as_t as _git

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


# --- R1 (PyAutoBrain#727) and the rulings of 2026-11-27 --------------------------
# Repo names are placeholders: the body map's known set is patched to them.

import datetime as _dt  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402

TASK = "draft/feature/x/array_task.md"
KNOWN = {"libalpha", "libbeta", "libgamma", "wsone", "wstwo"}
REPORT_ONLY = ["libgamma: 3 commit(s) behind origin",
               "libbeta: 2 uncommitted source changes",
               "manifest drift: example leg — 2 file(s) differ"]
STALE = ["release validation incomplete: no rehearsal for current source"]


@pytest.fixture(autouse=True)
def _known_repos(monkeypatch):
    monkeypatch.setattr(_batch, "_known_repos", lambda: set(KNOWN))
    monkeypatch.setattr(_batch, "_workspace_repos", lambda: {"wsone", "wstwo"})


def _heart(tmp_path: Path, red=(), yellow=(), stale=(), verdict="red", hours=0.0,
           keyed=()) -> Path:
    """A saved `readiness --json`, `hours` old."""
    f = tmp_path / "heart.json"
    ts = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)
    f.write_text(json.dumps({
        "verdict": verdict, "ts": ts.isoformat(), "red_reasons": list(red),
        "yellow_reasons": list(yellow), "stale_reasons": list(stale),
        "repository_reasons": [dict(k) for k in keyed]}))
    return f


def _task(mind: Path, repos: str = "- libalpha\n", target: str = "libalpha",
          rel: str = TASK, extra: str = "") -> None:
    (mind / rel).parent.mkdir(parents=True, exist_ok=True)
    (mind / rel).write_text(f"# A task\n\nType: feature\nTarget: {target}\n"
                            f"Repos:\n{repos}{extra}", encoding="utf-8")


def _r1_brief(tmp_path: Path, mind: Path, **kw) -> Path:
    """A live brief naming one task that touches libalpha, with no `heart-ack:`."""
    _task(mind, **kw)
    return _brief(tmp_path, extra=f"  - tasks:\n    - {TASK}\n")


def _ack(brief: Path, reason: str = "acknowledged by the human") -> str:
    text = brief.read_text().replace("- brief:", f"- heart-ack:\n  - {reason}\n- brief:")
    brief.write_text(text)
    return text


def _hj(heart: Path) -> tuple[str, str]:
    return ("--heart-json", str(heart))


def test_r1_report_only_red_off_the_touched_repos_needs_no_ack(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    heart = _heart(tmp_path, REPORT_ONLY, stale=STALE)
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 0, out
    assert "no heart-ack needed (R1)" in out
    text = brief.read_text()
    assert "\n## Heart\n" in text and "(R1, 2026-11-17)" in text
    for reason in REPORT_ONLY:
        assert f"- [red] {reason}" in text
    assert f"- [stale] {STALE[0]} — rule `release-validation` — not judged" in text
    # A second check replaces the reason set rather than adding another.
    assert _check(brief, mind, capsys, *_hj(heart))[0] == 0
    assert brief.read_text().count("(R1, 2026-11-17)") == 1


def test_r1_a_report_only_yellow_needs_no_ack(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    heart = _heart(tmp_path, yellow=REPORT_ONLY, verdict="yellow")
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 0, out
    assert "Heart **YELLOW**" in brief.read_text()


def test_r1_a_reason_on_a_touched_repo_still_needs_the_ack(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    heart = _heart(tmp_path, REPORT_ONLY + ["libalpha: 1 commit(s) behind origin"])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and "heart-ack: missing" in out and "names libalpha" in out
    assert "## Heart" not in brief.read_text()


@pytest.mark.parametrize("reason", [
    "libgamma: open PR 9d old",                                # human-only
    "release validation stale: source moved since rehearsal",  # release-scope
])
def test_r1_a_human_only_reason_still_needs_the_ack(tmp_path, capsys, reason):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    heart = _heart(tmp_path, REPORT_ONLY, yellow=[reason])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and "heart-ack: missing" in out and reason in out
    assert "## Heart" not in brief.read_text()
    # The human's acknowledgement launches it, and an acked RED writes nothing.
    acked = _ack(brief, reason)
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 0, out
    assert brief.read_text() == acked


def test_r1_a_heart_key_override_still_needs_the_ack(tmp_path, capsys):
    """The text reads `behind` (report only), but Heart's own key says open_pr:
    the class is human-only, so R1 does not pass."""
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    text = "libgamma: 4 commit(s) behind origin"
    heart = _heart(tmp_path, [text], keyed=[{"repo": "libgamma", "key": "open_pr",
                                              "text": text}])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and "heart-ack: missing" in out and "(human-only)" in out


@pytest.mark.parametrize("kind", ["old", "grey", "unreadable"])
def test_an_old_grey_or_unreadable_read_needs_the_ack(tmp_path, capsys, kind):
    """Ruling (a), 2026-11-27: a launch needs a fresh read or the ack."""
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    heart = {"old": lambda: _heart(tmp_path, REPORT_ONLY, hours=7),
             "grey": lambda: _heart(tmp_path, verdict=""),
             "unreadable": lambda: tmp_path / "missing.json"}[kind]()
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and "heart-ack: missing" in out, out
    assert "## Heart" not in brief.read_text()
    acked = _ack(brief)
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 0 and "evidence" not in out and "Heart read" not in out, out
    assert brief.read_text() == acked


def test_a_shadow_brief_is_not_read(tmp_path, capsys):
    mind = _mind(tmp_path)
    _task(mind)
    brief = _brief(tmp_path, issue="", extra=f"  - tasks:\n    - {TASK}\n  - shadow: yes\n")
    before = brief.read_text()
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path, ["libgamma: open PR 9d old"])))
    assert rc == 0 and "heart" not in out.lower(), out
    assert brief.read_text() == before


def test_planned_member_repos_count_as_touched(tmp_path):
    mind = _mind(tmp_path)
    _task(mind, repos="- libbeta\n", target="libbeta", rel="draft/feature/x/member.md")
    brief = {"backlog": {"value": "none", "children": []}}
    touched, why = _batch.touched_repos(brief, mind, {"members": [
        {"path": "draft/feature/x/member.md"}]})
    assert (touched, why) == ({"libbeta"}, "")


@pytest.mark.parametrize("repos,target,hit", [
    ("- example/libalpha (the array library)\n", "example/libalpha", "libalpha"),
    ("- libalpha — tests only\n", "`libalpha`", "libalpha"),
    ("- notarepo\n", "topicx", "every repo"),     # no known repo at all: fail closed
])
def test_path_style_or_annotated_repos_resolve_or_fail_closed(tmp_path, capsys, repos,
                                                              target, hit):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind, repos=repos, target=target)
    heart = _heart(tmp_path, ["libalpha: 1 commit(s) behind origin"])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and f"names {hit}" in out, out


def test_target_workspaces_touches_every_workspace(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind, repos="", target="workspaces")
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path,
                                                      ["wstwo: 1 commit(s) behind origin"])))
    assert rc == 1 and "names wstwo" in out, out


def test_a_topic_target_is_ignored_when_repos_resolve(tmp_path):
    mind = _mind(tmp_path)
    _task(mind, repos="- libalpha\n- notarepo\n", target="priors")
    brief = {"tasks": {"value": "", "children": [{"text": TASK, "children": []}]}}
    assert _batch.touched_repos(brief, mind) == ({"libalpha"}, "")


# A replica of the 2026-11-16-pm brief's shape (backlog: scoped): named tasks
# with topic targets, path-style and annotated `Repos:` entries. Placeholders.
REPLICA = {
    "draft/bug/ws/wall_estimates.md": ("wsone", "- wsone\n"),
    "draft/feature/nerves/lifecycle_p5a.md": ("libalpha", "- libalpha\n"),
    "draft/feature/euclid/campaign_p5d.md": ("euclid", "- group/wstwo (pipeline)\n"),
    "draft/bug/mind/dashboard_titles.md": ("health_fixes", "- libbeta — data fix\n"),
}


def test_touched_repos_on_a_scoped_brief_replica_is_concrete(tmp_path, capsys):
    """The human's ruling of 2026-11-27: named tasks plus the plan's members,
    never the whole backlog scope — the replica resolves to concrete repos."""
    mind = _mind(tmp_path)
    for rel, (target, repos) in REPLICA.items():
        _task(mind, repos=repos, target=target, rel=rel)
    # Backlog the scope admits but nobody named or planned is not touched.
    _task(mind, repos="- libgamma\n", target="libgamma", rel="draft/bug/x/dip.md",
          extra="\nConsequence: glance\n")
    tasks = "".join(f"    - {rel}\n" for rel in REPLICA)
    brief = _brief(tmp_path, extra=f"  - tasks:\n{tasks}  - scoped:\n    - tiers: notify, glance\n")
    brief.write_text(brief.read_text().replace("backlog: fill-idle", "backlog: scoped"))
    parsed = _batch._brief.parse(brief.read_text())["brief"]
    touched, why = _batch.touched_repos(parsed, mind)
    assert (touched, why) == ({"wsone", "libalpha", "wstwo", "libbeta"}, "")
    # A report-only RED on the unplanned dip's repo and the manifest: R1 holds.
    heart = _heart(tmp_path, ["libgamma: 3 commit(s) behind origin", REPORT_ONLY[2]])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 0 and "no heart-ack needed (R1)" in out, out
    assert "touches (libalpha, libbeta, wsone, wstwo)" in brief.read_text()
    # One on a named task's repo refuses, naming it.
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))
    assert rc == 1 and "names libbeta, which this brief touches" in out, out


def test_a_launch_read_that_no_longer_holds_is_removed(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    assert _check(brief, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))[0] == 0
    assert R1_MARK in brief.read_text()
    heart = _heart(tmp_path, REPORT_ONLY, yellow=["libgamma: open PR 9d old"])
    rc, out = _check(brief, mind, capsys, *_hj(heart))
    assert rc == 1 and "removed the earlier R1 launch read" in out
    # The heading R1 added went inside the marks: no empty `## Heart` is left.
    assert R1_MARK not in brief.read_text() and "## Heart" not in brief.read_text()


def test_removing_a_launch_read_keeps_the_heart_section_and_spacing():
    res = {"r1": True, "state": "red", "heart": {}, "findings": [], "stale": []}
    text = "# B\n- k: v\n\n## Heart\n\nlane text\n\n## Digest\n\nd\n"
    added = _batch._with_launch_read(text, res)
    assert added.count("## Heart") == 1 and "\n\n## Digest\n" in added
    assert _batch._with_launch_read(added, None) == text


R1_MARK = "heart-launch-read:start"


def test_no_write_into_a_main_git_checkout(tmp_path, capsys):
    """`write_hold`'s rule: a main checkout of any clone may be the shared
    Mind, whatever $PYAUTO_MIND says."""
    mind = _mind(tmp_path)
    _task(mind)
    brief = mind / "batches" / "2026-11-17-pm.md"
    brief.write_text(BRIEF.format(issue=f"- issue: {ISSUE}\n",
                                  extra=f"  - tasks:\n    - {TASK}\n"))
    before = brief.read_text()
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))
    assert rc == 1 and "is in a main git checkout" in out, out
    assert brief.read_text() == before


def _committed_mind(tmp_path):
    mind = _mind(tmp_path)
    _task(mind)
    rec = mind / "batches" / "2026-11-17-pm.md"
    rec.write_text(BRIEF.format(issue=f"- issue: {ISSUE}\n",
                                extra=f"  - tasks:\n    - {TASK}\n"))
    _git(mind, "add", "-A")
    _git(mind, "commit", "-qm", "brief")
    return mind, rec


def test_a_linked_worktree_record_is_written(tmp_path, capsys):
    mind, rec = _committed_mind(tmp_path)
    wt = tmp_path / "wt"
    _git(mind, "worktree", "add", "-q", "--detach", str(wt))
    brief = wt / "batches" / rec.name
    rc, out = _check(brief, wt, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))
    assert rc == 0, out
    assert R1_MARK in brief.read_text()


def test_a_pushed_record_reports_the_launch_read_as_info(tmp_path, capsys):
    """A post-launch re-check: the record is on origin/main, so nothing is
    written and the check is not refused for it."""
    mind, rec = _committed_mind(tmp_path)
    _git(mind, "update-ref", "refs/remotes/origin/main", "HEAD")
    before = rec.read_text()
    rc, out = _check(rec, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))
    assert rc == 0 and "launch read not written" in out and "already on origin/main" in out, out
    assert "its reason set is NOT on file for this shift" in out
    assert rec.read_text() == before


def test_the_probe_switch_is_honoured_only_under_pytest(tmp_path, monkeypatch, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    assert _check(brief, mind, capsys)[0] == 0          # PYAUTO_HEART_PROBE=off, in pytest
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    rc, out = _check(brief, mind, capsys)
    assert rc == 1 and "Heart not read" in out, out
    _ack(brief)
    assert _check(brief, mind, capsys)[0] == 0


def test_a_reason_is_matched_by_its_own_repo_first():
    touched = {"libalpha"}
    f = {"repo": "", "text": "libgamma: 1 uncommitted file under libalpha/"}
    assert _batch._names_repo(f, touched) == ""             # the leading token wins
    assert _batch._names_repo(dict(f, repo="libalpha"), touched) == "libalpha"
    assert _batch._names_repo({"repo": "", "text": "manifest drift: libalpha — 2"},
                              touched) == "libalpha"        # no token: the words
    # A path-form token names its last segment.
    assert _batch._names_repo({"repo": "", "text": "group/libalpha: 2 uncommitted files"},
                              touched) == "libalpha"


def test_unknown_repos_entries_are_warned_not_refused(tmp_path, capsys):
    """A `Repos:` entry that is no known repo narrows the touched set: the
    launch says so, but R1 still decides on the rest. A topic Target is not
    listed."""
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind, repos="- libalpha\n- notarepo (typo?)\n",
                      target="priors")
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)))
    assert rc == 0, out
    assert ("heart: `Repos:` entries that are no known repo, left out of the touched "
            "set: array_task.md: notarepo (typo?)") in out
    assert "priors" not in out


def test_check_json_carries_the_heart_result(tmp_path, capsys):
    mind = _mind(tmp_path)
    brief = _r1_brief(tmp_path, mind)
    rc, out = _check(brief, mind, capsys, *_hj(_heart(tmp_path, REPORT_ONLY)), "--json")
    heart = json.loads(out)["heart"]
    assert rc == 0 and heart["state"] == "red" and heart["r1"] is True
    assert heart["written"] is True and heart["touched"] == ["libalpha"]
    assert f"[red] {REPORT_ONLY[0]}" in heart["reasons"]

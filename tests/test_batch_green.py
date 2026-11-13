"""The keep-Heart-green lane (PyAutoBrain#625) — `batch brief --new` / `batch green`.

The human, 2026-11-13: "having the autonomous agent constantly trying to
ensure its green (without having it be overly eager doing releases)".
Witness: every class from real Heart reason strings
(`fixtures/heart_green/reasons.json`, quoted from the Mind's autonomy log and
the live verdict); dedupe; the per-brief cap; a brief with a `## Heart`
section; and proof that no release, dispatch or quarantine path is reachable.
Saved Heart documents only — nothing here reads a real Heart or the network.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_green", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_batch)
_green = _batch._green
_brief = _batch._brief

FIXTURE = json.loads((BRAIN / "tests" / "fixtures" / "heart_green" / "reasons.json")
                     .read_text(encoding="utf-8"))["reasons"]
NOW = dt.datetime(2026, 11, 13, 20, 0, tzinfo=dt.timezone.utc)


def _rows(*rules, sev=None):
    return [r for r in FIXTURE if r["rule"] in rules and (sev is None or r["severity"] == sev)]


def _readiness(rows, hours_ago=1.0, verdict="red", repo_reasons=()):
    ts = (NOW - dt.timedelta(hours=hours_ago)).isoformat()
    doc = {"verdict": verdict, "ts": ts, "repository_reasons": list(repo_reasons)}
    for sev in ("red", "yellow", "stale"):
        doc[f"{sev}_reasons"] = [r["text"] for r in rows if r["severity"] == sev]
    return doc


def _heart(rows, **kw):
    out = _green.from_doc(_readiness(rows, **kw))
    out.update(source="fixture", why="", age_hours=kw.get("hours_ago", 1.0))
    return out


def _git(mind, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    subprocess.run(["git", "-C", str(mind), *args], check=True, env=env,
                   capture_output=True)


@pytest.fixture
def mind(tmp_path):
    m = tmp_path / "mind"
    for d in ("draft/bug/x", "active", "batches"):
        (m / d).mkdir(parents=True)
    (m / "queue.md").write_text("# Queue\n\n## Live\n", encoding="utf-8")
    (m / "goals.md").write_text("# Goals\n\n## 1. Ship the flywheel\n", encoding="utf-8")
    _git(m, "init", "-q")
    _git(m, "add", "goals.md")
    _git(m, "commit", "-qm", "goals by hand")
    return m


@pytest.fixture
def wt_mind(mind, tmp_path):
    """A linked worktree of the `mind` repo — the only place the lane writes."""
    wt = tmp_path / "mind-wt"
    _git(mind, "worktree", "add", "-q", "--detach", str(wt))
    for d in ("draft/bug/x", "active", "batches"):
        (wt / d).mkdir(parents=True)
    (wt / "queue.md").write_text("# Queue\n", encoding="utf-8")
    return wt


def _run(mind, rows, mode="file", cap=3, **kw):
    return _green.run(mind, _heart(rows, **kw), mode=mode, cap=cap, lanes=("any",),
                      state_path=mind.parent / "home" / "heart_green.json", now=NOW)


# --- classes ------------------------------------------------------------------

@pytest.mark.parametrize("row", FIXTURE, ids=[r["text"][:50] for r in FIXTURE])
def test_every_real_reason_lands_in_its_class(row):
    f = _green.classify({"severity": row["severity"], "text": row["text"]})[0]
    assert (f["cls"], f["rule"], f["key"]) == (row["cls"], row["rule"], row["key"])


def test_the_fixture_covers_all_four_classes():
    assert {r["cls"] for r in FIXTURE} == set(_green.CLASSES)


def test_only_fixable_dev_rules_may_file():
    for name, cls, _rx, key, lane, _a in _green.RULES:
        classes = set(cls.values()) if isinstance(cls, dict) else {cls}
        if lane:
            assert "fixable-dev" in classes and key, name
        if classes <= {"local-checkout", "release-scope", "human-only"}:
            assert not lane, f"{name}: a report-only class must never file"


def test_heart_per_repo_key_wins_over_the_text():
    f = _green.classify({"severity": "red", "text": "Repo: CI failure",
                         "heart_key": "lib_dirty", "repo": "Repo"})[0]
    assert (f["cls"], f["file"]) == ("local-checkout", False)
    for row in _rows("ci-red", "dirty", "behind", "lib-branch", "open-pr"):
        key = {"ci-red": "lib_ci", "dirty": "lib_dirty", "behind": "lib_behind",
               "lib-branch": "lib_branch", "open-pr": "open_pr"}[row["rule"]]
        assert _green.HEART_KEY_CLASS[key] == row["cls"], row["text"]


def test_a_validation_line_naming_two_scripts_is_two_findings():
    row = _rows("workspace-script")[0]
    found = _green.classify(row)
    assert [f["key"].split("/")[-1] for f in found] == [
        "zero_contour_compat_jax.py", "critical_curves_zero_contour_jit_grad.py"]
    assert all(f["lane"] == "local-dev" for f in found)


def test_readiness_document_carries_the_per_repo_key():
    row = _rows("dirty")[0]
    doc = _readiness([row], repo_reasons=[{"repo": "R", "key": "lib_dirty",
                                           "text": row["text"]}])
    assert _green.from_doc(doc)["reasons"][0]["heart_key"] == "lib_dirty"


# --- filing, dedupe and the cap -----------------------------------------------

FIXABLE = ("ci-red", "ci-red-workflow", "ci-red-legacy", "floor-other", "url-hygiene")


def test_files_at_most_cap_and_defers_the_rest(mind):
    rows = _rows(*FIXABLE)
    assert len(rows) > 3
    res = _run(mind, rows + _rows("dirty", "release-validation", "open-pr"))
    assert len(res["filed"]) == 3
    deferred = [f for f in res["findings"] if "cap 3" in f.get("outcome", "")]
    assert len(deferred) == len(rows) - 3
    text = (mind / res["filed"][0]).read_text()
    for need in ("Lane: any", "Witness:", "Re-check first", "Consequence: judge",
                 "\nDifficulty: ", "<!-- heart-key: ci:", "> " + rows[0]["text"]):
        assert need in text, need
    assert "Unattended:" not in text, "the lane never grades its own drafts ready"
    p = _batch.parse_prompt(mind / res["filed"][0], mind)
    assert text.split("\nDifficulty: ")[1].split("\n")[0] == \
        _batch.effective_difficulty(p)[0], "Difficulty is the sizing faculty's"
    assert all(p.startswith("draft/bug/") for p in res["filed"])
    # report-only classes are never filed
    assert not [f for f in res["findings"]
                if f["cls"] != "fixable-dev" and "filed" in f.get("outcome", "")]


def test_reruns_file_each_key_once_at_most_cap_a_brief(mind):
    rows = _rows(*FIXABLE)
    keys = {f["key"] for r in rows for f in _green.classify(r)}
    runs = [_run(mind, rows) for _ in range(len(keys))]
    filed = [p for r in runs for p in r["filed"]]
    assert all(len(r["filed"]) <= 3 for r in runs)
    assert len(filed) == len(set(filed)) == len(keys), "each reason filed exactly once"
    assert runs[-1]["filed"] == []
    first_keys = {_key(mind, p) for p in runs[0]["filed"]}
    assert all(f["outcome"].startswith("existing draft/bug/")
               for f in runs[1]["findings"] if f["key"] in first_keys)


def _key(mind, rel):
    text = (mind / rel).read_text()
    return text.split("<!-- heart-key: ", 1)[1].split(" -->", 1)[0]


def test_state_stops_a_refile_after_the_draft_left_the_backlog(mind):
    rows = _rows("ci-red")[:1]
    filed = _run(mind, rows)["filed"]
    (mind / filed[0]).unlink()
    again = _run(mind, rows)
    assert again["filed"] == []
    assert "since left the backlog" in again["findings"][0]["outcome"]
    state = json.loads((mind.parent / "home" / "heart_green.json").read_text())
    assert state["reasons"]["ci:" + rows[0]["text"].split(":")[0]]["filed"] == filed[0]


def test_a_fresh_read_without_the_reason_clears_it_so_a_recurrence_files_again(mind):
    rows, other = _rows("ci-red")[:1], _rows("url-hygiene")
    filed = _run(mind, rows)["filed"]
    (mind / filed[0]).unlink()
    _run(mind, other)  # fresh and valid, and the reason is gone
    state = json.loads((mind.parent / "home" / "heart_green.json").read_text())
    assert not [k for k in state["reasons"] if k.startswith("ci:")]
    assert _run(mind, rows)["filed"] == filed, "the recurrence is filed again"
    assert _run(mind, rows)["filed"] == [], "and deduped against its open draft"


def test_an_over_age_read_clears_nothing(mind):
    rows = _rows("ci-red")[:1]
    filed = _run(mind, rows)["filed"]
    (mind / filed[0]).unlink()
    _run(mind, [], hours_ago=9.0)
    assert _run(mind, rows)["filed"] == []


def test_existing_human_draft_queue_entry_or_active_task_blocks_a_new_draft(mind):
    ci, wf, legacy = _rows("ci-red")[0], _rows("ci-red-workflow")[0], _rows("ci-red-legacy")[0]
    (mind / "draft/bug/x/human.md").write_text(
        f"# Fix it\n\nType: bug\nLane: any\n\nHeart said: {ci['text']}\n")
    (mind / "queue.md").write_text("# Queue\n\n- " + wf["text"] + "\n")
    (mind / "active/task.md").write_text(
        f"# In flight\n\n{_green.KEY_MARK.format(legacy['key'])}\n")
    res = _run(mind, [ci, wf, legacy], mode="pick")
    assert res["filed"] == [] and res["picks"] == []
    out = {f["key"]: f["outcome"] for f in res["findings"]}
    assert out[ci["key"]].startswith("mentioned by draft/bug/x/human.md")
    assert out[wf["key"]].startswith("already named in queue.md")
    assert "in flight (active/)" in out[legacy["key"]]


def test_pick_mode_names_lane_matching_drafts_only(mind):
    ws = _rows("workspace-script")[0]
    res = _run(mind, _rows("ci-red")[:1] + [ws], mode="pick", cap=5)
    assert len(res["filed"]) == 3
    assert len(res["picks"]) == 1 and res["picks"][0] in res["filed"]
    ci = [f for f in res["findings"] if f["rule"] == "ci-red"]
    assert ci[0]["outcome"].endswith("(picked)")
    local = [f for f in res["findings"] if f["rule"] == "workspace-script"]
    assert all("lane local-dev not in the brief's lanes" in f["outcome"] for f in local)


def test_lane_less_existing_draft_is_never_picked(mind):
    ci = _rows("ci-red")[0]
    (mind / "draft/bug/x/old.md").write_text(
        f"# Old\n\nType: bug\n\n{_green.KEY_MARK.format(ci['key'])}\n")
    res = _run(mind, [ci], mode="pick")
    assert res["picks"] == [] and res["filed"] == []
    assert "fail closed" in res["findings"][0]["outcome"]


def test_a_quarantined_script_is_never_filed_only_its_bug_task_picked(mind):
    q = _rows("quarantine-active")[0]
    res = _run(mind, [q], mode="pick")
    assert res["filed"] == [] and "pick-only" in res["findings"][0]["outcome"]
    bug = res["findings"][0]["bug"]
    repo, num = bug.split("#")
    (mind / "draft/bug/x/mention.md").write_text(
        f"# Mentions {bug} and {res['findings'][0]['text']}\n\nType: bug\nLane: any\n"
        "Unattended: ready\n")
    res = _run(mind, [q], mode="pick")
    assert res["picks"] == [], "a mention is not the quarantine's bug task"
    (mind / "draft/bug/x/qbug.md").write_text(
        f"# The bug\n\nType: bug\nIssue: https://github.com/someowner/{repo}/issues/{num}\n"
        "Lane: any\nUnattended: ready\n")
    res = _run(mind, [q], mode="pick")
    assert res["picks"] == ["draft/bug/x/qbug.md"] and res["filed"] == []


def test_report_mode_writes_nothing(mind):
    res = _run(mind, _rows(*FIXABLE), mode="report")
    assert res["filed"] == [] and not (mind.parent / "home").exists()
    assert any(f.get("outcome") == "would file (report mode)" for f in res["findings"])


@pytest.mark.parametrize("kw,why", [
    ({"hours_ago": 7.0}, "over the 6 h rule"),
    ({"verdict": "green"}, "GREEN"),
    ({"verdict": "stale"}, "STALE"),
])
def test_stale_old_or_green_heart_files_nothing(mind, kw, why):
    res = _run(mind, _rows(*FIXABLE), mode="pick", **kw)
    assert res["filed"] == [] and res["picks"] == [] and why in res["note"]


def test_unreadable_heart_does_nothing(mind):
    heart = _green.read_heart(str(mind / "missing.json"), now=NOW)
    res = _green.run(mind, heart, mode="pick", now=NOW)
    assert res["filed"] == [] and "unreadable" in res["note"]


# --- the brief ----------------------------------------------------------------

def test_brief_new_writes_a_heart_section_and_names_the_picks(wt_mind, tmp_path, capsys):
    mind = wt_mind
    rows = _rows("ci-red", "dirty", "release-validation", "open-pr", "workspace-script")
    hj = tmp_path / "heart.json"
    hj.write_text(json.dumps(_readiness(rows)))
    out = tmp_path / "brief.md"
    rc = _batch.main(["brief", "--new", "2026-11-14-am", "--review-at", "2099-01-01T12:00Z",
                      "--mind", str(mind), "--out", str(out), "--green", "pick",
                      "--heart-json", str(hj), "--at", NOW.isoformat(),
                      "--home", str(tmp_path / "home")])
    assert rc == 0
    text = out.read_text()
    assert "\n## Heart\n" in text
    for cls in ("### fixable-dev", "### local-checkout", "### release-scope",
                "### human-only", "### Needs the human"):
        assert cls in text, cls
    brief = _brief.parse(text)["brief"]
    goals = [c["text"] for c in brief["goals"]["children"]]
    assert goals[0] == "1. Ship the flywheel" and goals[-1].startswith("2. heart-green")
    picks = _brief.tasks_of(brief)
    assert picks and all((mind / p).is_file() for p in picks)
    assert _brief.check(out, mind)["ok"]
    assert "heart-green filed" in capsys.readouterr().err
    # the next brief's goal diff ignores the lane's own goal
    (mind / "batches" / "2026-11-14-am.md").write_text(text)
    assert _batch._last_brief_goals(mind)[1] == ["Ship the flywheel"]


def _snapshot(*roots):
    return {str(f): f.stat().st_mtime_ns for r in roots if r.exists()
            for f in sorted(r.rglob("*")) if f.is_file() and ".git" not in f.parts}


def _brief_new(mind, tmp_path, *extra, rows=None):
    hj = tmp_path / "heart.json"
    hj.write_text(json.dumps(_readiness(rows or _rows(*FIXABLE))))
    return _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                        "2099-01-01T12:00Z", "--heart-json", str(hj), "--at",
                        NOW.isoformat(), "--home", str(tmp_path / "home"), *extra])


@pytest.mark.parametrize("mode", ["file", "pick"])
def test_a_preview_writes_no_draft_and_no_state(mind, tmp_path, capsys, mode):
    before = _snapshot(mind, tmp_path / "home")
    assert _brief_new(mind, tmp_path, "--mind", str(mind), "--green", mode) == 0
    assert _snapshot(mind, tmp_path / "home") == before
    out = capsys.readouterr().out
    assert "Nothing written: a preview" in out and "would file (report mode)" in out
    assert "  - tasks:" not in out


def test_the_shared_canonical_mind_is_refused(mind, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(_batch, "BODY_MAP_PATH", mind / "repos.yaml")
    before = _snapshot(mind, tmp_path / "home")
    for extra in (["--mind", str(mind)], []):  # named, or the implicit default
        assert _brief_new(mind, tmp_path, *extra, "--green", "pick",
                          "--out", str(tmp_path / "b.md")) == 0
        text = (tmp_path / "b.md").read_text()
        assert "not a linked worktree" in text and "worktree add" in text
    assert _snapshot(mind, tmp_path / "home") == before


def test_only_a_linked_worktree_may_be_written(mind, wt_mind, tmp_path):
    """The main checkout of a Mind clone is refused wherever it lives (not only
    the one this Brain resolves); its linked worktree is allowed."""
    assert not _batch.is_linked_worktree(mind) and _batch.is_linked_worktree(wt_mind)
    assert not _batch.is_linked_worktree(tmp_path / "not-a-repo")
    for target, writes in ((mind, False), (wt_mind, True)):
        out = tmp_path / f"b-{target.name}.md"
        assert _brief_new(target, tmp_path, "--mind", str(target), "--green", "file",
                          "--out", str(out)) == 0
        filed = list(target.glob("draft/bug/*/heart_green_*.md"))
        assert bool(filed) is writes, target
        assert ("not a linked worktree" in out.read_text()) is not writes


def test_default_mode_files_but_never_picks(wt_mind, tmp_path, monkeypatch):
    mind = wt_mind
    monkeypatch.delenv("PYAUTO_HEART_GREEN")
    assert _green.DEFAULT_MODE == "file"
    out = tmp_path / "b.md"
    assert _brief_new(mind, tmp_path, "--mind", str(mind), "--out", str(out)) == 0
    text = out.read_text()
    assert list(mind.glob("draft/bug/*/heart_green_*.md"))
    assert "  - tasks:" not in text and "heart-green:" not in text


def test_stale_release_scope_reasons_reach_needs_the_human(mind):
    res = _run(mind, _rows("ci-red", "release-validation"), mode="report")
    human = _green.section(res).split("### Needs the human", 1)[1]
    assert "no rehearsal for current source" in human


def test_green_verb_defaults_to_report(mind, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("PYAUTO_HEART_GREEN")
    hj = tmp_path / "heart.json"
    hj.write_text(json.dumps(_readiness(_rows(*FIXABLE))))
    assert _batch.main(["green", "--mind", str(mind), "--heart-json", str(hj),
                        "--at", NOW.isoformat(), "--home", str(tmp_path / "h")]) == 0
    assert "would file (report mode)" in capsys.readouterr().out
    assert not list((mind / "draft").glob("bug/*/heart_green_*.md"))


# --- no release, dispatch or quarantine path ----------------------------------

FORBIDDEN = ("workflow run", "workflow_dispatch", "--force", "--accept-red",
             "pre_build", ".yml", "quarantine add", "freeze")


def test_lane_module_imports_no_process_or_network_module():
    tree = ast.parse((BRAIN / "agents/conductors/batch/_green.py").read_text())
    mods = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "datetime", "importlib.util", "json", "re",
                    "pathlib", "_sizing"}, mods
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr)}
    consts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
              and isinstance(n.value, str) and id(n) not in docs]
    assert not [c for c in consts if c.strip() == "gh" or c.startswith("gh ")]
    assert not [c for c in consts for f in FORBIDDEN if f in c]


def test_a_full_brief_run_spawns_only_heart_readiness_and_git(wt_mind, tmp_path,
                                                             monkeypatch):
    mind = wt_mind
    """Drive `brief --new --green pick` through the LIVE read path (a fake
    `pyauto-heart` first on PATH) and record every process and URL."""
    rows = _rows(*FIXABLE) + _rows("release-validation", "install-verification",
                                   "quarantine-active", "workspace-script")
    fake = tmp_path / "bin" / "pyauto-heart"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    calls, urls = [], []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def run(args, *a, **kw):  # the heart CLI is answered here, never spawned
        if Path(str(args[0])).name == "pyauto-heart":
            calls.append([str(x) for x in args])
            return subprocess.CompletedProcess(args, 0, json.dumps(
                _readiness(rows, hours_ago=0.5)), "")
        return real_run(args, *a, **kw)

    def popen(args, *a, **kw):  # every real process spawn passes here
        calls.append([str(x) for x in args])
        return real_popen(args, *a, **kw)

    def refuse(*a, **kw):
        raise AssertionError("no shell-out may bypass subprocess.Popen")

    def urlopen(url, *a, **kw):
        urls.append(getattr(url, "full_url", url))
        raise AssertionError("local readiness answered; the feed must not be read")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(os, "system", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    rc = _batch.main(["brief", "--new", "2026-11-14-am", "--review-at",
                      "2099-01-01T12:00Z", "--mind", str(mind), "--green", "pick",
                      "--home", str(tmp_path / "home"), "--out", str(tmp_path / "b.md")])
    assert rc == 0 and urls == []
    assert list(mind.glob("draft/bug/*/heart_green_*.md")), "it did file"
    heart = [c for c in calls if Path(c[0]).name == "pyauto-heart"]
    assert heart == [[str(fake), "readiness", "--json"]]
    others = [c for c in calls if c not in heart]
    assert others and all(c[0] == "git" and c[3] in ("blame", "show", "rev-parse")
                          for c in others), others
    flat = " ".join(" ".join(c) for c in calls)
    for bad in ("gh ", "workflow", "release", "dispatch", "--force", "quarantine"):
        assert bad not in flat, bad


def test_published_feed_fallback_reads_one_state_json(mind, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("BOARD_PAGES_BASE", "https://example.invalid")
    hf = _green._hf()
    monkeypatch.setattr(_green, "_hf", lambda: hf)
    monkeypatch.setattr(hf, "resolve_heart_cli", lambda: None)
    urls = []
    feed = {"status": "yellow", "updated": (NOW - dt.timedelta(hours=1)).isoformat(),
            "items": [{"severity": "yellow", "text": r["text"]} for r in _rows("url-hygiene")]}

    def urlopen(url, timeout=None):
        urls.append(url)
        return io.BytesIO(json.dumps(feed).encode())

    monkeypatch.setattr(hf.urllib.request, "urlopen", urlopen)
    heart = _green.read_heart(now=NOW)
    assert heart["source"] == "published feed" and len(urls) == 1
    assert urls[0].endswith("/state.json")
    assert _green.classify(heart["reasons"][0])[0]["rule"] == "url-hygiene"


def test_an_over_age_local_snapshot_yields_to_a_fresher_feed(monkeypatch):
    monkeypatch.setenv("BOARD_PAGES_BASE", "https://example.invalid")
    hf = _green._hf()
    monkeypatch.setattr(_green, "_hf", lambda: hf)
    old = _readiness(_rows("ci-red"), hours_ago=9.0)
    monkeypatch.setattr(hf, "local_readiness", lambda: (old, None))
    feed = {"status": "red", "updated": (NOW - dt.timedelta(hours=1)).isoformat(),
            "items": [{"severity": "red", "text": _rows("ci-red")[0]["text"]}]}
    monkeypatch.setattr(hf, "fetch_feed", lambda url: (feed, None))
    assert _green.read_heart(now=NOW)["source"] == "published feed"
    monkeypatch.setattr(hf, "fetch_feed", lambda url: (None, "offline"))
    heart = _green.read_heart(now=NOW)
    assert heart["source"] == "local readiness" and heart["age_hours"] > 6

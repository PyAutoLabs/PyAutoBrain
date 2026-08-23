"""Contract tests for the Brain board (board/_board.py).

Hermetic: PYAUTO_ROOT points at a fabricated PyAutoMind, BOARD_GH at a stub
`gh` serving fixture JSON, and BOARD_PAGES_BASE at file:// fixtures for the
sibling boards' badge.json — so the surface is asserted structurally with no
network and no real checkouts. The board is a read-only SURFACE: the stub
records every call so the tests can prove no mutating endpoint is ever hit,
and --apply writes only inside its --out directory.

Names here are fakes (ExampleOrg/RepoA) per the tenant firewall — the org is
derived from the fabricated body map at runtime, never asserted as an
instance fact. Repo names that DO appear (PyAutoBrain, PyAutoHeart, ...) come
from config/policy.yaml `board:`, the declared config surface.
"""

import base64
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"

SURFACE_KEYS = {
    "generated", "org", "overnight", "heart", "heart_blockers", "hands",
    "versions", "community", "resume", "open_issues", "devbox", "autonomy",
    "doors", "boards", "degraded", "history",
}

AUTONOMY_LOG = """\
# Autonomy calibration log

| date | task | effective level | gates | outcome |
|------|------|-----------------|-------|---------|
| 2026-08-01 | first-task (#1) | safe | tests pass | merged-unchanged |
| 2026-08-02 | second-task (#2) | supervised | tests pass | amended |
"""

HEART_BOARD_JSON = {
    "schema_version": 2,
    "blockers": [{
        "text": "RepoA: nightly smoke red",
        "severity": "red",
        "repo": "RepoA",
        "repo_url": "https://example.invalid/RepoA",
        "run_url": "https://example.invalid/run/9",
        "prompt": "/bug Heart board: RepoA nightly smoke red — https://example.invalid/run/9",
    }],
}

BRAIN_PREV_BOARD_JSON = {
    "history": [{"date": "2026-08-20", "need_you": 3}],
}

REPOS_YAML = """\
repos:
  RepoA:
    github: ExampleOrg/RepoA
    category: library
  RepoB:
    github: ExampleOrg/RepoB
    category: workspace
"""

DASHBOARD_MD = """\
# Dashboard

| Where | Count |
|-------|------:|
| [In flight](#in-flight) (`active/`) | 1 |
| [Parked](#parked) (`parked.md`) | 3 |
| [Planned](#planned) (`planned.md`) | 6 |
| [Backlog](#backlog) (`draft/`) | 152 |
"""

VERSION = "2026.8.17.1"
RECENT = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
    "%Y-%m-%dT%H:%M:%SZ")

EMPTY_SEARCH = {"items": []}


def _run_json(runs_conclusion="success"):
    return {"workflow_runs": [{
        "conclusion": runs_conclusion,
        "status": "completed",
        "created_at": RECENT,
        "id": 1,
        "html_url": "https://example.invalid/run/1",
    }]}


def _default_fixtures(**overrides):
    fx = {
        "runs.json": _run_json(),
        "jobs.json": {"jobs": [{"steps": [
            {"name": "ordinary step", "conclusion": "success"}]}]},
        "contents.json": {"content": base64.b64encode(
            f'__version__ = "{VERSION}"\n'.encode()).decode()},
        "release.json": {"tag_name": VERSION},
        "pending.json": {"items": [{
            "repository_url": "https://api.github.com/repos/ExampleOrg/RepoA",
            "number": 5,
            "title": "waiting release train",
            "html_url": "https://example.invalid/pr/5",
        }]},
        "issue_count.json": {"total_count": 42},
        "annotations.json": [],
        "comm_issues.json": EMPTY_SEARCH,
        "comm_prs.json": EMPTY_SEARCH,
        "comments.json": [],
    }
    fx.update(overrides)
    return fx


def _fabricate(tmp_path, fixtures):
    """A PYAUTO_ROOT with a fabricated Mind, file:// sibling-board badges, and
    a stub gh serving per-endpoint fixture JSON, logging every invocation."""
    mind = tmp_path / "PyAutoMind"
    (mind / "active").mkdir(parents=True)
    (mind / "repos.yaml").write_text(REPOS_YAML)
    (mind / "dashboard.md").write_text(DASHBOARD_MD)
    (mind / "active" / "some_task.md").write_text("# Fix the fixture widget\n")
    (mind / "queue.md").write_text(
        "# Queue\n\ndraft/feature/repoa/one.md\ndraft/feature/repoa/two.md\n")
    (mind / "autonomy_log.md").write_text(AUTONOMY_LOG)

    # One badge per sibling board named in the declared config surface —
    # read from policy.yaml so no board repo name is hardcoded here.
    import yaml
    board_cfg = yaml.safe_load(
        (BRAIN_HOME / "config" / "policy.yaml").read_text())["board"]
    pages = tmp_path / "pages"
    board_repos = set((board_cfg.get("boards") or {}).values())
    board_repos.add(board_cfg["heart_board"])
    for board_repo in board_repos:
        (pages / board_repo).mkdir(parents=True)
        (pages / board_repo / "badge.json").write_text(json.dumps({
            "schemaVersion": 1, "label": board_repo.lower(),
            "message": "GREEN", "color": "brightgreen"}))
    # The Heart's machine surface (structured blockers) and the Brain's own
    # previous page (the self-carrying trend history).
    (pages / board_cfg["heart_board"] / "board.json").write_text(
        json.dumps(HEART_BOARD_JSON))
    brain_repo = (board_cfg.get("boards") or {}).get("brain", "PyAutoBrain")
    (pages / brain_repo).mkdir(parents=True, exist_ok=True)
    (pages / brain_repo / "board.json").write_text(
        json.dumps(BRAIN_PREV_BOARD_JSON))

    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    for name, payload in fixtures.items():
        (fixture_dir / name).write_text(json.dumps(payload))

    stub = tmp_path / "gh"
    stub.write_text(f"""#!/usr/bin/env bash
echo "$@" >> "{tmp_path}/gh_calls.log"
for arg in "$@"; do
  case "$arg" in
    repos/*/actions/workflows/*)      cat "{fixture_dir}/runs.json"; exit 0 ;;
    repos/*/actions/runs/*/jobs)      cat "{fixture_dir}/jobs.json"; exit 0 ;;
    repos/*/check-runs/*/annotations) cat "{fixture_dir}/annotations.json"; exit 0 ;;
    repos/*/contents/*)               cat "{fixture_dir}/contents.json"; exit 0 ;;
    repos/*/releases/latest)          cat "{fixture_dir}/release.json"; exit 0 ;;
    search/issues?q=*pending-release*) cat "{fixture_dir}/pending.json"; exit 0 ;;
    "search/issues?q="*"is:issue+is:open&per_page=1") cat "{fixture_dir}/issue_count.json"; exit 0 ;;
    q=org:*is:issue*)                 cat "{fixture_dir}/comm_issues.json"; exit 0 ;;
    q=org:*is:pr*)                    cat "{fixture_dir}/comm_prs.json"; exit 0 ;;
    q=repo:*)                         cat "{fixture_dir}/comm_prs.json"; exit 0 ;;
    */comments)                       cat "{fixture_dir}/comments.json"; exit 0 ;;
  esac
done
exit 1
""")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def _run(args, tmp_path, stub):
    env = {
        **os.environ,
        "PYAUTO_ROOT": str(tmp_path),
        "BOARD_GH": str(stub),
        "BOARD_PAGES_BASE": f"file://{tmp_path}/pages",
        # Isolated from any devbox observation committed to this checkout.
        "BOARD_DEVBOX_FILE": str(tmp_path / "devbox_board.json"),
        "COMMUNITY_GH": str(stub),
        "COMMUNITY_SEARCH_PAUSE": "0",
    }
    return subprocess.run(
        [str(BRAIN), "board", *args],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )


def _surface(tmp_path, fixtures=None):
    stub = _fabricate(tmp_path, fixtures or _default_fixtures())
    r = _run(["--json"], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout), tmp_path / "gh_calls.log"


# ----------------------------------------------------------------- surface --


def test_json_surface_is_complete_and_derives_org(tmp_path):
    s, _ = _surface(tmp_path)
    assert set(s) == SURFACE_KEYS
    assert s["org"] == "ExampleOrg"  # derived from the fabricated body map
    # Overnight rows: one per policy job, owner defaulted onto the derived org.
    assert s["overnight"], "policy overnight_jobs rendered no rows"
    for row in s["overnight"]:
        assert set(row) == {"repo", "workflow", "conclusion", "age_h", "url",
                            "blocked", "blocked_reason"}
        assert row["repo"].startswith("ExampleOrg/")
        assert row["conclusion"] == "success"
    # Versions: every stamp resolves to the fixture, so consensus + no drift.
    v = s["versions"]
    assert v["consensus"] == VERSION
    assert v["drift"] == 0
    assert v["reference"] == VERSION
    # Heart headline via the file:// badge (the cross-board contract), plus
    # the structured blockers from its published machine surface, verbatim.
    assert s["heart"]["message"] == "GREEN"
    assert s["heart_blockers"] == HEART_BOARD_JSON["blockers"]
    assert s["hands"]["message"] == "GREEN"
    # Autonomy strip: the log's tail, and the self-carrying trend history.
    assert [a["task"] for a in s["autonomy"]] == [
        "first-task (#1)", "second-task (#2)"]
    assert s["history"][0] == {"date": "2026-08-20", "need_you": 3}
    assert len(s["history"]) == 2 and s["history"][1]["need_you"] == 0
    assert s["devbox"] is None  # no observation published in this fixture
    # Resume: the Mind's own generated counts + the task file + the queue.
    assert s["resume"]["counts"]["In flight"] == 1
    assert s["resume"]["counts"]["Backlog"] == 152
    assert s["resume"]["tasks"] == [
        {"path": "active/some_task.md", "title": "Fix the fixture widget"}]
    assert s["resume"]["queue_len"] == 2
    assert s["resume"]["pending_prs"][0]["repo"] == "ExampleOrg/RepoA"
    assert s["open_issues"] == 42
    # Community section reuses the Ears' scan surface wholesale.
    assert s["community"]["counts"]["awaiting_response"] == 0
    # The doors roster covers every agent (dispatcher registry, both tiers)
    # AND every workflow door (skills/ minus the agents).
    verbs = {d["verb"] for d in s["doors"]}
    assert {"intake", "health", "vitals"} <= verbs
    skill_verbs = {d["verb"] for d in s["doors"] if d["tier"] == "skill"}
    assert {"route", "prm", "start_dev", "issue_cleanup"} <= skill_verbs
    for d in s["doors"]:
        if d["tier"] == "skill":
            assert d["desc"], d["verb"]  # frontmatter description parsed
    assert "board" not in verbs    # the page never lists itself
    assert "wake_up" not in verbs  # superseded BY this page
    # Sibling boards resolved against the pages base.
    assert s["boards"]["heart"].endswith("/PyAutoHeart/")


def test_all_green_is_clear_to_work(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    r = _run(["--badge"], tmp_path, stub)
    badge = json.loads(r.stdout)
    assert badge == {"schemaVersion": 1, "label": "brain",
                     "message": "clear to work", "color": "brightgreen"}


def test_overnight_failure_is_blocking_and_red(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "runs.json": _run_json("failure")}))
    r = _run(["--badge"], tmp_path, stub)
    badge = json.loads(r.stdout)
    assert badge["color"] == "red"
    assert badge["message"].endswith("need you")
    md = _run([], tmp_path, stub).stdout
    assert "🚨 Blocking" in md


def test_blocked_gate_is_attention_not_blocking(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "jobs.json": {"jobs": [{"steps": [
            {"name": "Blocked at a gate — no release made",
             "conclusion": "success"}]}]}}))
    r = _run(["--badge"], tmp_path, stub)
    badge = json.loads(r.stdout)
    assert badge["color"] == "orange"
    html_page = _run(["--html"], tmp_path, stub).stdout
    assert "blocked at a gate" in html_page


# -------------------------------------------------------------------- html --


def test_html_is_self_contained_with_one_tap_payloads(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "runs.json": _run_json("failure")}))
    r = _run(["--html"], tmp_path, stub)
    page = r.stdout
    # Self-containment: inline script and href anchors are allowed; external
    # ASSETS are not (the invariant the Heart board's tests settled on).
    # data-cmd payloads legitimately carry URLs, so strip them first.
    import re
    stripped = re.sub(r'data-cmd="[^"]*"', 'data-cmd=""', page)
    assert "<link" not in stripped
    assert " src=" not in stripped
    assert "fetch(" not in stripped
    assert "@import" not in stripped
    # One-tap payloads for each actionable row family.
    assert 'data-cmd="/start_dev active/some_task.md"' in page
    assert 'data-cmd="/health"' in page
    assert 'data-cmd="/community"' in page
    assert 'data-cmd="/issue_cleanup"' in page
    assert 'data-cmd="/prm https://example.invalid/pr/5"' in page
    assert "/bug overnight:" in page  # the failing run's payload
    # The local morning leg is a TERMINAL chip, not a Claude payload.
    assert 'data-cmd="bash PyAutoBrain/bin/morning.sh"' in page
    # The doors roster is on the page.
    assert 'data-cmd="/intake"' in page


def test_apply_writes_the_four_pages_files(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    out = tmp_path / "site"
    r = _run(["--apply", "--out", str(out)], tmp_path, stub)
    assert r.returncode == 0, r.stderr
    for name in ("index.html", "badge.json", "board.json", "board.md"):
        assert (out / name).is_file(), name
    badge = json.loads((out / "badge.json").read_text())
    assert badge["label"] == "brain"


def _community_item(repo, number, login, title, comments=0):
    return {
        "number": number,
        "title": title,
        "user": {"login": login, "type": "User"},
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "labels": [],
        "comments": comments,
        "updated_at": "2026-07-10T00:00:00Z",
        "repository_url": f"https://api.github.com/repos/{repo}",
    }


def test_every_community_conversation_gets_its_own_chip(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "comm_issues.json": {"items": [
            _community_item("ExampleOrg/RepoA", 7, "some_user",
                            "lens model crashes"),
            _community_item("ExampleOrg/RepoB", 9, "other_user",
                            "docs question", comments=2),
        ]}}))
    page = _run(["--html"], tmp_path, stub).stdout
    # One 📋 triage chip per conversation — awaiting-reply and watched alike.
    assert 'data-cmd="/community triage ExampleOrg/RepoA#7"' in page
    assert 'data-cmd="/community triage ExampleOrg/RepoB#9"' in page
    md = _run([], tmp_path, stub).stdout
    assert "`/community triage ExampleOrg/RepoA#7`" in md
    assert "`/community triage ExampleOrg/RepoB#9`" in md


def test_boards_footer_lists_the_family_without_self(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    page = _run(["--html"], tmp_path, stub).stdout
    footer = page[page.rindex("Boards:"):]
    for name in ("mind", "heart", "hands", "memory", "organism"):
        assert f">{name}</a>" in footer, name
    assert ">brain</a>" not in footer  # a board never links itself


def test_heart_blockers_render_with_their_own_prompts(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    page = _run(["--html"], tmp_path, stub).stdout
    blocker = HEART_BOARD_JSON["blockers"][0]
    # The Heart's own /bug prompt is the chip payload — never re-derived.
    assert f'data-cmd="{blocker["prompt"]}"' in page
    assert "nightly smoke red" in page
    md = _run([], tmp_path, stub).stdout
    assert blocker["prompt"] in md
    assert "Shipped: **GREEN**" in md  # the Hands headline joined the section


def test_blocked_gate_annotation_renders_inline(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures(**{
        "jobs.json": {"jobs": [{"id": 77, "steps": [
            {"name": "Blocked at a gate — no release made",
             "conclusion": "success"}]}]},
        "annotations.json": [
            {"title": "Nightly release blocked",
             "message": "The driver stopped at a gate (exit 3); no release "
                        "was made.",
             "annotation_level": "warning"}]}))
    page = _run(["--html"], tmp_path, stub).stdout
    assert "The driver stopped at a gate (exit 3)" in page


def _devbox_payload(ts):
    return {
        "schema": 1,
        "ts": ts,
        "hygiene": {"rows": [
            {"mode": "artifacts", "status": "debris", "count": 4,
             "summary": "4 generated packaging leftovers across 2 repos",
             "delegate": "/repo_cleanup"},
            {"mode": "crlf", "status": "clean", "count": 0,
             "summary": "clean", "delegate": "/refactor"},
        ]},
        "worktrees": [
            {"repo": "RepoA", "branch": "feature/x", "ahead": 2,
             "dirty": False, "stashes": 1}],
    }


def test_devbox_observation_renders_age_stamped(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    fresh = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "devbox_board.json").write_text(
        json.dumps(_devbox_payload(fresh)))
    page = _run(["--html"], tmp_path, stub).stdout
    assert "Dev box" in page and "5h" in page
    assert "packaging leftovers" in page
    assert 'data-cmd="/repo_cleanup"' in page  # the row's own delegate door
    assert "<b>crlf</b>" not in page  # clean rows are not rendered
    assert "feature/x" in page and "2 unpushed" in page


def test_expired_devbox_observation_is_dropped(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    old = (datetime.now(timezone.utc) - timedelta(days=9)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "devbox_board.json").write_text(
        json.dumps(_devbox_payload(old)))
    s = json.loads(_run(["--json"], tmp_path, stub).stdout)
    assert s["devbox"] is None


# ----------------------------------------------------------------- publish --


def _publish_env(tmp_path, hygiene_json=None):
    """A fabricated Brain repo (with a bare origin), workspace, and stub
    hygiene entrypoint for board publish."""
    workspace = tmp_path / "ws"
    dirty_repo = workspace / "RepoA"
    dirty_repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(dirty_repo)], check=True)
    (dirty_repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(dirty_repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(dirty_repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(dirty_repo), "checkout", "-qb",
                    "feature/task"], check=True)

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                   check=True)
    brain = tmp_path / "brainrepo"
    subprocess.run(["git", "clone", "-q", str(origin), str(brain)], check=True)
    (brain / "seed.txt").write_text("seed")
    subprocess.run(["git", "-C", str(brain), "add", "."], check=True)
    subprocess.run(["git", "-C", str(brain), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(brain), "push", "-q", "-u", "origin",
                    "main"], check=True)

    hyg = tmp_path / "hygiene_stub.sh"
    home = os.path.expanduser("~")
    default_decision = {"decision": "HygieneDecision", "rows": [
        {"mode": "artifacts", "kind": "debris", "status": "debris", "count": 2,
         "summary": f"2 leftovers under {home}/Code somewhere",
         "delegate": "/repo_cleanup"}]}
    hyg.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n"
                   + json.dumps(hygiene_json or default_decision)
                   + "\nEOF\n")
    hyg.chmod(hyg.stat().st_mode | stat.S_IEXEC)

    return {
        **os.environ,
        "PYAUTO_ROOT": str(workspace),
        "BOARD_PUBLISH_REPO": str(brain),
        "BOARD_DEVBOX_FILE": str(brain / "state" / "devbox_board.json"),
        "BOARD_HYGIENE_CMD": str(hyg),
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }, brain, origin


def test_publish_dry_run_distills_and_scrubs(tmp_path):
    env, brain, _origin = _publish_env(tmp_path)
    r = subprocess.run([str(BRAIN), "board", "publish", "--dry-run"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["schema"] == 1
    # Worktree scan sees the off-main repo; only names travel.
    assert payload["worktrees"][0]["repo"] == "RepoA"
    assert payload["worktrees"][0]["branch"] == "feature/task"
    # The hygiene summary's home path was collapsed before leaving the box.
    summary = payload["hygiene"]["rows"][0]["summary"]
    assert os.path.expanduser("~") not in summary
    assert "~/Code" in summary
    # Dry run wrote nothing.
    assert not (brain / "state" / "devbox_board.json").exists()


def test_publish_commits_and_pushes_to_main_only(tmp_path):
    env, brain, origin = _publish_env(tmp_path)
    r = subprocess.run([str(BRAIN), "board", "publish", "--no-hygiene"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    # The observation landed on the bare origin's main.
    shown = subprocess.run(
        ["git", "-C", str(origin), "show", "main:state/devbox_board.json"],
        capture_output=True, text=True)
    assert shown.returncode == 0
    assert json.loads(shown.stdout)["worktrees"][0]["repo"] == "RepoA"
    assert "hygiene" not in json.loads(shown.stdout)  # --no-hygiene
    # Re-publishing an identical observation pushes nothing new.
    r2 = subprocess.run([str(BRAIN), "board", "publish", "--no-hygiene"],
                        capture_output=True, text=True, env=env, cwd=tmp_path)
    assert "nothing to push" in r2.stdout
    # Off main, publish refuses (guard against feature-branch commits).
    subprocess.run(["git", "-C", str(brain), "checkout", "-qb", "other"],
                   check=True)
    r3 = subprocess.run([str(BRAIN), "board", "publish", "--no-hygiene"],
                        capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r3.returncode == 2
    assert "main only" in r3.stderr


# --------------------------------------------------------------- read-only --


def test_board_never_hits_a_mutating_endpoint(tmp_path):
    s, log = _surface(tmp_path)
    calls = log.read_text().splitlines()
    assert calls, "the stub gh was never consulted"
    for call in calls:
        args = call.split()
        assert "-X" not in args or args[args.index("-X") + 1] == "GET", call
        for verb in ("POST", "PATCH", "PUT", "DELETE"):
            assert verb not in args, call


# --------------------------------------------------------------- degrading --


def test_missing_mind_degrades_honestly(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    env_root = tmp_path / "elsewhere"
    env_root.mkdir()
    env = {
        **os.environ,
        "PYAUTO_ROOT": str(env_root),
        "BOARD_GH": str(stub),
        "BOARD_PAGES_BASE": f"file://{tmp_path}/pages",
        "COMMUNITY_GH": str(stub),
        "COMMUNITY_SEARCH_PAUSE": "0",
    }
    r = subprocess.run([str(BRAIN), "board", "--json"],
                       capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    # Org falls back to the Brain checkout's own remote; the community and
    # resume sections degrade into listed reasons, never fabricated content.
    assert s["community"] is None
    assert any("community" in d for d in s["degraded"])
    assert any("resume" in d for d in s["degraded"])
    assert s["resume"]["tasks"] == []

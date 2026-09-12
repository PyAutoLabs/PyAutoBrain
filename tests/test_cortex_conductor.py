"""Contract tests for the Cortex conductor — the Brain's science door.

These run against the **real** Cortex checkout's `tests/fixtures/skeleton`,
not a copy: that fixture is the schema's own witness (project `example`,
active on both partitions with two runs and seven log entries and an issue;
`single`, active on one partition with nothing out; `wound_down`, retired;
`sleeping`, dormant with no ledger at all; a `checkin.yaml`), and a copy here
would drift from the schema it claims to exercise. When no Cortex is checked
out every test skips cleanly — `tests.yml` checks the repo out so CI does
exercise them.

The module is imported directly wherever the assertion is about a value (the
census, a page, the normaliser); the CLI is exercised by subprocess where the
assertion is about exit codes, because those are the `dashboard_refresh.yml`
contract.
"""

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

BRAIN_HOME = Path(__file__).resolve().parents[1]
CONDUCTOR = BRAIN_HOME / "agents" / "conductors" / "cortex" / "_cortex.py"
BRAIN = BRAIN_HOME / "bin" / "pyauto-brain"


def _load():
    spec = importlib.util.spec_from_file_location("_cortex_under_test", CONDUCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cortex = _load()


def cortex_root() -> Path:
    """The real PyAutoCortex checkout, or skip."""
    env = os.environ.get("PYAUTO_CORTEX")
    for candidate in ([Path(env)] if env else []) + [BRAIN_HOME.parent / "PyAutoCortex"]:
        if (candidate / "scripts" / "cortex.py").is_file():
            return candidate
    pytest.skip("no PyAutoCortex checkout beside PyAutoBrain")


@pytest.fixture(scope="module")
def skeleton():
    root = cortex_root() / "tests" / "fixtures" / "skeleton"
    if not (root / "projects" / "example.md").is_file():
        pytest.skip("PyAutoCortex checkout has no ledger skeleton fixture")
    return root


@pytest.fixture()
def tmp_skeleton(tmp_path, skeleton):
    """A writable copy of the fixture — outside any git repo, so the renderer
    derives no `home` and the pages are identical wherever this runs."""
    dst = tmp_path / "cortex"
    shutil.copytree(skeleton, dst)
    return dst


def _run(args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(CONDUCTOR), *args],
                          capture_output=True, text=True, cwd=cwd, env=env)


FAKE_CLI = """#!/bin/sh
case "$1" in
  pull) echo "pulled {key}"; exit {pull_rc} ;;
  jobs) echo "JOBID        PARTITION  STATE"; echo "{jobs}"; exit 0 ;;
  *) echo "unknown verb $1" >&2; exit 2 ;;
esac
"""


def wire_cli(root: Path, tmp_path: Path, fail=(), jobs="3002_[0-3]   ral   RUNNING"):
    """Point every `local_path` of the copied fixture at a directory holding a
    fake `hpc/sync` that echoes — so `--apply` pulls something that exists
    and reaches nothing."""
    text = (root / "projects.yaml").read_text(encoding="utf-8")
    for key in re.findall(r"^([a-z][a-z0-9_]*):$", text, re.M):
        local = tmp_path / "science" / key
        (local / "hpc").mkdir(parents=True, exist_ok=True)
        cli = local / "hpc" / "sync"
        cli.write_text(FAKE_CLI.format(key=key, pull_rc=3 if key in fail else 0,
                                       jobs=jobs), encoding="utf-8")
        cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
        text = text.replace(f"local_path: /tmp/{key}\n", f"local_path: {local}\n")
    (root / "projects.yaml").write_text(text, encoding="utf-8")
    return tmp_path / "science"


# --- the census ------------------------------------------------------------
def test_the_census_counts_runs_by_state_and_projects_by_status(skeleton):
    c = _cortex.census(skeleton)
    assert c["counts"] == {"running": 1, "open": 1, "active": 2}
    assert [d["key"] for d in c["ledgers"]] == ["example", "single", "wound_down"]
    assert c["checkin"] == "2026-09-02T09:00Z"
    assert c["problems"] == []


def test_a_ledger_dict_carries_the_card_facts(skeleton):
    c = _cortex.census(skeleton)
    ex = _cortex.ledger_of(c, "example")
    assert ex["status"] == "active" and ex["partition"] == "both"
    assert ex["issue"] == "example#7"
    # the owner is the Cortex script's default, not a fact this test states
    assert ex["issue_url"].startswith("https://github.com/")
    assert ex["issue_url"].endswith("/example/issues/7")
    assert ex["rel"] == "projects/example.md"
    assert ex["local_path"] == "/tmp/example" and ex["ral_root"] == "/mnt/ral/example"
    assert [(r["ident"], r["state"]) for r in ex["runs"]] == \
        [("3002_[0-3]", "running"), ("3003", "open")]
    # a continuation line joins the run's text
    assert ex["runs"][1]["what"].endswith("chained after 3002 with afterok")
    assert ex["n_log"] == 7 and ex["updated"] == "2026-09-02"
    assert ex["log"][0] == {"date": "2026-09-02", "kind": "run",
                            "text": "3003 submitted: joint fit on the same four seeds"}
    assert _cortex.ledger_of(c, "single")["issue_url"] == ""
    assert _cortex.no_ledger_rows(c)[0][0] == "sleeping"


def test_census_json_is_the_same_dict(skeleton):
    r = _run(["census", "--json", "--cortex", str(skeleton)])
    assert r.returncode == 0, r.stderr
    c = json.loads(r.stdout)
    assert c["counts"] == {"running": 1, "open": 1, "active": 2}
    assert {d["key"] for d in c["ledgers"]} == {"example", "single", "wound_down"}


def test_census_text_names_every_ledger_and_the_stamp(skeleton):
    r = _run(["census", "--cortex", str(skeleton)])
    assert r.returncode == 0
    assert "1 running · 1 open" in r.stdout
    assert "Last check-in:   2026-09-02T09:00Z" in r.stdout
    assert "wound_down" in r.stdout and "retired" in r.stdout


# --- dashboard.md ----------------------------------------------------------
BOARD_ROW = re.compile(r"^\|\s*\[([^\]]+)\]\([^)]*\)[^|]*\|\s*(\d+)\s*\|", re.M)


def test_the_counts_table_is_the_shape_the_brain_board_parses(skeleton):
    """`board/_board.py::collect_cortex` regex-parses this table; the three
    rows are what its strip shows."""
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    assert "| Where | Count |\n|-------|------:|\n" in page
    assert dict((k, int(n)) for k, n in BOARD_ROW.findall(page)) == \
        {"Running": 1, "Open": 1, "Projects": 2}
    assert page.startswith("# PyAutoCortex Dashboard\n\n<!-- generated by ")
    assert "> **Last updated " in page


def test_the_summary_table_has_four_narrow_columns_and_active_rows_only(skeleton):
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    summary = page.split("## Summary")[1].split("## Projects")[0]
    assert "| Project | Running | Open | Last update |" in summary
    rows = [ln for ln in summary.splitlines() if ln.startswith("| ") and
            not ln.startswith("| Project")]
    assert rows == ["| example | 1 | 1 | 2026-09-02 |",
                    "| single | 0 | 0 | 2026-09-01 |"]


def test_one_resume_chip_per_active_project_and_no_other_chips(skeleton):
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    chips = re.findall(r"<summary>📋 ([^<]+)</summary>", page)
    assert chips == ["check in since last time", "resume example", "resume single"]
    # the paste, verbatim
    assert ("/cortex — resume example: read PyAutoCortex projects/example.md "
            "(Now, Runs, Log) and then /tmp/example/wiki/project/state.md and "
            "the assistant example_assistant's AGENTS.md; tell me where I left "
            "off and what I said I would do next. Submit nothing and log "
            "nothing until I say.") in page
    # `assistant: none` names no assistant
    assert ("and then /tmp/single/NOTES.md; tell me where I left off" in page)
    assert "since the last check-in (2026-09-02T09:00Z)" in page
    assert "Record nothing about results — I will tell you what to log." in page
    assert "### Last check-in: 2026-09-02T09:00Z" in page
    assert "retire" not in page.lower().replace("retired", "")


def test_a_project_card_shows_now_runs_and_the_last_five(skeleton):
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    card = page.split("### example — ")[1].split("### single — ")[0]
    assert card.startswith("Does the example pipeline recover the truth on the fixture lens")
    assert ("active · both · [example#7](https://github.com/PyAutoLabs/example/"
            "issues/7) · [projects/example.md](projects/example.md) · local "
            "`/tmp/example` · RAL `/mnt/ral/example`") in card
    assert "**Now**\n\nWave 2 is on the cluster" in card
    assert "- 3002_[0-3] — running — ral — 2026-09-01 — wave 2, four seeds" in card
    assert "- 3003 — open — gpu — 2026-09-02 — joint fit on the same four seeds chained" in card
    last = card.split("**Last 5**")[1].split("[full log]")[0]
    assert len([ln for ln in last.splitlines() if ln.startswith("- ")]) == 5
    assert "- 2026-09-01 — *lesson* — the adapt image" in last
    assert "3001_[0-3] submitted" not in last  # the sixth entry
    single = page.split("### single — ")[1]
    assert "no issue yet" in single and "- _nothing on the cluster_" in single


def test_run_and_log_text_are_truncated_on_the_card(tmp_skeleton):
    led = tmp_skeleton / "projects" / "example.md"
    text = led.read_text(encoding="utf-8")
    long_what = "w" * 300
    long_note = "n" * 400
    text = text.replace("- 3003 — open — gpu — 2026-09-02 — joint fit on the same four seeds",
                        f"- 3003 — open — gpu — 2026-09-02 — {long_what}")
    text = text.replace("- 2026-09-02 — run — 3003 submitted: joint fit on the same four seeds",
                        f"- 2026-09-02 — note — {long_note}")
    led.write_text(text, encoding="utf-8")
    page = _cortex.render_dashboard(_cortex.census(tmp_skeleton))
    run = re.search(r"^- 3003 — open — gpu — 2026-09-02 — (w+…)$", page, re.M)
    assert run and len(run.group(1)) == _cortex.RUN_CLIP
    note = re.search(r"^- 2026-09-02 — \*note\* — (n+…)$", page, re.M)
    assert note and len(note.group(1)) == _cortex.LOG_CLIP
    assert long_what not in page and long_note not in page


def test_retired_projects_fold_and_dormant_rows_without_a_ledger_table(skeleton):
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    assert "### wound_down" not in page
    fold = page.split("<details><summary>1 retired</summary>")[1].split("</details>")[0]
    assert "[wound_down](projects/wound_down.md) — A project that finished and was retired — retired 2026-09-01: done" in fold
    table = page.split("#### No ledger")[1]
    assert "| Project | Status | Note |" in table
    assert "| sleeping | dormant | no ledger yet |" in table
    assert "### sleeping" not in page


def test_active_cards_lead_and_a_broken_tree_is_said_out_loud(tmp_skeleton):
    """The card order is projects.yaml order, active first; a tree that does
    not check says so on the page rather than rendering as if it did."""
    page = _cortex.render_dashboard(_cortex.census(tmp_skeleton))
    assert page.index("### example — ") < page.index("### single — ") < page.index("1 retired")
    led = tmp_skeleton / "projects" / "single.md"
    led.write_text(led.read_text(encoding="utf-8").replace("## Now\n\nNothing", "## Now\n\n\nNothing").replace(
        "Nothing submitted yet; the first run goes out once the dataset is on RAL.", ""),
        encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    assert any("`## Now` is empty" in p for p in c["problems"])
    assert "⚠️ **The tree does not check**" in _cortex.render_dashboard(c)


# --- dashboard.html --------------------------------------------------------
def test_the_html_twin_wears_the_theme_with_real_copy_buttons(skeleton):
    c = _cortex.census(skeleton)
    html = _cortex.render_dashboard_html(c)
    assert html.startswith("<!doctype html>")
    assert "<!-- generated by `pyauto-brain cortex dashboard --apply` on " in html
    assert _cortex._theme_css("cortex") in html
    assert html.count('<button class="copy"') == 3
    assert 'data-cmd="/cortex — resume example:' in html
    assert 'data-cmd="/cortex — check in on every active science project' in html
    assert '<time id="checkin" datetime="2026-09-02T09:00Z">2026-09-02T09:00Z</time>' in html
    assert "fresh-bad" in html and _cortex._CHECKIN_JS in html
    assert "<b>1</b><span>Running</span>" in html
    assert "<b>1</b><span>Open</span>" in html
    assert "<b>2</b><span>Projects</span>" in html
    assert "table.map{width:100%" in html
    assert ("<tr><th>Project</th><th>Running</th><th>Open</th>"
            "<th>Last update</th></tr>") in html
    assert html.count('<section class="project">') == 2
    assert "<details><summary>1 retired</summary>" in html
    assert "<h4>No ledger</h4>" in html
    assert 'class="pathchip">/tmp/example</span>' in html


def test_the_html_escapes_the_ledgers_text(tmp_skeleton):
    led = tmp_skeleton / "projects" / "single.md"
    led.write_text(led.read_text(encoding="utf-8").replace(
        "- 2026-09-01 — note — ledger opened",
        "- 2026-09-01 — note — a <script>alert(1)</script> & co"), encoding="utf-8")
    html = _cortex.render_dashboard_html(_cortex.census(tmp_skeleton))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html


# --- --check / --apply -----------------------------------------------------
def test_apply_then_check_is_clean_and_a_ledger_edit_is_drift(tmp_skeleton):
    assert _run(["dashboard", "--cortex", str(tmp_skeleton), "--apply"]).returncode == 0
    assert (tmp_skeleton / "dashboard.md").is_file()
    assert (tmp_skeleton / "dashboard.html").is_file()
    r = _run(["dashboard", "--cortex", str(tmp_skeleton), "--check"])
    assert r.returncode == 0, r.stderr
    led = tmp_skeleton / "projects" / "single.md"
    led.write_text(led.read_text(encoding="utf-8").replace(
        "Nothing submitted yet;", "The dataset landed;"), encoding="utf-8")
    r = _run(["dashboard", "--cortex", str(tmp_skeleton), "--check"])
    assert r.returncode == 1 and "stale" in r.stderr


def test_a_date_only_rerender_is_not_drift(skeleton):
    c = _cortex.census(skeleton)
    today = dict(c, generated="2026-01-01")
    later = dict(c, generated="2027-12-31")
    for name in ("dashboard.md", "dashboard.html"):
        a = _cortex.render_pages(today)[name]
        b = _cortex.render_pages(later)[name]
        assert a != b
        assert _cortex.dashboard_body(a) == _cortex.dashboard_body(b)


def test_check_exit_codes_are_the_refresh_workflow_contract(tmp_path):
    assert _run(["dashboard", "--check", "--cortex", str(tmp_path / "nowhere")]).returncode == 2
    (tmp_path / "bare").mkdir()
    r = _run(["dashboard", "--check", "--cortex", str(tmp_path / "bare")])
    assert r.returncode in (1, 2, 3)


# --- checkin ---------------------------------------------------------------
def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_a_dry_run_names_every_active_pull_and_reaches_nothing(tmp_skeleton, tmp_path):
    wire_cli(tmp_skeleton, tmp_path)
    before = _tree_bytes(tmp_skeleton)
    r = _run(["checkin", "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr
    assert "dry run" in r.stdout
    assert f"$ cd {tmp_path / 'science' / 'example'} && hpc/sync pull" in r.stdout
    assert f"$ cd {tmp_path / 'science' / 'single'} && hpc/sync pull" in r.stdout
    assert f"$ cd {tmp_path / 'science' / 'example'} && hpc/sync jobs" in r.stdout
    assert "wound_down" not in r.stdout and "sleeping" not in r.stdout
    assert "pulled example" not in r.stdout  # the fake CLI never ran
    assert _tree_bytes(tmp_skeleton) == before
    assert _run(["checkin", "--dry-run", "--cortex", str(tmp_skeleton)]).stdout == r.stdout


def test_apply_pulls_then_prints_the_jobs_output_verbatim_and_renders(tmp_skeleton, tmp_path):
    wire_cli(tmp_skeleton, tmp_path)
    r = _run(["checkin", "--apply", "--no-push", "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout
    assert "pulled example" in out and "pulled single" in out
    # jobs ran for the project with runs, not for the one without
    assert out.count("3002_[0-3]   ral   RUNNING") >= 2  # streamed, then in the summary
    summary = out.split("# The Cortex by project")[1]
    ex = summary.split("## example — ")[1].split("## single — ")[0]
    assert "pull: ok" in ex
    assert "jobs:\nJOBID        PARTITION  STATE\n3002_[0-3]   ral   RUNNING" in ex
    assert "Now:\nWave 2 is on the cluster" in ex
    assert "- 3002_[0-3] — running — ral — 2026-09-01" in ex
    assert "- 2026-09-01 — lesson — the adapt image" in ex
    assert "python3 scripts/cortex.py done example 3002_[0-3] [--wall H:MM]" in ex
    assert 'python3 scripts/cortex.py log example "<what I learned>" --kind result|lesson' in ex
    assert 'python3 scripts/cortex.py now example "<where I am>"' in ex
    single = summary.split("## single — ")[1]
    assert "jobs: no jobs verb" in single
    assert "- nothing on the cluster" in single
    # nothing was inferred: no state moved, the ledgers are untouched
    assert (tmp_skeleton / "projects" / "example.md").read_text() == \
        (cortex_root() / "tests" / "fixtures" / "skeleton" / "projects" / "example.md").read_text()
    stamp = (tmp_skeleton / "checkin.yaml").read_text()
    assert re.fullmatch(r"refreshed: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\n", stamp)
    assert stamp.split()[1] in (tmp_skeleton / "dashboard.md").read_text()
    assert (tmp_skeleton / "dashboard.html").is_file()
    assert "push: off" in out


def test_one_failing_pull_does_not_stop_the_sweep_and_exits_1(tmp_skeleton, tmp_path):
    wire_cli(tmp_skeleton, tmp_path, fail=("example",))
    r = _run(["checkin", "--apply", "--no-push", "--cortex", str(tmp_skeleton)])
    assert r.returncode == 1
    assert "pulled single" in r.stdout
    ex = r.stdout.split("## example — ")[1].split("## single — ")[0]
    assert "pull: pull exited 3" in ex
    assert "pull: ok" in r.stdout.split("## single — ")[1]
    assert (tmp_skeleton / "checkin.yaml").read_text().startswith("refreshed: 20")


def test_skip_pull_and_project_narrow_the_sweep(tmp_skeleton, tmp_path):
    wire_cli(tmp_skeleton, tmp_path)
    r = _run(["checkin", "--apply", "--no-push", "--skip-pull",
              "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr
    assert "pulled " not in r.stdout
    assert "pull: skipped (--skip-pull)" in r.stdout
    assert "3002_[0-3]   ral   RUNNING" in r.stdout  # jobs still asked
    r = _run(["checkin", "--apply", "--no-push", "--project", "single",
              "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr
    assert "pulled single" in r.stdout and "pulled example" not in r.stdout
    assert "## example — " not in r.stdout
    r = _run(["checkin", "--apply", "--no-push", "--project", "nope",
              "--cortex", str(tmp_skeleton)])
    assert "nope: no such project" in r.stdout


def test_checkin_keys_sweep_active_rows_and_any_ledger_with_a_run(tmp_skeleton):
    mod = _cortex.load_cortex(tmp_skeleton)
    projects, _ = mod.load_projects(tmp_skeleton)
    ledgers, _ = mod.load_ledgers(tmp_skeleton)
    assert _cortex.checkin_keys(projects, ledgers, [])[0] == ["example", "single"]
    # a dormant project with a job still out there is still out there
    (tmp_skeleton / "projects" / "sleeping.md").write_text(
        "# sleeping — A dormant project with a run\n\nProject: sleeping\nIssue: none\n\n"
        "## Now\n\nOne job.\n\n## Runs\n\n- 42 — open — ral — 2026-09-01 — a job\n\n"
        "## Log\n\n- 2026-09-01 — run — 42 submitted: a job\n", encoding="utf-8")
    ledgers, _ = mod.load_ledgers(tmp_skeleton)
    assert _cortex.checkin_keys(projects, ledgers, [])[0] == ["example", "single", "sleeping"]


# --- the push rule ---------------------------------------------------------
def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True)


def test_push_preflight_refuses_a_dirty_tree_or_a_branch(tmp_skeleton, tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    gh = fake / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    _git(tmp_skeleton, "init", "-q", "-b", "main")
    _git(tmp_skeleton, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(tmp_skeleton, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    ok, why = _cortex.push_preflight(tmp_skeleton)
    assert ok, why
    (tmp_skeleton / "checkin.yaml").write_text("refreshed: 2026-09-03T09:00Z\n")
    ok, why = _cortex.push_preflight(tmp_skeleton)
    assert not ok and "uncommitted" in why
    _git(tmp_skeleton, "checkout", "-q", "-b", "feature")
    ok, why = _cortex.push_preflight(tmp_skeleton)
    assert not ok and "`feature`" in why


def test_push_preflight_refuses_without_gh(tmp_skeleton, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    ok, why = _cortex.push_preflight(tmp_skeleton)
    assert not ok and "gh" in why


def test_push_ledger_refuses_a_code_classified_diff(tmp_skeleton):
    """`scripts/ledger_merge.py classify` is the Cortex's own gate; a fixture
    tree has none, and that is a refusal too — not the same one."""
    ok, lines = _cortex.push_ledger(tmp_skeleton, "2026-09-12", ["projects.yaml"])
    assert not ok and lines[0].startswith("push: REFUSED")
    ok, lines = _cortex.push_ledger(tmp_skeleton, "2026-09-12", [])
    assert ok and "nothing changed" in lines[0]


# --- issue -----------------------------------------------------------------
def test_the_issue_block_prints_for_example_and_not_for_single(skeleton):
    r = _run(["issue", "--cortex", str(skeleton)])
    assert r.returncode == 0, r.stderr
    assert "== example → https://github.com/PyAutoLabs/example/issues/7" in r.stdout
    assert "<!-- cortex:ledger begin — regenerated from projects/example.md; edit there -->" in r.stdout
    assert "<!-- cortex:ledger end -->" in r.stdout
    assert "**Now**" in r.stdout and "- `3002_[0-3]` — running" in r.stdout
    assert "single" not in r.stdout.replace("single-", "")
    r = _run(["issue", "--project", "single", "--cortex", str(skeleton)])
    assert "nothing to sync" in r.stdout


def test_issue_apply_without_gh_says_what_it_would_write_and_exits_1(skeleton, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    r = _run(["issue", "--apply", "--cortex", str(skeleton)],
             env={**os.environ, "PATH": "/nonexistent"})
    assert r.returncode == 1
    assert "no `gh` on PATH — would write the block above to https://github.com/PyAutoLabs/example/issues/7" in r.stdout


def test_issue_apply_replaces_the_block_through_gh(skeleton, tmp_path):
    """A fake `gh`: `issue view` serves a body with a stale block, `issue
    edit` captures the file it was handed. Never `issue create`."""
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "gh.log"
    gh = fake / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {log}\n'
        'if [ "$1 $2" = "issue view" ]; then\n'
        '  printf "<!-- cortex:ledger begin — regenerated from projects/example.md; edit there -->\\nold\\n<!-- cortex:ledger end -->\\n\\nThe human wrote this.\\n"; exit 0\n'
        "fi\n"
        'if [ "$1 $2" = "issue edit" ]; then\n'
        f'  cp "$5" {tmp_path / "body.md"}; exit 0\n'
        "fi\n"
        "exit 1\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
    r = _run(["issue", "--apply", "--cortex", str(skeleton)], env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = (tmp_path / "body.md").read_text(encoding="utf-8")
    assert "\nold\n" not in body
    assert body.count("<!-- cortex:ledger begin") == 1
    assert body.rstrip().endswith("The human wrote this.")
    assert "**Now**" in body
    calls = log.read_text()
    assert "issue view https://github.com/PyAutoLabs/example/issues/7" in calls
    assert "issue edit https://github.com/PyAutoLabs/example/issues/7 --body-file" in calls
    assert "create" not in calls


def test_sync_issue_body_prepends_when_the_markers_are_absent():
    begin = "<!-- cortex:ledger begin — regenerated from projects/{key}.md; edit there -->"
    end = "<!-- cortex:ledger end -->"
    block = f"{begin.format(key='x')}\nnew\n{end}\n"
    out = _cortex.sync_issue_body("Prose.\n", block, begin.format(key="x"), end)
    assert out == f"{begin.format(key='x')}\nnew\n{end}\n\nProse.\n"
    stale = f"{begin.format(key='y')}\nold\n{end}\nProse.\n"
    assert _cortex.sync_issue_body(stale, block, begin.format(key="x"), end) == \
        f"{begin.format(key='x')}\nnew\n{end}\nProse.\n"


# --- footing ---------------------------------------------------------------
def test_root_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setenv("PYAUTO_CORTEX", str(tmp_path / "env"))
    assert _cortex.resolve_root(str(tmp_path / "explicit")) == tmp_path / "explicit"
    assert _cortex.resolve_root() == tmp_path / "env"
    monkeypatch.delenv("PYAUTO_CORTEX")
    assert _cortex.resolve_root().name == "PyAutoCortex"


def test_the_conductor_is_mind_free_and_names_no_instance_path():
    src = CONDUCTOR.read_text(encoding="utf-8")
    assert not re.search(r"^(?:from|import) _(?:intake|sizing)\b", src, re.M)
    assert not re.search(r"^(?:from|import) yaml\b", src, re.M), "PyYAML comes through the Cortex script"
    assert not re.search(r"/mnt/|/home/\w|Users/", src), "a science path leaked into organ code"
    assert "PyAutoLabs" not in src, "no org is named in organ code"


def test_the_conductor_never_writes_a_ledger():
    """Every ledger write is the Cortex script's; the conductor's own writes
    are the stamp and the two pages."""
    src = CONDUCTOR.read_text(encoding="utf-8")
    for verb in ("add_entry", "set_now", "finish_run", "set_running", "add_run",
                 "retire_project", "new_ledger"):
        assert f"mod.{verb}" not in src
    assert "awaiting-ruling" not in src and "witness" not in src.lower()


def test_the_dispatcher_lists_the_verb():
    assert "[cortex]=" in BRAIN.read_text(encoding="utf-8")
    r = _run(["--help"])
    for verb in ("census", "dashboard", "checkin", "issue"):
        assert verb in r.stdout
    assert "collect" not in r.stdout and "gates" not in r.stdout

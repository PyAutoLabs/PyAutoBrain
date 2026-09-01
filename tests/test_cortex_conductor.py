"""Contract tests for the Cortex conductor — the Brain's science door.

These run against the **real** Cortex checkout's `tests/fixtures/skeleton`,
not a copy: that fixture is the phase-1 witness (one project, one phase per
state, five rulings including a superseded chain, one batch record), and a
copy here would drift from the schema it claims to exercise. When no Cortex
is checked out (a laptop that never cloned it) every test skips cleanly —
`tests.yml` checks the repo out so CI does exercise them.

The module is imported directly rather than run as a subprocess wherever the
assertion is about a value (the census, the plan, the normaliser); the CLI is
exercised by subprocess where the assertion is about exit codes, because those
are the `dashboard_refresh.yml` contract.
"""

import importlib.util
import os
import shutil
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
    if not root.is_dir():
        pytest.skip("PyAutoCortex checkout has no skeleton fixture")
    return root


@pytest.fixture()
def tmp_skeleton(tmp_path, skeleton):
    """A writable copy of the fixture — outside any git repo, so the renderer
    derives no `home` and the pages are identical wherever this runs."""
    dst = tmp_path / "cortex"
    shutil.copytree(skeleton, dst)
    return dst


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(CONDUCTOR), *args],
                          capture_output=True, text=True, cwd=cwd)


# --- the census ------------------------------------------------------------
def test_the_census_sorts_every_fixture_state_into_its_section(skeleton):
    c = _cortex.census(skeleton)
    # The fixture holds one phase per state; the board shows the four that
    # are live work and leaves planned/accepted/rerun/dropped to the ledger.
    assert {r["state"] for r in c["awaiting"]} == {"pulled", "awaiting-ruling"}
    assert {r["state"] for r in c["live"]} == {"submitted", "running"}
    assert [r["state"] for r in c["ready"]] == ["ready"]
    assert [r["state"] for r in c["gated"]] == ["gated"]
    assert c["by_state"]["planned"] == 1 and c["by_state"]["dropped"] == 1


def test_awaiting_orders_failures_before_the_clean_ones(skeleton):
    c = _cortex.census(skeleton)
    ranks = [0 if r["failed_runs"] else 1 for r in c["awaiting"]]
    assert ranks == sorted(ranks), [r["rel"] for r in c["awaiting"]]
    assert c["awaiting"][0]["failed_runs"], "a failed run must lead the section"


def test_a_superseded_ruling_is_not_a_standing_verdict(skeleton):
    c = _cortex.census(skeleton)
    by_id = {r["id"]: r for r in c["rulings"]}
    # The fixture's R-…-02 supersedes R-…-01 over the same phase.
    assert by_id["R-20260901-01"]["head"] is False
    assert by_id["R-20260901-02"]["head"] is True
    assert [r["id"] for r in c["rulings"]] == sorted(by_id, reverse=True)


def test_the_record_reader_keeps_every_refreshed_line(skeleton):
    """`cortex.py`'s own `_record_members` keeps the FIRST value of a repeated
    key; `refreshed:` is repeated once per pull, and the live strip needs them
    all — hence this module's own reader."""
    mod = _cortex.load_cortex(skeleton)
    record = next(p for p in mod.batch_records(skeleton))
    rec = _cortex.read_record(record.read_text(encoding="utf-8"), mod.MEMBER_RE)
    assert len(rec["keys"]["refreshed"]) == 3
    assert len(rec["members"]) == 6
    assert rec["members"][0]["slug"] == "05_running_array"


def test_a_running_phase_carries_its_last_refresh(skeleton):
    c = _cortex.census(skeleton)
    running = next(r for r in c["live"] if r["state"] == "running")
    assert running["refreshed"]["at"].startswith("2026-09-01T15:30")
    # wall against budget is what the strip prints
    assert "of 8:00" in _cortex._live_note(running)


# --- the renderer ----------------------------------------------------------
def test_every_section_renders_in_order_with_its_source_link(skeleton):
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    titles = [t for _k, t, _s, _b in _cortex.SECTIONS]
    positions = [page.index(f"## {t}") for t in titles]
    assert positions == sorted(positions), titles
    assert page.count("[markdown version]") == len(titles)


def test_every_live_phase_of_the_fixture_appears_in_its_section(skeleton):
    c = _cortex.census(skeleton)
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    for key in ("awaiting", "live", "ready", "gated"):
        for r in c[key]:
            assert r["rel"] in page, (key, r["rel"])
            assert r["rel"] in html, (key, r["rel"])
    # …and the gated row shows what it is actually waiting on.
    for ref in c["gated"][0]["gates"]:
        assert ref in page and ref in html


def test_the_counts_table_is_the_one_the_brain_board_reads(skeleton):
    import re
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    # board/_board.py's regex, verbatim.
    found = dict(re.findall(
        r"^\|\s*\[([^\]]+)\]\([^)]*\)[^|]*\|\s*(\d+)\s*\|", page, re.M))
    assert found == {"Awaiting ruling": "2", "Running / submitted": "2",
                     "Ready": "1", "Gated": "1", "Recent rulings": "5"}


def test_the_pages_wear_the_cortex_and_nothing_of_the_mind(skeleton):
    html = _cortex.render_dashboard_html(_cortex.census(skeleton))
    sys.path.insert(0, str(BRAIN_HOME / "board"))
    import _theme
    assert _theme.ORGANS["cortex"]["tagline"] in html
    assert _theme.MARKS["cortex"] in html
    assert "PyAutoMind" not in html and "/start_dev" not in html


def test_the_check_compare_ignores_the_date_but_not_the_content(skeleton):
    """Two renders on different days must compare equal — the Mind's
    normaliser strips only the generated comment, which is why its refresh
    self-heals with an empty commit most nights."""
    c = _cortex.census(skeleton)
    today = _cortex.render_pages(c)
    c_tomorrow = dict(c, generated="2099-12-31")
    tomorrow = _cortex.render_pages(c_tomorrow)
    for name in ("dashboard.md", "dashboard.html"):
        assert today[name] != tomorrow[name], name  # the stamp did change
        assert (_cortex.dashboard_body(today[name])
                == _cortex.dashboard_body(tomorrow[name])), name
    # A real content change is still drift.
    changed = dict(c, ready=[])
    assert (_cortex.dashboard_body(_cortex.render_pages(changed)["dashboard.md"])
            != _cortex.dashboard_body(today["dashboard.md"]))


def test_apply_then_check_is_clean_and_check_alone_is_drift(tmp_skeleton):
    """The witness: `--apply` writes the two pages, `--check` then passes."""
    stale = _run(["dashboard", "--check", "--cortex", str(tmp_skeleton)])
    assert stale.returncode == _cortex.RC_DRIFT
    assert "stale" in stale.stderr

    wrote = _run(["dashboard", "--apply", "--cortex", str(tmp_skeleton)])
    assert wrote.returncode == 0, wrote.stderr
    assert (tmp_skeleton / "dashboard.md").is_file()
    assert (tmp_skeleton / "dashboard.html").is_file()

    clean = _run(["dashboard", "--check", "--cortex", str(tmp_skeleton)])
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "current" in clean.stdout


def test_a_stale_page_by_one_row_is_drift(tmp_skeleton):
    _run(["dashboard", "--apply", "--cortex", str(tmp_skeleton)])
    page = tmp_skeleton / "dashboard.md"
    page.write_text(page.read_text().replace("[Ready](#ready) | 1 |",
                                             "[Ready](#ready) | 9 |"),
                    encoding="utf-8")
    assert _run(["dashboard", "--check", "--cortex",
                 str(tmp_skeleton)]).returncode == _cortex.RC_DRIFT


# --- plan ------------------------------------------------------------------
def test_plan_admits_the_ready_phase_and_hands_over_the_launch_lines(skeleton):
    c = _cortex.census(skeleton)
    d = _cortex.plan(c, budget=45, lane="local-dev")
    assert [r["rel"] for r in d["members"]] == ["phases/example/03_ready_cleared.md"]
    lines = d["launch"][0]
    assert lines[0] == "phases/example/03_ready_cleared.md"
    # the project's own sync CLI, from projects.yaml — never a literal here
    assert c["projects"]["example"]["sync_cli"] in lines[1]
    assert lines[2].startswith("python3 scripts/cortex.py move ")
    assert lines[2].endswith("submitted --run <jobid>")


def test_a_cloud_session_plans_nothing_and_reports_the_count(skeleton, capsys):
    d = _cortex.plan(_cortex.census(skeleton), lane="web-github")
    _cortex.emit_plan(d)
    out = capsys.readouterr().out
    assert d["members"] == [] and d["ready_count"] == 1
    assert "1 phase(s) are ready" in out and "from the laptop" in out


def test_the_budget_takes_the_cheapest_and_states_why_it_stopped(skeleton):
    c = _cortex.census(skeleton)
    ready = c["ready"][0]
    cheap = dict(ready, rel="phases/example/98_cheap.md", review_minutes=2)
    dear = dict(ready, rel="phases/example/99_dear.md", review_minutes=40)
    d = _cortex.plan(dict(c, ready=[dear, cheap]), budget=10, lane="local-dev")
    assert [r["rel"] for r in d["members"]] == ["phases/example/98_cheap.md"]
    assert any("exceed the budget" in why for _rel, why in d["rejected"])


def test_a_phase_without_a_witness_is_not_plannable(skeleton):
    c = _cortex.census(skeleton)
    naked = dict(c["ready"][0], witness="")
    d = _cortex.plan(dict(c, ready=[naked]), lane="local-dev")
    assert d["members"] == []
    assert "no Witness" in d["rejected"][0][1]


def test_the_lane_is_probed_not_declared():
    # Same signal the batch conductor uses: a remote session has no `gh`.
    assert _cortex.detect_lane() == (
        "local-dev" if shutil.which("gh") else "web-github")


# --- gates -----------------------------------------------------------------
def _closed_issue():
    return {"state": "closed", "state_reason": "completed", "merged_at": None,
            "is_pr": False}


def _merged_pr():
    return {"state": "closed", "state_reason": None,
            "merged_at": "2026-08-30T10:00:00Z", "is_pr": True}


def test_grading_flips_exactly_one_phase_when_every_ref_has_cleared(tmp_skeleton):
    """The daily job's whole job, offline: the fixture's one `gated` phase
    waits on an issue and a PR; with both cleared it becomes `ready` and
    nothing else in the tree moves."""
    mod = _cortex.load_cortex(tmp_skeleton)
    before = {p.rel: p.state for p in mod.load_phases(tmp_skeleton)[0]}

    # PR-ness comes from the fixture's own `Gates:` value, not from a repo
    # name written here: an instance fact in Brain test code is the tenant
    # firewall's concern (PyAutoMind/scripts/repos_sync.py).
    gated = next(p for p in mod.load_phases(tmp_skeleton)[0]
                 if p.state == "gated")
    prs = {mod.gate_url(ref) for ref in mod.gate_refs(gated.get("Gates"))[0]
           if "/pull/" in ref}

    def fetch(urls):
        return {u: (_merged_pr() if u in prs else _closed_issue()) for u in urls}

    lines, rc = mod.gates_report(tmp_skeleton, grade=True, write=True,
                                 fetch=fetch, today=__import__("datetime").date(2026, 9, 2))
    assert rc == 0, "\n".join(lines)
    after = {p.rel: p.state for p in mod.load_phases(tmp_skeleton)[0]}
    moved = {rel for rel in after if after[rel] != before[rel]}
    assert moved == {"phases/example/02_gated_on_dev.md"}
    assert after["phases/example/02_gated_on_dev.md"] == "ready"
    assert "Gates-cleared: 2026-09-02" in (
        tmp_skeleton / "phases/example/02_gated_on_dev.md").read_text()


def test_an_unreadable_ref_fails_closed_and_flips_nothing(tmp_skeleton):
    mod = _cortex.load_cortex(tmp_skeleton)
    lines, rc = mod.gates_report(tmp_skeleton, grade=True, write=True,
                                 fetch=lambda urls: {u: "unreadable: HTTP 502"
                                                     for u in urls})
    assert rc == 1
    assert "fails closed" in "\n".join(lines)
    states = {p.rel: p.state for p in mod.load_phases(tmp_skeleton)[0]}
    assert states["phases/example/02_gated_on_dev.md"] == "gated"


def test_the_gates_verb_is_a_wrapper_and_passes_the_scripts_rc_through(tmp_skeleton):
    """No `--grade`: the offline listing, exit 0, nothing fetched."""
    r = _run(["gates", "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr
    gated = _cortex.census(tmp_skeleton)["gated"][0]
    assert gated["rel"] in r.stdout
    for ref in gated["gates"]:  # the refs come from the fixture, not from here
        assert ref in r.stdout


def test_the_epics_schema_block_is_not_read_as_an_epic(tmp_path):
    """`epics.md` documents its own schema in a fenced block whose body is a
    `## <slug>` template — an empty Cortex must show no epic card."""
    (tmp_path / "epics.md").write_text(
        "# Epics\n\n```markdown\n## <slug>\n- title: <one line>\n```\n"
        "\n## real-epic\n- title: A real one\n- mind-half: dev-half\n",
        encoding="utf-8")
    entries = _cortex.parse_epics(tmp_path / "epics.md")
    assert [e["slug"] for e in entries] == ["real-epic"]
    assert entries[0]["mind-half"] == "dev-half"


# --- footing ---------------------------------------------------------------
def test_the_root_resolves_by_flag_then_env_then_sibling(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_CORTEX", raising=False)
    assert _cortex.resolve_root(str(tmp_path)) == tmp_path
    monkeypatch.setenv("PYAUTO_CORTEX", str(tmp_path / "env"))
    assert _cortex.resolve_root() == tmp_path / "env"
    assert _cortex.resolve_root(str(tmp_path / "flag")) == tmp_path / "flag"
    monkeypatch.delenv("PYAUTO_CORTEX")
    # …and with neither, beside this Brain checkout.
    assert _cortex.resolve_root().name == "PyAutoCortex"


def test_a_fixture_tree_finds_the_schema_its_checkout_ships(skeleton):
    """A data root need not be a checkout: the fixture has no `scripts/`, and
    the script that governs it is the one shipped beside it."""
    assert (skeleton / "scripts").exists() is False
    assert _cortex.find_script(skeleton) == cortex_root() / "scripts" / "cortex.py"


def test_the_page_home_comes_from_a_file_that_travels_with_the_repo(tmp_path):
    """The renderer must produce the same bytes on a laptop and inside the
    Cortex's own refresh workflow, or `--check` reports permanent drift and
    the self-heal commits a page every night. So the owner is read from the
    repo's own docs, not from a git remote a CI container may not expose."""
    root = tmp_path / "cortex"
    (root / "scripts").mkdir(parents=True)
    assert _cortex._home(root) == ""
    (root / "README.md").write_text(
        "See [the map](https://github.com/ExampleOrg/PyAutoBrain/blob/main/"
        "ORGANISM.md).\n", encoding="utf-8")
    assert _cortex._home(root) == "https://github.com/ExampleOrg/PyAutoCortex"
    assert _cortex._pages_url(_cortex._home(root)) == \
        "https://exampleorg.github.io/PyAutoCortex/"


def test_no_cortex_is_a_clean_error_not_a_traceback(tmp_path):
    r = _run(["census", "--cortex", str(tmp_path / "nowhere")])
    assert r.returncode == _cortex.RC_USAGE
    assert "no Cortex tree" in r.stderr
    assert "Traceback" not in r.stderr


def test_the_conductor_is_stdlib_only_and_never_imports_the_mind():
    """`_sizing` (and so `_intake`) reads the Mind's body map at import and
    hard-fails without a checkout; this renderer runs inside the Cortex's own
    workflow, where no Mind exists."""
    import ast
    tree = ast.parse(CONDUCTOR.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"_sizing", "_intake", "yaml"}, sorted(imported)
    # The whole import list, pinned: stdlib, the one root resolver and the
    # shared theme. Anything else would be a dependency this page cannot
    # carry into the Cortex's own workflow.
    assert imported <= {
        "__future__", "argparse", "ast", "datetime", "html", "importlib",
        "json", "os", "re", "shutil", "subprocess", "sys", "pathlib",
        "_pyauto_root", "_theme",
    }, sorted(imported)


def test_no_absolute_instance_path_is_named_in_the_conductor():
    """Science projects live outside the workspace; the only place carrying
    such a path is the Cortex's own `projects.yaml`, read at runtime."""
    src = CONDUCTOR.read_text()
    assert "/mnt/c" not in src and "/home/" not in src


def test_the_dispatcher_lists_the_conductor_and_the_skill_exists():
    r = subprocess.run([str(BRAIN), "help"], capture_output=True, text=True,
                       check=True)
    assert "\n    cortex " in r.stdout
    assert (BRAIN_HOME / "skills" / "cortex" / "SKILL.md").is_file()


def test_the_board_family_declares_the_cortex():
    policy = (BRAIN_HOME / "config" / "policy.yaml").read_text()
    assert "\n    cortex: PyAutoCortex\n" in policy

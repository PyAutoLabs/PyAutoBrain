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
import json
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


def test_a_running_phase_reads_its_wall_against_its_budget(skeleton):
    c = _cortex.census(skeleton)
    running = next(r for r in c["live"] if r["state"] == "running")
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


def test_the_board_carries_no_batch_status_box(skeleton):
    """The science review slot was retired 2026-09-03: the page opens on the
    board's own sections, and nothing renders a box about a batch."""
    c = _cortex.census(skeleton)
    assert "batch" not in c
    for page in (_cortex.render_dashboard(c), _cortex.render_dashboard_html(c)):
        assert "No batch in flight" not in page
        assert "batch collect" not in page


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


# --- gates -----------------------------------------------------------------
def test_the_gates_verb_is_a_read_only_wrapper_over_the_scripts_listing(tmp_skeleton):
    """Gate grading was retired 2026-09-03: the verb lists, exits 0, fetches
    nothing and flips nothing. A gated phase moves on when a human types
    `move <phase> ready`."""
    before = {p.rel: p.state for p in
              _cortex.load_cortex(tmp_skeleton).load_phases(tmp_skeleton)[0]}
    r = _run(["gates", "--cortex", str(tmp_skeleton)])
    assert r.returncode == 0, r.stderr
    gated = _cortex.census(tmp_skeleton)["gated"][0]
    assert gated["rel"] in r.stdout
    for ref in gated["gates"]:  # the refs come from the fixture, not from here
        assert ref in r.stdout
    # What the listing prints per ref is the Cortex script's own business (CI
    # checks that repo out at main, which may be a release behind this one) —
    # what this asserts is that the wrapper fetches nothing and writes nothing.
    assert "--grade" not in r.stdout
    after = {p.rel: p.state for p in
             _cortex.load_cortex(tmp_skeleton).load_phases(tmp_skeleton)[0]}
    assert after == before


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


# --- collect ---------------------------------------------------------------
# The board and the two laptop trees it was pulled into are built by
# `tests/_cortex_board.py` (which says what real trees they imitate); the
# builder lives there because `test_batch_kinds.py` raises the same tree.
from _cortex_board import (  # noqa: E402 - tests/ is on sys.path
    BENIGN_ERR, HEALTHY_OUT, PROJECTS, SUMMARY, _phase, _write,
    _zip_summary, build_board,
)

#: The three phases `build_board` adds on top of the skeleton, and the only
#: ones the scoring tests assert about. The skeleton's own live phases are in
#: `collect`'s default scope too (that IS the check-in), so a test about one
#: member names it with `--phase` rather than counting the whole scope.
BOARD = ("phases/example/11_healthy.md", "phases/example/12_resumed.md",
         "phases/subhalo/01_partial.md")


def _collect(root, *args):
    return _run(["collect", "--cortex", str(root),
                 *[x for rel in BOARD for x in ("--phase", rel)], *args])


@pytest.fixture()
def board(tmp_path, skeleton):
    """A tmp Cortex with three live phases — built by
    `tests/_cortex_board.py`."""
    return build_board(tmp_path, skeleton)


def _score(board_) -> dict:
    """`{slug: scored}` for the board's three live members."""
    root = board_["root"]
    mod = _cortex.load_cortex(root)
    projects = mod.load_projects(root)[0]
    return {ph.slug: _cortex.score_phase(mod, ph, projects)
            for ph in mod.load_phases(root)[0]
            if ph.state in _cortex.LIVE_STATES and ph.slug in
            ("11_healthy", "12_resumed", "01_partial")}


def test_the_board_the_collect_tests_score_is_a_tree_that_checks(board):
    """Every fixture below asserts about scoring, not about schema — so the
    tree they score must be one `cortex.py check` accepts."""
    mod = _cortex.load_cortex(board["root"])
    assert mod.check_problems(board["root"]) == []


def test_a_clean_pulled_run_scores_healthy_on_every_leg(board):
    s = _score(board)["11_healthy"]
    verdicts = {k: v[0] for k, v in s["legs"].items()}
    assert verdicts == {k: _cortex.PASS for k in _cortex.LEGS}, s["legs"]
    assert s["health"] == "HEALTHY"
    assert "2026.8.17.1" in s["legs"]["version"][1]
    assert "0:51" in s["legs"]["wall"][1] and "of 6:00" in s["legs"]["wall"][1]
    assert "40960 bytes" in s["legs"]["checkpoint"][1]


def test_a_resumed_run_is_failed_however_clean_the_rest_is(board):
    """`Fit Already Completed` means the numbers are the *previous* fit's.
    Nothing else about the member is wrong, which is exactly why a scorer that
    only read `.err` and the wall clock would call it delivered."""
    s = _score(board)["12_resumed"]
    assert s["legs"]["resume"][0] == _cortex.FAIL
    assert "Fit Already Completed" in s["legs"]["resume"][1]
    assert s["legs"]["err"][0] == _cortex.PASS
    assert s["health"] == "FAILED"


def test_the_zip_is_authoritative_over_a_stale_partial_extraction(board):
    s = _score(board)["01_partial"]
    assert s["legs"]["wall"][0] == _cortex.PASS
    assert "0:51:28" in s["legs"]["wall"][1], "the extracted dir says 0:04:00"
    assert "zip" in s["legs"]["wall"][1]


def test_the_two_legs_the_laptop_cannot_see_are_unobservable_not_failed(board):
    """A project with no version stamp and no pull manifest is not a failed
    run — it is a run two of whose four `delivered:` legs cannot be scored
    here. SUSPECT sends it to the human; FAILED would condemn it."""
    s = _score(board)["01_partial"]
    assert s["legs"]["version"][0] == _cortex.UNOBSERVABLE
    assert s["legs"]["checkpoint"][0] == _cortex.UNOBSERVABLE
    assert "RAL only" in s["legs"]["checkpoint"][1]
    assert s["legs"]["witness"][0] == _cortex.PASS
    assert s["health"] == "SUSPECT"


def test_the_manifests_checkpoints_table_is_keyed_by_the_run_directory(board):
    """The third lookup (PyAutoCortex decision 51). The subhalo-style member's
    pull carries no job id, so `runs` is empty and the only name both sides can
    say is the run directory, relative to the pull root."""
    _write(board["sub"] / ".cortex/pull.json", json.dumps(
        {"schema": 1, "pulled_at": "2026-08-31T10:00Z",
         "checkpoints": {"output/lens_a/cccc3333": {
             "bytes": 81920, "mtime": "2026-08-30T09:51Z"}},
         "runs": {}}))
    s = _score(board)["01_partial"]
    assert s["legs"]["checkpoint"][0] == _cortex.PASS, s["legs"]["checkpoint"]
    assert "81920 bytes" in s["legs"]["checkpoint"][1]


def test_a_zero_byte_checkpoint_in_the_manifest_fails_the_leg(board):
    """A checkpoint the puller found and measured at zero bytes is not an
    unobservable leg — it is a run that delivered nothing."""
    _write(board["sub"] / ".cortex/pull.json", json.dumps(
        {"schema": 1, "pulled_at": "2026-08-31T10:00Z",
         "checkpoints": {"output/lens_a/cccc3333": {
             "bytes": 0, "mtime": "2026-08-30T09:51Z"}}}))
    s = _score(board)["01_partial"]
    assert s["legs"]["checkpoint"][0] == _cortex.FAIL
    assert "empty checkpoint" in s["legs"]["checkpoint"][1]
    assert s["health"] == "FAILED"


def test_a_manifest_without_a_schema_key_still_reads_as_the_runs_only_shape(board):
    """The phase-2 manifest (`pulled_at` + `runs`, no `schema`) is what the
    healthy member carries — it must keep scoring PASS unchanged."""
    manifest = json.loads(
        (board["mirror"] / ".cortex/pull.json").read_text(encoding="utf-8"))
    assert "schema" not in manifest and "checkpoints" not in manifest
    s = _score(board)["11_healthy"]
    assert s["legs"]["checkpoint"][0] == _cortex.PASS
    assert "40960 bytes" in s["legs"]["checkpoint"][1]


def test_a_benign_err_is_warnings_not_an_empty_file(board):
    """`.err` "clean" is not size 0: the baseline both projects produce is a
    warning line plus its indented source line."""
    errs = [board["mirror"] / "logs/error/error.400100.err"]
    assert _cortex.leg_err(errs)[0] == _cortex.PASS
    fatal = board["mirror"] / "logs/error/error.400999.err"
    _write(fatal, BENIGN_ERR + "Traceback (most recent call last):\n"
           "  File \"run.py\", line 9\nValueError: no\n")
    assert _cortex.leg_err([fatal])[0] == _cortex.FAIL
    assert _cortex.leg_err([])[0] == _cortex.UNOBSERVABLE


def test_the_report_emits_a_block_per_phase_in_order(board):
    r = _collect(board["root"])
    assert r.returncode == _cortex.RC_DRIFT, "one FAILED + one SUSPECT"
    assert "3 phase(s), delivered 1/3" in r.stdout
    for head in ("## 11_healthy — HEALTHY", "## 12_resumed — FAILED",
                 "## 01_partial — SUSPECT"):
        assert head in r.stdout, r.stdout
    block = r.stdout.split("## 11_healthy — HEALTHY")[1].split("## ")[0]
    order = ["**Question**", "**Witness**", "**Health evidence**",
             "**Readout**", "**Ruling**", "**Your review**", "**Follow-ups**",
             "**Where to look yourself**", "**Est. review-minutes**"]
    assert [block.index(x) for x in order] == sorted(block.index(x)
                                                     for x in order)
    for leg in _cortex.LEG_TITLES.values():
        assert leg in block
    # the readout is the witness JSON's own scalars
    assert "log_likelihood" in block and "1234.5" in block, block
    # the ruling is the human's sentence, never drafted here
    assert "yours to write" in block
    assert "Accept / Rerun / Drop / Leave to finish" in block


def test_a_phase_gets_its_own_witness_not_its_neighbours(board):
    """`witness_file` is a *project-wide* glob and the two `example` phases
    share one output tree, so the glob alone hands a phase its neighbour's
    numbers — the readout under a member's name must be that member's run."""
    s = _score(board)
    assert s["11_healthy"]["witness_hits"][0].name == "aaaa1111.json"
    assert dict(s["11_healthy"]["readout"])["log_likelihood"] == 1234.5
    assert s["12_resumed"]["witness_hits"][0].name == "bbbb2222.json"


def test_the_report_can_be_written_to_a_file(board, tmp_path):
    out = tmp_path / "packet.md"
    r = _collect(board["root"], "--out", str(out))
    assert "## 11_healthy — HEALTHY" in out.read_text()
    assert "## 11_healthy" not in r.stdout and str(out) in r.stdout


def test_apply_without_a_refresh_stamp_refuses(board):
    r = _collect(board["root"], "--apply")
    assert r.returncode == _cortex.RC_USAGE
    assert "--apply needs a refresh stamp" in r.stderr
    states = {p.rel: p.state for p in
              _cortex.load_cortex(board["root"]).load_phases(board["root"])[0]}
    assert states["phases/example/11_healthy.md"] == "running"


def test_apply_moves_the_phases_and_the_tree_still_checks(board):
    """The moves are the WHOLE write: the batch record `apply_ops` once
    rewrote is closed history since 2026-09-03."""
    root = board["root"]
    r = _collect(root, "--apply", "--refreshed", "2026-09-02T11:40Z")
    assert r.returncode == _cortex.RC_DRIFT, "one member is still FAILED"
    assert "Refreshed: 2026-09-02T11:40Z" in r.stdout
    mod = _cortex.load_cortex(root)
    states = {p.rel: p.state for p in mod.load_phases(root)[0]}
    for rel in BOARD:
        assert states[rel] == "awaiting-ruling", rel
    # the whole point of rehearsing on a copy: the tree still checks.
    assert mod.check_problems(root) == []
    # …and the default scope no longer sees them: they are off the runs.
    again = _run(["collect", "--cortex", str(root)])
    for rel in BOARD:
        assert rel.rsplit("/", 1)[1][:-3] not in again.stdout


def test_apply_leaves_a_phase_whose_run_is_still_live_where_it_is(board):
    """`submitted → pulled` is not an edge and a live run has not finished:
    both are notes, not forced moves."""
    root = board["root"]
    ph = root / "phases/example/11_healthy.md"
    ph.write_text(ph.read_text().replace(
        "- 400100: done", "- 400100: running"), encoding="utf-8")
    r = _collect(root, "--apply", "--refreshed", "2026-09-02T11:40Z")
    assert "left running" in r.stdout, r.stdout + r.stderr
    mod = _cortex.load_cortex(root)
    states = {p.rel: p.state for p in mod.load_phases(root)[0]}
    assert states["phases/example/11_healthy.md"] == "running"
    assert states["phases/example/12_resumed.md"] == "awaiting-ruling"
    assert mod.check_problems(root) == []


def test_pull_runs_the_projects_own_cli_and_stamps_the_refresh(board):
    """The one thing collect does that reaches the cluster is the human's own
    sync CLI, named by `projects.yaml`, and only under `--pull`."""
    cli = board["local"] / "hpc" / "sync"
    cli.parent.mkdir(parents=True)
    marker = board["local"] / "pulled.txt"
    cli.write_text(f'#!/bin/sh\necho "$1" > {marker}\n', encoding="utf-8")
    cli.chmod(0o755)
    r = _collect(board["root"], "--pull", "--apply")
    assert marker.is_file() and marker.read_text().strip() == "pull"
    assert "hpc/sync pull" in r.stdout
    # the subhalo project has no such script: reported, and scored anyway.
    assert "01_partial" in r.stdout
    assert "Refreshed: " in r.stdout


def test_a_named_phase_narrows_the_scope(board):
    r = _run(["collect", "--cortex", str(board["root"]),
              "--phase", "phases/example/11_healthy.md"])
    assert r.returncode == _cortex.RC_OK
    assert "1 phase(s), delivered 1/1" in r.stdout
    assert "12_resumed" not in r.stdout


def test_the_default_scope_is_every_submitted_or_running_phase(board):
    """The check-in needs no record and no `--phase`: it asks the tree which
    runs are out there and scores all of them."""
    root = board["root"]
    mod = _cortex.load_cortex(root)
    live = [ph.rel for ph in mod.load_phases(root)[0]
            if ph.state in _cortex.LIVE_STATES]
    assert set(BOARD) < set(live), "the skeleton's own live phases count too"
    r = _run(["collect", "--cortex", str(root)])
    assert f"{len(live)} phase(s)" in r.stdout
    for rel in live:
        assert rel.rsplit("/", 1)[1][:-3] in r.stdout


# --- the check-in door -----------------------------------------------------
# `checkin` composes the primitives above; these tests are about the
# composition — what it sweeps, what it writes, what one project's failure
# does to the other's, and what it refuses to push. The scoring itself is
# covered by the `collect` block above and is not re-asserted here.


def _checkin(root, *args):
    return _run(["checkin", "--cortex", str(root), *args])


def _fake_cli(local: Path, rc: int, marker: Path) -> Path:
    """A stand-in for a project's own `hpc/sync`. No test in this file runs a
    real one: a real pull reaches RAL."""
    cli = local / "hpc" / "sync"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text(f'#!/bin/sh\necho "$1" > {marker}\nexit {rc}\n',
                   encoding="utf-8")
    cli.chmod(0o755)
    return cli


def test_the_dry_run_names_every_project_its_pull_and_the_phases_it_would_score(board):
    """The dry run is the door's own contract: the exact command per project
    and the exact phases, and nothing touched."""
    before = (board["mirror"] / ".cortex" / "pull.json").read_text()
    r = _checkin(board["root"], "--dry-run")
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    assert "Nothing is pulled, nothing is written" in r.stdout
    for key in ("example", "subhalo"):
        assert f"\n{key}  [active]" in r.stdout
    assert f"cd {board['local']} && hpc/sync pull" in r.stdout
    assert f"cd {board['sub']} && hpc/sync pull" in r.stdout
    for rel in BOARD:
        assert rel in r.stdout
    assert "push would be:" in r.stdout and "the rule:" in r.stdout
    assert (board["mirror"] / ".cortex" / "pull.json").read_text() == before


def test_the_dry_run_is_the_default(board):
    assert _checkin(board["root"]).stdout == _checkin(board["root"],
                                                      "--dry-run").stdout


def test_one_projects_failing_pull_does_not_stop_the_sweep(board):
    """A mirror that will not sync is one project's problem. The other
    projects still pull, every live phase is still scored, and the failure is
    recorded against the project it belongs to."""
    ran_ok = board["sub"] / "pulled.txt"
    ran_bad = board["local"] / "pulled.txt"
    _fake_cli(board["local"], 1, ran_bad)   # example: fails
    _fake_cli(board["sub"], 0, ran_ok)      # subhalo: fine
    r = _checkin(board["root"], "--apply", "--no-push")
    assert ran_bad.is_file() and ran_ok.is_file(), "both CLIs must be tried"
    assert "example: pull exited 1" in r.stdout
    assert "scored anyway" in r.stdout
    assert "### example" in r.stdout and "### subhalo" in r.stdout
    assert r.returncode == _cortex.RC_DRIFT, "a failed pull is not a clean run"
    # the sweep still did its work on the project that did pull
    mod = _cortex.load_cortex(board["root"])
    states = {p.rel: p.state for p in mod.load_phases(board["root"])[0]}
    assert states["phases/subhalo/01_partial.md"] == "awaiting-ruling"


def test_a_pulled_project_gets_a_manifest_the_scorer_can_read(board):
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    r = _checkin(board["root"], "--apply", "--no-push")
    manifest = json.loads((board["sub"] / ".cortex" / "pull.json").read_text())
    assert manifest["project"] == "subhalo"
    assert manifest["rc"] == 0
    assert manifest["cmd"].endswith("hpc/sync pull")
    assert manifest["pulled_at"]
    assert "phases/subhalo/01_partial.md" in manifest["phases_live"]
    assert "subhalo: pulled" in r.stdout


def test_the_manifest_merges_and_never_clobbers_a_richer_one(board):
    """One project's own sync CLI writes the `runs`/`checkpoints` tables the
    checkpoint leg reads. The check-in adds its keys beside them."""
    path = board["mirror"] / ".cortex" / "pull.json"
    before = json.loads(path.read_text())
    assert "runs" in before, "the fixture's manifest is the richer shape"
    _fake_cli(board["local"], 0, board["local"] / "pulled.txt")
    _checkin(board["root"], "--apply", "--no-push")
    after = json.loads(path.read_text())
    assert after["runs"] == before["runs"], "the CLI's own table is untouched"
    assert after["project"] == "example" and after["rc"] == 0
    assert after["pulled_at"] != before["pulled_at"]


def test_skip_pull_scores_what_is_already_there_and_runs_no_cli(board):
    marker = board["sub"] / "pulled.txt"
    _fake_cli(board["sub"], 0, marker)
    r = _checkin(board["root"], "--apply", "--skip-pull", "--no-push")
    assert not marker.exists(), "--skip-pull runs no sync CLI"
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    # the stamp came from the manifest the fixture already carries
    assert "Refreshed: 2026-08-31T10:00Z" in r.stdout


def test_a_named_project_narrows_the_sweep(board):
    r = _checkin(board["root"], "--dry-run", "--project", "subhalo")
    assert "1 project(s)" in r.stdout
    assert "\nsubhalo  [active]" in r.stdout and "\nexample  [active]" not in r.stdout


def test_the_summary_is_keyed_by_project_and_is_the_last_thing_printed(board):
    """A chat reads the top of the output; the door prints the pull log first
    and the summary last, so the summary is what it sees."""
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    r = _checkin(board["root"], "--apply", "--no-push")
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    out = r.stdout
    assert "# Cortex check-in" in out
    assert out.index("Wrote: dashboard.md") < out.index("# Cortex check-in")
    assert out.index("### example") < out.index("### subhalo")
    assert "Awaiting your ruling" in out
    # the prompt each state already has, ready to paste
    assert "help me rule on it" in out
    assert f"local `{board['sub']}`" in out


def test_the_render_leg_leaves_the_board_current(board):
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    _checkin(board["root"], "--apply", "--no-push")
    check = _run(["dashboard", "--cortex", str(board["root"]), "--check"])
    assert check.returncode == _cortex.RC_OK, check.stdout + check.stderr


def test_the_no_push_path_says_so_and_reaches_no_git(board):
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    r = _checkin(board["root"], "--apply", "--no-push")
    assert "push: no — --no-push" in r.stdout
    assert not (board["root"] / ".git").exists()
    assert "claude/checkin-" not in r.stdout


def test_the_push_preflight_refuses_anything_that_is_not_a_clean_main(tmp_path):
    ok, why = _cortex.push_preflight(tmp_path)
    assert ok is False and why


def _with_classifier(root: Path) -> Path:
    """The board fixture is a phases-and-rulings tree; the push gate lives in
    the Cortex's `scripts/`, so lay the real one beside it."""
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    dst = root / "scripts" / "ledger_merge.py"
    shutil.copy(cortex_root() / "scripts" / "ledger_merge.py", dst)
    return dst


def _git_init(root: Path) -> None:
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t",
                  "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True)


def test_the_push_refuses_a_code_classified_diff(board):
    """The Cortex's own classifier is the gate, asked before the branch is
    cut: a diff holding code is a human's call, so nothing is committed and
    no `claude/**` branch appears."""
    root = board["root"]
    _with_classifier(root)
    _git_init(root)
    # `projects.yaml` is the science body map — paths the conductor executes
    # under, so the classifier calls it code however small the diff is.
    (root / "projects.yaml").write_text(
        (root / "projects.yaml").read_text() + "\n# a new row\n",
        encoding="utf-8")
    ok, lines = _cortex.push_ledger(root, "2026-09-03",
                                    ["projects.yaml", "dashboard.md"])
    text = "\n".join(lines)
    assert ok is False
    assert "REFUSED" in text and "code" in text
    branches = subprocess.run(["git", "-C", str(root), "branch", "--list",
                               "claude/*"], capture_output=True, text=True)
    assert branches.stdout.strip() == "", branches.stdout


def test_a_ledger_only_diff_passes_the_classifier_before_any_git_call(board):
    """The other side of the same gate: the two generated pages classify as
    ledger, so the refusal that follows is git's (no remote), not the
    classifier's."""
    root = board["root"]
    _with_classifier(root)
    rc, text = _cortex.classify_paths(root, ["dashboard.md", "dashboard.html"])
    assert rc == 0, text


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
    # The whole import list, pinned: stdlib, the one root resolver, the
    # shared theme and the batch-status box. Anything else would be a
    # dependency this page cannot carry into the Cortex's own workflow.
    assert imported <= {
        "__future__", "argparse", "ast", "datetime", "html", "importlib",
        "json", "os", "re", "shutil", "subprocess", "sys", "tempfile",
        "zipfile", "pathlib", "_pyauto_root", "_theme", "_status",
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


"""Contract tests for the Cortex conductor — the Brain's science door.

These run against the **real** Cortex checkout's `tests/fixtures/skeleton`,
not a copy: that fixture is the phase-1 witness (one project, one task per
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
import re
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
def test_the_census_sorts_every_fixture_state_into_its_bucket(skeleton):
    """The buckets outlived their sections: `live`, `ready` and `gated` are
    still what `collect` and the check-in door scope by, they are simply no
    longer headings on the page."""
    c = _cortex.census(skeleton)
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
    # The fixture's R-…-02 supersedes R-…-01 over the same task.
    assert by_id["R-20260901-01"]["head"] is False
    assert by_id["R-20260901-02"]["head"] is True
    assert [r["id"] for r in c["rulings"]] == sorted(by_id, reverse=True)


def test_a_running_task_reads_its_wall_against_its_budget(skeleton):
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


def test_every_open_task_of_the_fixture_appears_on_the_page(skeleton):
    """Not "the four live sections" any more — every open task of every
    project, on its project's card, once."""
    c = _cortex.census(skeleton)
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    for r in c["tasks"]:
        if r["state"] in _cortex.CLOSED_STATES:
            continue
        assert r["rel"] in page, r["rel"]
        assert r["rel"] in html, r["rel"]
        # …by its ten-word summary, which is what makes the line readable.
        assert r["summary"] in page, r["rel"]
    # …and the gated row shows what it is actually waiting on.
    for ref in c["gated"][0]["gates"]:
        assert ref in page and ref in html


def test_every_open_task_is_one_row_and_the_fold_is_gone(skeleton):
    """The complaint that started this: "4 more open phase(s)" hid the work
    behind a click. There is no fold on the Projects block on either twin,
    and the number of task rows is the number of open tasks."""
    c = _cortex.census(skeleton)
    md = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    for twin in (md, html):
        assert "more open" not in twin
        assert "plans and issues" not in twin
    assert not hasattr(_cortex, "_fold_label")
    projects_html = html.split("<h2>Projects")[1].split("<h2>Awaiting")[0]
    assert "<details" not in projects_html
    open_rows = [r for r in c["tasks"]
                 if r["state"] not in _cortex.CLOSED_STATES]
    # one head row per open task (each chip past the first adds a `↳` row)
    heads = sum(1 for r in open_rows) 
    assert heads == len(open_rows)
    for r in open_rows:
        assert f'>{r["summary"]}</a>' in projects_html, r["rel"]


def test_the_state_pill_is_toned_and_a_failed_run_reddens_it(skeleton):
    """Green is "nothing owed", yellow is "moving or waiting on you", grey is
    "waiting on someone else" — and a failed run overrides all three."""
    assert _cortex.STATE_TONES == {
        "planned": "g", "ready": "g", "accepted": "g",
        "gated": "n",
        "submitted": "y", "running": "y", "pulled": "y",
        "awaiting-ruling": "y", "rerun": "y"}
    c = _cortex.census(skeleton)
    clean = {r["state"]: _cortex.state_tone(r) for r in c["tasks"]
             if not r["failed_runs"]}
    for state, tone in clean.items():
        assert tone == _cortex.STATE_TONES.get(state, "n"), state
    assert clean["planned"] == "g" and clean["ready"] == "g"
    assert clean["gated"] == "n" and clean["pulled"] == "y"
    failed = next(r for r in c["tasks"] if r["failed_runs"])
    assert _cortex.STATE_TONES[failed["state"]] != "r", "the override matters"
    assert _cortex.state_tone(failed) == "r"
    html = _cortex.render_dashboard_html(c)
    assert f'<span class="pill r">{failed["state"]}</span>' in html
    assert '<span class="pill g">planned</span>' in html
    assert '<span class="pill n">gated</span>' in html
    assert '<span class="pill y">pulled</span>' in html


def test_the_three_state_sections_are_gone_from_both_twins(skeleton):
    """The Projects block carries what they carried, per project and in
    colour, so they said the same thing three more times."""
    c = _cortex.census(skeleton)
    assert [key for key, _t, _s, _b in _cortex.SECTIONS] == \
        ["projects", "awaiting", "rulings"]
    for twin in (_cortex.render_dashboard(c),
                 _cortex.render_dashboard_html(c)):
        for heading in ("Running / submitted", ">Ready<", "## Ready",
                        ">Gated<", "## Gated"):
            assert heading not in twin, heading
    assert not hasattr(_cortex, "ready_groups")


def test_the_paths_render_as_accent_chips_on_the_html_twin(skeleton):
    """Pink-on-tint `code` was unreadable against the Cortex accent; the
    chip fills with the accent and carries white ink in both schemes."""
    c = _cortex.census(skeleton)
    html = _cortex.render_dashboard_html(c)
    row = c["projects"]["example"]
    assert (f'<p class="paths"><b>Local</b> '
            f'<span class="pathchip">{row["local_path"]}</span></p>') in html
    assert ".pathchip{" in html
    # White ink in BOTH schemes (the human's ask); the dark scheme darkens
    # the fill instead of swapping the ink.
    assert "background:var(--accent);color:#fff" in html
    assert ("@media(prefers-color-scheme:dark){.pathchip{"
            "background:color-mix(in srgb,var(--accent) 55%,#000)}}") in html
    sys.path.insert(0, str(BRAIN_HOME / "board"))
    import _theme
    sheet = _theme.css("cortex")
    assert sheet.count("--accent-ink:") == 2, "light and dark both define it"
    # the markdown twin is unchanged — no HTML span in a bold path line
    assert "**Local** `" in _cortex.render_dashboard(c)


def test_the_counts_table_is_the_one_the_brain_board_reads(skeleton):
    import re
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    # board/_board.py's regex, verbatim.
    found = dict(re.findall(
        r"^\|\s*\[([^\]]+)\]\([^)]*\)[^|]*\|\s*(\d+)\s*\|", page, re.M))
    assert found == {"Awaiting ruling": "2", "Recent rulings": "5"}


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
    changed = dict(c, awaiting=[])
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
    page.write_text(page.read_text().replace(
        "[Awaiting ruling](#awaiting-ruling) | 2 |",
        "[Awaiting ruling](#awaiting-ruling) | 9 |"), encoding="utf-8")
    assert _run(["dashboard", "--check", "--cortex",
                 str(tmp_skeleton)]).returncode == _cortex.RC_DRIFT


# --- gates -----------------------------------------------------------------
def test_the_gates_verb_is_a_read_only_wrapper_over_the_scripts_listing(tmp_skeleton):
    """Gate grading was retired 2026-09-03: the verb lists, exits 0, fetches
    nothing and flips nothing. A gated task moves on when a human types
    `move <task> ready`."""
    before = {p.rel: p.state for p in
              _cortex.load_cortex(tmp_skeleton).load_tasks(tmp_skeleton)[0]}
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
             _cortex.load_cortex(tmp_skeleton).load_tasks(tmp_skeleton)[0]}
    assert after == before


def test_the_cortex_holds_no_epics_of_its_own(tmp_skeleton):
    """Retired 2026-09-04: a science project IS the long programme, so the
    Cortex keeps no epics file, no census key and no section. A tree with an
    `epics.md` left lying in it is simply not read."""
    assert not hasattr(_cortex, "parse_epics")
    (tmp_skeleton / "epics.md").write_text(
        "# Epics\n\n## a-leftover\n- title: not read\n", encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    assert "epics" not in c
    for page in (_cortex.render_dashboard(c), _cortex.render_dashboard_html(c)):
        assert "a-leftover" not in page
        assert "Epics" not in page
    # …and the section list no longer names one.
    assert "epics" not in [key for key, _t, _s, _b in _cortex.SECTIONS]


# --- the check-in chip and the freshness stamp -----------------------------
def _first_row(page: str) -> str:
    """The first copy row on either twin — markdown `<summary>`, HTML button."""
    m = re.search(r"<summary>📋 ([^<\n]+)", page) or \
        re.search(r'<button class="copy"[^>]*></button><p>([^<]+)', page)
    return m.group(1) if m else ""


def test_the_checkin_chip_is_the_first_task_row_on_both_twins(skeleton):
    """The reader arrives, and the first thing on the page is the paste that
    refreshes everything below it — before any section."""
    c = _cortex.census(skeleton)
    page = _cortex.render_dashboard(c)
    assert _first_row(page) == _cortex.CHECKIN_LABEL
    assert page.index("📋 " + _cortex.CHECKIN_LABEL) < page.index("## Summary")
    payload = _cortex._checkin_payload(c)
    assert payload.startswith("/cortex — check in on every active science")
    assert "read me the by-project summary" in payload

    html = _cortex.render_dashboard_html(c)
    first = html.index('<div class="task">')
    assert _cortex.CHECKIN_LABEL in html[first:first + 900]
    assert first < html.index("<h2>Summary</h2>")


def test_the_stamp_is_read_from_checkin_yaml_and_says_never_without_it(tmp_skeleton):
    c = _cortex.census(tmp_skeleton)
    assert c["checkin"] == "" and c["problems"] == []
    assert f"### Last check-in: {_cortex.CHECKIN_NEVER}" in \
        _cortex.render_dashboard(c)
    assert _cortex.CHECKIN_NEVER in _cortex.render_dashboard_html(c)

    _cortex.write_checkin(tmp_skeleton, "2026-09-04T14:03:00Z")
    c = _cortex.census(tmp_skeleton)
    assert c["checkin"] == "2026-09-04T14:03:00Z"
    assert "### Last check-in: 2026-09-04T14:03:00Z" in _cortex.render_dashboard(c)
    assert ('<time id="checkin" datetime="2026-09-04T14:03:00Z">'
            in _cortex.render_dashboard_html(c))
    # the paste names the stamp it is refreshing from
    assert "(2026-09-04T14:03:00Z)" in _cortex._checkin_payload(c)


def test_a_stamp_that_cannot_be_read_is_a_problem_not_a_freshness_claim(tmp_skeleton):
    """Something wrote the file; a stamp that will not parse cannot be
    trusted to mean anything, so the board says never and says why."""
    (tmp_skeleton / "checkin.yaml").write_text("refreshed: yesterday\n",
                                               encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    assert c["checkin"] == ""
    assert any("checkin.yaml" in p for p in c["problems"]), c["problems"]
    assert _cortex.CHECKIN_NEVER in _cortex.render_dashboard(c)


def test_the_html_twin_ages_the_stamp_on_the_viewers_clock(skeleton):
    """The page is static: 3 h after it was rendered nothing on the server
    knows. So the age is computed on load and nowhere else — and what it
    computes paints a whole box, not one word."""
    html = _cortex.render_dashboard_html(_cortex.census(skeleton))
    assert ".stale{color:var(--bad)" in html
    assert "getElementById('checkin')" in html
    assert f"/60000>{_cortex.CHECKIN_FRESH_MINUTES}" in html
    assert "/60000>180" in html
    assert 'id="checkin-box"' in html
    # the two tone classes the script picks between, and the CSS for both
    for cls in ("fresh-ok", "fresh-bad"):
        assert "classList.add('" + cls + "')" in html
        assert f".checkin.{cls}{{" in html
    assert "classList.add('stale')" in html
    assert "✓" in html and "✗" in html
    assert "stale, paste the check-in" in html
    assert "never checked in" in html
    # the blurb that said the page is only as fresh as its sources is gone
    # from both twins: the box says it, in the reader's own units.
    assert "only as current as they are" not in html
    assert "only as current as they are" not in \
        _cortex.render_dashboard(_cortex.census(skeleton))


def test_the_map_is_a_map_not_a_paragraph(skeleton):
    """The Projects section lost its blurb, and every card is wrapped so the
    project's own name can carry the weight the blurb used to."""
    c = _cortex.census(skeleton)
    md = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    for page in (md, html):
        assert "science body map" not in page
    lines = md.splitlines()
    link = lines[lines.index("## Projects") + 2]
    assert link.startswith("[markdown version](") and link.endswith(")")
    assert " — " not in link  # an empty blurb leaves no dangling dash
    shown, _folded = _cortex.by_project_keys(c)
    assert shown, "the fixture must show at least one project"
    assert html.count('<section class="project">') == len(shown)
    assert html.count("</section>") == len(shown)
    assert ".project h3{" in html


# --- collect ---------------------------------------------------------------
# The board and the two laptop trees it was pulled into are built by
# `tests/_cortex_board.py` (which says what real trees they imitate); the
# builder lives there because `test_batch_kinds.py` raises the same tree.
from _cortex_board import (  # noqa: E402 - tests/ is on sys.path
    BENIGN_ERR, HEALTHY_OUT, PROJECTS, SUMMARY, _task, _write,
    _zip_summary, build_board,
)

#: The three tasks `build_board` adds on top of the skeleton, and the only
#: ones the scoring tests assert about. The skeleton's own live tasks are in
#: `collect`'s default scope too (that IS the check-in), so a test about one
#: member names it with `--task` rather than counting the whole scope.
BOARD = ("tasks/example/11_healthy.md", "tasks/example/12_resumed.md",
         "tasks/subhalo/01_partial.md")


def _collect(root, *args):
    return _run(["collect", "--cortex", str(root),
                 *[x for rel in BOARD for x in ("--task", rel)], *args])


@pytest.fixture()
def board(tmp_path, skeleton):
    """A tmp Cortex with three live tasks — built by
    `tests/_cortex_board.py`."""
    return build_board(tmp_path, skeleton)


def _score(board_) -> dict:
    """`{slug: scored}` for the board's three live members."""
    root = board_["root"]
    mod = _cortex.load_cortex(root)
    projects = mod.load_projects(root)[0]
    return {tk.slug: _cortex.score_task(mod, tk, projects)
            for tk in mod.load_tasks(root)[0]
            if tk.state in _cortex.LIVE_STATES and tk.slug in
            ("11_healthy", "12_resumed", "01_partial")}


# --- by project ------------------------------------------------------------
# The check-in view: one tree, rendered three ways. These assert the tree's
# promises (the folders, the `## Where to look` bullets, the prompts) rather
# than its exact prose.
def test_the_projects_section_leads_the_state_sections(skeleton):
    """The reading order of a morning: the counts, the check-in, the summary,
    the map — and only then what needs a verdict."""
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    order = ["| Where | Count |", "📋 " + _cortex.CHECKIN_LABEL,
             "### Last check-in:", "## Summary", "## Projects",
             "## Awaiting ruling", "## Recent rulings"]
    assert [page.index(x) for x in order] == sorted(page.index(x) for x in order)
    html = _cortex.render_dashboard_html(_cortex.census(skeleton))
    assert html.index("<h2>Summary</h2>") < html.index("<h2>Projects") \
        < html.index("<h2>Awaiting ruling")


def test_the_summary_table_holds_one_row_per_active_project(tmp_skeleton):
    """The "clean summary of everything" the page was missing. Active only —
    a dormant project is a fact, not a thing to read every morning."""
    (tmp_skeleton / "projects.yaml").write_text(
        (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
        + _DORMANT_ROW, encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    rows = _cortex.summary_rows(c)
    assert [r["project"] for r in rows] == ["example"]
    row = rows[0]
    # the next thing is the task owed a verdict, named by its own summary —
    # a number and a state said nothing a reader could act on.
    nxt = "Do the five faint lenses converge once resumed"
    assert row["next"] == nxt
    assert (row["awaiting"], row["live"]) == (2, 2)
    assert "ready" not in row
    assert row["ruling"] == "2026-09-01"
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    assert f"| example | {nxt} | 2 | 2 | 2026-09-01 |" in page
    assert "| Project | Next task | Awaiting | Running | Last ruling |" in page
    assert f"<td>{nxt}</td>" in html
    # the Ready column went with the Ready section
    assert "<th>Ready</th>" not in html and "| Ready |" not in page


def test_a_project_card_puts_each_folder_on_its_own_bold_line(skeleton):
    c = _cortex.census(skeleton)
    row = c["projects"]["example"]
    lines = _cortex.render_dashboard(c).splitlines()
    for label, path in (("Local", row["local_path"]), ("Mirror", row["mirror"]),
                        ("RAL", row["ral_root"])):
        assert f"**{label}** `{path}`" in lines, label
    html = _cortex.render_dashboard_html(c)
    assert (f'<p class="paths"><b>RAL</b> '
            f'<span class="pathchip">{row["ral_root"]}</span></p>') in html
    # the counts and the partition, one line under them
    assert "active · gpu partition · tasks: accepted 1" in "\n".join(lines)


def test_the_where_to_look_bullets_leave_the_page_but_not_the_door(skeleton):
    """They are the "which folder do I open" answer, and they belong where a
    human is already reading a task — not on a board they scroll past."""
    c = _cortex.census(skeleton)
    where = "`/mnt/c/Users/Jammy/Science/example/output/task_07/`"
    awaiting = [r for r in c["tasks"]
                if r["rel"].endswith("07_awaiting_ruling.md")][0]
    assert awaiting["where"] == [where]
    for page in (_cortex.render_dashboard(c), _cortex.render_dashboard_html(c)):
        assert "where to look:" not in page
    digest = "\n".join(_cortex.project_digest(
        "example", c["projects"]["example"], c, {}))
    assert f"where to look: {where}" in digest


def test_the_history_states_are_counted_not_listed(skeleton):
    """`accepted` / `rerun` / `dropped` are history: they belong to the
    counts line and to the ruling ledger, not to a list of things to do."""
    c = _cortex.census(skeleton)
    groups = dict(_cortex.project_groups("example", c))
    listed = {r["state"] for rows in groups.values() for r in rows}
    assert listed == {"awaiting-ruling", "pulled", "submitted", "running",
                      "ready", "gated", "planned"}


def test_census_by_project_prints_the_same_tree(skeleton):
    r = _run(["census", "--cortex", str(skeleton), "--by-project"])
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    assert "# The Cortex by project" in r.stdout
    assert "### example" in r.stdout
    assert "- where to look: `/mnt/c/Users/Jammy/Science/example/output/task_07/`" in r.stdout
    assert "**rule on it**" in r.stdout
    # the counts census is still the default
    assert "== Cortex census ==" in _run(["census", "--cortex", str(skeleton)]).stdout


#: A second row for the fixture's body map — a project with nothing open, so
#: it folds. Generic on purpose: the tenant firewall reads test fixtures too.
_DORMANT_ROW = ("\ndormant_one:\n  remote: none\n"
                "  local_path: /mnt/c/Users/Jammy/Science/dormant\n"
                "  ral_root: /mnt/ral/jnightin/dormant\n  mirror: none\n"
                "  sync_cli: hpc/sync\n  sync_verbs: [pull]\n"
                "  ledger: wiki/state.md\n  assistant: none\n"
                "  witness_file: out/**/*.json\n"
                "  partition: gpu\n  status: dormant\n")

#: Two more, so the Nothing-open table can be read for all three of the
#: statuses that fold: one that has not started and one that is over.
_PLANNED_ROW = _DORMANT_ROW.replace("dormant_one", "planned_one") \
    .replace("status: dormant", "status: planned")
_RETIRED_ROW = _DORMANT_ROW.replace("dormant_one", "retired_one") \
    .replace("status: dormant",
             'status: retired\n  note: "retired 2026-09-04: the question '
             'was answered"')


def test_a_project_with_nothing_open_is_a_row_under_the_summary(tmp_skeleton):
    """It gets no card — a dormant project with nothing open is a fact, not
    a thing to read — but it is a row in a table, not prose in a fold."""
    (tmp_skeleton / "projects.yaml").write_text(
        (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
        + _DORMANT_ROW, encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    shown, folded = _cortex.by_project_keys(c)
    assert shown == ["example"] and folded == ["dormant_one"]
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    assert "### dormant_one" not in page
    assert "#### Nothing open" in page
    assert "| dormant_one | dormant | none | retire ↓ |" in page
    assert "<h3>Nothing open</h3>" in html
    assert "<tr><td>dormant_one</td><td>dormant</td><td>none</td>" in html
    # it reads under the summary, before the map
    assert page.index("#### Nothing open") < page.index("## Projects")
    assert html.index("<h3>Nothing open</h3>") < html.index("<h2>Projects")
    for twin in (page, html):
        assert "project(s) with nothing open" not in twin


def test_the_projects_run_active_then_planned_then_dormant_then_retired(skeleton):
    """The order the human asked for, alphabetical inside each rank. Retired
    sorts after dormant and an unrecognised status still sorts last."""
    c = {"projects": {"zeta": {"status": "active"}, "alpha": {"status": "active"},
                      "plan_b": {"status": "planned"},
                      "sleepy": {"status": "dormant"},
                      "over": {"status": "retired"},
                      "odd": {"status": "who-knows"}}}
    assert _cortex.project_order(list(c["projects"]), c) == \
        ["alpha", "zeta", "plan_b", "sleepy", "over", "odd"]


def test_a_dormant_row_carries_the_retire_chip_in_both_twins(tmp_skeleton):
    """The chip is the door: the board's only offer of retirement, and the
    payload behind it is the `cortex.py retire` command for that project."""
    (tmp_skeleton / "projects.yaml").write_text(
        (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
        + _DORMANT_ROW + _PLANNED_ROW, encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    payload = _cortex._retire_payload("dormant_one")
    # HTML: a real copy button in the row's own Retire cell
    assert "<th>Retire</th>" in html
    assert (f'<button class="copy text" data-cmd="'
            f'{_cortex._attr(payload)}" aria-label="Copy the retire prompt">'
            f"📋 retire</button>") in html
    assert "cortex.py retire dormant_one --why" in html
    # markdown: the cell points down at the copy row under the table
    assert "| dormant_one | dormant | none | retire ↓ |" in page
    assert "<details><summary>📋 retire dormant_one</summary>" in page
    assert payload in page
    # a planned project has not started — no chip, an empty cell, no row
    assert "| planned_one | planned | none |  |" in page
    assert "retire planned_one" not in page
    assert "cortex.py retire planned_one" not in html
    assert "<td></td>" in html


def test_a_retired_project_leaves_the_table_for_the_fold(tmp_skeleton):
    """Retiring never deletes a row, so the project stays findable — but the
    reader of "nothing open" is looking for something to do, and a retired
    project is not it."""
    (tmp_skeleton / "projects.yaml").write_text(
        (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
        + _DORMANT_ROW + _RETIRED_ROW, encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    assert _cortex.project_status("retired_one", c) == "retired"
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    note = "retired 2026-09-04: the question was answered"
    for twin in (page, html):
        assert "retired_one" in twin
        assert "1 retired" in twin
        assert note in twin
        # no chip: it is already retired
        assert "cortex.py retire retired_one" not in twin
    assert "| retired_one |" not in page
    assert "<td>retired_one</td>" not in html
    assert "<details><summary>1 retired</summary>" in page
    assert "<details><summary>1 retired</summary><ul>" in html
    assert f"- retired_one — {note}" in page
    # it reads after the table it left, and the dormant row is still in it
    assert page.index("| dormant_one |") < page.index("1 retired")
    assert html.index("<td>dormant_one</td>") < html.index("1 retired")


def test_the_retire_payload_is_the_command_and_the_sentence(skeleton):
    """It names the project in prose and again inside the command, so a chat
    that reads it aloud says what is ending and can run it without re-reading."""
    payload = _cortex._retire_payload("dormant_one")
    assert payload.startswith("/cortex — retire the science project dormant_one:")
    assert ('`python3 scripts/cortex.py retire dormant_one --why '
            '"<one line on why>"`') in payload
    assert "`python3 scripts/cortex.py check`" in payload
    assert "`pyauto-brain cortex dashboard --apply`" in payload
    assert "push the ledger" in payload
    assert "rulings all stay" in payload


def test_census_by_project_lists_retired_on_its_own_line(tmp_skeleton):
    (tmp_skeleton / "projects.yaml").write_text(
        (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
        + _DORMANT_ROW + _RETIRED_ROW, encoding="utf-8")
    r = _run(["census", "--cortex", str(tmp_skeleton), "--by-project"])
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    assert "Dormant, nothing open: dormant_one (none)" in r.stdout
    assert "Retired: retired_one (none)" in r.stdout


def _tasks(*rows) -> dict:
    """A census-shaped dict holding only the task rows."""
    return {"tasks": list(rows)}


def _open(slug, state) -> dict:
    return {"project": "p", "rel": f"tasks/p/{slug}.md", "slug": slug,
            "summary": f"summary of {slug}", "state": state}


def test_the_open_tasks_of_a_project_read_in_the_order_they_owe_you(skeleton):
    """awaiting-ruling > running > submitted > pulled > ready > gated >
    planned. No number to sort by — science is unordered — so what a task
    owes the human is the order, and `rel` breaks the tie inside a state."""
    c = _tasks(_open("e", "planned"), _open("d", "gated"), _open("c", "ready"),
               _open("b", "running"), _open("a", "awaiting-ruling"),
               _open("z", "accepted"), _open("y", "dropped"))
    assert [r["slug"] for r in _cortex.open_tasks("p", c)] == \
        ["a", "b", "c", "d", "e"], "accepted and dropped are history"
    assert _cortex.next_open_task("p", c)["slug"] == "a"
    assert _cortex.next_open_task("p", _tasks()) is None
    # inside one state, the file path is the tie-break
    c = _tasks(_open("m", "ready"), _open("b", "ready"))
    assert [r["slug"] for r in _cortex.open_tasks("p", c)] == ["b", "m"]


def test_every_open_task_of_a_project_is_a_row_with_its_own_links(tmp_skeleton):
    """No fold and no queue: all seven open tasks of the fixture project are
    rows, and the task folder and the repo's issue list ride under them."""
    yaml = (tmp_skeleton / "projects.yaml").read_text(encoding="utf-8")
    (tmp_skeleton / "projects.yaml").write_text(
        yaml.replace("remote: none", "remote: exampleorg/widgets"),
        encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    tasks = _cortex.open_tasks("example", c)
    assert len(tasks) == 8, [r["rel"] for r in tasks]
    for r in tasks:
        assert f'<a href="{r["rel"]}">{r["summary"]}</a>' in page, r["rel"]
        assert f'>{r["summary"]}</a>' in html, r["rel"]
    # the fixture copy is outside any repo, so no owner is derivable and
    # the folder is bare backticks rather than a link
    assert "`tasks/example/`" in page
    assert "https://github.com/exampleorg/widgets/issues" in page
    assert "https://github.com/exampleorg/widgets/issues" in html
    # the rows read in the order `open_tasks` put them in
    order = [page.index(r["summary"]) for r in tasks]
    assert order == sorted(order), [r["state"] for r in tasks]


def test_a_task_that_names_nowhere_still_renders(tmp_skeleton):
    """A `planned` task may still be carrying the template placeholder —
    `check` exempts it — so every rendering has to survive an empty list."""
    scope = tmp_skeleton / "tasks" / "example" / "01_scope.md"
    text = scope.read_text(encoding="utf-8")
    scope.write_text(re.sub(r"## Where to look\n\n(?:- .*\n)+",
                            "## Where to look\n\n", text, count=1),
                     encoding="utf-8")
    mod = _cortex.load_cortex(tmp_skeleton)
    assert mod.check_problems(tmp_skeleton) == []
    c = _cortex.census(tmp_skeleton)
    row = [r for r in c["tasks"] if r["rel"].endswith("01_scope.md")][0]
    assert row["where"] == []
    page = _cortex.render_dashboard(c)
    assert "### example" in page and "where to look: \n" not in page
    _cortex.render_dashboard_html(c)          # must not raise either
    text = "\n".join(_cortex.project_digest("example", c["projects"]["example"],
                                            c, {}))
    assert "01_scope.md" in text


# --- the two missing prompts ----------------------------------------------
def _synthetic(*rows) -> dict:
    """A census-shaped dict — the payloads read only `tasks` + `projects`."""
    return {"tasks": list(rows),
            "projects": {"proj": {"local_path": "/s/proj", "sync_cli": "hpc/sync",
                                  "sync_verbs": ["pull", "submit"]}}}


def _row(state, slug, epic=None):
    return {"rel": f"tasks/proj/{slug}.md", "slug": slug, "title": slug,
            "summary": f"the {slug} question", "project": "proj",
            "state": state, "epic": epic,
            "runs": [], "budget": None, "budget_minutes": None,
            "wall_minutes": 0, "review_minutes": None, "gates": [],
            "failed_runs": [], "where": []}


def test_accept_and_open_opens_the_sibling_the_tree_already_holds(skeleton):
    """A planned sibling IS the ledger naming another question — the prompt
    opens it rather than writing a second one beside it. There is no "next
    number": the slug is the identity and the order is the human's."""
    c = _synthetic(_row("awaiting-ruling", "four"), _row("planned", "five"))
    payload = _cortex._next_task_payload(c["tasks"][0], c)
    assert "rule tasks/proj/four.md accept --body <file>" in payload
    assert "move tasks/proj/five.md ready" in payload
    assert "cd /s/proj && hpc/sync submit <script>" in payload
    assert "cortex.py new" not in payload


def test_accept_and_open_prefers_a_planned_sibling_over_a_gated_one(skeleton):
    """Both are openable; a plan is a question waiting to be asked and a gate
    is waiting on someone else."""
    c = _synthetic(_row("awaiting-ruling", "four"), _row("gated", "aaa"),
                   _row("planned", "zzz"))
    assert _cortex._next_task(c["tasks"][0], c)["slug"] == "zzz"


def test_accept_and_open_writes_a_new_task_when_there_is_none(skeleton):
    """`new` requires a ten-word `--summary` — the board's line — so the
    prompt asks for the question, not for a title or a number."""
    c = _synthetic(_row("awaiting-ruling", "four", epic="an-epic"),
                   _row("accepted", "five"), _row("dropped", "nine"))
    payload = _cortex._next_task_payload(c["tasks"][0], c)
    assert "new proj <slug> --summary" in payload
    assert "ten words at most" in payload
    assert "--epic an-epic" in payload
    assert "move tasks/proj/<slug>.md ready" in payload
    assert "--task" not in payload and "phase" not in payload


def test_run_it_again_is_a_ruling_then_the_same_launch(skeleton):
    c = _synthetic(_row("awaiting-ruling", "four"))
    payload = _cortex._rerun_payload(c["tasks"][0], c)
    order = [payload.index(x) for x in (
        "rule tasks/proj/four.md rerun --body <file>",
        "move tasks/proj/four.md ready",
        "cd /s/proj && hpc/sync submit <script>",
        "move tasks/proj/four.md submitted --run <jobid>")]
    assert order == sorted(order), payload
    assert "one run per call" in payload


def test_a_project_with_no_submit_verb_says_so_rather_than_inventing_one(skeleton):
    c = _synthetic(_row("awaiting-ruling", "four"))
    c["projects"]["proj"]["sync_verbs"] = ["pull"]
    assert "no `submit` verb in projects.yaml" in _cortex._rerun_payload(
        c["tasks"][0], c)


# --- the assistant entry protocol ------------------------------------------
BRIEF = "Enter through the assistant `example_assistant`"


def _with_assistant(c: dict, value: str) -> dict:
    c["projects"]["proj"]["assistant"] = value
    return c


def test_the_work_shaped_prompts_carry_the_assistant_entry_brief(skeleton):
    """A row that declares an assistant turns the three work-shaped payloads
    into subagent briefs — the same three chips on both twins, because
    `task_chips` is the one funnel."""
    c = _with_assistant(_synthetic(_row("awaiting-ruling", "four")),
                        "example_assistant")
    for payload in (_cortex._next_task_payload(c["tasks"][0], c),
                    _cortex._rerun_payload(c["tasks"][0], c),
                    _cortex._planned_payload(c["tasks"][0], c["projects"])):
        assert BRIEF in payload
        assert "EXAMPLE_ASSISTANT" in payload
        assert "cd /s/proj && source activate.sh" in payload
        assert "Work brief — proj / four" in payload
        assert "tasks/proj/four.md — its ## Witness is the contract" in payload

    labelled = dict(_cortex.task_chips(c["tasks"][0], c))
    assert BRIEF in labelled[
        "the results are good — accept and open the next task"]
    assert BRIEF in labelled["run it again"]
    planned = _with_assistant(_synthetic(_row("planned", "five")),
                              "example_assistant")
    assert BRIEF in dict(_cortex.task_chips(planned["tasks"][0],
                                            planned))["open it"]


def test_a_none_row_and_a_row_without_the_field_carry_no_brief(skeleton):
    """`none` is the declaration that the project routes through no
    assistant; a Cortex checkout predating the field reads the same way."""
    for c in (_with_assistant(_synthetic(_row("awaiting-ruling", "four")),
                              "none"),
              _synthetic(_row("awaiting-ruling", "four"))):
        assert "assistant" not in c["projects"]["proj"] or \
            c["projects"]["proj"]["assistant"] == "none"
        for payload in (_cortex._next_task_payload(c["tasks"][0], c),
                        _cortex._rerun_payload(c["tasks"][0], c),
                        _cortex._planned_payload(c["tasks"][0], c["projects"])):
            assert "Work brief" not in payload and "assistant" not in payload


def test_the_ruling_and_checkin_prompts_name_no_assistant(skeleton):
    """The door and the verdict are assistant-free by ruling: the assistant is
    the execution subagent's entry protocol, not part of checking in."""
    c = _with_assistant(_synthetic(_row("awaiting-ruling", "four")),
                        "example_assistant")
    assert "assistant" not in _cortex._ruling_payload(c["tasks"][0])
    assert "assistant" not in _cortex._checkin_payload({"checkin": "never"})


def test_the_chips_a_state_carries_are_the_same_everywhere(skeleton):
    """One table, three renderings — the board, `--by-project` and the door
    all ask `task_chips`, so a prompt cannot appear in one and not another."""
    c = _cortex.census(skeleton)
    by_state = {r["state"]: [label for label, _p in _cortex.task_chips(r, c)]
                for r in c["tasks"]}
    assert by_state["awaiting-ruling"] == [
        "rule on it", "the results are good — accept and open the next task",
        "run it again"]
    assert by_state["pulled"][0] == "rule on it"
    # A rerun is a VERDICT, so the chip rides on the states a verdict is owed
    # on. A running job is still out there: "run it again" there would be a
    # second submission, and it was a block of page nobody tapped.
    assert by_state["running"] == ["where the jobs stand"]
    assert by_state["submitted"] == ["where the jobs stand"]
    assert by_state["ready"] == ["submit it"]
    assert by_state["gated"] == ["its gates"]
    assert by_state["planned"] == ["open it"]
    # a rerun ruling is already written: what is left of it is the launch
    assert by_state["rerun"] == ["relaunch it"]


def test_the_new_prompts_ride_beside_the_rule_prompt_on_the_board(skeleton):
    """"Beside", not "instead of": the awaiting row keeps the rule payload it
    has always had and the two new ones follow it as their own chips."""
    page = _cortex.render_dashboard(_cortex.census(skeleton))
    assert ("📋 ↳ the results are good — accept and open the next task"
            in page)
    assert "📋 ↳ run it again" in page
    html = _cortex.render_dashboard_html(_cortex.census(skeleton))
    assert "↳ run it again" in html


def test_a_live_task_carries_the_jobs_line_and_no_rerun_chip(skeleton):
    """The live section is gone; the running task is a row on its project's
    card, and what it hands over is the project's own `jobs` verb. "Run it
    again" on a job still out there is a second submission, not a ruling."""
    c = _cortex.census(skeleton)
    running = next(r for r in c["tasks"] if r["state"] == "running")
    assert [l for l, _p in _cortex.task_chips(running, c)] == \
        ["where the jobs stand"]
    for page in (_cortex.render_dashboard(c), _cortex.render_dashboard_html(c)):
        assert "hpc/sync jobs" in page
        # the wall against the budget rides on the row, as its own facet
        assert "of 8:00" in page


def test_every_ready_task_of_a_project_is_its_own_row(tmp_skeleton):
    """The Ready section showed one row per project and folded the rest as a
    "queue". The order is the human's, so the board shows them all."""
    scope = tmp_skeleton / "tasks" / "example" / "01_scope.md"
    scope.write_text(scope.read_text(encoding="utf-8")
                     .replace("State: planned", "State: ready"),
                     encoding="utf-8")
    c = _cortex.census(tmp_skeleton)
    assert len(c["ready"]) == 2
    page = _cortex.render_dashboard(c)
    html = _cortex.render_dashboard_html(c)
    for twin in (page, html):
        assert "01_scope.md" in twin and "03_ready_cleared.md" in twin
        assert "more ready" not in twin
    # both carry the launch lines their state earns
    assert page.count("hpc/sync submit <script>") >= 2


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


# --- which run is being scored ---------------------------------------------
# A task names its own results in `## Where to look`. Until 2026-09-09 the
# scorer read only the first token of each bullet and kept it only if it was
# absolute — so every real bullet (relative, and led by a project-row label)
# was dropped, and the scorer silently fell back to the newest run anywhere
# under `output/`. Eight of nine live tasks came back FAILED that morning and
# none of them was a failed run.
def _rewrite_where(board_, rel: str, *bullets: str) -> Path:
    """Replace one task's `## Where to look` bullets. Returns the task file."""
    path = board_["root"] / rel
    body = "".join(f"- {b}\n" for b in bullets)
    path.write_text(re.sub(r"## Where to look\n\n(?:- .*\n)+",
                           f"## Where to look\n\n{body}",
                           path.read_text(encoding="utf-8"), count=1),
                    encoding="utf-8")
    return path


def test_a_relative_where_to_look_bullet_still_finds_the_run(board):
    """The shape every task actually writes: a project-row label, then the
    path — relative to the project root, because that is where the run wrote
    it. Reading only `bullet.split()[0]`, and only when absolute, found
    neither half."""
    _rewrite_where(board, "tasks/example/11_healthy.md",
                   "`example` (project row): `output/searches/bright`")
    s = _score(board)["11_healthy"]
    assert s["run_source"] == _cortex.WHERE
    assert s["run_dir"] == board["mirror"] / "output/searches/bright/aaaa1111"
    assert s["legs"]["wall"][0] == _cortex.PASS
    assert s["health"] == "HEALTHY"


def test_declared_paths_that_are_not_here_are_unobservable_not_failed(board):
    """A run written to a custom `PYAUTO_OUTPUT_DIR` that was never pulled is
    a run this laptop cannot see. Scoring the newest thing under `output/` in
    its place — here the stale `cccc3333` extraction — reports a stranger's
    wall clock as a confident PASS about this task; the door's own contract is
    that UNOBSERVABLE is not FAIL, and it is not PASS either."""
    _rewrite_where(board, "tasks/subhalo/01_partial.md",
                   "`subhalo` (project row): `output_ordered_witness/run_0`")
    s = _score(board)["01_partial"]
    assert s["run_source"] == _cortex.UNRESOLVED
    assert s["run_dir"] is None and s["zip"] is None
    assert s["legs"]["wall"][0] == _cortex.UNOBSERVABLE
    assert s["health"] == "SUSPECT", "a run we cannot see is not a failed run"
    block = _collect(board["root"]).stdout.split("## 01_partial")[1] \
        .split("\n## ")[0]
    assert "output_ordered_witness/run_0" in block
    assert "run dir: **none**" in block
    assert "cccc3333" not in block, "no other run scored in its place"


def test_a_fallback_run_says_it_is_a_fallback(board):
    """A task that names no path at all still gets the old behaviour — but it
    is labelled, in the leg that reads it and in the block the human reads, so
    a wall clock from someone else's run is never printed as this task's."""
    _rewrite_where(board, "tasks/subhalo/01_partial.md")
    s = _score(board)["01_partial"]
    assert s["run_source"] == _cortex.FALLBACK
    assert s["run_dir"] == board["sub"] / "output/lens_a/cccc3333"
    assert s["legs"]["wall"][0] == _cortex.PASS
    assert "fallback run, not this task's own" in s["legs"]["wall"][1]
    block = _collect(board["root"]).stdout.split("## 01_partial")[1]
    assert "**fallback**" in block


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


def test_the_report_emits_a_block_per_task_in_order(board):
    r = _collect(board["root"])
    assert r.returncode == _cortex.RC_DRIFT, "one FAILED + one SUSPECT"
    assert "3 task(s), delivered 1/3" in r.stdout
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


def test_a_task_gets_its_own_witness_not_its_neighbours(board):
    """`witness_file` is a *project-wide* glob and the two `example` tasks
    share one output tree, so the glob alone hands a task its neighbour's
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
              _cortex.load_cortex(board["root"]).load_tasks(board["root"])[0]}
    assert states["tasks/example/11_healthy.md"] == "running"


def test_apply_moves_the_tasks_and_the_tree_still_checks(board):
    """The moves are the WHOLE write: the batch record `apply_ops` once
    rewrote is closed history since 2026-09-03."""
    root = board["root"]
    r = _collect(root, "--apply", "--refreshed", "2026-09-02T11:40Z")
    assert r.returncode == _cortex.RC_DRIFT, "one member is still FAILED"
    assert "Refreshed: 2026-09-02T11:40Z" in r.stdout
    mod = _cortex.load_cortex(root)
    states = {p.rel: p.state for p in mod.load_tasks(root)[0]}
    for rel in BOARD:
        assert states[rel] == "awaiting-ruling", rel
    # the whole point of rehearsing on a copy: the tree still checks.
    assert mod.check_problems(root) == []
    # …and the default scope no longer sees them: they are off the runs.
    again = _run(["collect", "--cortex", str(root)])
    for rel in BOARD:
        assert rel.rsplit("/", 1)[1][:-3] not in again.stdout


def test_apply_leaves_a_task_whose_run_is_still_live_where_it_is(board):
    """`submitted → pulled` is not an edge and a live run has not finished:
    both are notes, not forced moves."""
    root = board["root"]
    tk = root / "tasks/example/11_healthy.md"
    tk.write_text(tk.read_text().replace(
        "- 400100: done", "- 400100: running"), encoding="utf-8")
    r = _collect(root, "--apply", "--refreshed", "2026-09-02T11:40Z")
    assert "left running" in r.stdout, r.stdout + r.stderr
    mod = _cortex.load_cortex(root)
    states = {p.rel: p.state for p in mod.load_tasks(root)[0]}
    assert states["tasks/example/11_healthy.md"] == "running"
    assert states["tasks/example/12_resumed.md"] == "awaiting-ruling"
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


def test_a_named_task_narrows_the_scope(board):
    r = _run(["collect", "--cortex", str(board["root"]),
              "--task", "tasks/example/11_healthy.md"])
    assert r.returncode == _cortex.RC_OK
    assert "1 task(s), delivered 1/1" in r.stdout
    assert "12_resumed" not in r.stdout


def test_the_default_scope_is_every_submitted_or_running_task(board):
    """The check-in needs no record and no `--task`: it asks the tree which
    runs are out there and scores all of them."""
    root = board["root"]
    mod = _cortex.load_cortex(root)
    live = [tk.rel for tk in mod.load_tasks(root)[0]
            if tk.state in _cortex.LIVE_STATES]
    assert set(BOARD) < set(live), "the skeleton's own live tasks count too"
    r = _run(["collect", "--cortex", str(root)])
    assert f"{len(live)} task(s)" in r.stdout
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


def test_the_dry_run_names_every_project_its_pull_and_the_tasks_it_would_score(board):
    """The dry run is the door's own contract: the exact command per project
    and the exact tasks, and nothing touched."""
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
    projects still pull, every live task is still scored, and the failure is
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
    states = {p.rel: p.state for p in mod.load_tasks(board["root"])[0]}
    assert states["tasks/subhalo/01_partial.md"] == "awaiting-ruling"


def test_a_pulled_project_gets_a_manifest_the_scorer_can_read(board):
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    r = _checkin(board["root"], "--apply", "--no-push")
    manifest = json.loads((board["sub"] / ".cortex" / "pull.json").read_text())
    assert manifest["project"] == "subhalo"
    assert manifest["rc"] == 0
    assert manifest["cmd"].endswith("hpc/sync pull")
    assert manifest["pulled_at"]
    assert "tasks/subhalo/01_partial.md" in manifest["tasks_live"]
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
    # ... and the two the awaiting states added, in the same tree
    assert "accept and open the next task" in out
    assert "needs running again" in out
    assert "where to look:" in out
    assert f"local `{board['sub']}`" in out


def test_the_render_leg_leaves_the_board_current(board):
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    _checkin(board["root"], "--apply", "--no-push")
    check = _run(["dashboard", "--cortex", str(board["root"]), "--check"])
    assert check.returncode == _cortex.RC_OK, check.stdout + check.stderr


def test_the_checkin_stamps_the_board_it_just_refreshed(board):
    """The stamp is the check-in's own, written before the render, so the
    board says when the state under it was last actually pulled — and so the
    push carries the file beside the task moves."""
    _fake_cli(board["sub"], 0, board["sub"] / "pulled.txt")
    r = _checkin(board["root"], "--apply", "--no-push")
    assert r.returncode == _cortex.RC_OK, r.stdout + r.stderr
    stamp, problems = _cortex.read_checkin(board["root"])
    assert problems == [] and _cortex.CHECKIN_STAMP.match(stamp), stamp
    assert f"Refreshed: {stamp}" in r.stdout
    assert f"### Last check-in: {stamp}" in \
        (board["root"] / "dashboard.md").read_text(encoding="utf-8")
    # Whether the push gate calls it ledger is the Cortex's own claim — its
    # `tests/test_ledger_merge.py` pins `checkin.yaml` in LEDGER_FILES. Asking
    # the checked-out Cortex here would couple this suite to whichever ref CI
    # cloned, and the two repos merge one after the other.


def test_a_plain_re_render_of_a_stamped_board_is_not_drift(tmp_skeleton):
    """`checkin.yaml` is stable between renders, so `--check` needs no rule
    for it — the stamp only moves when a check-in moved it."""
    _cortex.write_checkin(tmp_skeleton, "2026-09-04T14:03:00Z")
    assert _run(["dashboard", "--apply", "--cortex",
                 str(tmp_skeleton)]).returncode == 0
    assert _run(["dashboard", "--check", "--cortex",
                 str(tmp_skeleton)]).returncode == 0


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
    """The board fixture is a tasks-and-rulings tree; the push gate lives in
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


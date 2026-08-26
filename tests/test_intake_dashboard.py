"""Contract tests for `intake dashboard` — the PyAutoMind task page.

The dashboard is the one Mind surface a human reads *away from a terminal*
(GitHub web, or a phone), so its failures are rendering failures rather than
crashes: a page that silently swallows itself, a link pointing at prose, a
"status" that reports conception state as if it were live state. Each test here
drives an input that produced one of those.

Hermetic: every fixture is a fictional Mind in tmp_path, so the assertions are
about the renderer, not about whatever backlog happens to be checked out.
"""

import importlib.util
import re
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_intake_dashboard_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_dashboard_under_test"] = _intake
_spec.loader.exec_module(_intake)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _prompt(title, difficulty="medium", autonomy="supervised", priority="normal",
            status="formalised"):
    return (f"# {title}\n\nType: feature\nTarget: widgets\n"
            f"Difficulty: {difficulty}\nAutonomy: {autonomy}\n"
            f"Priority: {priority}\nStatus: {status}\n\nBody prose.\n")


def _mind(root: Path, drafts=None, active=None, registries=None,
          complete=None) -> Path:
    for rel, body in (drafts or {}).items():
        p = root / "draft" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for rel, body in (complete or {}).items():
        p = root / "complete" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for name, body in (active or {}).items():
        p = root / "active" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for name, body in (registries or {}).items():
        (root / name).write_text(body, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _page(mind: Path) -> str:
    return _intake.render_dashboard(_intake.census(mind))


# --------------------------------------------------------------------------- #
# picking: the top of the page answers "what should I do now?"
# --------------------------------------------------------------------------- #
def test_start_here_leads_with_high_priority_smallest_first(tmp_path):
    mind = _mind(tmp_path, drafts={
        "feature/widgets/later.md": _prompt("Later thing", priority="low"),
        "feature/widgets/huge.md": _prompt("Huge urgent thing",
                                           difficulty="too-large", priority="high"),
        "feature/widgets/tiny.md": _prompt("Tiny urgent thing",
                                           difficulty="small", priority="high"),
    })
    page = _page(mind)
    head = page.split("## In flight")[0]
    assert head.index("Tiny urgent thing") < head.index("Huge urgent thing"), \
        "high-priority picks must be sorted smallest-first"
    assert "Later thing" not in head, "a low-priority prompt is not a pick"


def test_quick_wins_are_small_and_safe_only(tmp_path):
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Small and safe", difficulty="small",
                                        autonomy="safe"),
        "feature/widgets/b.md": _prompt("Small but supervised", difficulty="small",
                                        autonomy="supervised"),
        "feature/widgets/c.md": _prompt("Safe but large", difficulty="large",
                                        autonomy="safe"),
    })
    quick = _page(mind).split("**Quick wins**")[1].split("## In flight")[0]
    assert "Small and safe" in quick
    assert "Small but supervised" not in quick
    assert "Safe but large" not in quick


def test_every_backlog_prompt_is_one_collapsed_row_not_a_wide_table(tmp_path):
    """Wide tables scroll sideways on a phone; rows wrap. Pin the shape: one
    `<details>` per task whose summary is `📋 <linked title> — facets`."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one"),
        "feature/widgets/two.md": _prompt("Feature two"),
    })
    page = _page(mind)
    backlog = page.split("## Backlog")[1]
    assert ('<details><summary>📋 <a href="draft/bug/widgets/one.md">'
            "Bug one</a> — ") in backlog
    assert '<a href="draft/feature/widgets/two.md">Feature two</a>' in backlog
    # The only table on the page is the 2-column where/count summary.
    assert backlog.count("|") == 0, "the backlog must not render as tables"
    assert "<summary><b>bug</b> — 1</summary>" in backlog, \
        "long sections must be collapsible"


# --------------------------------------------------------------------------- #
# in flight: the issue link is the registry's, and the status is live
# --------------------------------------------------------------------------- #
# The issue URLs are deliberately synthetic (ExampleOrg/Widgets): the dashboard
# regex captures whole URLs and never inspects the owner, so a real GitHub
# owner here would be an instance fact in organ code — the tenant firewall's
# concern (PyAutoMind/scripts/repos_sync.py) — for no test value.
ACTIVE_MD = """# Active Tasks

## widget-rework
- issue: https://github.com/ExampleOrg/Widgets/issues/42 (opened after the spike)
- status: library-dev — branch pushed, awaiting review
- prompt: active/widget_rework.md
"""


def test_in_flight_links_the_registry_issue_and_its_live_status(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework")},
                 registries={"active.md": ACTIVE_MD})
    flight = _page(mind).split("## In flight")[1].split("## Parked")[0]
    assert ('<a href="https://github.com/ExampleOrg/Widgets/issues/42">'
            "issue #42</a>") in flight, \
        "the link must be the matched URL, not the field's trailing prose"
    assert "(opened after the spike)" not in flight
    assert "library-dev" in flight
    assert "formalised" not in flight, \
        "a prompt's conception-time Status: is stale once issued — never show it"


def test_parked_prompt_still_in_active_is_not_listed_in_flight(tmp_path):
    """A parked task's prompt file legitimately stays in active/ (parked.md
    holds started-then-parked work), so the in-flight list must exclude it —
    otherwise the same task renders under BOTH In flight and Parked and the
    in-flight count inflates with tasks deliberately not in flight."""
    mind = _mind(
        tmp_path,
        active={"widget_rework.md": _prompt("Widget rework"),
                "gadget_polish.md": _prompt("Gadget polish")},
        registries={
            "active.md": ("# Active\n\n## gadget-polish\n"
                          "- prompt: active/gadget_polish.md\n"),
            "parked.md": ("# Parked\n\n## widget-rework\n"
                          "- prompt: active/widget_rework.md\n"
                          "- parked: deliberate deferral\n"),
        },
    )
    page = _page(mind)
    flight = page.split("## In flight")[1].split("## Parked")[0]
    assert "gadget_polish.md" in flight
    assert "widget_rework.md" not in flight, \
        "a parked prompt must not double-list as in flight"
    parked = page.split("## Parked")[1].split("## Planned")[0]
    assert "widget_rework.md" in parked
    assert "| [In flight](#in-flight) (`active/`) | 1 |" in page


def test_in_flight_prompt_with_no_registry_row_claims_no_issue(tmp_path):
    """Silence beats a wrong link: prose issue URLs are usually cross-references."""
    body = _prompt("Orphan task") + \
        "\nFollow-up to https://github.com/ExampleOrg/Widgets/issues/7 (unrelated).\n"
    mind = _mind(tmp_path, active={"orphan.md": body})
    flight = _page(mind).split("## In flight")[1].split("## Parked")[0]
    assert "Orphan task" in flight
    assert "issues/7" not in flight


def test_registry_entry_without_fields_still_lists(tmp_path):
    mind = _mind(tmp_path, registries={"parked.md": "# Parked\n\n## lonely-slug\n"})
    parked = _page(mind).split("## Parked")[1].split("## Planned")[0]
    assert "<b>lonely-slug</b>" in parked


# --------------------------------------------------------------------------- #
# copy blocks: every task row's 📋 toggle hides a paste-ready message
# --------------------------------------------------------------------------- #
def test_backlog_and_picks_carry_a_start_dev_copy_block(tmp_path):
    """GitHub's copy button lives on fenced code blocks — the one clipboard a
    static page has, and the whole point of the row's hidden body on a phone."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one", priority="high")})
    page = _page(mind)
    fence = "```\n/start_dev draft/bug/widgets/one.md\n```"
    head, backlog = page.split("## In flight")[0], page.split("## Backlog")[1]
    assert fence in head and "<details><summary>📋 " in head, \
        "the Start-here picks must carry the copy block"
    assert fence in backlog and "<details><summary>📋 " in backlog, \
        "backlog rows must carry the copy block"


def test_task_row_is_one_line_with_no_repeated_label(tmp_path):
    """The 📋 toggle rides at the left of the task text on the SAME line —
    an extra 'copy for Claude' line per task doubled the page's height."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one", priority="high")})
    page = _page(mind)
    assert "copy for Claude" not in page
    assert ('<details><summary>📋 <a href="draft/bug/widgets/one.md">'
            "Bug one</a>") in page, \
        "the summary line must open with 📋 then the task text"


def test_in_flight_copy_block_targets_the_active_prompt(tmp_path):
    mind = _mind(tmp_path, active={"widget_rework.md": _prompt("Widget rework")})
    flight = _page(mind).split("## In flight")[1].split("## Parked")[0]
    assert "\n/start_dev active/widget_rework.md\n" in flight


def test_registry_row_copy_block_prefers_its_prompt_path(tmp_path):
    """A parked row naming its prompt gets `/start_dev`; a bare slug has no
    start_dev target, so it routes as free prose instead."""
    mind = _mind(tmp_path, registries={"parked.md": (
        "# Parked\n\n## with-prompt\n- prompt: active/widget_rework.md\n"
        "\n## lonely-slug\n")})
    parked = _page(mind).split("## Parked")[1].split("## Planned")[0]
    assert "\n/start_dev active/widget_rework.md\n" in parked
    assert ("\n/route resume the parked PyAutoMind task lonely-slug — "
            "its record is in parked.md\n") in parked


def test_copy_details_never_swallow_the_next_row(tmp_path):
    """GitHub's renderer treats lines after `</details>` as raw HTML until a
    blank line — a row directly beneath one would vanish from the page."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one"),
        "bug/widgets/two.md": _prompt("Bug two"),
    }, active={"a.md": _prompt("A"), "b.md": _prompt("B")})
    page = _page(mind)
    assert "</details>\n<details>" not in page
    assert "</details>\n-" not in page


# --------------------------------------------------------------------------- #
# the HTML twin: real one-tap copy buttons, served by GitHub Pages
# --------------------------------------------------------------------------- #
# The org is fictional for the same tenant-firewall reason as the issue URLs:
# renderers read the GitHub home from repos.yaml, never from organ code.
REPOS_YAML = "repos:\n  PyAutoMind:\n    github: ExampleOrg/PyAutoMind\n"


def _html(mind: Path) -> str:
    return _intake.render_dashboard_html(_intake.census(mind))


def test_html_task_has_a_copy_button_holding_the_command(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    html = _html(mind)
    assert ('<button class="copy" data-cmd="/start_dev '
            'draft/bug/widgets/one.md"') in html
    assert "navigator.clipboard.writeText" in html, \
        "the page must carry its own clipboard script — that is its point"


def test_html_links_use_the_github_home_from_repos_yaml(tmp_path):
    """Pages serves the file away from the repo blobs, so links must be
    absolute — and the org comes from repos.yaml, never organ code."""
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")},
                 registries={"repos.yaml": REPOS_YAML})
    html = _html(mind)
    assert ('<a href="https://github.com/ExampleOrg/PyAutoMind/blob/main/'
            'draft/bug/widgets/one.md">Bug one</a>') in html


def test_markdown_page_points_at_the_pages_twin_only_when_home_known(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")},
                 registries={"repos.yaml": REPOS_YAML})
    assert "https://exampleorg.github.io/PyAutoMind/" in _page(mind)
    bare = _mind(tmp_path / "bare", drafts={"bug/widgets/x.md": _prompt("X")})
    assert "github.io" not in _page(bare), \
        "a Mind without repos.yaml must not invent a Pages link"


def test_check_covers_the_html_twin(tmp_path, capsys):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    assert _intake.main(["--mind", str(mind), "--apply", "dashboard"]) == 0
    html = mind / "dashboard.html"
    html.write_text(
        html.read_text(encoding="utf-8").replace("Bug one", "Bug gone"),
        encoding="utf-8")
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 1
    assert "dashboard.html" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# rendering safety
# --------------------------------------------------------------------------- #
def test_a_prompt_titled_with_an_html_comment_cannot_swallow_the_page(tmp_path):
    """`_title` faithfully reports a leading `<!--`; unescaped it hides the rest."""
    mind = _mind(tmp_path, drafts={
        "triage/widgets/raw.md": "<!-- TRIAGE: needs manual review\n\nBody.\n",
        "feature/widgets/after.md": _prompt("Visible after the comment"),
    })
    page = _page(mind)
    assert "<!--" not in page.split("## Start here")[1]
    assert "Visible after the comment" in page


def test_a_long_title_is_cut_where_a_reader_can_stop(tmp_path):
    """A silent cut is indistinguishable from a title that just ends badly —
    the page read "kernel-CDF numba fast path (the" for months. Long titles
    now end on a real word and say that there was more."""
    # The plain cut would land on "... convolution kernels for".
    assert _intake._title(
        "Numba CPU likelihood phase 2 kernel-CDF numba fast path convolution "
        "kernels for the batched dataset"
    ) == "Numba CPU likelihood phase 2 kernel-CDF numba fast path convolution "\
         "kernels…"
    # An orphaned bracket goes with the fragment it opened.
    assert _intake._title(
        "Rectangular mesh split Bilinear fast CPU default versus RTU "
        "(advanced GPU backend variant)"
    ) == "Rectangular mesh split Bilinear fast CPU default versus RTU…"
    # An unpaired backtick would let the code span bleed into the page.
    assert _intake._title(
        "Give every fitted search a proper `seed today because no search can "
        "set it now"
    ) == "Give every fitted search a proper…"


def test_a_short_title_is_left_exactly_alone(tmp_path):
    assert _intake._title("Fix the mask edge case") == "Fix the mask edge case"
    assert not _intake._title("Fix the mask edge case").endswith("…")


def test_the_dashboard_row_shows_the_work_type(tmp_path):
    """The facet `draft/` is organised around, and the one the page never
    showed — carried as a glyph so colour stays reserved for judgement."""
    mind = _mind(tmp_path, drafts={"bug/widgets/b.md": _prompt("Bug one")})
    html = _intake.render_dashboard_html(_intake.census(mind))
    assert '<span class="pill w">🐛 bug</span>' in html


def test_title_markup_survives_the_html_summary(tmp_path):
    """Summaries are HTML: brackets pass through untouched, raw angle brackets
    are escaped, and a title's `code` span renders as <code> (GitHub does not
    process markdown inside <summary>)."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/b.md": _prompt("[JAX] `grad(x)` fails on x<0",
                                    priority="high")})
    page = _page(mind)
    assert ('<a href="draft/bug/widgets/b.md">'
            "[JAX] <code>grad(x)</code> fails on x&lt;0</a>") in page


# --------------------------------------------------------------------------- #
# --check: drift is content, not the calendar
# --------------------------------------------------------------------------- #
def test_check_ignores_the_generation_stamp_but_sees_content_drift(tmp_path, capsys):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    assert _intake.main(["--mind", str(mind), "--apply", "dashboard"]) == 0

    stale_stamp = (mind / "dashboard.md").read_text(encoding="utf-8").replace(
        "<!-- generated by", "<!-- generated by [1999-01-01 rerun]")
    (mind / "dashboard.md").write_text(stale_stamp, encoding="utf-8")
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 0, \
        "a re-render on an unchanged Mind is not drift"

    (mind / "draft" / "bug" / "widgets" / "two.md").write_text(
        _prompt("Bug two"), encoding="utf-8")
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 1
    assert "stale" in capsys.readouterr().err


def test_check_on_a_missing_dashboard_is_drift(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 1


# --------------------------------------------------------------------------- #
# epics: long-running programmes resume from their ledger, not a paired issue
# --------------------------------------------------------------------------- #
_EPICS = """# Epics

## jax-profiling
- title: JAX inference programme
- ledger: widgets/results/notes/inference/PROGRAMME.md
- notes: slices ship as widgets issues/PRs, not Mind prompts

## bare-epic
"""


def test_epics_section_sits_at_the_bottom_with_a_resume_prompt(tmp_path):
    """Epics group at the bottom — after the Backlog, so members and their
    programme read as one unit rather than scattering through the page."""
    mind = _mind(tmp_path, registries={"epics.md": _EPICS})
    page = _page(mind)
    assert page.index("## Backlog") < page.index("## Epics")
    epics = page.split("## Epics")[1]
    assert "JAX inference programme" in epics
    assert "PROGRAMME.md" in epics
    # The copy payload is a procedure — work out the state, then continue.
    assert "work out the last completed phase" in epics
    assert "/start_dev" in epics
    # A slug-only entry still lists (tolerant, like the other registries).
    assert "bare-epic" in epics


def _epic_prompt_body(title, epic, phase=None, priority="high"):
    phase_line = f"Phase: {phase}\n" if phase is not None else ""
    return (f"# {title}\n\nType: feature\nTarget: widgets\n"
            f"Difficulty: medium\nAutonomy: supervised\nPriority: {priority}\n"
            f"Status: formalised\nEpic: jax-profiling\n{phase_line}\nBody.\n")


def test_epic_members_leave_the_pick_lists_and_work_type_sections(tmp_path):
    """An `Epic:` member must be workable only through its epic — never
    pickable standalone from Start here or a work-type dropdown, whatever its
    priority says."""
    mind = _mind(tmp_path, registries={"epics.md": _EPICS}, drafts={
        "feature/widgets/phase_two.md": _epic_prompt_body("Phase two", "jax-profiling", 2),
        "feature/widgets/phase_one.md": _epic_prompt_body("Phase one", "jax-profiling", 1),
        "feature/widgets/loner.md": _prompt("Standalone thing", priority="high"),
    })
    page = _page(mind)
    epics_at = page.index("## Epics")
    body, epics = page[:epics_at], page[epics_at:]
    assert "Phase one" not in body and "Phase two" not in body
    assert "Standalone thing" in body
    # Grouped under the epic, phase order, with the resume prompt first and
    # the start-in-order caution present.
    assert epics.index("work out the last completed phase") \
        < epics.index("Phase one") < epics.index("Phase two")
    assert "2 queued prompt(s), in order" in epics
    assert "in order through the epic" in epics
    # The Backlog header points at where the members went.
    assert "belong to an epic" in body


def test_phaseless_members_sort_after_phased_by_filename(tmp_path):
    mind = _mind(tmp_path, registries={"epics.md": _EPICS}, drafts={
        "feature/widgets/b_unphased.md": _epic_prompt_body("B unphased", "jax-profiling"),
        "feature/widgets/a_unphased.md": _epic_prompt_body("A unphased", "jax-profiling"),
        "feature/widgets/last_phase.md": _epic_prompt_body("The phased one", "jax-profiling", 7),
    })
    epics = _page(mind).split("## Epics")[1]
    assert epics.index("The phased one") < epics.index("A unphased") \
        < epics.index("B unphased")


def test_a_member_of_an_unregistered_epic_still_groups_loudly(tmp_path):
    """A typo'd or unfiled slug must not silently return the member to the
    standalone backlog — it groups under the stray slug with a warning."""
    body = _prompt("Orphan phase").replace("Status: formalised",
                                           "Status: formalised\nEpic: no-such-epic")
    mind = _mind(tmp_path, drafts={"feature/widgets/orphan.md": body})
    page = _page(mind)
    assert "## Epics" in page
    epics = page.split("## Epics")[1]
    assert "Orphan phase" in epics and "not in `epics.md`" in epics
    assert "Orphan phase" not in page.split("## Epics")[0]


# --------------------------------------------------------------------------- #
# drift: a fixed-but-never-advanced draft must not masquerade as backlog
# --------------------------------------------------------------------------- #
def test_a_draft_recording_a_fix_pr_is_flagged_for_reconciliation(tmp_path):
    body = _prompt("Numba-style bug") + \
        "\n## Root cause\n\nFix: @PyAutoThing PR #456 (branch x) — merged.\n"
    mind = _mind(tmp_path, drafts={"bug/widgets/fixed_bug.md": body})
    page = _page(mind)
    assert "Needs lifecycle reconciliation" in page
    assert "bug/widgets/fixed_bug.md" in page.split("## Start here")[0]


def test_a_prompt_merely_citing_a_pr_is_not_drift(tmp_path):
    body = _prompt("Cites context") + \
        "\nBackground: superseded by workspace PR #60, see also pull/152.\n"
    mind = _mind(tmp_path, drafts={"bug/widgets/cites.md": body})
    assert "Needs lifecycle reconciliation" not in _page(mind)


def test_a_draft_whose_own_status_says_shipped_is_flagged(tmp_path):
    """The commonest way a finished task keeps advertising itself as backlog:
    the shipping session writes the outcome into the prompt's `Status:` header
    and leaves the file in `draft/`."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/done.md": _prompt("Already fixed",
                                       status="shipped 2026-08-24 (#277)")})
    page = _page(mind)
    assert "Needs lifecycle reconciliation" in page
    head = page.split("## Start here")[0]
    assert "bug/widgets/done.md" in head and "shipped" in head


def test_superseded_and_absorbed_statuses_are_drift_too(tmp_path):
    for status in ("superseded by the epic", "ABSORBED 2026-08-10", "retired"):
        mind = _mind(tmp_path / status.split()[0],
                     drafts={"bug/widgets/x.md": _prompt("Spent", status=status)})
        assert "Needs lifecycle reconciliation" in _page(mind), status


def test_a_partly_shipped_status_is_not_drift(tmp_path):
    """A tracker reporting *some* phases shipped is still live work — only a
    status that OPENS on a done-word means the prompt itself is spent."""
    for status in ("phases 1-3 SHIPPED; phase 4 open",
                   "split (phases 1-2 SHIPPED 2026-08-23; phase 3 open)",
                   "in progress — core landed, real-data swap-in remains"):
        mind = _mind(tmp_path / status.split()[0],
                     drafts={"bug/widgets/x.md": _prompt("Live", status=status)})
        assert "Needs lifecycle reconciliation" not in _page(mind), status


# --------------------------------------------------------------------------- #
# freshness: the page says how current it is, and hands over its own refresh
# --------------------------------------------------------------------------- #
def test_the_page_states_when_it_was_generated_and_why_that_can_lie(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    c = _intake.census(mind)
    page = _intake.render_dashboard(c)
    banner = page.split("| Where | Count |")[0]
    assert f"Last updated {c['generated']}" in banner
    # the distinction that matters: a self-healing render is not a fresh backlog
    assert "dashboard_refresh.yml" in banner and "stale prompt" in banner


def test_the_refresh_banner_is_a_copyable_instruction_not_a_bare_command(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    banner = _page(mind).split("| Where | Count |")[0]
    assert "📋" in banner, "the banner uses the same one-tap idiom as a task row"
    for step in ("lifecycle.py record", "git pull --ff-only",
                 "pyauto-brain intake --apply dashboard"):
        assert step in banner, step
    assert "never hand-edit" in banner.lower()


def test_the_html_twin_carries_the_banner_with_a_real_copy_button(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    c = _intake.census(mind)
    html = _intake.render_dashboard_html(c)
    fresh = html.split('<div class="fresh">')[1].split("</div>")[0]
    assert f"Last updated {c['generated']}" in fresh
    assert 'button class="copy"' in fresh and "data-cmd=" in fresh
    # backticks are markdown; the blurb must render them as code spans, while
    # the copy payload keeps its own verbatim (see _prose)
    assert "<code>draft/</code>" in _prose(fresh) and "`draft/`" not in _prose(fresh)
    assert "`git pull --ff-only`" in fresh, "the payload is copied, not rendered"
    assert ".fresh{" in html, "the banner ships its own rule, not the shared theme"


def test_no_epics_file_means_no_epics_section(tmp_path):
    page = _page(_mind(tmp_path, active={"one.md": _prompt("Solo task")}))
    assert "## Epics" not in page, "a spawned Mind without epics.md stays clean"


def test_html_sections_link_their_markdown_source(tmp_path):
    mind = _mind(tmp_path, registries={"epics.md": _EPICS,
                                       "repos.yaml": REPOS_YAML})
    html = _html(mind)
    for src in ("active.md", "epics.md", "parked.md", "planned.md"):
        assert f'/blob/main/{src}">markdown version</a>' in html, src
    assert '/tree/main/draft">markdown version</a>' in html


# --------------------------------------------------------------------------- #
# recent: the one section laid out by date rather than by state
# --------------------------------------------------------------------------- #
def _record(slug, date):
    return f"## {slug}\n- completed: {date}\n- summary: it shipped.\n"


def _recent_mind(root, n_records=0, month="08"):
    """A Mind with one task in each live state plus `n_records` completions."""
    return _mind(
        root,
        active={"sprocket_calibration.md": _prompt("Sprocket calibration")},
        complete={f"2026/{month}/shipped-{i:02d}.md": _record(f"shipped-{i:02d}",
                                                              f"2026-{month}-2{i % 10}")
                  for i in range(n_records)},
        registries={
            "active.md": "## sprocket-calibration\n- issued: 2026-08-19\n"
                         "- prompt: active/sprocket_calibration.md\n",
            "parked.md": "## flywheel-balance\n- parked: 2026-08-18 — deferred\n",
            "planned.md": "## gearbox-survey\n- filed: 2026-07-01\n",
        })


def test_recent_merges_every_live_state_into_one_dated_feed(tmp_path):
    """Recency is orthogonal to state, so it is the one question no other
    section on the page can answer."""
    page = _page(_recent_mind(tmp_path))
    recent = page.split("## Recent")[1]
    for slug in ("Sprocket calibration", "flywheel-balance", "gearbox-survey"):
        assert slug in recent
    assert "| Date | Event | Task |" in recent


def test_shipped_work_is_not_in_the_feed(tmp_path):
    """The `complete/` ledger is a thousand records deep and ships ~200 a
    month, so including it made this a list of receipts — twenty things nobody
    can act on, on the page whose whole job is work in hand."""
    mind = _recent_mind(tmp_path, n_records=40)
    rows = _intake.census(mind)["recent"]
    assert len(rows) == 3
    assert not any("shipped" in r["title"] for r in rows)
    assert "shipped-00" not in _page(mind)


def test_the_complete_ledger_is_never_opened(tmp_path):
    """Not merely filtered out afterwards — a 20-row table of live work must
    not read a thousand records to render."""
    assert not hasattr(_intake, "completed_records")
    assert "completed" not in _intake.census(_recent_mind(tmp_path, n_records=5))


def test_recent_names_the_event_each_date_records(tmp_path):
    """A bare date says nothing; `parked` / `issued` / `filed` says what
    happened — the whole reason the registry key is the event name."""
    rows = _intake.census(_recent_mind(tmp_path))["recent"]
    assert {r["title"]: r["event"] for r in rows} == {
        "Sprocket calibration": "issued",
        "flywheel-balance": "parked",
        "gearbox-survey": "filed",
    }


def test_recent_is_newest_first(tmp_path):
    rows = _intake.census(_recent_mind(tmp_path))["recent"]
    assert [r["date"] for r in rows] == sorted(
        (r["date"] for r in rows), reverse=True)


def test_recent_sits_after_the_backlog_and_before_the_epics(tmp_path):
    mind = _recent_mind(tmp_path)
    (mind / "epics.md").write_text(_EPICS, encoding="utf-8")
    page = _page(mind)
    assert page.index("## Backlog") < page.index("## Recent") < page.index("## Epics")


def test_an_undated_task_is_absent_rather_than_sorted_to_the_bottom(tmp_path):
    """`lifecycle.py dates` is where a missing date gets reported; padding the
    feed with unknowns would bury the answer it exists to give."""
    mind = _mind(tmp_path, registries={
        "planned.md": "## gearbox-survey\n- status: planned\n"})
    assert _intake.census(mind)["recent"] == []
    assert "## Recent" not in _page(mind)


def test_recent_links_a_registry_row_to_its_own_entry_not_the_file_top(tmp_path):
    """parked.md is long enough that landing at its top is not the same as
    landing on the task."""
    page = _page(_recent_mind(tmp_path))
    assert 'href="parked.md#flywheel-balance"' in page


def test_an_in_flight_prompt_can_be_dated_by_its_own_header(tmp_path):
    """The prompt's `Issued:` header is its own copy of the registry date, so
    an orphan (no row claims it) still dates rather than dropping out."""
    body = _prompt("Sprocket calibration").replace(
        "Status: formalised", "Status: formalised\nIssued: 2026-08-19")
    rows = _intake.census(
        _mind(tmp_path, active={"sprocket_calibration.md": body}))["recent"]
    assert [(r["date"], r["event"]) for r in rows] == [("2026-08-19", "issued")]


def test_a_registry_date_beats_the_prompts_own_copy(tmp_path):
    """The registry row is the live record; the header is the fallback."""
    body = _prompt("Sprocket calibration").replace(
        "Status: formalised", "Status: formalised\nIssued: 2026-07-01")
    mind = _mind(tmp_path, active={"sprocket_calibration.md": body},
                 registries={"active.md": "## sprocket-calibration\n"
                                          "- issued: 2026-08-19\n"
                                          "- prompt: active/sprocket_calibration.md\n"})
    assert _intake.census(mind)["recent"][0]["date"] == "2026-08-19"


def test_a_date_in_another_fields_prose_does_not_count_as_a_date(tmp_path):
    """`- issue: …/1501 (issued 2026-08-19)` is the un-parseable habit the
    convention replaced — reading it back would re-legitimise it."""
    mind = _mind(tmp_path, registries={
        "planned.md": "## gearbox-survey\n"
                      "- issue: https://example.invalid/issues/1 (filed 2026-08-19)\n"})
    assert _intake.census(mind)["recent"] == []


def test_the_html_twin_carries_the_same_feed_with_real_copy_buttons(tmp_path):
    html = _intake.render_dashboard_html(_intake.census(_recent_mind(tmp_path)))
    assert "<h2>Recent" in html
    assert html.index("Backlog") < html.index("<h2>Recent") < html.index("<h2>Epics") \
        if "<h2>Epics" in html else True
    assert '<table class="recent">' in html
    assert 'data-cmd="/start_dev active/sprocket_calibration.md"' in html


def test_a_live_row_wears_its_date_where_the_task_is(tmp_path):
    """A status line reads very differently against a row issued yesterday
    than against one issued in May, so the date rides on the row too — not
    only down in the Recent feed."""
    page = _page(_recent_mind(tmp_path))
    flight = page.split("## In flight")[1].split("## Parked")[0]
    assert "issued 2026-08-19" in flight
    assert "parked 2026-08-18" in page.split("## Parked")[1].split("## Planned")[0]
    assert "filed 2026-07-01" in page.split("## Planned")[1].split("## Backlog")[0]


def test_an_undated_row_gets_no_placeholder(tmp_path):
    """`lifecycle.py dates` reports the gap; the page must not invent one."""
    mind = _mind(tmp_path, active={"sprocket_calibration.md": _prompt("Sprocket")},
                 registries={"active.md": "## sprocket-calibration\n"
                                          "- prompt: active/sprocket_calibration.md\n"})
    row = _page(mind).split("## In flight")[1].split("<details>")[1]
    assert "—" not in row.split("</summary>")[0]


# --------------------------------------------------------------------------- #
# recent: fifty deep, ten on screen
# --------------------------------------------------------------------------- #
def _many(root, n):
    """A Mind whose planned.md holds `n` dated tasks, newest first by slug."""
    return _mind(root, registries={"planned.md": "".join(
        f"## task-{i:03d}\n- filed: 2026-01-01\n\n" for i in range(n))})


def test_the_feed_runs_deeper_than_the_page(tmp_path):
    """Fifty is what the feed HOLDS; ten is what it SHOWS."""
    rows = _intake.census(_many(tmp_path, 80))["recent"]
    assert len(rows) == _intake.RECENT_MAX == 50
    assert _intake.RECENT_PAGE == 10


def test_markdown_shows_one_page_then_nests_the_rest(tmp_path):
    """GitHub strips the JS the Pages twin uses, so the markdown page reveals
    with `<details>` — nested, so each tap shows the next page and leaves
    another one behind it."""
    page = _page(_many(tmp_path, 80))
    section = page.split("## Recent")[1]
    before = section.split("<details>")[0]
    assert before.count("| 2026-01-01 |") == 10
    assert section.count("<details>") == 4
    assert "… 10 more (40 left)" in section
    assert "… 10 more (10 left)" in section


def test_each_revealed_page_carries_its_own_table_header(tmp_path):
    """A markdown table cannot span an HTML block boundary — without a header
    per page the reveal is a headerless slab of pipes."""
    section = _page(_many(tmp_path, 80)).split("## Recent")[1]
    assert section.count("| Date | Event | Task |") == 5


def test_a_feed_that_fits_on_one_page_has_no_reveal(tmp_path):
    page = _page(_many(tmp_path, 6))
    section = page.split("## Recent")[1]
    assert "<details>" not in section
    assert "…" not in section
    assert "opens the next" not in section


def test_html_hides_the_overflow_rows_and_offers_a_button(tmp_path):
    html = _intake.render_dashboard_html(_intake.census(_many(tmp_path, 80)))
    section = html.split("<h2>Recent")[1]
    assert section.count("<tr>") == 10
    assert section.count("<tr hidden>") == 40
    assert '<button class="more" data-page="10">… 10 more (40 left)</button>' in section


def test_html_ships_every_row_so_a_reader_without_js_sees_the_feed(tmp_path):
    """Hidden, not absent: with JS off the whole feed is there rather than ten
    rows and a dead button."""
    html = _intake.render_dashboard_html(_intake.census(_many(tmp_path, 80)))
    section = html.split("<h2>Recent")[1]
    assert section.count("<tr") == 50


def _prose(html: str) -> str:
    """The page minus every copy payload.

    A `data-cmd` attribute is a clipboard literal — the message a human pastes
    into a Claude chat — so it legitimately carries markdown that the page must
    NOT render. Assertions about how the page *reads* have to exclude it.
    """
    return re.sub(r'data-cmd="[^"]*"', "data-cmd=\"\"", html)


def test_the_html_blurb_renders_its_code_spans(tmp_path):
    """The blurb is shared with the markdown page; its backticks would
    otherwise print literally here."""
    html = _prose(_intake.render_dashboard_html(_intake.census(_many(tmp_path, 80))))
    assert "<code>complete/index.md</code>" in html
    assert "`complete/index.md`" not in html


# --------------------------------------------------------------------------- #
# recent: the backlog is most of the work
# --------------------------------------------------------------------------- #
def test_a_dated_draft_is_in_the_feed(tmp_path):
    """The backlog is the largest pool of work the Mind holds, so a feed that
    skipped it saw almost none of what has been happening."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/sprocket.md":
            _prompt("Sprocket work").replace("Status: formalised",
                                             "Status: formalised\nFiled: 2026-08-20")})
    rows = _intake.census(mind)["recent"]
    assert [(r["date"], r["event"], r["title"]) for r in rows] == [
        ("2026-08-20", "filed", "Sprocket work")]
    assert rows[0]["payload"] == "/start_dev draft/feature/widgets/sprocket.md"


def test_an_undated_draft_stays_out(tmp_path):
    mind = _mind(tmp_path, drafts={"feature/widgets/sprocket.md": _prompt("S")})
    assert _intake.census(mind)["recent"] == []


def test_an_epic_member_is_not_offered_standalone_in_the_feed(tmp_path):
    """Members are worked in order through their epic — every other pick list
    on the page excludes them, and a Recent row hands out a `/start_dev`."""
    member = _epic_prompt_body("Phase one", "jax-profiling", phase=1).replace(
        "Status: formalised", "Status: formalised\nFiled: 2026-08-20")
    mind = _mind(tmp_path, registries={"epics.md": _EPICS},
                 drafts={"feature/widgets/phase_one.md": member,
                         "feature/widgets/loose.md":
                             _prompt("Loose end").replace(
                                 "Status: formalised",
                                 "Status: formalised\nFiled: 2026-08-21")})
    assert [r["title"] for r in _intake.census(mind)["recent"]] == ["Loose end"]


def test_issued_beats_filed_on_a_prompt_carrying_both(tmp_path):
    """An issued prompt keeps the `Filed:` it had as a draft; the later, more
    specific event is the one the feed reports."""
    body = _prompt("Sprocket").replace(
        "Status: formalised",
        "Status: formalised\nFiled: 2026-07-01\nIssued: 2026-08-19")
    rows = _intake.census(
        _mind(tmp_path, active={"sprocket.md": body}))["recent"]
    assert [(r["date"], r["event"]) for r in rows] == [("2026-08-19", "issued")]

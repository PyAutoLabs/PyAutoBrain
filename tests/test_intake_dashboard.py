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
    # The Backlog SECTION, not "everything after Backlog": Bundles renders a
    # members table directly below it (a bundle is a comparison of four rows,
    # not a 133-row pick list), and that table is not a backlog regression.
    backlog = page.split("## Backlog")[1].split("\n## ")[0]
    assert ('<details><summary>📋 <a href="draft/bug/widgets/one.md">'
            "Bug one</a> — ") in backlog
    assert '<a href="draft/feature/widgets/two.md">Feature two</a>' in backlog
    # No table in the backlog itself — a wide table is what this pins against.
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


# --------------------------------------------------------------------------- #
# bundles: several INDEPENDENT tasks in one orchestrated session
# --------------------------------------------------------------------------- #
# A bundle is the opposite of an epic. An epic is ordered and phase-gated, and
# its members are pulled out of every pick list; a bundle is a flat set whose
# members stay exactly where they were and gain a second, session-shaped view.
# Pinned bundles are the human record in `bundles.md`; auto bundles are computed
# at render time and never written anywhere — so these tests drive the renderer
# against a fixture Mind and assert on the page, never on a file.
_BUNDLES = """# Bundles

## euclid-tidy
- title: Euclid pipeline tidy-up
- members:
  - draft/feature/widgets/pinned_one.md
  - draft/feature/widgets/pinned_two.md
- rationale: same reviewer, same afternoon
- status: proposed 2026-08-27
"""


def _bundle_page(mind: Path) -> str:
    return _page(mind).split("## Bundles")[1].split("\n## ")[0]


def _card_titles(section: str) -> list:
    return re.findall(r"<summary><b>([^<]+)</b> — \d+ task\(s\)", section)


def test_auto_bundles_group_by_target_repo(tmp_path):
    """Independent tasks bundle only with tasks in the same repo — a session
    that spans two repos is two worktrees and two sets of tests."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Widget A"),
        "feature/widgets/b.md": _prompt("Widget B"),
        "bug/gadgets/c.md": _prompt("Gadget C").replace("Target: widgets",
                                                        "Target: gadgets"),
        "bug/gadgets/d.md": _prompt("Gadget D").replace("Target: widgets",
                                                        "Target: gadgets"),
    })
    bundles = _intake.auto_bundles(_intake.census(mind))
    assert [b["slug"] for b in bundles] == ["auto-gadgets-1", "auto-widgets-1"]
    assert [[m["title"] for m in b["members"]] for b in bundles] == [
        ["Gadget C", "Gadget D"], ["Widget A", "Widget B"]]


def test_a_lone_prompt_is_not_a_bundle(tmp_path):
    """One task is a task. The minimum is two, or the section is just the
    backlog again with extra words."""
    mind = _mind(tmp_path, drafts={"feature/widgets/only.md": _prompt("Only")})
    assert _intake.auto_bundles(_intake.census(mind)) == []
    assert "## Bundles" not in _page(mind)


def test_each_exclusion_keeps_a_prompt_out_of_the_auto_pool(tmp_path):
    """Everything a bundle member must be: startable on its own, unblocked,
    not already spoken for, and not a session in itself."""
    blocked = _prompt("Blocked one").replace(
        "Status: formalised", "Status: formalised\nBlocked-by: Widgets#12")
    mind = _mind(tmp_path, registries={"epics.md": _EPICS,
                                       "bundles.md": _BUNDLES}, drafts={
        "feature/widgets/ok_one.md": _prompt("Fine one"),
        "feature/widgets/ok_two.md": _prompt("Fine two"),
        "feature/widgets/blocked.md": blocked,
        "feature/widgets/human.md": _prompt("Human one",
                                            autonomy="human-required"),
        "feature/widgets/huge.md": _prompt("Huge one", difficulty="too-large"),
        "feature/widgets/phase.md": _epic_prompt_body("Phase one",
                                                      "jax-profiling", 1),
        "feature/widgets/pinned_one.md": _prompt("Pinned one"),
        "feature/widgets/pinned_two.md": _prompt("Pinned two"),
        "feature/widgets/headed.md": _prompt("Header-pinned").replace(
            "Status: formalised", "Status: formalised\nBundle: euclid-tidy"),
    })
    auto = _intake.auto_bundles(_intake.census(mind))
    assert [m["title"] for b in auto for m in b["members"]] == ["Fine one",
                                                               "Fine two"]


def test_a_declared_gate_reads_as_unresolved(tmp_path):
    """The renderer makes no network call (it runs bare in the Mind's refresh
    workflow), so a `Blocked-by:` is treated as still closed — proposing a
    gated task is the more expensive mistake."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Open one"),
        "feature/widgets/b.md": _prompt("Gated one").replace(
            "Status: formalised", "Status: formalised\nBlocked-by: Widgets#1")})
    assert _intake.auto_bundles(_intake.census(mind)) == []


def test_the_size_cap_starts_a_new_bundle(tmp_path):
    """Points, not counts: one large task plus three small ones is a session;
    a second large one is the next session."""
    drafts = {f"feature/widgets/s{i}.md": _prompt(f"Small {i}",
                                                  difficulty="small")
              for i in range(3)}
    drafts["feature/widgets/l1.md"] = _prompt("Large one", difficulty="large",
                                              priority="high")
    drafts["feature/widgets/l2.md"] = _prompt("Large two", difficulty="large",
                                              priority="high")
    drafts["feature/widgets/s9.md"] = _prompt("Small nine", difficulty="small",
                                              priority="high")
    bundles = _intake.auto_bundles(_intake.census(_mind(tmp_path, drafts=drafts)))
    assert [[m["title"] for m in b["members"]] for b in bundles] == [
        ["Large one", "Small nine", "Small 0", "Small 1"],
        ["Large two", "Small 2"]]
    assert [b["points"] for b in bundles] == [7, 5]
    for b in bundles:
        assert b["points"] <= _intake.BUNDLE_POINT_CAP
        assert len(b["members"]) <= _intake.BUNDLE_MAX_MEMBERS
        assert sum(m["difficulty"] == "large" for m in b["members"]) <= 1


def test_four_medium_tasks_are_one_bundle(tmp_path):
    """The other shape the cap is drawn around (4 × medium = 8 points)."""
    drafts = {f"feature/widgets/m{i}.md": _prompt(f"Medium {i}")
              for i in range(4)}
    bundles = _intake.auto_bundles(_intake.census(_mind(tmp_path, drafts=drafts)))
    assert len(bundles) == 1 and bundles[0]["points"] == 8
    assert len(bundles[0]["members"]) == 4


def test_auto_bundles_are_priority_ordered_and_deterministic(tmp_path):
    """Most-pickable first, and the same input renders the same page — the
    nightly re-render must not churn the section every time it runs."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/b_low.md": _prompt("Low one", priority="low"),
        "feature/widgets/a_high.md": _prompt("High one", priority="high"),
        "feature/widgets/c_high.md": _prompt("High two", priority="high"),
    })
    c = _intake.census(mind)
    assert [m["title"] for m in _intake.auto_bundles(c)[0]["members"]] == [
        "High one", "High two", "Low one"]
    assert _intake.auto_bundles(c) == _intake.auto_bundles(_intake.census(mind))
    assert _bundle_page(mind) == _bundle_page(mind)


def test_a_bundle_member_still_appears_in_the_backlog(tmp_path):
    """A bundle is an extra VIEW of the backlog, never a replacement — the
    opposite of an epic, whose members leave every pick list."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Widget A", priority="high"),
        "feature/widgets/b.md": _prompt("Widget B", priority="high")})
    page = _page(mind)
    backlog = page.split("## Backlog")[1].split("\n## ")[0]
    assert "Widget A" in backlog and "Widget B" in backlog
    assert "Widget A" in page.split("## Start here")[1].split("## In flight")[0]


def test_pinned_bundles_come_first_and_carry_their_registry_prose(tmp_path):
    """`bundles.md` is the human record; the proposals follow it."""
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts={
        "feature/widgets/pinned_one.md": _prompt("Pinned one"),
        "feature/widgets/pinned_two.md": _prompt("Pinned two"),
        "feature/widgets/loose_a.md": _prompt("Loose A"),
        "feature/widgets/loose_b.md": _prompt("Loose B"),
    })
    section = _bundle_page(mind)
    assert _card_titles(section) == ["Euclid pipeline tidy-up", "widgets — bundle 1"]
    assert "same reviewer, same afternoon" in section
    assert "proposed 2026-08-27" in section
    assert section.index("Pinned one") < section.index("Loose A")
    assert "· pinned" in section and "· auto — proposed" in section


def test_a_pinned_member_leaves_the_auto_pool(tmp_path):
    """A pinned prompt belongs to its bundle, not to a computed one."""
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts={
        "feature/widgets/pinned_one.md": _prompt("Pinned one"),
        "feature/widgets/pinned_two.md": _prompt("Pinned two"),
    })
    assert _intake.auto_bundles(_intake.census(mind)) == []


def test_a_header_declared_member_joins_its_pinned_bundle(tmp_path):
    """`Bundle: <slug>` in a prompt header is the second way to pin — the
    dashboard merges it into the registry entry's members."""
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts={
        "feature/widgets/pinned_one.md": _prompt("Pinned one"),
        "feature/widgets/pinned_two.md": _prompt("Pinned two"),
        "feature/widgets/headed.md": _prompt("Header-pinned").replace(
            "Status: formalised", "Status: formalised\nBundle: euclid-tidy"),
    })
    cards = _intake.bundle_cards(_intake.census(mind))
    assert [m["title"] for m in cards[0]["members"]] == [
        "Pinned one", "Pinned two", "Header-pinned"]


def test_a_member_of_an_unregistered_bundle_still_groups_loudly(tmp_path):
    """A typo shows up on the page instead of silently rendering nothing —
    the same treatment an unregistered `Epic:` slug gets."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/one.md": _prompt("Stray one").replace(
            "Status: formalised", "Status: formalised\nBundle: no-such-bundle"),
    })
    section = _bundle_page(mind)
    assert "no-such-bundle" in section
    assert "not in `bundles.md`" in section
    assert "Stray one" in section
    html = _intake.render_dashboard_html(_intake.census(mind))
    assert "not in bundles.md" in _prose(html)


def test_a_missing_member_prompt_still_renders(tmp_path):
    """A pinned path that resolves to no filed prompt is exactly the drift
    worth seeing — it renders as itself rather than vanishing."""
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts={
        "feature/widgets/pinned_one.md": _prompt("Pinned one")})
    section = _bundle_page(mind)
    assert "draft/feature/widgets/pinned_two.md" in section


def test_the_bundle_prompt_states_the_orchestration_contract(tmp_path):
    """The 📋 payload is the whole contract: one issue and one PR per member,
    one shared worktree per repo, execution delegated a rung down."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Widget A"),
        "feature/widgets/b.md": _prompt("Widget B")})
    prompt = _intake.bundle_prompt(_intake.auto_bundles(_intake.census(mind))[0])
    assert "architect (Fable)" in prompt
    assert "draft/feature/widgets/a.md" in prompt
    assert "/start_dev <member prompt>" in prompt
    assert "one issue" in prompt and "bulk issue queue" in prompt
    assert "One shared worktree per repo" in prompt
    assert "Opus subagent" in prompt
    assert "ONE PR per task" in prompt
    assert "/prm" in prompt
    assert "/ship_library" in prompt


def test_bundles_sit_between_backlog_and_recent_on_both_pages(tmp_path):
    """Bundles read the backlog a second way, so they sit under it — and the
    page still turns to Recent afterwards."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Widget A").replace(
            "Status: formalised", "Status: formalised\nFiled: 2026-08-20"),
        "feature/widgets/b.md": _prompt("Widget B").replace(
            "Status: formalised", "Status: formalised\nFiled: 2026-08-21")})
    page = _page(mind)
    assert page.index("## Backlog") < page.index("## Bundles") \
        < page.index("## Recent")
    html = _intake.render_dashboard_html(_intake.census(mind))
    assert html.index("<h2>Backlog") < html.index("<h2>Bundles") \
        < html.index("<h2>Recent")
    section = html.split("<h2>Bundles")[1].split("<h2>")[0]
    assert '<table class="bundle">' in section
    assert '<button class="copy"' in section


def test_the_section_is_absent_from_a_mind_with_no_bundles(tmp_path):
    """No cards, no section — and no stylesheet or heading left behind."""
    mind = _mind(tmp_path, drafts={"feature/widgets/only.md": _prompt("Only")})
    assert "## Bundles" not in _page(mind)
    html = _intake.render_dashboard_html(_intake.census(mind))
    assert "<h2>Bundles" not in html and "table.bundle" not in html


def test_dashboard_check_is_idempotent_with_bundles(tmp_path, capsys):
    """`--apply` then `--check` must be clean, or `dashboard_refresh.yml`
    self-heals a commit every night."""
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts={
        "feature/widgets/pinned_one.md": _prompt("Pinned one"),
        "feature/widgets/pinned_two.md": _prompt("Pinned two"),
        "feature/widgets/loose_a.md": _prompt("Loose A"),
        "feature/widgets/loose_b.md": _prompt("Loose B"),
    })
    assert _intake.main(["--mind", str(mind), "--apply", "dashboard"]) == 0
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 0
    assert "current" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# bundles: the section is a pick list, so it is ranked and capped
# --------------------------------------------------------------------------- #
def _targets(tmp_path, n, **kw):
    """A Mind with `n` bundle-able target repos, two identical prompts each."""
    return _mind(tmp_path, drafts={
        f"feature/t{i:02d}/{name}.md": _prompt(f"T{i:02d} {name}", **kw)
        for i in range(n) for name in ("a", "b")})


def test_auto_bundles_are_ranked_before_they_are_cut(tmp_path):
    """Most urgent member first (a bundle is only as pickable as its most
    urgent task), then the biggest session, then slug — so the cap keeps the
    bundles worth running rather than the repos that sort early."""
    mind = _mind(tmp_path, drafts={
        "feature/aaa/a.md": _prompt("Aaa one"),
        "feature/aaa/b.md": _prompt("Aaa two"),
        "feature/bbb/a.md": _prompt("Bbb one", priority="high"),
        "feature/bbb/b.md": _prompt("Bbb two", priority="high"),
        "feature/ccc/a.md": _prompt("Ccc one", difficulty="large",
                                    priority="high"),
        "feature/ccc/b.md": _prompt("Ccc two", difficulty="small"),
        "feature/ccc/c.md": _prompt("Ccc three", difficulty="small"),
        "feature/ddd/a.md": _prompt("Ddd one", difficulty="small",
                                    priority="low"),
        "feature/ddd/b.md": _prompt("Ddd two", difficulty="small",
                                    priority="low"),
    })
    cards = _intake.bundle_cards(_intake.census(mind))
    assert [b["slug"] for b in cards] == ["auto-ccc-1", "auto-bbb-1",
                                          "auto-aaa-1", "auto-ddd-1"]
    assert [b["points"] for b in cards] == [6, 4, 4, 2]


def test_only_the_first_page_of_auto_bundles_reaches_the_page(tmp_path):
    """One card per repo in the Mind is an inventory, not a pick list."""
    cards = _intake.bundle_cards(_intake.census(_targets(tmp_path, 12)))
    assert len(cards) == _intake.BUNDLE_LIST_MAX == 8
    # Equal rank throughout, so the tie-break decides: slug, ascending.
    assert [b["slug"] for b in cards] == [f"auto-t{i:02d}-1" for i in range(8)]
    section = _bundle_page(_targets(tmp_path, 12))
    assert section.count("· auto — proposed") == 8


def test_a_cut_section_says_so_and_says_how_to_keep_one(tmp_path):
    """Truncation is only honest if the page reports it, and pinning is the
    answer to "but I wanted that one"."""
    mind = _targets(tmp_path, 12)
    line = ("Showing 8 of 12 auto bundles — pin one in `bundles.md` to keep "
            "it on the page.")
    assert f"_{line}_" in _bundle_page(mind)
    html = _prose(_intake.render_dashboard_html(_intake.census(mind)))
    assert ("Showing 8 of 12 auto bundles — pin one in "
            "<code>bundles.md</code> to keep it on the page.") in html


def test_an_uncut_section_has_no_footer(tmp_path):
    mind = _targets(tmp_path, 3)
    assert "Showing" not in _bundle_page(mind)
    html = _prose(_intake.render_dashboard_html(_intake.census(mind)))
    assert "auto bundles — pin one" not in html


def test_pinned_bundles_are_never_capped(tmp_path):
    """A human put them there; the cap is only ever spent on proposals."""
    drafts = {f"feature/t{i:02d}/{name}.md": _prompt(f"T{i:02d} {name}")
              for i in range(12) for name in ("a", "b")}
    drafts["feature/widgets/pinned_one.md"] = _prompt("Pinned one")
    drafts["feature/widgets/pinned_two.md"] = _prompt("Pinned two")
    mind = _mind(tmp_path, registries={"bundles.md": _BUNDLES}, drafts=drafts)
    cards = _intake.bundle_cards(_intake.census(mind))
    assert cards[0]["slug"] == "euclid-tidy"
    assert len(cards) == _intake.BUNDLE_LIST_MAX + 1
    # The footer counts AUTO bundles only — the pinned card is not a proposal.
    assert "Showing 8 of 12 auto bundles" in _bundle_page(mind)


# --------------------------------------------------------------------------- #
# themes: what the work is ABOUT, and the bundles keyed on it
# --------------------------------------------------------------------------- #
# `Target:` says where the code lives — a mechanical key, one worktree per repo,
# which made the proposals read as "three things that live in autoarray". A
# prompt's `Themes:` list says what the work is about, which is the useful
# grouping and is routinely cross-repo. The vocabulary is a markdown list in
# `PyAutoMind/themes.md`, so a human adds a theme without touching the Brain.
_THEMES = """# Themes

The controlled vocabulary for a prompt's `Themes:` header.

## Vocabulary

- `mge`: Multi-Gaussian Expansion profiles, and fitting with them.
- `jax-gradient`: JAX autodiff — gradient correctness and gradient-based search.
- `interferometer`: Visibility-space datasets and their fits.
- `dashboard`: The Mind dashboard and its sibling boards.
"""


def _themed(title, *themes, target="widgets", **kw):
    """A prompt carrying a `Themes:` list, in the same shape as `Repos:`."""
    body = _prompt(title, **kw).replace("Target: widgets", f"Target: {target}")
    bullets = "".join(f"- {t}\n" for t in themes)
    return body.replace("Difficulty:", f"Themes:\n{bullets}Difficulty:", 1)


def test_the_vocabulary_is_read_from_the_minds_own_markdown(tmp_path):
    """`themes.md` is the source of truth — one editable markdown list, never
    a second copy inside the renderer."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES})
    vocab = _intake.parse_themes(mind)
    assert list(vocab) == ["mge", "jax-gradient", "interferometer", "dashboard"]
    assert vocab["mge"].startswith("Multi-Gaussian")
    assert _intake.parse_themes(tmp_path / "nowhere") == {}


def test_a_prompts_theme_list_keeps_the_order_it_was_written_in(tmp_path):
    """The first bullet is the grouping key and the rest are affinity, so the
    list is a sequence — parsing must never sort or de-order it."""
    text = _themed("Ordered", "jax-gradient", "mge", "mge")
    assert _intake.parse_theme_list(text) == ["jax-gradient", "mge"]
    assert _intake.parse_list_header(text, "Themes") == ["jax-gradient", "mge",
                                                         "mge"]


def test_a_primary_theme_pools_across_repos(tmp_path):
    """The point of the whole feature: one bundle about MGE, not one bundle
    per repo that MGE happens to touch."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("Widget MGE", "mge"),
        "bug/gadgets/b.md": _themed("Gadget MGE", "mge", target="gadgets"),
    })
    bundles = _intake.auto_bundles(_intake.census(mind))
    assert [b["slug"] for b in bundles] == ["auto-mge-1"]
    assert bundles[0]["title"] == "mge"
    assert [m["title"] for m in bundles[0]["members"]] == ["Gadget MGE",
                                                          "Widget MGE"]
    assert {m["target"] for m in bundles[0]["members"]} == {"widgets", "gadgets"}


def test_a_theme_bundle_names_every_members_repo(tmp_path):
    """A theme bundle is cross-repo by construction, so the members table has
    to say where each task lives — a Target-keyed card never needs to, because
    the column would be a constant."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("Widget MGE", "mge"),
        "bug/gadgets/b.md": _themed("Gadget MGE", "mge", target="gadgets"),
        "feature/doodads/c.md": _prompt("Plain C").replace("Target: widgets",
                                                           "Target: doodads"),
        "feature/doodads/d.md": _prompt("Plain D").replace("Target: widgets",
                                                           "Target: doodads"),
    })
    # Pools sort by key text, so the Target-keyed `doodads` card is first.
    plain, themed = _bundle_page(mind).split("<summary><b>mge")
    assert "| Prompt | Repo | Difficulty | Priority | Status |" in themed
    assert "| gadgets |" in themed and "| widgets |" in themed
    assert "| Prompt | Difficulty | Priority | Status |" in plain
    assert "| Prompt | Repo |" not in plain
    html = _intake.render_dashboard_html(_intake.census(mind))
    cards = html.split("<h2>Bundles")[1].split("<h2>")[0].split("<details>")
    assert "<th>Repo</th>" not in cards[1] and "<th>Repo</th>" in cards[2]


def test_affinity_packing_beats_filename_order(tmp_path):
    """Inside a pool the next member is the one that shares the most keywords
    with the seed — so a big pool splits by what the work is about, not by
    whichever filename sorts early."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a_seed.md": _themed(
            "Seed", "mge", "jax-gradient", "interferometer",
            difficulty="small", priority="high"),
        "feature/widgets/b_plain.md": _themed("Plain B", "mge",
                                              difficulty="small"),
        "feature/widgets/c_overlap.md": _themed("Overlap C", "mge",
                                                "jax-gradient",
                                                difficulty="small"),
        "feature/widgets/d_overlap.md": _themed("Overlap D", "mge",
                                                "interferometer",
                                                difficulty="small"),
        "feature/widgets/e_plain.md": _themed("Plain E", "mge",
                                              difficulty="small"),
        "feature/widgets/f_plain.md": _themed("Plain F", "mge",
                                              difficulty="small"),
    })
    bundles = _intake.auto_bundles(_intake.census(mind))
    assert [[m["title"] for m in b["members"]] for b in bundles] == [
        ["Seed", "Overlap C", "Overlap D", "Plain B"],
        ["Plain E", "Plain F"]]
    assert [b["slug"] for b in bundles] == ["auto-mge-1", "auto-mge-2"]
    # A pool's second bundle is numbered: a bundle is picked BY NAME, and the
    # title rides in the copied orchestration prompt.
    assert [b["title"] for b in bundles] == ["mge", "mge — bundle 2"]


def test_a_cards_title_carries_the_keywords_every_member_shares(tmp_path):
    """`mge · jax-gradient` says what the session is; `mge` alone says it when
    the members agree on nothing else."""
    shared = _mind(tmp_path / "shared", registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("A", "mge", "jax-gradient"),
        "feature/widgets/b.md": _themed("B", "mge", "jax-gradient"),
    })
    assert _intake.auto_bundles(_intake.census(shared))[0]["title"] == \
        "mge · jax-gradient"
    split = _mind(tmp_path / "split", registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("A", "mge", "jax-gradient"),
        "feature/widgets/b.md": _themed("B", "mge", "interferometer"),
    })
    assert _intake.auto_bundles(_intake.census(split))[0]["title"] == "mge"


def test_an_unthemed_prompt_falls_back_to_its_target(tmp_path):
    """Themes are optional, so the old key has to keep working — and the two
    kinds of pool sit side by side, ordered by their key text."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("Themed A", "mge"),
        "bug/gadgets/b.md": _themed("Themed B", "mge", target="gadgets"),
        "feature/widgets/c.md": _prompt("Plain C"),
        "feature/widgets/d.md": _prompt("Plain D"),
    })
    bundles = _intake.auto_bundles(_intake.census(mind))
    assert [b["slug"] for b in bundles] == ["auto-mge-1", "auto-widgets-1"]
    assert [b["title"] for b in bundles] == ["mge", "widgets — bundle 1"]
    assert [m["title"] for m in bundles[1]["members"]] == ["Plain C", "Plain D"]


def test_every_prompt_lands_in_at_most_one_auto_bundle(tmp_path):
    """Themes are a list, but only the FIRST one groups — otherwise the same
    task would be proposed from three cards and picked up twice."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("A", "mge", "jax-gradient"),
        "feature/widgets/b.md": _themed("B", "mge", "jax-gradient"),
        "feature/widgets/c.md": _themed("C", "jax-gradient", "mge"),
        "feature/widgets/d.md": _themed("D", "jax-gradient", "dashboard"),
        "feature/gadgets/e.md": _prompt("E").replace("Target: widgets",
                                                     "Target: gadgets"),
        "feature/gadgets/f.md": _prompt("F").replace("Target: widgets",
                                                     "Target: gadgets"),
    })
    bundles = _intake.auto_bundles(_intake.census(mind))
    paths = [m["path"] for b in bundles for m in b["members"]]
    assert len(paths) == len(set(paths)) == 6
    assert [b["slug"] for b in bundles] == ["auto-gadgets-1",
                                            "auto-jax-gradient-1", "auto-mge-1"]


def test_an_unknown_keyword_is_loud_on_the_card_and_counted_in_hygiene(tmp_path):
    """The list must not rot into free-text tags, so a keyword `themes.md`
    does not know still groups — visibly, the way an unregistered `Epic:`
    slug does — and the page says how many prompts carry one."""
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _themed("Odd one", "no-such-theme"),
        "feature/widgets/b.md": _themed("Odd two", "no-such-theme", "mge"),
    })
    c = _intake.census(mind)
    assert [r["unknown_themes"] for r in c["records"]] == [["no-such-theme"]] * 2
    page = _page(mind)
    assert "⚠️ theme(s) not in `themes.md`: no-such-theme" in page
    assert "2 prompt(s) with unknown theme keyword(s)" in page
    assert "draft/feature/widgets/a.md — unknown theme keyword(s): " \
        "no-such-theme" in page
    html = _prose(_intake.render_dashboard_html(c))
    assert "⚠️ theme(s) not in themes.md: no-such-theme" in html


def test_a_mind_with_no_vocabulary_warns_about_nothing(tmp_path):
    """A freshly-spawned Mind has an empty `themes.md`; shouting at every
    keyword in its backlog would be noise, not hygiene."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _themed("A", "whatever"),
        "feature/widgets/b.md": _themed("B", "whatever")})
    c = _intake.census(mind)
    assert c["theme_flags"] == []
    assert _intake.auto_bundles(c)[0]["slug"] == "auto-whatever-1"
    assert "unknown theme keyword" not in _page(mind)


# The un-themed page must be byte-for-byte what it was before themes existed:
# 130-odd prompts carry no `Themes:` yet, and a grouping change that also
# reflowed every existing card would make the backfill diff unreadable.
_UNTHEMED_HEAD = ("<summary><b>widgets — bundle 1</b> — 2 task(s) · 4 pts · "
                  "auto — proposed</summary>")
_UNTHEMED_TABLE = """| Prompt | Difficulty | Priority | Status |
|--------|------------|----------|--------|
| <a href="draft/feature/widgets/a.md">Widget A</a> | medium | normal | formalised |
| <a href="draft/feature/widgets/b.md">Widget B</a> | medium | normal | formalised |"""


def test_an_unthemed_backlog_renders_exactly_as_it_did_before_themes(tmp_path):
    mind = _mind(tmp_path, registries={"themes.md": _THEMES}, drafts={
        "feature/widgets/a.md": _prompt("Widget A"),
        "feature/widgets/b.md": _prompt("Widget B")})
    section = _bundle_page(mind)
    assert _UNTHEMED_HEAD in section
    assert _UNTHEMED_TABLE in section
    assert "| Prompt | Repo |" not in section and "themes.md" not in section
    bundles = _intake.auto_bundles(_intake.census(mind))
    assert [b["slug"] for b in bundles] == ["auto-widgets-1"]
    assert bundles[0]["title"] == "widgets — bundle 1"
    html = _intake.render_dashboard_html(_intake.census(mind))
    section = html.split("<h2>Bundles")[1].split("<h2>")[0]
    assert ("<tr><th>Prompt</th><th>Difficulty</th><th>Priority</th>"
            "<th>Status</th></tr>") in section


def test_formalising_writes_themes_under_repos_and_never_waits_for_one(tmp_path):
    """Intake assigns the keywords at formalisation — but a prompt formalises
    with or without them, and the bundler falls back to `Target:`."""
    # An organ repo, not a satellite one: the tenant firewall bars instance
    # repo names from organ code, and a made-up name would resolve to no repo
    # at all — leaving no `Repos:` block for the themes to land under.
    text = "Speed up the @PyAutoMind MGE gradient path."
    themed = _intake.analyse(text, "test", ["mge", "jax-gradient"])
    assert themed["themes"] == ["mge", "jax-gradient"]
    assert ("Repos:\n- PyAutoMind\nThemes:\n- mge\n- jax-gradient\n"
            "Difficulty:") in themed["header"]
    bare = _intake.analyse(text, "test")
    assert bare["themes"] == [] and "Themes:" not in bare["header"]
    # A pasted header block that already carries the list keeps it.
    pasted = _intake.analyse(_themed("Pasted", "mge"), "test")
    assert pasted["themes"] == ["mge"]


# --------------------------------------------------------------------------- #
# human review — the manual-only work-type (a complete task a human must check)
# --------------------------------------------------------------------------- #
def _review(title, target="widgets", priority="normal", date="2026-08-29"):
    return (f"# {title}\n\nType: human_review\nTarget: {target}\n"
            f"Difficulty: small\nAutonomy: human-required\n"
            f"Priority: {priority}\nStatus: formalised\nFiled: {date}\n\n"
            "Shipped in PR #99. Wanted eyes on it before calling it done.\n")


def test_human_review_is_never_inferred_only_declared():
    """The one work-type no classifier may reach.

    Every other type is a reading of the prose; this one is a human saying
    "my eyes are needed", which no keyword carries. Prose that talks about
    reviewing shipped work still classifies as ordinary work.
    """
    prose = ("Someone should review and assess the finished work on the "
             "widget pipeline and check it is ok before we call it done.")
    assert _intake.classify_work_type(prose)[0] != "human_review"
    assert _intake.analyse(prose, "test")["work_type"] != "human_review"
    for declaration in ("Type: human review", "Type: human-review",
                        "Type: human_review"):
        d = _intake.analyse(f"{declaration}\n\nCheck the @PyAutoMind widget "
                            "work shipped in PR #99.", "test")
        assert d["work_type"] == "human_review", declaration
        assert d["work_type_source"] == "declared"
        assert d["proposed_path"].startswith("draft/human_review/")


def test_declared_human_review_is_never_demoted_to_triage():
    """`triage/` means nobody classified this; here somebody did.

    A review's subject is shipped work whose repo may only be named in a
    completion record, so an unresolved target must not send it to triage the
    way it would an ordinary prompt.
    """
    d = _intake.analyse("Type: human review\n\nCheck last week's thing.", "test")
    assert d["work_type"] == "human_review"
    assert d["proposed_path"] == "draft/human_review/check_last_week_s_thing.md"
    assert "triage" not in d["proposed_path"]
    assert not any("No target repo resolved" in r for r in d["risks"])
    assert "start_dev" not in d["next_action"]
    # The same input WITHOUT the declaration is the ordinary triage filing.
    assert _intake.analyse("Check last week's thing.",
                           "test")["proposed_path"].startswith("draft/triage/")


def test_declaring_a_type_does_not_leak_into_the_derived_title(tmp_path):
    """A declaration that opens the input must not name the file after itself."""
    d = _intake.analyse("Type: human review. Check the widget fit quality.",
                        "test")
    assert d["title"] == "Check the widget fit quality"
    assert d["proposed_path"].endswith("check_the_widget_fit_quality.md")


def test_human_review_is_its_own_section_not_backlog(tmp_path):
    """Shipped work waiting on a person is not work to pick up.

    It must not inflate the backlog count, appear in the pick lists, or sink
    into a work-type section under 140 other prompts.
    """
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Widget A", priority="high"),
        "human_review/widgets/checked.md": _review("Check the widget rollout",
                                                   priority="high")})
    c = _intake.census(mind)
    assert c["total"] == 1
    assert [r["path"] for r in c["human_review"]] == [
        "draft/human_review/widgets/checked.md"]
    assert "human_review" not in c["by_work_type"]
    assert all(r["work_type"] != "human_review" for r in c["records"])

    page = _page(mind)
    section = page.split("## Human review")[1].split("## Parked")[0]
    assert "Check the widget rollout" in section
    assert "Widget A" not in section
    assert "| [Backlog](#backlog) (`draft/`) | 1 |" in page
    assert "| [Human review](#human-review) (`draft/human_review/`) | 1 |" in page
    # The row hands out a review prompt, never a /start_dev.
    assert "/start_dev draft/human_review" not in page
    assert "so I can sign it off" in section
    # Highest priority is a pick list; a review is not pickable work.
    assert "Check the widget rollout" not in page.split("## In flight")[0]


def test_human_review_section_renders_empty_rather_than_vanishing(tmp_path):
    """An absent section reads as "nothing to review"; so must an empty one —
    but only the section says which, so it is always drawn."""
    page = _page(_mind(tmp_path, drafts={"feature/widgets/a.md": _prompt("A")}))
    section = page.split("## Human review")[1].split("## Parked")[0]
    assert "_(nothing awaiting review)_" in section
    assert "nothing has been flagged, not that nothing shipped" in section


def test_human_review_body_may_name_its_shipped_pr_without_reading_as_drift(
        tmp_path):
    """For every other prompt a merged PR in the body means the lifecycle
    stalled. For a review it is the premise."""
    mind = _mind(tmp_path, drafts={
        "human_review/widgets/checked.md": _review("Check it"),
        "feature/widgets/stalled.md": _prompt("Stalled") + "\nFix: PR #12\n"})
    drift = _intake.census(mind)["drift"]
    assert any("stalled.md" in d for d in drift)
    assert not any("human_review" in d for d in drift)


def test_human_review_appears_in_the_recent_feed_as_its_own_event(tmp_path):
    mind = _mind(tmp_path, drafts={
        "human_review/widgets/checked.md": _review("Check it")})
    row = _intake.census(mind)["recent"][0]
    assert row["event"] == "flagged for review"
    assert row["payload"].startswith("Walk me through the completed work")


def test_human_review_renders_on_the_html_twin(tmp_path):
    mind = _mind(tmp_path, drafts={
        "human_review/widgets/checked.md": _review("Check the widget rollout")})
    html = _intake.render_dashboard_html(_intake.census(mind))
    section = html.split('<a id="human-review"></a>')[1].split("<h2>")[1]
    assert "Check the widget rollout" in section
    assert "so I can sign it off" in section
    # The blurb's markdown must not print literally on a page that renders HTML.
    assert "**you**" not in html and "<b>you</b>" in html

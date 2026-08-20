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


def _mind(root: Path, drafts=None, active=None, registries=None) -> Path:
    for rel, body in (drafts or {}).items():
        p = root / "draft" / rel
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
- ledger: autolens_profiling/results/notes/inference/PROGRAMME.md
- notes: slices ship as autolens_profiling issues/PRs, not Mind prompts

## bare-epic
"""


def test_epics_section_sits_under_in_flight_with_a_resume_prompt(tmp_path):
    mind = _mind(tmp_path, registries={"epics.md": _EPICS})
    page = _page(mind)
    assert page.index("## In flight") < page.index("## Epics") < page.index("## Parked")
    epics = page.split("## Epics")[1].split("## Parked")[0]
    assert "JAX inference programme" in epics
    assert "PROGRAMME.md" in epics
    # The copy payload is a procedure — work out the state, then continue.
    assert "work out the last completed phase" in epics
    assert "/start_dev" in epics
    # A slug-only entry still lists (tolerant, like the other registries).
    assert "bare-epic" in epics


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

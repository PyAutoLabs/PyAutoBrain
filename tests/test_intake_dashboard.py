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
            status="formalised", unattended=None, review_minutes=None,
            consequence=None, witness=None):
    extra = ""
    for key, value in (("Consequence", consequence), ("Witness", witness),
                       ("Review-minutes", review_minutes),
                       ("Unattended", unattended)):
        if value is not None:
            extra += f"{key}: {value}\n"
    return (f"# {title}\n\nType: feature\nTarget: widgets\n"
            f"Difficulty: {difficulty}\nAutonomy: {autonomy}\n"
            f"Priority: {priority}\nStatus: {status}\n{extra}\nBody prose.\n")


def _mind(root: Path, drafts=None, active=None, registries=None,
          complete=None, batches=None) -> Path:
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
    # `rel` is relative to `batches/` itself, so `reviews/<slot>.md` lands the
    # review file the batch-status box's "is this slot reviewed?" check reads.
    for rel, body in (batches or {}).items():
        p = root / "batches" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
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


def test_fits_a_slot_lists_only_unattended_ready_work(tmp_path):
    """Replaced "Quick wins" (`small and safe`), which was near-empty: ten
    prompts in the live backlog carried `safe`, so the surface that exists to
    hand out unattended work had almost nothing to hand out. The question is
    not how small the work is — it is whether it can finish without the human."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Ready and cheap", unattended="ready",
                                        review_minutes="0"),
        "feature/widgets/b.md": _prompt("Needs slicing", difficulty="too-large",
                                        unattended="needs-slicing"),
        "feature/widgets/c.md": _prompt("Never unattended", unattended="never"),
        "feature/widgets/d.md": _prompt("Ungraded"),
    })
    slot = _page(mind).split("**Fits a slot**")[1].split("## In flight")[0]
    assert "Ready and cheap" in slot
    assert "Needs slicing" not in slot
    assert "Never unattended" not in slot
    assert "Ungraded" not in slot


def test_fits_a_slot_is_ordered_by_what_review_costs(tmp_path):
    """Ordered by review-minutes ascending, not by priority. This list is read
    when the human has a slot to fill and wants to know what fits in it;
    `Highest priority` above is where importance is answered."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Expensive but urgent", priority="high",
                                        unattended="ready", review_minutes="20"),
        "feature/widgets/b.md": _prompt("Cheap and dull", priority="low",
                                        unattended="ready", review_minutes="2"),
    })
    slot = _page(mind).split("**Fits a slot**")[1].split("## In flight")[0]
    assert slot.index("Cheap and dull") < slot.index("Expensive but urgent")


def test_an_ungraded_prompt_sorts_last_rather_than_being_hidden(tmp_path):
    """A prompt that is `ready` with no review-minutes is still pickable; the
    page's standing rule is that unknown sorts last, never disappears."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("No cost recorded", unattended="ready"),
        "feature/widgets/b.md": _prompt("Costed", unattended="ready",
                                        review_minutes="5"),
    })
    slot = _page(mind).split("**Fits a slot**")[1].split("## In flight")[0]
    assert slot.index("Costed") < slot.index("No cost recorded")


def test_a_prompt_with_no_witness_is_reported_as_hygiene(tmp_path):
    """Not an error — the intended default. But the human is the only thing
    that can write one, so the page has to say which prompts are waiting."""
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("Has one", witness="ids bit-identical"),
        "feature/widgets/b.md": _prompt("Has none"),
    })
    page = _page(mind)
    hygiene = page.split("## Hygiene")[1]
    assert "no `Witness:`" in hygiene
    assert "feature/widgets/b.md" in hygiene
    assert "feature/widgets/a.md" not in hygiene


def test_every_backlog_prompt_is_one_collapsed_row_not_a_wide_table(tmp_path):
    """Wide tables scroll sideways on a phone; rows wrap. Pin the shape: one
    `<details>` per task whose summary is `📋 <linked title> — facets`."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one"),
        "feature/widgets/two.md": _prompt("Feature two"),
    })
    page = _page(mind)
    # Limit this assertion to Backlog; Recent has its own table.
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
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
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
    flight = page.split("## In flight")[1].split("## Planned")[0]
    assert "gadget_polish.md" in flight
    assert "widget_rework.md" not in flight, \
        "a parked prompt must not double-list as in flight"
    assert "## Parked" not in page
    assert "widget_rework.md" not in page
    assert _intake.census(mind)["parked"][0]["slug"] == "widget-rework"
    assert "| [In flight](#in-flight) | 1 |" in page


def test_in_flight_prompt_with_no_registry_row_claims_no_issue(tmp_path):
    """Silence beats a wrong link: prose issue URLs are usually cross-references."""
    body = _prompt("Orphan task") + \
        "\nFollow-up to https://github.com/ExampleOrg/Widgets/issues/7 (unrelated).\n"
    mind = _mind(tmp_path, active={"orphan.md": body})
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
    assert "Orphan task" in flight
    assert "issues/7" not in flight


def test_registry_entry_without_fields_still_lists(tmp_path):
    mind = _mind(tmp_path, registries={"planned.md": "# Planned\n\n## lonely-slug\n"})
    planned = _page(mind).split("## Planned")[1].split("## Backlog")[0]
    assert "<b>lonely-slug</b>" in planned


# --------------------------------------------------------------------------- #
# copy blocks: every task row's 📋 toggle hides a paste-ready message
# --------------------------------------------------------------------------- #
def test_backlog_and_picks_carry_a_start_dev_copy_block(tmp_path):
    """GitHub's copy button lives on fenced code blocks — the one clipboard a
    static page has, and the whole point of the row's hidden body on a phone."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one", priority="high")})
    page = _page(mind)
    fence = "```\nUse the start-dev skill. draft/bug/widgets/one.md\n```"
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
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
    assert "\nUse the start-dev skill. active/widget_rework.md\n" in flight


def test_registry_row_copy_block_prefers_its_prompt_path(tmp_path):
    """A planned row naming its prompt gets `/start_dev`; a bare slug has no
    start_dev target, so it routes as free prose instead."""
    mind = _mind(tmp_path, registries={"planned.md": (
        "# Planned\n\n## with-prompt\n- prompt: active/widget_rework.md\n"
        "\n## lonely-slug\n")})
    planned = _page(mind).split("## Planned")[1].split("## Backlog")[0]
    assert "\nUse the start-dev skill. active/widget_rework.md\n" in planned
    assert ("\nUse the route skill. start the planned PyAutoMind task lonely-slug — "
            "its record is in planned.md\n") in planned


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
    from copy_contract import assert_portable_copy_payloads
    page = _intake.render_dashboard_html(_intake.census(mind))
    if 'data-cmd="' in page:
        assert_portable_copy_payloads(page)
    return page


def test_html_task_has_a_copy_button_holding_the_command(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    html = _html(mind)
    assert ('<button class="copy" data-cmd="Use the start-dev skill. '
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


def test_epics_section_follows_start_here_with_a_resume_prompt(tmp_path):
    """Epics follow Start here, with their members and resume prompt together."""
    mind = _mind(tmp_path, registries={"epics.md": _EPICS})
    page = _page(mind)
    assert page.index("## Start here") < page.index("## Epics") < page.index("## In flight")
    epics = page.split("## Epics")[1]
    assert "JAX inference programme" in epics
    assert "PROGRAMME.md" in epics
    # The copy payload is a procedure — work out the state, then continue.
    assert "work out the last completed phase" in epics
    assert "Use the start-dev skill" in epics
    # A slug-only entry still lists (tolerant, like the other registries).
    assert "bare-epic" in epics


def _epic_prompt_body(title, epic, phase=None, priority="high"):
    phase_line = f"Phase: {phase}\n" if phase is not None else ""
    return (f"# {title}\n\nType: feature\nTarget: widgets\n"
            f"Difficulty: medium\nAutonomy: supervised\nPriority: {priority}\n"
            f"Status: formalised\nEpic: {epic}\n{phase_line}\nBody.\n")


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
    flight_at = page.index("## In flight")
    body, epics = page[:epics_at] + page[flight_at:], page[epics_at:flight_at]
    assert "Phase one" not in body and "Phase two" not in body
    assert "Standalone thing" in body
    # Grouped under the epic, phase order, with the resume prompt first and
    # the start-in-order caution present.
    assert epics.index("work out the last completed phase") \
        < epics.index("Phase one") < epics.index("Phase two")
    assert "2 queued prompt(s), in order" in epics
    assert "in order through the epic" in epics
    assert "belong to an epic" not in body


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
def test_the_page_states_when_it_was_generated_without_usage_prose(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    c = _intake.census(mind)
    page = _intake.render_dashboard(c)
    banner = page.split("| Where | Count |")[0]
    assert f"Last updated {c['generated']}" in banner
    assert "This page is generated" not in banner
    assert "Every task the Mind is holding" not in banner


def test_redundant_refresh_prompt_is_removed(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    banner = _page(mind).split("| Where | Count |")[0]
    assert "Refresh this page" not in banner
    assert "lifecycle.py record" not in banner


def test_html_retains_update_button_without_redundant_refresh_prompt(tmp_path):
    mind = _mind(tmp_path, drafts={"bug/widgets/x.md": _prompt("A task")})
    c = _intake.census(mind)
    c['home'] = 'https://github.com/Example/Mind'
    html = _intake.render_dashboard_html(c)
    assert f'data-refreshed-at="{c["refreshed_at"]}"' in html
    assert '/actions/workflows/dashboard_refresh.yml' in html
    assert 'Refresh this page' not in html
    assert '<div class="fresh">' not in html


def test_no_epics_file_renders_an_empty_destination(tmp_path):
    page = _page(_mind(tmp_path, active={"one.md": _prompt("Solo task")}))
    assert "## Epics" in page and "_(no epics)_" in page


def test_html_sections_link_their_markdown_source(tmp_path):
    mind = _mind(tmp_path, registries={"epics.md": _EPICS,
                                       "repos.yaml": REPOS_YAML})
    html = _html(mind)
    for src in ("active.md", "epics.md", "planned.md"):
        assert f'/blob/main/{src}" title="Markdown version" aria-label="Markdown version"><svg' in html, src
    assert '/tree/main/draft" title="Markdown version" aria-label="Markdown version"><svg' in html
    # Redundant header links are removed; section source icons remain.
    assert '/blob/main/README.md">GitHub Page</a>' not in html


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
    for slug in ("Sprocket calibration", "gearbox-survey"):
        assert slug in recent
    assert "| Date | Event | Task |" in recent


def test_shipped_work_is_not_in_the_feed(tmp_path):
    """The `complete/` ledger is a thousand records deep and ships ~200 a
    month, so including it made this a list of receipts — twenty things nobody
    can act on, on the page whose whole job is work in hand."""
    mind = _recent_mind(tmp_path, n_records=40)
    rows = _intake.census(mind)["recent"]
    assert len(rows) == 2
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
        "gearbox-survey": "filed",
    }


def test_recent_is_newest_first(tmp_path):
    rows = _intake.census(_recent_mind(tmp_path))["recent"]
    assert [r["date"] for r in rows] == sorted(
        (r["date"] for r in rows), reverse=True)


def test_recent_sits_after_backlog_and_before_pending_release(tmp_path):
    mind = _recent_mind(tmp_path)
    (mind / "epics.md").write_text(_EPICS, encoding="utf-8")
    page = _page(mind)
    assert page.index("## Backlog") < page.index("## Recent") < page.index("## Pending release")


def test_an_undated_task_is_absent_rather_than_sorted_to_the_bottom(tmp_path):
    """`lifecycle.py dates` is where a missing date gets reported; padding the
    feed with unknowns would bury the answer it exists to give."""
    mind = _mind(tmp_path, registries={
        "planned.md": "## gearbox-survey\n- status: planned\n"})
    assert _intake.census(mind)["recent"] == []
    assert "_(no recent activity)_" in _page(mind)


def test_recent_links_a_registry_row_to_its_own_entry_not_the_file_top(tmp_path):
    """parked.md is long enough that landing at its top is not the same as
    landing on the task."""
    page = _page(_recent_mind(tmp_path))
    assert 'href="planned.md#gearbox-survey"' in page
    assert "flywheel-balance" not in page


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
    assert html.index("<h2>Backlog") < html.index("<h2>Recent") < html.index("<h2>Pending release")
    assert '<table class="recent">' in html
    assert 'data-cmd="Use the start-dev skill. active/sprocket_calibration.md"' in html


def test_a_live_row_wears_its_date_where_the_task_is(tmp_path):
    """A status line reads very differently against a row issued yesterday
    than against one issued in May, so the date rides on the row too — not
    only down in the Recent feed."""
    page = _page(_recent_mind(tmp_path))
    flight = page.split("## In flight")[1].split("## Planned")[0]
    assert "issued 2026-08-19" in flight
    assert "flywheel-balance" not in page
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


def test_recent_explanatory_blurb_is_removed(tmp_path):
    html = _prose(_intake.render_dashboard_html(_intake.census(_many(tmp_path, 80))))
    assert "<code>complete/index.md</code>" not in html
    assert "newest things to happen" not in html
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
    assert rows[0]["payload"] == "Use the start-dev skill. draft/feature/widgets/sprocket.md"


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


# Optional thematic metadata remains useful when selecting work.
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


def test_an_unknown_keyword_is_counted_in_hygiene(tmp_path):
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
    assert "2 prompt(s) with unknown theme keyword(s)" in page
    assert "draft/feature/widgets/a.md — unknown theme keyword(s): " \
        "no-such-theme" in page


def test_formalising_writes_themes_under_repos_and_never_waits_for_one(tmp_path):
    """Intake assigns the keywords at formalisation — but a prompt formalises
    with or without them."""
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


def test_human_review_is_nested_in_backlog_without_becoming_a_dev_pick(tmp_path):
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
    section = page.split('<a id="human-review"></a>')[1].split("<summary><b>feature</b>")[0]
    assert "Check the widget rollout" in section
    assert "Widget A" not in section
    assert "| [Backlog](#backlog) | 2 |" in page
    assert "| [Human review]" not in page
    assert page.index("## Backlog") < page.index('<a id="human-review"></a>') < page.index("## Recent")
    # The row hands out a review prompt, never a /start_dev.
    assert "Use the start-dev skill. draft/human_review" not in page
    assert "so I can sign it off" in section
    # Highest priority is a pick list; a review is not pickable work.
    assert "Check the widget rollout" not in page.split("## In flight")[0]


def test_human_review_section_renders_empty_rather_than_vanishing(tmp_path):
    """An absent section reads as "nothing to review"; so must an empty one —
    but only the section says which, so it is always drawn."""
    page = _page(_mind(tmp_path, drafts={"feature/widgets/a.md": _prompt("A")}))
    section = page.split('<a id="human-review"></a>')[1].split("<summary><b>feature</b>")[0]
    assert "_(nothing awaiting review)_" in section
    assert "nothing has been flagged, not that nothing shipped" not in section


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
    section = html.split('<details id="human-review">')[1].split("</details>")[0]
    assert "Check the widget rollout" in section
    assert "so I can sign it off" in section
    assert "Shipped work waiting on" not in section


# --------------------------------------------------------------------------- #
# the batch-status box: c["batch"], shared with the Cortex's own dashboard
# --------------------------------------------------------------------------- #
DEV_RECORD_IN_FLIGHT = """# Batch 2026-09-03 pm
- dispatched: 2026-09-03T18:00Z
- members:
  - autofit-resampling-info: draft/bug/autofit/resampling.md — glance — 3 — RUNNING
"""

DEV_RECORD_COLLECTED = """# Batch 2026-09-03 pm
- dispatched: 2026-09-03T18:00Z
- collected: 2026-09-03T20:00Z
- members:
  - autofit-resampling-info: draft/bug/autofit/resampling.md — glance — 3 — DELIVERED (Widgets#1554)
  - autonerves-colab-silence: draft/feature/autonerves/colab_silence.md — glance — 5 — MERGED
"""

DEV_RECORD_REVIEWED = """# Batch 2026-09-02 pm
- dispatched: 2026-09-02T18:00Z
- collected: 2026-09-02T20:00Z
- reviewed-at: 2026-09-02T21:00Z
- members:
  - autofit-resampling-info: draft/bug/autofit/resampling.md — glance — 3 — DELIVERED
"""


def test_in_flight_batch_reads_as_in_progress_with_no_button(tmp_path):
    mind = _mind(tmp_path, batches={"2026-09-03-pm.md": DEV_RECORD_IN_FLIGHT})
    page, html = _page(mind), _html(mind)
    assert "Batch 2026-09-03-pm" in page
    assert "autofit-resampling-info" in page and "autofit-resampling-info" in html
    assert "in progress" in page
    assert "Nothing to review yet" in page
    assert '<a class="go"' not in html


def test_button_appears_once_collected_is_stamped(tmp_path):
    mind = _mind(tmp_path, batches={"2026-09-03-pm.md": DEV_RECORD_COLLECTED},
                registries={"repos.yaml": REPOS_YAML})
    page, html = _page(mind), _html(mind)
    url = "https://exampleorg.github.io/PyAutoMind/packets/2026-09-03-pm.html"
    assert f"[Review this batch →]({url})" in page
    assert f'<a class="go" href="{url}">Review this batch →</a>' in html


def test_a_reviewed_batch_disappears_from_the_box(tmp_path):
    mind = _mind(tmp_path, batches={"2026-09-02-pm.md": DEV_RECORD_REVIEWED})
    assert "No batch in flight." not in _page(mind)
    assert "No batch in flight." not in _html(mind)


def test_a_review_file_on_disk_closes_the_slot_without_a_reviewed_at_key(tmp_path):
    # A migrated/transcribed record can carry no `reviewed-at:` line at all —
    # the review file's existence must still close the box.
    mind = _mind(tmp_path, batches={
        "2026-09-03-pm.md": DEV_RECORD_COLLECTED,
        "reviews/2026-09-03-pm.md": "# Batch review 2026-09-03-pm\n",
    })
    assert "No batch in flight." not in _page(mind)


def test_empty_mind_omits_batch_placeholder(tmp_path):
    mind = _mind(tmp_path)
    assert "No batch in flight." not in _page(mind)
    assert "No batch in flight." not in _html(mind)


def test_batch_box_md_and_html_agree_on_slugs_and_the_review_url(tmp_path):
    mind = _mind(tmp_path, batches={"2026-09-03-pm.md": DEV_RECORD_COLLECTED},
                registries={"repos.yaml": REPOS_YAML})
    page, html = _page(mind), _html(mind)
    url = "https://exampleorg.github.io/PyAutoMind/packets/2026-09-03-pm.html"
    for slug in ("autofit-resampling-info", "autonerves-colab-silence"):
        assert slug in page and slug in html
    assert url in page and url in html


# --------------------------------------------------------------------------- #
# the PR ledger — `library-pr:` / `workspace-pr:` / `pending-release:`
#
# The keys were written by ship_library and read by /prm for months while the
# page rendered only the free-text `status:`, so a reader on a phone could see
# that a task was "awaiting-merge" and had no way to reach the PR. The whole
# section is a LEDGER render: no `gh` call may happen here, at any input.
# --------------------------------------------------------------------------- #
PR_LEDGER_ACTIVE = """# Active

## widget-rework
- issue: https://github.com/ExampleOrg/Widgets/issues/42
- prompt: active/widget_rework.md
- status: library-shipped, awaiting-merge
- library-pr: https://github.com/ExampleOrg/Widgets/pull/7
- library-pr: https://github.com/ExampleOrg/Gadgets/pull/8
- workspace-pr: https://github.com/ExampleOrg/widgets_workspace/pull/9
"""


def test_in_flight_rows_link_every_pr_key_labelled_by_repo(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework")},
                 registries={"active.md": PR_LEDGER_ACTIVE})
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
    for label, url in (("Widgets#7", "https://github.com/ExampleOrg/Widgets/pull/7"),
                       ("Gadgets#8", "https://github.com/ExampleOrg/Gadgets/pull/8"),
                       ("widgets_workspace#9",
                        "https://github.com/ExampleOrg/widgets_workspace/pull/9")):
        assert f'<a href="{url}">{label}</a>' in flight, \
            "every *-pr: key must render as one repo-labelled link"


def test_the_older_single_line_comma_form_of_a_pr_key_still_links(tmp_path):
    """Rows written before the key was schematised must not lose their links."""
    mind = _mind(
        tmp_path,
        active={"widget_rework.md": _prompt("Widget rework")},
        registries={"active.md": (
            "# Active\n\n## widget-rework\n"
            "- prompt: active/widget_rework.md\n"
            "- status: shipped\n"
            "- library-pr: https://github.com/ExampleOrg/Widgets/pull/7, "
            "https://github.com/ExampleOrg/Gadgets/pull/8\n")})
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
    assert "Widgets#7" in flight and "Gadgets#8" in flight


PENDING_ACTIVE = """# Active

## widget-rework
- issue: https://github.com/ExampleOrg/Widgets/issues/42
- prompt: active/widget_rework.md
- status: library-shipped, awaiting-merge
- library-pr: https://github.com/ExampleOrg/Widgets/pull/7
- pending-release: Widgets@https://github.com/ExampleOrg/Widgets/pull/7

## gadget-polish
- prompt: active/gadget_polish.md
- status: workspace-dev
- release-gate: Widgets
"""


def test_a_pending_release_badge_is_read_from_the_ledger_not_github(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework"),
                         "gadget_polish.md": _prompt("Gadget polish")},
                 registries={"active.md": PENDING_ACTIVE})
    flight = _page(mind).split("## In flight")[1].split("## Planned")[0]
    assert "⏳ pending release: Widgets" in flight
    assert "⏸ waiting on Widgets's release" in flight


def test_pending_release_groups_the_prs_and_the_tasks_waiting_on_them(tmp_path):
    mind = _mind(
        tmp_path,
        active={"widget_rework.md": _prompt("Widget rework"),
                "gadget_polish.md": _prompt("Gadget polish")},
        registries={"active.md": PENDING_ACTIVE},
        complete={"2026/01/sprocket_fix.md": (
            "## sprocket-fix\n- completed: 2026-01-01\n"
            "- pending-release: Sprockets@https://github.com/ExampleOrg/Sprockets/pull/3\n"
            "\n## Original prompt\n\n"
            "- pending-release: Decoys@https://github.com/ExampleOrg/Decoys/pull/99\n")})
    section = _page(mind).split("## Pending release")[1].split("## Planned")[0]
    assert "**Widgets**" in section and "**Sprockets**" in section
    assert "[Widgets#7](https://github.com/ExampleOrg/Widgets/pull/7)" in section
    assert "Sprockets#3" in section, \
        "a complete/ record's uncleared pending-release: belongs in the section"
    assert "Decoys" not in section, \
        "the appended Original prompt is not the record's own fields"
    assert "⏸ waiting: [Gadget polish]" in section
    assert "never a live GitHub query" not in section


def test_an_empty_pending_release_section_keeps_its_destination(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework")},
                 registries={"active.md": ACTIVE_MD})
    page = _page(mind)
    assert "## Pending release" in page and "nothing pending release" in page
    assert 'id="pending-release"' in _intake.render_dashboard_html(_intake.census(mind))


def test_pending_release_renders_on_the_html_page_too(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework"),
                         "gadget_polish.md": _prompt("Gadget polish")},
                 registries={"active.md": PENDING_ACTIVE})
    html = _intake.render_dashboard_html(_intake.census(mind))
    assert 'id="pending-release"' in html
    assert '<a href="https://github.com/ExampleOrg/Widgets/pull/7">Widgets#7</a>' in html


# --------------------------------------------------------------------------- #
# the cockpit feed — state.json (board/_state.py, contract v1; PyAutoBrain#418)
#
# The third render of the one census. Its items carry the payloads the page
# already copies, and `--check` must ignore its `updated` render stamp the way
# it ignores the page's generation date — or the self-heal commits hourly.
# --------------------------------------------------------------------------- #
sys.path.insert(0, str(BRAIN_HOME / "board"))
import json  # noqa: E402

import _state  # noqa: E402


def _feed(mind: Path) -> dict:
    return json.loads(_intake.render_state(_intake.census(mind)))


def test_apply_writes_a_state_feed_that_satisfies_the_contract(tmp_path):
    mind = _mind(tmp_path, drafts={
        "feature/widgets/urgent.md": _prompt("Urgent widget", priority="high")},
        registries={"repos.yaml": REPOS_YAML})
    assert _intake.main(["--mind", str(mind), "--apply", "dashboard"]) == 0
    state = json.loads((mind / "state.json").read_text(encoding="utf-8"))
    assert _state.validate_state(state) == []
    assert (state["organ"], state["repo"]) == ("mind", "PyAutoMind")
    assert state["pages_url"] == "https://exampleorg.github.io/PyAutoMind/"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", state["updated"])
    # a pick is waiting: yellow, and the pick carries the page's own payload
    assert state["status"] == "yellow"
    assert state["headline"] == "YELLOW — 1 picks · 0 in flight"
    pick = state["items"][-1]
    assert pick["severity"] == "info"
    assert pick["prompt"] == "Use the start-dev skill. draft/feature/widgets/urgent.md"
    assert pick["url"] == ("https://github.com/ExampleOrg/PyAutoMind/blob/main/"
                           "draft/feature/widgets/urgent.md")


def test_an_awaiting_merge_row_is_a_yellow_item_linking_its_pr(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework")},
                 registries={"active.md": PR_LEDGER_ACTIVE})
    state = _feed(mind)
    assert _state.validate_state(state) == []
    assert state["status"] == "yellow"
    item = state["items"][0]
    assert item["severity"] == "yellow"
    assert item["text"].startswith("Widget rework — library-shipped, awaiting-merge")
    assert item["url"] == "https://github.com/ExampleOrg/Widgets/pull/7", \
        "the first PR is the door, not the issue"
    assert item["prompt"] == "Use the start-dev skill. active/widget_rework.md"
    # no repos.yaml: nothing to derive a Pages site from, still a valid feed
    assert state["pages_url"] == "./"


def test_an_awaiting_input_row_turns_the_feed_red(tmp_path):
    mind = _mind(tmp_path,
                 active={"widget_rework.md": _prompt("Widget rework")},
                 registries={"active.md": PR_LEDGER_ACTIVE.replace(
                     "library-shipped, awaiting-merge", "awaiting-input")})
    state = _feed(mind)
    assert state["status"] == "red"
    assert state["headline"].startswith("RED — ")
    assert state["items"][0]["severity"] == "red"


def test_an_empty_mind_is_a_grey_feed(tmp_path):
    state = _feed(_mind(tmp_path))
    assert _state.validate_state(state) == []
    assert state["status"] == "grey" and state["items"] == []


def test_check_is_clean_after_apply_when_only_the_clock_moved(tmp_path, monkeypatch):
    mind = _mind(tmp_path, drafts={"bug/widgets/one.md": _prompt("Bug one")})
    monkeypatch.setattr(_intake, "_now_iso", lambda: "2026-01-01T00:00:00Z")
    assert _intake.main(["--mind", str(mind), "--apply", "dashboard"]) == 0
    monkeypatch.setattr(_intake, "_now_iso", lambda: "2027-12-31T23:59:59Z")
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 0
    # ...but a changed feed body is drift
    feed = mind / "state.json"
    feed.write_text(feed.read_text(encoding="utf-8").replace(
        '"status": "green"', '"status": "red"'), encoding="utf-8")
    assert _intake.main(["--mind", str(mind), "dashboard", "--check"]) == 1


def test_navigation_cards_follow_banner_and_have_existing_targets(tmp_path):
    page = _html(_mind(tmp_path, drafts={"feature/widgets/one.md": _prompt("One")}))
    assert page.index('class="hero"') < page.index('class="orchestration-panel"') < page.index('class="board-nav"')
    nav = re.search(r'<nav class="board-nav".*?</nav>', page, re.S).group()
    for target in re.findall(r'href="#([^"]+)"', nav):
        assert f'id="{target}"' in page
    assert 'board-nav-count">0</span><span class="board-nav-label">In flight' in nav


def test_start_here_summary_counts_unique_visible_tasks(tmp_path):
    mind = _mind(tmp_path, drafts={
        'feature/widgets/one.md': _prompt('One', priority='high', autonomy='safe', difficulty='small')})
    page = _html(mind)
    assert '<h2>Start here</h2><span class="section-badge">1</span>' in page



def test_seven_navigation_counts_and_nested_review(tmp_path):
    mind = _mind(tmp_path, drafts={
        "feature/widgets/one.md": _prompt("One", priority="high", unattended="ready"),
        "feature/widgets/two.md": _prompt("Two", unattended="ready"),
        "feature/widgets/phase.md": _epic_prompt_body("Phase", "unregistered", 1),
        "human_review/widgets/review.md": _review("Review shipped work"),
    }, registries={"epics.md": _EPICS, "active.md": PENDING_ACTIVE})
    c = _intake.census(mind)
    page = _intake.render_dashboard_html(c)
    nav = re.search(r'<nav class="board-nav".*?</nav>', page, re.S).group()
    counts = re.findall(r'board-nav-count">(\d+)</span><span class="board-nav-label">([^<]+)', nav)
    assert [(label, int(count)) for count, label in counts] == [
        ("Start here", 2), ("Epics", len(c["epics"]) + 1),
        ("In flight", c["issued_count"]), ("Planned", 0), ("Backlog", 4),
        ("Recent", len(c["recent"])),
        ("Pending release", len(c["pending_release"]))]
    assert 'style="--nav-columns:7"' in nav
    assert "Human review" not in nav and "Parked" not in nav and "Bundles" not in nav
    backlog = page.split('<a id="backlog"></a>')[1].split('<a id="recent"></a>')[0]
    assert '<details id="human-review">' in backlog
    assert 'Review shipped work' in backlog
    assert '<h2>Human review' not in page
    assert 'Use the start-dev skill. draft/human_review' not in page


def test_empty_mind_has_seven_zero_count_destinations(tmp_path):
    c = _intake.census(_mind(tmp_path))
    page = _intake.render_dashboard_html(c)
    nav = re.search(r'<nav class="board-nav".*?</nav>', page, re.S).group()
    assert nav.count('board-nav-count">0</span>') == 7
    for target in re.findall(r'href="#([^"]+)"', nav):
        assert page.count(f'id="{target}"') == 1
    assert page.count('<details class="board-section">') == 7
    assert "nothing pending release" in page and "no epics" in page


def test_legacy_bundle_registry_and_headers_do_not_create_functionality(tmp_path):
    mind = _mind(tmp_path, drafts={
        "feature/widgets/a.md": _prompt("A") + "\nBundle: legacy\n",
        "feature/widgets/b.md": _prompt("B"),
    }, registries={"bundles.md": "# Bundles\n\n## legacy\n- members:\n  - draft/feature/widgets/a.md\n"})
    c = _intake.census(mind)
    assert "bundles" not in c
    assert all("bundle" not in r and "bundle" not in r["header"] for r in c["records"])
    assert c["total"] == 2
    for page in (_intake.render_dashboard(c), _intake.render_dashboard_html(c)):
        assert "Bundles" not in page and "start-bundle" not in page
        assert "draft/feature/widgets/a.md" in page and "draft/feature/widgets/b.md" in page

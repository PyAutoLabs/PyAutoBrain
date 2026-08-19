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


def test_every_backlog_prompt_is_a_bullet_not_a_wide_table_row(tmp_path):
    """Wide tables scroll sideways on a phone; bullets wrap. Pin the shape."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one"),
        "feature/widgets/two.md": _prompt("Feature two"),
    })
    page = _page(mind)
    backlog = page.split("## Backlog")[1]
    assert "- [Bug one](draft/bug/widgets/one.md)" in backlog
    assert "- [Feature two](draft/feature/widgets/two.md)" in backlog
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
    assert "[issue #42](https://github.com/ExampleOrg/Widgets/issues/42)" in flight, \
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
    assert "**lonely-slug**" in parked


# --------------------------------------------------------------------------- #
# copy blocks: every task carries a paste-ready message that routes Claude
# --------------------------------------------------------------------------- #
COPY_SUMMARY = "<summary>📋 copy for Claude</summary>"


def test_backlog_and_picks_carry_a_start_dev_copy_block(tmp_path):
    """GitHub's copy button lives on fenced code blocks — the one clipboard a
    static page has, and the whole point of the block on a phone."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one", priority="high")})
    page = _page(mind)
    fence = "  ```\n  /start_dev draft/bug/widgets/one.md\n  ```"
    head, backlog = page.split("## In flight")[0], page.split("## Backlog")[1]
    assert fence in head and COPY_SUMMARY in head, \
        "the Start-here picks must carry the copy block"
    assert fence in backlog and COPY_SUMMARY in backlog, \
        "backlog bullets must carry the copy block"


def test_in_flight_copy_block_targets_the_active_prompt(tmp_path):
    mind = _mind(tmp_path, active={"widget_rework.md": _prompt("Widget rework")})
    flight = _page(mind).split("## In flight")[1].split("## Parked")[0]
    assert "  /start_dev active/widget_rework.md" in flight


def test_registry_row_copy_block_prefers_its_prompt_path(tmp_path):
    """A parked row naming its prompt gets `/start_dev`; a bare slug has no
    start_dev target, so it routes as free prose instead."""
    mind = _mind(tmp_path, registries={"parked.md": (
        "# Parked\n\n## with-prompt\n- prompt: active/widget_rework.md\n"
        "\n## lonely-slug\n")})
    parked = _page(mind).split("## Parked")[1].split("## Planned")[0]
    assert "  /start_dev active/widget_rework.md" in parked
    assert ("  /route resume the parked PyAutoMind task lonely-slug — "
            "its record is in parked.md") in parked


def test_copy_details_never_swallow_the_next_bullet(tmp_path):
    """GitHub's renderer treats lines after `</details>` as raw HTML until a
    blank line — a bullet directly beneath one would vanish from the page."""
    mind = _mind(tmp_path, drafts={
        "bug/widgets/one.md": _prompt("Bug one"),
        "bug/widgets/two.md": _prompt("Bug two"),
    }, active={"a.md": _prompt("A"), "b.md": _prompt("B")})
    page = _page(mind)
    assert "</details>\n-" not in page
    assert "</details>\n  <details>" not in page


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


def test_bracketed_title_does_not_break_the_link(tmp_path):
    mind = _mind(tmp_path, drafts={
        "bug/widgets/b.md": _prompt("[JAX] fails on [gpu]", priority="high")})
    page = _page(mind)
    assert r"\[JAX\] fails on \[gpu\]" in page
    assert "(draft/bug/widgets/b.md)" in page


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

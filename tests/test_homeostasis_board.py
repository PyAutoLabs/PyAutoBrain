"""Homeostasis (maintenance orchestrator) on the Brain board, the Mind
dashboard split, and the writer's priority cap — PyAutoBrain#747.

Witness: the board section's counts are `batch maintain`'s (`collect`) by
source and tier; each finding's status comes from the Mind by its key mark
(open, promoted, in-progress, done) and a key the Mind carries that a fresh,
complete read no longer reports is `cleared`, never from an unread source; an
unread source shows UNREAD, never zero findings; `homeostasis.json` is
written beside board.json only on `--apply`. On the Mind dashboard a
generated glance prompt (a `Source-key:` header) is in no pickable list and
is counted by one collapsed Homeostasis line with the Brain board link; a
generated judge prompt is in one "Promoted from Homeostasis" group with its
copy row; ordinary prompts are unchanged. Generated prompts are `Priority:`
at most `normal`. Placeholder repos and fixture boards only — nothing reads
the network, a real Heart or the shared Mind.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

from _helpers import load_module
from _shift_fixtures import _batch  # noqa: F401 — puts the batch package on sys.path
import _maintain  # noqa: E402
import _maintain_write as W  # noqa: E402

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "board"))
import _homeostasis as H  # noqa: E402
import _hygiene_ledger as L  # noqa: E402
from test_board import _default_fixtures, _fabricate, _run  # noqa: E402

_intake = load_module("_intake_homeostasis_under_test", "agents/conductors/intake/_intake.py")

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
TS = (NOW - dt.timedelta(hours=1)).isoformat()


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """Never the network, a real Heart or the body map."""
    monkeypatch.setattr(_maintain, "ledger_url", lambda: (None, "tests: no ledger URL"))
    monkeypatch.setattr(_maintain, "glance_organs", lambda: set())
    monkeypatch.setattr(_maintain, "HEART_STATE_DIR", tmp_path / "no_heart_state")


# --- fixtures ---------------------------------------------------------------------

def _mon(family, subject, evidence=None, status="red"):
    return {"id": f"{family}:{subject}:", "family": family, "subject": subject,
            "status": status, "summary": "failure", "observed_at": TS, "fresh": True,
            "source": f"snapshot.{family}", "evidence": evidence}


CENSUS_ROWS = [
    {"repo": "ws_alpha", "entry": "imaging/slow_one", "marker": "SLOW",
     "date": "2026-07-30", "reason": "times out at the 300s cap", "measured": False},
    {"repo": "ws_beta", "entry": "graphical/ep.py", "marker": "NEEDS_FIX",
     "date": "2026-08-03", "reason": "EP parked", "measured": False},
]
HEART_BOARD = {
    "ts": TS, "verdict": "green",
    "monitoring": {"findings": [
        _mon("ci_status", "OrganA/workflows/Pages Dashboard",
             {"conclusion": "failure", "on_head": True}),
        _mon("ci_status", "OrganB/workflows/Docs", {"conclusion": "failure", "on_head": True}),
    ] + [_mon("no_run_census", f"{r['repo']}/{r['entry']}", dict(r), "yellow")
         for r in CENSUS_ROWS]},
    "performance": {"no_run": {"rows": CENSUS_ROWS[:1], "totals": {}}},
}
HEART_VERDICT = {"verdict": "GREEN", "ts": TS, "red_reasons": [], "yellow_reasons": [],
                 "stale_reasons": []}
HYGIENE_ROWS = [{"mode": "refs", "status": "finding", "count": 1, "findings": [
    {"repo": "ws_alpha", "file": "README.md", "line": 10, "reference": "old_folder/"}]}]
REFS_KEY = "refs:ws_alpha:README.md:old_folder/"


def _inputs(tmp_path, heart=True) -> dict:
    d = tmp_path / "inputs"
    d.mkdir(exist_ok=True)
    (d / "board.json").write_text(json.dumps(HEART_BOARD))
    (d / "heart.json").write_text(json.dumps(HEART_VERDICT))
    L.record(d / "ledger.jsonl", HYGIENE_ROWS, NOW.strftime("%Y-%m-%d"), "sha0")
    return {"board_json": str(d / "board.json"),
            "heart_json": str(d / "heart.json") if heart else str(d / "absent.json"),
            "hygiene_json": str(d / "ledger.jsonl")}


def _gen(key, tier="judge", source="monitoring", title="Maintenance: x"):
    """A prompt the maintenance writer generated (its header and marks)."""
    return (f"# {title}\n\nType: maintenance\nTarget: organa\nDifficulty: small\n"
            f"Autonomy: supervised\nPriority: normal\nStatus: draft\nFiled: 2026-11-27\n"
            f"Consequence: {tier}\nWitness: the key is absent\nReview-minutes: 5\n"
            f"Lane: any\nUnattended: {'ready' if tier == 'glance' else 'never'}\n"
            f"Source-key: {key}\n\n**Re-check first.** Filed from the `{source}` source "
            f"(fixture, 1.0 h old).\n\n<!-- maint-key: {key} -->\n")


def _write(root: Path, files: dict) -> Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _fixture_mind(root: Path) -> Path:
    return _write(root, {
        # promoted: a judge prompt in draft/
        "draft/maintenance/organa/maint_a.md": _gen("ci:OrganA:Pages Dashboard"),
        # in-progress: the prompt is in active/
        "active/maint_b.md": _gen("ci:OrganB:Docs"),
        # done: a complete/ record carrying the key (its original prompt)
        "complete/2026/11/fixed_slow_one.md":
            "# Record\n\n## Original prompt\n\n" + _gen("no_run:ws_alpha/imaging/slow_one",
                                                         source="census"),
        # open, with its glance draft (Homeostasis's own queue)
        "draft/maintenance/ws_alpha/maint_refs.md":
            _gen(REFS_KEY, tier="glance", source="hygiene:refs"),
        # cleared: a monitoring key no fresh monitoring read reports
        "draft/maintenance/organc/maint_gone.md": _gen("ci:OrganC:Gone"),
        # NOT cleared: its source (release) is unread in the unread test
        "draft/maintenance/organd/maint_rel.md": _gen("ci:OrganD:Rel", source="release"),
        "draft/feature/widgets/ordinary.md": "# Ordinary\n\nType: feature\n",
    })


def _section(tmp_path, heart=True):
    mind = _fixture_mind(tmp_path / "mind")
    inputs = _inputs(tmp_path, heart)
    result = _maintain.read_sources(_maintain.SOURCES, **inputs)
    return H.collect(mind, reader=lambda: result), result


# --- the board section --------------------------------------------------------------

def test_section_counts_match_batch_maintain_collect(tmp_path):
    sec, (reads, raw, found) = _section(tmp_path)
    assert sec["count"] == len(found) == len(sec["findings"])
    assert [r["key"] for r in sec["findings"]] == [f.key for f in found]
    by_source, by_tier = {}, {}
    for f in found:
        by_source[f.source] = by_source.get(f.source, 0) + 1
        by_tier[f.tier_floor] = by_tier.get(f.tier_floor, 0) + 1
    assert sec["counts"]["source"] == dict(sorted(by_source.items(),
                                                  key=lambda kv: (-kv[1], kv[0])))
    assert sec["counts"]["tier"] == dict(sorted(by_tier.items(),
                                                key=lambda kv: (-kv[1], kv[0])))
    assert sec["unread"] == [] and sec["mind"] == "read"
    for r in sec["findings"]:
        assert {"key", "source", "tier", "repo", "status", "witness"} <= set(r)


def test_statuses_from_the_mind(tmp_path):
    sec, _ = _section(tmp_path)
    st = {r["key"]: r["status"] for r in sec["findings"]}
    assert st["ci:OrganA:Pages Dashboard"] == "promoted"
    assert st["ci:OrganB:Docs"] == "in-progress"
    assert st["no_run:ws_alpha/imaging/slow_one"] == "done"
    assert st["no_run:ws_beta/graphical/ep.py"] == "open"
    assert st[REFS_KEY] == "open"  # a glance draft: Homeostasis's own queue
    paths = {r["key"]: r["mind_path"] for r in sec["findings"]}
    assert paths[REFS_KEY] == "draft/maintenance/ws_alpha/maint_refs.md"
    assert paths["no_run:ws_beta/graphical/ep.py"] == ""
    cleared = {r["key"] for r in sec["cleared"]}
    # the release source read fresh and lists no ci:OrganD:Rel either
    assert cleared == {"ci:OrganC:Gone", "ci:OrganD:Rel"}
    assert sec["counts"]["status"] == {"open": 2, "promoted": 1, "in-progress": 1,
                                       "done": 1, "cleared": 2}


def test_unread_source_is_shown_unread_and_never_clears(tmp_path):
    sec, _ = _section(tmp_path, heart=False)
    assert sec["unread"] == ["release"]
    assert "UNREAD" in H.headline(sec) and "not all-clear" in H.headline(sec)
    md = "\n".join(H.render_md(sec))
    assert re.search(r"release: UNREAD — .*not all-clear", md)
    # a key filed from the unread source is never cleared; a fresh source's is
    assert {r["key"] for r in sec["cleared"]} == {"ci:OrganC:Gone"}


def test_no_mind_is_unknown_status_not_open(tmp_path):
    inputs = _inputs(tmp_path)
    result = _maintain.read_sources(_maintain.SOURCES, **inputs)
    sec = H.collect(tmp_path / "absent_mind", reader=lambda: result)
    assert {r["status"] for r in sec["findings"]} == {"unknown"}
    assert "statuses unknown" in H.headline(sec) and sec["cleared"] == []


def test_a_failing_read_fails_this_section_only(tmp_path):
    def boom():
        raise RuntimeError("board unreachable")
    sec = H.collect(tmp_path, reader=boom)
    assert sec["error"].startswith("RuntimeError")
    assert "UNREAD" in H.headline(sec)
    page = "".join(H.render_html(sec, lambda s: s, lambda *a, **k: "", lambda s: s))
    assert 'id="homeostasis"' in page and "UNREAD" in page


def _board_env(tmp_path, heart=True):
    stub = _fabricate(tmp_path, _default_fixtures())
    _fixture_mind(tmp_path / "PyAutoMind")
    inputs = _inputs(tmp_path, heart)
    env = {"BOARD_HOMEOSTASIS": "1", "HEART_STATE_DIR": str(tmp_path / "no_heart_state"),
           **{H.INPUT_ENV[k]: v for k, v in inputs.items()}}
    return stub, env


def test_board_renders_the_section_and_writes_the_sidecar_only_on_apply(tmp_path):
    stub, env = _board_env(tmp_path)
    r = _run(["--html"], tmp_path, stub, env)
    assert r.returncode == 0, r.stderr
    assert "<h2>Homeostasis (maintenance orchestrator)</h2>" in r.stdout
    assert 'href="#homeostasis"' in r.stdout and "promoted" in r.stdout
    md = _run([], tmp_path, stub, env).stdout
    assert "## Homeostasis (maintenance orchestrator)" in md
    assert "| ci:OrganB:Docs | monitoring | judge | OrganB | in-progress" in md
    assert not list(tmp_path.rglob(H.SIDECAR)), "no sidecar without --apply"
    out = tmp_path / "site"
    r = _run(["--apply", "--out", str(out)], tmp_path, stub, env)
    assert r.returncode == 0, r.stderr
    assert H.SIDECAR in r.stdout
    side = json.loads((out / H.SIDECAR).read_text())
    board = json.loads((out / "board.json").read_text())
    assert side["count"] == len(side["findings"]) == board["homeostasis"]["count"] > 0
    assert "findings" not in board["homeostasis"]
    assert board["homeostasis"]["sidecar"] == H.SIDECAR


def test_board_without_opt_in_collects_nothing_and_writes_no_sidecar(tmp_path):
    stub = _fabricate(tmp_path, _default_fixtures())
    out = tmp_path / "site"
    r = _run(["--apply", "--out", str(out)], tmp_path, stub, {"BOARD_HOMEOSTASIS": ""})
    assert r.returncode == 0, r.stderr
    assert not (out / H.SIDECAR).exists()
    assert "not collected this render" in (out / "board.md").read_text()


# --- the Mind dashboard split -------------------------------------------------------

REPOS_YAML = "repos:\n  PyAutoMind:\n    github: ExampleOrg/PyAutoMind\n"


def _ordinary(title, priority="high"):
    return (f"# {title}\n\nType: feature\nTarget: widgets\nDifficulty: small\n"
            f"Autonomy: supervised\nPriority: {priority}\nStatus: formalised\n"
            f"Consequence: glance\nWitness: a test\nReview-minutes: 5\nLane: any\n"
            f"Unattended: ready\n\nBody.\n")


def _dash_mind(tmp_path):
    glance = _gen("ci:OrganA:Pages", tier="glance").replace("Priority: normal",
                                                             "Priority: high")
    judge = _gen("ci:OrganB:Docs", title="Maintenance: judge me").replace(
        "Priority: normal", "Priority: high")
    return _write(tmp_path / "mind", {
        "repos.yaml": REPOS_YAML,
        "draft/maintenance/organa/maint_glance_one.md": glance,
        "draft/maintenance/organa/maint_glance_two.md": glance.replace(
            "ci:OrganA:Pages", "ci:OrganA:Other"),
        "draft/maintenance/organb/maint_judge.md": judge,
        "draft/feature/widgets/ordinary.md": _ordinary("Ordinary pick"),
    })


def _start_here_md(page):
    return page[page.index("## Start here"):page.index("## Epics")]


def test_generated_glance_leaves_every_pickable_list(tmp_path):
    c = _intake.census(_dash_mind(tmp_path))
    page = _intake.render_dashboard(c)
    html = _intake.render_dashboard_html(c)
    picks_md = _start_here_md(page).split("<summary>Homeostasis")[0]
    assert "maint_glance" not in picks_md and "maint_judge" not in picks_md
    assert "draft/feature/widgets/ordinary.md" in picks_md
    for section in (page[page.index("## Backlog"):], html[html.index('id="backlog"'):]):
        assert "maint_glance" not in section
    assert "maint_glance" not in html
    assert "maint_glance" not in json.dumps(json.loads(_intake.render_state(c))["items"])
    assert {r["path"] for r in _intake._start_here_picks(c)} == {
        "draft/feature/widgets/ordinary.md"}


def test_one_collapsed_homeostasis_line_with_count_and_board_link(tmp_path):
    c = _intake.census(_dash_mind(tmp_path))
    page = _intake.render_dashboard(c)
    html = _intake.render_dashboard_html(c)
    line = "Homeostasis (maintenance orchestrator): 2 generated glance prompt(s) — see the Brain board"
    assert page.count(line) == 1 and html.count(line) == 1
    assert f"<details>\n<summary>{line}</summary>" in page
    board = c["homeostasis"]["board"]
    assert board.startswith("https://exampleorg.github.io/") and board.endswith("#homeostasis")
    assert f"({board})" in page and f'href="{board}"' in html
    item = [i for i in json.loads(_intake.render_state(c))["items"] if i["text"] == line]
    assert item and item[0]["url"] == board


def test_generated_judge_is_in_the_promoted_group_with_its_copy_row(tmp_path):
    c = _intake.census(_dash_mind(tmp_path))
    page = _intake.render_dashboard(c)
    html = _intake.render_dashboard_html(c)
    group = page[page.index("Promoted from Homeostasis"):]
    group = group[:group.index("</details>\n\n</details>") + 30]
    assert "<b>Promoted from Homeostasis (maintenance orchestrator)</b> — 1" in page
    assert "Use the start-dev skill. draft/maintenance/organb/maint_judge.md" in group
    assert page.count("draft/maintenance/organb/maint_judge.md\">") == 2  # group + Recent
    hgroup = html[html.index('<details id="promoted-homeostasis">'):]
    hgroup = hgroup[:hgroup.index("</details>")]
    assert 'data-cmd="Use the start-dev skill. draft/maintenance/organb/maint_judge.md"' in hgroup


def test_ordinary_prompts_unchanged_and_census_keeps_all_marked(tmp_path):
    mind = _dash_mind(tmp_path)
    c = _intake.census(mind)
    marks = {r["path"]: r["generated"] for r in c["records"]}
    assert marks == {"draft/maintenance/organa/maint_glance_one.md": "glance",
                     "draft/maintenance/organa/maint_glance_two.md": "glance",
                     "draft/maintenance/organb/maint_judge.md": "judge",
                     "draft/feature/widgets/ordinary.md": ""}
    # with no generated prompt, the page is exactly the ordinary page
    bare = _write(tmp_path / "bare", {"repos.yaml": REPOS_YAML,
                                      "draft/feature/widgets/ordinary.md":
                                          _ordinary("Ordinary pick")})
    cb = _intake.census(bare)
    assert "Homeostasis" not in _intake.render_dashboard(cb)
    assert "Homeostasis" not in _intake.render_dashboard_html(cb)
    assert _start_here_md(_intake.render_dashboard(c)).split("<details>\n<summary>Homeostasis")[0] \
        == _start_here_md(_intake.render_dashboard(cb))


# --- the writer ------------------------------------------------------------------------

def test_writer_priority_capped_at_normal(tmp_path):
    red = _maintain.Finding(
        key="ci:OrganA:tests", source="monitoring", repo="OrganA", paths=[],
        summary="[red] ci_status", witness="w", tier_floor="glance", lane="any",
        evidence={"status": "red"})
    assert W._priority(red) == "high"            # its own priority still ranks it
    assert W.prompt_priority(red) == "normal"    # the prompt carries it capped
    text = W.draft_text(red, {"source": "x", "age_hours": 1.0}, "2026-11-28",
                        target="organa", lane="any", difficulty="small",
                        unattended="ready", review_minutes=5)
    assert "Priority: normal" in text and "Priority: high" not in text

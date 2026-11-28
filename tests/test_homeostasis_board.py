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
    assert re.search(r"Heart release check: UNREAD — .*not all-clear", md)
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
    assert 'href="#homeostasis"' in r.stdout and H.NEXT_PROMOTED in r.stdout
    # the Mind links come from the board family (policy `board.boards.mind`)
    assert "/PyAutoMind/blob/main/active/maint_b.md" in r.stdout
    md = _run([], tmp_path, stub, env).stdout
    assert "## Homeostasis (maintenance orchestrator)" in md
    assert "| `Docs · OrganB` | Latest run: failure | Being fixed ([Mind prompt](" in md
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


# --- the section reads plainly (PyAutoBrain#749) ------------------------------------

import html as _html  # noqa: E402

LONG_PROMPT = ("draft/maintenance/ws_gamma_test/"
               "maint_no_run_ws_gamma_test_imaging_visualization_modelin.md")
OLD_ROW_FIELDS = {"key", "source", "tier", "repo", "status", "note", "mind_path",
                  "stale", "witness", "summary"}


MIND_PAGES = "https://exampleorg.github.io/ExampleMind/"


def _page(sec, org="ExampleOrg", mind_pages=MIND_PAGES):
    return "\n".join(H.render_html(sec, _html.escape, lambda *a, **k: "",
                                   lambda s: f"<p>{s}</p>", org, mind_pages))


def _md(sec):
    return "\n".join(H.render_md(sec, "ExampleOrg", MIND_PAGES))


def _cells(page):
    """Each table cell's visible text (tags and attributes stripped)."""
    return [_html.unescape(re.sub(r"<[^>]+>", "", c))
            for c in re.findall(r"<td[^>]*>(.*?)</td>", page, re.S)]


def test_intro_says_what_the_section_is_and_that_nothing_runs(tmp_path):
    sec, _ = _section(tmp_path)
    page, md = _page(sec), "\n".join(H.render_md(sec))
    for text in (_html.unescape(re.sub(r"<[^>]+>", "", page)), md):
        assert H.INTRO.split('"Promoted')[0] in text
        assert "Nothing runs from this page." in text
        assert '"Could run unattended"' in text and '"Needs you"' in text
    assert 'href="https://exampleorg.github.io/ExampleMind/#promoted-homeostasis"' in page
    assert page.index(H.INTRO[:40]) < page.index("<details")


def test_counts_are_plain_words_and_keep_the_not_all_clear_flags(tmp_path):
    sec, _ = _section(tmp_path)
    assert H.headline(sec) == ("5 problems reported · 1 could run unattended · 4 need you"
                               " · 1 waiting on you in Mind · 1 being fixed"
                               " · 1 closed, waiting for a fresh check"
                               " · 2 no longer reported")
    unread, _ = _section(tmp_path / "u", heart=False)
    assert H.headline(unread).startswith("5 problems reported")
    assert "UNREAD" in H.headline(unread) and "not all-clear" in H.headline(unread)


def test_kind_of_every_key_prefix():
    assert {k: H.kind_of(k) for k in (
        "no_run:r/a.py", "smoke:r:a", "escapes:r:f:latex-escapes", "docstrings:r:f:x",
        "refs:r:f:x", "optdeps:r:f:dep", "extras:::dep", "ci:R:wf", "timing:gate:r:wf",
        "wf:legacy", "weird")} == {
        "no_run:r/a.py": "no_run", "smoke:r:a": "smoke",
        "escapes:r:f:latex-escapes": "escapes", "docstrings:r:f:x": "docstrings",
        "refs:r:f:x": "refs", "optdeps:r:f:dep": "deps", "extras:::dep": "deps",
        "ci:R:wf": "ci", "timing:gate:r:wf": "timing", "wf:legacy": "other",
        "weird": "other"}


def test_findings_are_grouped_by_kind_with_counts_and_one_sentence(tmp_path):
    sec, _ = _section(tmp_path)
    assert sec["counts"]["kind"] == {"no_run": 2, "ci": 2, "refs": 1}
    page, md = _page(sec), "\n".join(H.render_md(sec))
    order = [page.index(f"<summary>{H.KIND_TITLE[k]} ({n})</summary>")
             for k, n in (("no_run", 2), ("ci", 2), ("refs", 1))]
    assert order == sorted(order)
    for kind, title, text in H.KINDS:
        present = kind in sec["counts"]["kind"]
        assert (_html.escape(text) in page) is present
        assert (f"### {title} (" in md) is present
    assert "| What | Why | Next |" in md
    assert "Findings (" not in page


def test_rows_say_what_why_and_next_in_plain_words(tmp_path):
    sec, _ = _section(tmp_path)
    rows = {r["key"]: r for r in sec["findings"]}
    assert {k: r["next"] for k, r in rows.items()} == {
        "ci:OrganA:Pages Dashboard": H.NEXT_PROMOTED,
        "ci:OrganB:Docs": H.NEXT_ACTIVE,
        # done: its record is complete, but a source still reports the key
        "no_run:ws_alpha/imaging/slow_one": H.NEXT_CLOSED,
        "no_run:ws_beta/graphical/ep.py": H.NEXT_JUDGE,
        REFS_KEY: H.NEXT_QUEUED}
    assert "Fixed" not in _page(sec) and "Fixed" not in _md(sec)
    assert rows["no_run:ws_beta/graphical/ep.py"]["what"] == "ep · ws_beta"
    assert rows["ci:OrganA:Pages Dashboard"]["what"] == "Pages Dashboard · OrganA"
    cells = _cells(_page(sec))
    # the finding's own summary is shown (not only its key)
    assert "Marked NEEDS_FIX since 2026-08-03: EP parked" in cells
    assert "Marked SLOW since 2026-07-30: times out at the 300s cap" in cells
    assert any(c.startswith(H.NEXT_PROMOTED + " Mind prompt") for c in cells)
    # keys and witnesses are tooltips, not cells
    assert not [c for c in cells if "no_run:" in c or "witness" in c]


def test_a_long_path_is_never_printed_in_a_cell(tmp_path):
    sec, _ = _section(tmp_path)
    long_key = ("no_run:ws_gamma_test/imaging/visualization/"
                "modeling_visualization_jit")
    sec["findings"].append(dict(sec["findings"][0], key=long_key, kind=H.kind_of(long_key),
                                repo="ws_gamma_test", status="promoted",
                                mind_path=LONG_PROMPT, next=H.NEXT_PROMOTED,
                                summary="SLOW since 2026-07-30: times out in "
                                        "ws_gamma_test/scripts/imaging/"
                                        "visualization/modeling_visualization_jit.py"))
    H.name_rows(sec["findings"])
    page = _page(sec)
    cells = _cells(page)
    assert "modeling_visualization_jit · ws_gamma_test" in cells
    for c in cells:
        assert LONG_PROMPT not in c and "maint_no_run" not in c, c
        assert not re.search(r"\S+/\S+/\S+/\S+", c), c  # no path deeper than two parts
    # the prompt is a short link: its path only in the href and the tooltip
    assert (f'<a href="https://github.com/ExampleOrg/ExampleMind/blob/main/{LONG_PROMPT}" '
            f'title="{LONG_PROMPT}">Mind prompt</a>') in page
    md = "\n".join(H.render_md(sec, "ExampleOrg", MIND_PAGES))
    assert f"[Mind prompt](https://github.com/ExampleOrg/ExampleMind/blob/main/{LONG_PROMPT})" in md


def test_names_that_clash_get_just_enough_folders():
    rows = [{"key": f"escapes:ws:scripts/{mode}/features/{f}/likelihood_function.py:x",
             "repo": "ws", "kind": "escapes"}
            for mode in ("imaging", "interferometer") for f in ("pixelization", "mge")]
    rows.append({"key": "escapes:ws:scripts/other.py:x", "repo": "ws", "kind": "escapes"})
    H.name_rows(rows)
    assert [r["what"] for r in rows] == [
        "imaging/…/pixelization/likelihood_function · ws",
        "imaging/…/mge/likelihood_function · ws",
        "interferometer/…/pixelization/likelihood_function · ws",
        "interferometer/…/mge/likelihood_function · ws",
        "other · ws"]


def test_cleared_is_its_own_no_longer_reported_block(tmp_path):
    sec, _ = _section(tmp_path)
    page, md = _page(sec), "\n".join(H.render_md(sec, "ExampleOrg", MIND_PAGES))
    assert "<summary>No longer reported (2)</summary>" in page
    assert _html.escape(H.CLEARED_TEXT) in page and H.CLEARED_TEXT in md
    assert "### No longer reported (2)" in md
    assert "Cleared (" not in page and "Cleared (" not in md
    assert "<code title=\"ci:OrganC:Gone\">Gone · OrganC</code>" in page
    assert ("- `Gone · OrganC` — prompt still open: [Mind prompt](https://github.com/"
            "ExampleOrg/ExampleMind/blob/main/draft/maintenance/organc/maint_gone.md)") in md
    assert "Gone · OrganC</code> — prompt still open: <a href=" in page


def test_source_lines_are_plain_names_with_no_absolute_paths():
    rows = [
        {"source": "monitoring", "ok": True, "stale": False, "partial": False,
         "from": "/home/runner/work/PyAutoBrain/PyAutoBrain/_inputs/board.json",
         "why": "", "age_hours": 1.23},
        {"source": "hygiene:refs", "ok": True, "stale": True, "partial": False,
         "from": "published hygiene ledger, day 2026-11-28", "why": "",
         "age_hours": 12.4},
        {"source": "release", "ok": False, "stale": False, "partial": False,
         "from": "none", "why": "cannot read /home/runner/work/x/heart.json",
         "age_hours": None},
    ]
    lines = [H.read_line(r) for r in rows]
    assert lines[0] == "Heart board (1.2 h old)"
    assert lines[1].startswith("hygiene ledger: broken references, 2026-11-28 (12 h old)"
                               " — STALE")
    assert lines[2] == ("Heart release check: UNREAD — cannot read heart.json. "
                        "Problems from it are not all-clear.")
    assert not [ln for ln in lines if "/home/" in ln]
    sec = {"title": H.TITLE, "count": 0, "unread": ["release"], "stale": ["hygiene:refs"],
           "mind": "read", "reads": rows, "findings": [], "cleared": [],
           "counts": {"source": {}, "tier": {}, "status": {}, "kind": {}}}
    page = _page(sec)
    assert "/home/" not in page and "<summary>Sources read (3)</summary>" in page
    assert "/home/" not in "\n".join(H.render_md(sec))


def test_sidecar_keeps_every_old_field_and_adds_the_plain_words(tmp_path):
    sec, _ = _section(tmp_path)
    side = H.sidecar(sec)
    assert {"title", "count", "unread", "stale", "mind", "reads", "counts", "findings",
            "cleared", "schema"} <= set(side)
    assert {"source", "tier", "status"} <= set(side["counts"])
    for r in side["findings"]:
        assert OLD_ROW_FIELDS | {"kind", "what", "next"} <= set(r)
    for r in side["cleared"]:
        assert {"key", "where", "path", "tier", "source"} <= set(r)
    # a row from an older sidecar (no plain-word fields) still renders
    old = dict(sec, findings=[{k: r[k] for k in OLD_ROW_FIELDS} for r in sec["findings"]])
    assert _cells(_page(old)) == _cells(_page(sec))


def _finding(key, tier="judge", stale=False, source="monitoring", evidence=None):
    return _maintain.Finding(key=key, source=source, repo="OrganX", paths=[],
                             summary="[red] ci_status: OrganX/workflows/x — failure",
                             witness="w", tier_floor=tier, lane="any",
                             evidence=evidence or {}, stale=stale)


def test_next_never_says_fixed_or_promises_a_run_before_the_gate(tmp_path):
    mind = _write(tmp_path / "mind", {
        "draft/maintenance/organx/maint_q.md": _gen("ci:OrganX:Queued", tier="glance"),
        "complete/2026/11/closed.md": "# Record\n\n" + _gen("ci:OrganX:Closed")})
    found = [_finding("ci:OrganX:Queued", "glance"), _finding("ci:OrganX:Fresh", "glance"),
             _finding("ci:OrganX:Closed"), _finding("ci:OrganX:Release"),
             _finding("ci:OrganX:Old", "glance", stale=True), _finding("ci:OrganX:Judge"),
             _finding("ci:OrganX:Timing", source="release",
                      evidence={"rule": "unit-test", "timing": True})]
    sec = H.build({}, {"monitoring": found}, found, mind)
    nxt = {r["key"]: r["next"] for r in sec["findings"]}
    assert nxt == {
        "ci:OrganX:Queued": "Queued — runs unattended once the M3 gate opens",
        "ci:OrganX:Fresh": "Not filed yet — could run unattended once the M3 gate opens",
        "ci:OrganX:Closed": "Task closed — waiting for a fresh check",  # done, still reported
        "ci:OrganX:Release": "Needs you — not filed automatically",  # release-execution
        "ci:OrganX:Old": "Not checked fresh — re-check first",
        "ci:OrganX:Judge": "Needs you — not filed yet",
        "ci:OrganX:Timing": "Needs you — not filed automatically"}  # release timing line
    assert {r["key"]: r["status"] for r in sec["findings"]}["ci:OrganX:Closed"] == "done"
    assert {r["key"] for r in sec["findings"] if r["human_only"]} == {
        "ci:OrganX:Release", "ci:OrganX:Timing"}
    page = _page(sec)
    assert "Fixed" not in page and "Could run in a maintenance shift" not in page


def test_no_abs_paths_leaves_urls_alone():
    why = ("cannot fetch the hygiene ledger at "
           "https://exampleorg.github.io/PyAutoBrain/hygiene_ledger.jsonl: HTTP 404; "
           "local copy /home/runner/work/x/hygiene_ledger.jsonl missing")
    assert H.no_abs_paths(why) == (
        "cannot fetch the hygiene ledger at "
        "https://exampleorg.github.io/PyAutoBrain/hygiene_ledger.jsonl: HTTP 404; "
        "local copy hygiene_ledger.jsonl missing")
    line = H.read_line({"source": "hygiene", "ok": False, "stale": False, "partial": False,
                        "from": "none", "why": why, "age_hours": None})
    assert "https://exampleorg.github.io/PyAutoBrain/hygiene_ledger.jsonl" in line
    assert "https:/hygiene" not in line and "/home/" not in line


def test_a_cleared_key_from_a_record_is_not_called_an_open_prompt(tmp_path):
    sec, _ = _section(tmp_path)
    sec["cleared"].append({"key": "ci:OrganE:Old", "where": "complete", "tier": "judge",
                           "path": "complete/2026/11/old.md", "source": "monitoring",
                           "kind": "ci", "what": "Old · OrganE"})
    page, md = _page(sec), _md(sec)
    assert "Old · OrganE</code> — <a href=" in page and ">Mind record</a>" in page
    assert ("- `Old · OrganE` — [Mind record](https://github.com/ExampleOrg/ExampleMind/"
            "blob/main/complete/2026/11/old.md)") in md
    assert "Gone · OrganC</code> — prompt still open:" in page
    assert "for each is still open" not in H.CLEARED_TEXT


def test_mind_links_come_from_the_board_family_never_a_guess():
    assert H.mind_links("ExampleOrg", "https://exampleorg.github.io/OtherMind/") == {
        "blob": "https://github.com/ExampleOrg/OtherMind/blob/main/",
        "promoted": "https://exampleorg.github.io/OtherMind/#promoted-homeostasis"}
    assert H.mind_links("ExampleOrg", "") == {} and H.mind_links("", MIND_PAGES) == {}
    assert H.mind_links("ExampleOrg", "https://exampleorg.github.io") == {}


def test_without_the_mind_board_prompts_are_named_not_linked(tmp_path):
    sec, _ = _section(tmp_path)
    page = _page(sec, mind_pages="")
    assert "github.com" not in page and "#promoted-homeostasis" not in page
    assert 'title="draft/maintenance/organa/maint_a.md">(Mind prompt)</span>' in page


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


# --- review follow-ups (PyAutoBrain#747) ----------------------------------------------

def test_a_stale_source_with_no_findings_is_never_green_or_all_clear(tmp_path):
    stale = {"ok": True, "stale": True, "partial": False, "source": "fixture",
             "why": "", "age_hours": 9.0}
    fresh = dict(stale, stale=False, age_hours=1.0)
    for reads in ({"monitoring": stale, "release": fresh},
                  {"monitoring": dict(fresh, partial=True, why="absent_repos x"),
                   "release": fresh}):
        sec = H.collect(_write(tmp_path / "m", {"draft/x.md": "# x\n"}),
                        reader=lambda reads=reads: (reads, {}, []))
        assert sec["count"] == 0 and sec["stale"] == ["monitoring"]
        assert "stale/partial (monitoring): not all-clear" in H.headline(sec)
        assert not H.all_clear_reads(sec)
        tones = []
        H.render_html(sec, lambda s: s,
                      lambda *vals, **k: tones.extend(t for _v, t in vals) or "",
                      lambda s: s)
        assert tones[0] == "y"
    sec = H.collect(tmp_path / "m", reader=lambda: ({"release": fresh}, {}, []))
    assert H.all_clear_reads(sec) and "not all-clear" not in H.headline(sec)


def test_a_closed_task_whose_key_is_still_reported_says_so(tmp_path):
    mind = _fixture_mind(tmp_path / "mind")
    # A `lifecycle.py close` record: names the key in prose, no Source-key mark.
    _write(mind, {"complete/2026/11/closed_ep.md":
                  "# Closed\n\nFixed no_run:ws_beta/graphical/ep.py upstream.\n"})
    result = _maintain.read_sources(_maintain.SOURCES, **_inputs(tmp_path))
    sec = H.collect(mind, reader=lambda: result)
    row = {r["key"]: r for r in sec["findings"]}["no_run:ws_beta/graphical/ep.py"]
    assert row["status"] == "open" and row["note"] == H.CLOSED_NOTE
    assert row["mind_path"] == "complete/2026/11/closed_ep.md"
    assert row["next"] == H.NEXT_CLOSED and H.NEXT_CLOSED in "\n".join(H.render_md(sec))
    # a key no record mentions stays plain open
    plain = {r["key"]: r for r in sec["findings"]}["ci:OrganA:Pages Dashboard"]
    assert plain["note"] == ""


def test_system_exit_is_contained_to_the_section(tmp_path):
    def bye():
        raise SystemExit(4)
    sec = H.collect(tmp_path, reader=bye)
    assert sec["error"].startswith("SystemExit") and "UNREAD" in H.headline(sec)


def test_a_hung_read_times_out_as_unread(tmp_path):
    import threading
    release = threading.Event()
    sec = H.collect(tmp_path, reader=lambda: release.wait(30), timeout=0.2)
    release.set()
    assert sec["error"] == "timed out after 0.2 s"
    assert "UNREAD this render (timed out" in H.headline(sec)


def test_feed_only_never_runs_the_local_readiness_cli(monkeypatch):
    import _green
    hf = _green._hf()
    calls = []
    monkeypatch.setattr(_green, "_hf", lambda: hf)
    monkeypatch.setattr(hf, "local_readiness", lambda *a, **k: calls.append(1) or (None, "x"))
    monkeypatch.setattr(hf, "feed_url", lambda: ("https://example.invalid/state.json", None))
    monkeypatch.setattr(hf, "fetch_feed", lambda url: ({"status": "green", "updated": TS,
                                                        "items": []}, None))
    monkeypatch.setenv(H.FEED_ONLY_ENV, "1")
    assert H.FEED_ONLY_ENV == _maintain.FEED_ONLY_ENV
    r = _maintain.load_release()
    assert calls == [] and r["source"] == "published feed" and r["ok"]
    monkeypatch.delenv(H.FEED_ONLY_ENV)
    _maintain.load_release()
    assert calls == [1]  # unset: batch maintain's read, local CLI first


def test_promoted_summary_survives_the_state_item_cap(tmp_path):
    files = {"repos.yaml": REPOS_YAML,
             "draft/maintenance/organb/maint_judge.md": _gen("ci:OrganB:Docs")}
    for i in range(14):
        files[f"draft/feature/widgets/high_{i:02}.md"] = _ordinary(f"High {i}").replace(
            "Unattended: ready", "Unattended: never")
        files[f"draft/feature/widgets/ready_{i:02}.md"] = _ordinary(f"Ready {i}", "normal")
    c = _intake.census(_write(tmp_path / "mind", files))
    items = json.loads(_intake.render_state(c))["items"]
    assert len(items) == _intake.STATE_ITEM_CAP
    summary = [i for i in items if i["text"].startswith(_intake.PROMOTED_TITLE)]
    assert summary and summary[0]["severity"] == "yellow"
    assert summary[0]["text"] == ("Promoted from Homeostasis (maintenance orchestrator): "
                                  "1 prompt(s) need you — see the dashboard")
    assert summary[0]["url"].endswith("#promoted-homeostasis")
    assert not [i for i in items if i["text"].startswith("promoted from Homeostasis:")]


def test_a_copied_source_key_header_alone_does_not_hide_a_hand_written_prompt(tmp_path):
    copied = _ordinary("Hand-written fix").replace(
        "Unattended: ready\n", "Unattended: ready\nSource-key: ci:OrganA:Pages\n")
    c = _intake.census(_write(tmp_path / "mind", {
        "repos.yaml": REPOS_YAML, "draft/feature/widgets/hand.md": copied}))
    assert c["records"][0]["generated"] == "" and c["homeostasis"]["glance"] == 0
    assert "draft/feature/widgets/hand.md" in {r["path"] for r in _intake._start_here_picks(c)}


def test_a_hand_written_prompt_quoting_a_mark_is_not_a_cleared_key(tmp_path):
    quoted = ("# Close-out carries the key\n\nType: feature\nWitness: the record keeps "
              "`Source-key: <key>` (and the writer's `<!-- maint-key: … -->` mark)\n")
    assert W.generated_keys(quoted) == set()
    assert W.generated_keys(_gen("ci:OrganA:x")) == {"ci:OrganA:x"}
    assert W.generated_keys("<!-- heart-key: wf:legacy -->") == {"wf:legacy"}
    mind = _fixture_mind(tmp_path / "mind")
    _write(mind, {"draft/feature/pyautomind/quoted.md": quoted})
    result = _maintain.read_sources(_maintain.SOURCES, **_inputs(tmp_path))
    sec = H.collect(mind, reader=lambda: result)
    assert "draft/feature/pyautomind/quoted.md" not in {r["path"] for r in sec["cleared"]}

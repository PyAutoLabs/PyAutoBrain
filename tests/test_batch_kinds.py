"""tests/test_batch_kinds.py — the batch conductor's second member kind.

One rule shapes every test here, and it is `PyAutoCortex/batches/AGENTS.md`'s:
**a science batch is a rolling board, not a dispatch.** A phase joins the
review when its results are pulled; nothing in `submitted`/`running` holds
review control; carry-forward — not an unclickable chip — moves an unfinished
member to the next board. So most of these are refusals too: refusals to give
a running member a decision it cannot honestly make, refusals to write the
Mind's vocabulary into a Cortex record, and refusals to plan a laptop board
from a session that is not at the laptop.

The fixture is two organs at once: a mini Mind (as `test_batch_collect.py`
raises one) and the science board of `tests/_cortex_board.py`, over the real
PyAutoCortex checkout's `tests/fixtures/skeleton`. With no Cortex checked out
every test skips, as the conductor's own suite does.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_kinds_under_test",
    BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_kinds_under_test"] = _batch
_spec.loader.exec_module(_batch)

from _cortex_board import build_board  # noqa: E402 - tests/ is on sys.path

STAMP = "2026-09-03T12:00Z"
DISPATCHED = "2026-09-03T18:40Z"
REVIEW_AT = "2026-09-03T21:00Z"
AM = "2026-09-02-am"

PROMPT = """# Add a resampling info section

Type: bug
Target: autofit
Witness: the new section appears in search.summary and a unit test pins it

The bottom of `search.summary` says nothing about resampling.
"""

DEV_RECORD = """# Batch 2026-09-03 pm
- dispatched: 2026-09-03T17:40Z
- review-at: 2026-09-04T08:00Z
- lane: any
- review-minutes-planned: 3
- members:
  - resampling: draft/bug/autofit/resampling.md — glance — 3 — session ended green
"""


def cortex_root() -> Path:
    """The real PyAutoCortex checkout, or skip."""
    env = os.environ.get("PYAUTO_CORTEX")
    for candidate in ([Path(env)] if env else []) + [BRAIN.parent / "PyAutoCortex"]:
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
def two_organ(tmp_path, skeleton):
    """A Mind and a Cortex side by side, each with its own `batches/`."""
    mind = tmp_path / "mind"
    (mind / "batches" / "packets").mkdir(parents=True)
    (mind / "batches" / "reviews").mkdir(parents=True)
    (mind / "draft" / "bug" / "autofit").mkdir(parents=True)
    (mind / "active").mkdir(parents=True)
    (mind / "draft" / "bug" / "autofit" / "resampling.md").write_text(
        PROMPT, encoding="utf-8")
    (mind / "batches" / "2026-09-03-pm.md").write_text(DEV_RECORD,
                                                       encoding="utf-8")
    (mind / "active.md").write_text("# Active Tasks\n", encoding="utf-8")
    board = build_board(tmp_path, skeleton)
    board["mind"] = mind
    return board


def ctx_of(board) -> dict:
    return _batch.cortex_context(str(board["root"]))


def cli(board, *args, kind="cortex") -> int:
    return _batch.main(["collect" if args and args[0] == "collect" else "plan",
                        *[a for a in args if a != "collect"],
                        "--kind", kind, "--cortex", str(board["root"]),
                        "--mind", str(board["mind"])])


def record_text(board, slot=AM) -> str:
    return (board["root"] / "batches" / f"{slot}.md").read_text(
        encoding="utf-8")


def packet_text(board, slot=AM) -> str:
    return (board["root"] / "batches" / "packets" / f"{slot}.html").read_text(
        encoding="utf-8")


def spans(page: str) -> dict:
    """`{member id: its whole <section>}` — what a refresh must not disturb."""
    return {mid: page[start:end]
            for start, end, mid in _batch._member_spans(page)}


def set_run_state(board, rel: str, state: str) -> None:
    """Flip a phase's run line. A live run line is the difference between a
    member the board may move on and one it may not."""
    path = board["root"] / rel
    text = path.read_text(encoding="utf-8")
    line = next(ln for ln in text.split("\n") if re.match(r"^- \d+", ln))
    head, _sep, tail = line.partition(": ")
    path.write_text(text.replace(
        line, f"{head}: {state}{tail[tail.index(' —'):]}"), encoding="utf-8")


def check(board) -> list:
    mod = _batch.load_cortex_conductor().load_cortex(board["root"])
    return mod.check_problems(board["root"])


# --------------------------------------------------------------- the kinds --
def test_a_local_session_offers_both_kinds_and_a_cloud_one_only_dev(
        two_organ, capsys):
    """Every Cortex phase is `local-dev` — the review happens at the laptop.
    A cloud session is therefore offered the dev board and TOLD the science
    count, rather than shown a board it cannot run."""
    assert _batch.default_kinds("local-dev") == "both"
    assert _batch.default_kinds("web-github") == "dev"

    rc = _batch.main(["plan", "--mind", str(two_organ["mind"]),
                      "--cortex", str(two_organ["root"]),
                      "--lane", "web-github"])
    out = capsys.readouterr().out
    assert rc == _batch.RC_OK
    assert "== BatchDecision ==" in out and "== CortexPlan ==" not in out
    assert "phases/example/03_ready_cleared.md" not in out
    assert "1 Cortex phase(s) are ready" in out
    assert "from the laptop" in out


def test_plan_cortex_applies_the_phase_two_rule_not_the_autonomy_cap(
        two_organ):
    """A science member is supervised by definition and the ruling is the
    human's, so there is no autonomy cap to reject it against — the admission
    rule is `ready` + a registered witness + a budget + the lane, whole."""
    root = two_organ["root"]
    ready = (root / "phases/example/03_ready_cleared.md").read_text(
        encoding="utf-8")
    assert "Autonomy:" not in ready, "a phase file has no autonomy header"
    witnessless = ready.replace(
        "Witness: anchor lens theta_E within 0.01 arcsec of the published value\n",
        "").replace("# Example — phase 3:", "# Example — phase 13:").replace(
        "Phase: 3", "Phase: 13")
    (root / "phases/example/13_no_witness.md").write_text(witnessless,
                                                          encoding="utf-8")
    assert check(two_organ) == [], "the fixture must stay a tree that checks"

    ctx = ctx_of(two_organ)
    d = _batch.plan_cortex(ctx, budget=45, lane="local-dev")
    assert [r["rel"] for r in d["members"]] == [
        "phases/example/03_ready_cleared.md"]
    why = dict(d["rejected"])["phases/example/13_no_witness.md"]
    assert "no Witness" in why


def test_plan_apply_writes_the_cortex_schema_and_the_tree_still_checks(
        two_organ, capsys):
    rc = cli(two_organ, "--lane", "local-dev", "--apply",
             "--review-at", REVIEW_AT, "--slot", "2026-09-03-pm",
             "--stamp", DISPATCHED)
    capsys.readouterr()
    assert rc == _batch.RC_OK
    text = record_text(two_organ, "2026-09-03-pm")
    keys = [ln.split(":")[0][2:] for ln in text.split("\n")
            if ln.startswith("- ")]
    assert keys[:7] == ["dispatched", "review-at", "shift", "lane",
                        "review-minutes-planned", "carried-from", "members"]
    assert text.startswith("# Batch 2026-09-03 pm\n")
    assert ("  - 03_ready_cleared: phases/example/03_ready_cleared.md — none "
            "— 4 — ready") in text
    # The organ's own schema drops both, on purpose: the Heart gates releases,
    # not runs, and a science batch has no autonomy leg to license.
    assert "heart-ack" not in text and "expected-effects" not in text
    assert " -- " not in text, "em dash, not two hyphens"
    assert check(two_organ) == []


def test_plan_apply_refuses_without_a_review_at_and_never_overwrites(
        two_organ, capsys):
    """`review-at:` is the shift, and it is the human's to declare."""
    rc = cli(two_organ, "--lane", "local-dev", "--apply",
             "--slot", "2026-09-03-pm")
    err = capsys.readouterr().err
    assert rc == _batch.RC_USAGE
    assert "--review-at" in err
    assert not (two_organ["root"] / "batches/2026-09-03-pm.md").exists()

    assert cli(two_organ, "--lane", "local-dev", "--apply", "--review-at",
               REVIEW_AT, "--slot", "2026-09-03-pm") == _batch.RC_OK
    capsys.readouterr()
    assert cli(two_organ, "--lane", "local-dev", "--apply", "--review-at",
               REVIEW_AT, "--slot", "2026-09-03-pm") == _batch.RC_USAGE
    assert "already exists" in capsys.readouterr().err


def test_neither_record_ever_lists_the_others_members(two_organ, capsys):
    """Two surfaces, two records, two `review-at:`s — and no line crosses."""
    before = sorted(p.name for p in (two_organ["mind"] / "batches").iterdir())
    assert cli(two_organ, "--lane", "local-dev", "--apply", "--review-at",
               REVIEW_AT, "--slot", "2026-09-03-am") == _batch.RC_OK
    capsys.readouterr()
    assert sorted(p.name for p in (two_organ["mind"] / "batches").iterdir()) \
        == before, "a cortex plan writes nothing Mind-side"
    cortex_record = record_text(two_organ, "2026-09-03-am")
    for line in cortex_record.split("\n"):
        if line.startswith("  - "):
            assert " phases/" in line and "draft/" not in line

    # …and the dev collect of a Mind record scores no science member, because
    # the cortex kind claims one only where a cortex context is loaded.
    d = _batch.collect(two_organ["mind"], "2026-09-03-pm")
    assert {s["kind"] for s in d["members"]} == {"dev"}
    assert "phases/" not in (two_organ["mind"] / "batches"
                             / "2026-09-03-pm.md").read_text(encoding="utf-8")


# ------------------------------------------------------- the rolling board --
def _late_member(board) -> None:
    """A fourth member on the am record whose phase is still `ready` — it is
    off the board at the first collect and joins at the second."""
    root = board["root"]
    ready = (root / "phases/example/03_ready_cleared.md").read_text(
        encoding="utf-8")
    (root / "phases/example/14_late.md").write_text(
        ready.replace("# Example — phase 3:", "# Example — phase 14:").replace(
            "Phase: 3", "Phase: 14"), encoding="utf-8")
    record = root / "batches" / f"{AM}.md"
    record.write_text(record.read_text(encoding="utf-8")
                      + "  - 14_late: phases/example/14_late.md — none — 4 — "
                        "ready\n", encoding="utf-8")


def _land_the_late_member(board) -> None:
    """…and now its run has landed: `ready` → `running`, one done run line."""
    path = board["root"] / "phases/example/14_late.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("State: ready", "State: running")
    text = text.replace("Lane: local-dev", "Runs: 400400\nLane: local-dev")
    text = text.replace("## Runs\n",
                        "## Runs\n\n- 400400: done — gpu — submitted "
                        "2026-08-30 — wall 0:20\n")
    path.write_text(text, encoding="utf-8")


def test_a_newly_pulled_member_is_appended_and_the_others_are_untouched(
        two_organ, capsys):
    """The rolling board's whole promise: the human keeps reading the page
    while the overnight members land under them."""
    _late_member(two_organ)
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    first = spans(packet_text(two_organ))
    assert "m-14_late" not in first
    assert set(first) == {"m-11_healthy", "m-12_resumed", "m-01_partial"}

    _land_the_late_member(two_organ)
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", "2026-09-03T13:00Z") == _batch.RC_FINDINGS
    capsys.readouterr()
    second = spans(packet_text(two_organ))
    assert "m-14_late" in second
    for mid, section in first.items():
        assert second[mid] == section, f"{mid} was re-rendered"
    assert check(two_organ) == []


def test_a_running_member_holds_no_review_control(two_organ, capsys):
    """`batches/AGENTS.md`: nothing in `submitted`/`running` holds review
    control. Not a disabled chip — no chip, no Ruled box, and out of the
    progress denominator, because a board whose count can never read "all
    decided" teaches the human to ignore it."""
    set_run_state(two_organ, "phases/example/11_healthy.md", "running")
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    page = packet_text(two_organ)
    live = spans(page)["m-11_healthy"]
    assert 'data-decision="m-11_healthy"' not in live
    assert 'data-ruled="m-11_healthy"' not in live
    assert 'data-note="m-11_healthy"' in live, "a note on it is still kept"
    assert "chip-running" in live and "RUNNING" in live
    members = json.loads(re.search(r"var MEMBERS = (\[.*?\]);", page,
                                   re.S).group(1))
    by_slug = {m["slug"]: m for m in members}
    assert by_slug["11_healthy"]["reviewable"] is False
    assert by_slug["12_resumed"]["reviewable"] is True
    assert "Ruled 0 of 2 · decisions 0 of 2" in page, "3 members, 2 reviewable"
    assert "still running — they hold no review control" in page


def test_the_cortex_submit_markdown_is_the_cortexs_own_vocabulary(
        two_organ, tmp_path, capsys):
    """`cortex.py check` reads every `##` heading in a review as a member name
    and every decision as a ruling verb — so the follow-ups block sits one
    level down and the no-verdict word is `(none)`, not `UNREVIEWED`."""
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    page = packet_text(two_organ)
    assert '"### Follow-ups accepted"' in page
    assert '"## Follow-ups accepted"' not in page
    assert 'DEFAULT_DECISION = "(none)"' in page
    assert 'DEFAULT_DECISION = "UNREVIEWED"' not in page
    for value in ("accept", "rerun", "drop", "leave-to-finish"):
        assert f'value="{value}"' in page
    assert "PyAutoCortex/batches/packets" in page

    # …and the dev packet still says what it always said.
    mind = two_organ["mind"]
    d = _batch.collect(mind, "2026-09-03-pm")
    d["stamp"] = STAMP
    dev_page, _notes = _batch.packet_html(d)
    assert '"## Follow-ups accepted"' in dev_page
    assert 'DEFAULT_DECISION = "UNREVIEWED"' in dev_page
    assert "PyAutoMind/batches/packets" in dev_page


def test_the_records_state_column_stays_a_phase_state(two_organ, capsys):
    """The dev rewrite would write `HEALTHY (…)` into a column `cortex.py
    check` reads as a phase state. The member lines are `apply_ops`' — this
    verb writes only the collect keys."""
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    text = record_text(two_organ)
    assert "— awaiting-ruling" in text
    for word in ("HEALTHY (", "SUSPECT (", "FAILED (", "NOT-DELIVERED"):
        assert word not in text
    assert "- collected: 2026-09-03T12:00Z" in text
    assert "- delivered: 1/3" in text
    assert "- packet: batches/packets/2026-09-02-am.html" in text
    assert check(two_organ) == []


def test_a_second_apply_does_not_re_stamp_a_member_already_on_the_board(
        two_organ, capsys):
    """`apply_ops` writes one `refreshed:` line per phase it is handed, and a
    member that is already `awaiting-ruling` was not pulled again."""
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    first = record_text(two_organ)
    assert first.count("- refreshed: ") == 3

    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", "2026-09-03T14:00Z") == _batch.RC_FINDINGS
    capsys.readouterr()
    second = record_text(two_organ)
    assert second.count("- refreshed: ") == 3
    assert "2026-09-03T14:00Z" not in second
    assert "- collected: 2026-09-03T12:00Z" in second, "collected: is once"


def test_carried_members_ride_onto_the_next_record_unnamed(two_organ, capsys):
    """The human never re-specifies a carried member: whatever was still live
    at the last closed record's review is on this board too, at its CURRENT
    state, with the record it came from recorded."""
    assert cli(two_organ, "--lane", "local-dev", "--apply", "--review-at",
               REVIEW_AT, "--slot", "2026-09-03-pm") == _batch.RC_OK
    out = capsys.readouterr().out
    text = record_text(two_organ, "2026-09-03-pm")
    assert "- carried-from: batches/2026-09-01-pm.md" in text
    assert ("  - 05_running_array: phases/example/05_running_array.md — "
            "342091, 342102 — 8 — running") in text
    assert "carried from batches/2026-09-01-pm.md" in out
    # the closed record's own line is left as the ledger of what it was
    assert "05_running_array" in (
        two_organ["root"] / "batches/2026-09-01-pm.md").read_text(
            encoding="utf-8")
    assert check(two_organ) == []


def test_the_close_leg_fills_never_overwrites_and_carries_once(
        two_organ, capsys):
    """A submitted review closes the board: the packet is never rewritten (it
    and the review file are the audit pair), the close fields are filled where
    the human left them blank, and every member still running is carried."""
    set_run_state(two_organ, "phases/example/11_healthy.md", "running")
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", STAMP) == _batch.RC_FINDINGS
    capsys.readouterr()
    frozen = packet_text(two_organ)

    (two_organ["root"] / "batches" / "reviews" / f"{AM}.md").write_text(
        f"# Batch review {AM}\n\n"
        f"- packet: batches/packets/{AM}.html\n"
        "- reviewed-at: 2026-09-03T15:00Z\n"
        "- review-minutes-actual: 21\n\n"
        "## 12_resumed — FAILED\n- decision: rerun\n- ruled: yes\n\n"
        "It resumed the previous fit.\n\n"
        "## 01_partial — SUSPECT\n- decision: accept\n- ruled: yes\n\n"
        "Good enough.\n\n"
        "### Follow-ups accepted\n- none\n", encoding="utf-8")

    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", "2026-09-03T16:00Z") == _batch.RC_FINDINGS
    out = capsys.readouterr().out
    assert "never rewritten after a review" in out
    assert packet_text(two_organ) == frozen
    text = record_text(two_organ)
    assert f"- review: batches/reviews/{AM}.md" in text
    assert "- reviewed-at: 2026-09-03T15:00Z" in text
    assert "- review-minutes-actual: 21" in text
    assert "- collected: 2026-09-03T12:00Z" in text, "history, not this run"
    assert "- carried: 11_healthy — still running at review" in text
    # a ruled member is not re-scored, and the carried line is written once
    assert cli(two_organ, "collect", "--slot", AM, "--apply",
               "--stamp", "2026-09-03T17:00Z") == _batch.RC_FINDINGS
    out = capsys.readouterr().out
    assert record_text(two_organ).count("- carried: 11_healthy") == 1
    assert "already ruled in this slot's review" in out
    assert check(two_organ) == []


def test_a_record_naming_a_phase_this_cortex_does_not_have_is_a_note(
        two_organ, capsys):
    record = two_organ["root"] / "batches" / f"{AM}.md"
    record.write_text(record.read_text(encoding="utf-8")
                      + "  - ghost: phases/example/99_ghost.md — none — 3 — "
                        "pulled\n", encoding="utf-8")
    d = _batch.collect(two_organ["root"], AM, kind="cortex",
                       cortex=ctx_of(two_organ))
    ghost = next(s for s in d["members"] if s["slug"] == "ghost")
    assert ghost["health"] == "SUSPECT"
    assert ghost["review_chips"] == [] and ghost["reviewable"] is False
    assert "is not in this Cortex" in " ".join(d["notes"])
    d["stamp"] = STAMP
    page, notes = _batch.packet_html(d)
    assert 'id="m-ghost"' in page and notes == []


def test_review_at_is_re_declared_at_a_refresh(two_organ, capsys):
    """"When the human next sits at the laptop" moves, and the record is where
    it is stated."""
    assert cli(two_organ, "collect", "--slot", AM, "--apply", "--stamp", STAMP,
               "--review-at", "2026-09-02T21:30Z") == _batch.RC_FINDINGS
    capsys.readouterr()
    text = record_text(two_organ)
    assert "- review-at: 2026-09-02T21:30Z" in text
    assert text.count("- review-at:") == 1
    assert check(two_organ) == []


# ------------------------------------------------------------- the wiring ---
def test_the_cortex_conductor_is_loaded_lazily_and_never_the_other_way(
        two_organ):
    """`_cortex.py` renders the Cortex's own board inside that repo's
    `dashboard_refresh.yml`, where no Mind and no batch conductor exist. The
    import runs one way, and only when a science kind is actually in play."""
    source = (BRAIN / "agents" / "conductors" / "cortex"
              / "_cortex.py").read_text(encoding="utf-8")
    assert "_batch" not in source
    assert _batch.load_cortex_conductor() is _batch.load_cortex_conductor()


def test_a_laptop_with_no_science_checkout_still_gets_its_dev_board(
        two_organ, capsys):
    """`both` is what the LANE offers, not what the human asked for — so a
    missing Cortex is a line, not the end of the plan."""
    rc = _batch.main(["plan", "--lane", "local-dev",
                      "--mind", str(two_organ["mind"]),
                      "--cortex", str(two_organ["root"] / "nowhere")])
    out = capsys.readouterr().out
    assert rc == _batch.RC_OK
    assert "== BatchDecision ==" in out and "no science board" in out


def test_no_usable_cortex_tree_is_its_own_exit_code(tmp_path, capsys):
    """Not a usage error: a session with no science checkout did not type
    something wrong."""
    rc = _batch.main(["collect", "--kind", "cortex", "--cortex",
                      str(tmp_path / "nowhere"), "--mind", str(tmp_path)])
    assert rc == _batch.RC_NO_CORTEX
    assert "no Cortex tree" in capsys.readouterr().err


def test_both_kinds_print_two_boards_and_the_reason_they_are_two(
        two_organ, capsys):
    rc = _batch.main(["plan", "--kind", "both", "--lane", "local-dev",
                      "--mind", str(two_organ["mind"]),
                      "--cortex", str(two_organ["root"])])
    out = capsys.readouterr().out
    assert rc == _batch.RC_OK
    assert out.index("== BatchDecision ==") < out.index("== CortexPlan ==")
    assert "phases/example/03_ready_cleared.md" in out
    assert "Two records, one per organ" in out
    assert "review-at:" in out


def test_pull_from_a_cloud_session_says_run_it_from_the_laptop(
        two_organ, capsys):
    """`--pull` runs the project's own CLI, and only the laptop has one."""
    assert cli(two_organ, "collect", "--slot", AM, "--pull",
               "--lane", "web-github") == _batch.RC_FINDINGS
    out = capsys.readouterr().out
    assert "no laptop here" in out and "run collect from the laptop" in out
    assert "11_healthy" in out, "what is mirrored is scored anyway"


def test_the_cortex_budget_is_its_own(two_organ):
    """The science slot's minutes are not the dev slot's."""
    ctx = ctx_of(two_organ)
    d = _batch.plan_cortex(ctx, budget=2, lane="local-dev")
    assert d["members"] == []
    assert "exceed the budget" in dict(d["rejected"])[
        "phases/example/03_ready_cleared.md"]


def test_pr_evidence_flags_are_the_dev_boards(two_organ, capsys):
    """A science member's evidence is what the project's own pull mirrored —
    there is no PR to read."""
    assert cli(two_organ, "collect", "--slot", AM, "--fetch") \
        == _batch.RC_USAGE
    assert "belong to the dev board" in capsys.readouterr().err

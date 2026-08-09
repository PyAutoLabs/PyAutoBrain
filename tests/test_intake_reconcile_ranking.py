"""Contract tests for the `intake reconcile` ranking.

Reconcile ranks backlog prompts that look already-shipped, for a human to
retire. It was measured against a labelled set on 2026-08-09 (PyAutoMind
`f25e154e`, 148 prompts, findings independently confirmed against upstream
source) and scored badly: **96 of 148 flagged — 65%** — while missing the
largest true positive entirely. The cause was not a missing signal, it was that
every signal counted the same. A completion record merely *naming* a prompt made
it `high`, which described most of the backlog.

These tests pin the discriminations that fixed it. Each drives input that must
trip (or must NOT trip) the leg — a ranker that cannot rank is decoration.

Hermetic: every fixture is a fictional Mind tree in tmp_path. Nothing here names
a real prompt or record, so the assertions are about the ranking logic, not
about whatever happens to be checked out.
"""

import importlib.util
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_intake_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_under_test"] = _intake
_spec.loader.exec_module(_intake)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _mind(root: Path, prompts: dict, records: dict) -> Path:
    """Fictional Mind: draft/<work-type>/<target>/<name>.md + complete/ records."""
    for rel, body in prompts.items():
        p = root / "draft" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for name, body in records.items():
        p = root / "complete" / "2026" / "07" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


def _paths(res) -> set:
    return {s["path"] for s in res["suspects"]}


def _score(res, stem):
    for s in res["suspects"]:
        if s["path"].endswith(stem):
            return s["overlap_score"]
    return None


# --------------------------------------------------------------------------- #
# the noise that swamped the original ranking
# --------------------------------------------------------------------------- #
def test_a_record_merely_naming_a_prompt_is_not_a_suspect(tmp_path):
    """The 2026-08-09 measurement's single biggest noise source. Any reference
    scored `high`, which is why 52 of 148 prompts were `high` and the real
    findings were indistinguishable from them."""
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md": "# Sprocket wobble\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: adjacent to "
                                "sprocket_wobble.md, which is unrelated here.\n"},
    )
    assert _paths(_intake.reconcile(root)) == set()


def test_a_record_asserting_the_work_shipped_is_a_suspect(tmp_path):
    """The same reference, with a completion claim attached, is the real signal
    — `jax-substructure-simulator.md` opens 'the 4 prompts shipped to main'."""
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md": "# Sprocket wobble\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: sprocket_wobble.md "
                                "shipped to main over PRs #1 and #2.\n"},
    )
    res = _intake.reconcile(root)
    assert "draft/bug/flywheel/sprocket_wobble.md" in _paths(res)


def test_status_alone_never_makes_a_suspect(tmp_path):
    """`Status:` is hand-set on most of the backlog; on its own it said nothing
    and contributed a whole confidence band of noise."""
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md":
            "# Sprocket wobble\n\nStatus: planned\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: unrelated.\n"},
    )
    assert _paths(_intake.reconcile(root)) == set()


# --------------------------------------------------------------------------- #
# the signals that found real drift
# --------------------------------------------------------------------------- #
def test_a_rare_token_across_several_record_stems_outranks_a_common_one(tmp_path):
    """The biggest find of the sweep, in miniature. A phased series leaves
    several records whose stems share one rare token; the prompt that started it
    keeps that token. Raw Jaccard scores that case ~0.25 — below any workable
    threshold — because the record stems are short and share nothing else.

    The control prompt shares a token present in EVERY record, which must not
    rank: that is the `jax`/`workspace` case that made topic overlap useless.

    NOTE the archive size. This signal is IDF-weighted, so it is inherently
    scale-relative: a token in 4 of 5 records is common, the same token in 4 of
    200 is rare. The real archive holds ~950 records, where `kxs` in 7 of them
    is decisive. A toy fixture of five records cannot express that, and an
    earlier version of this test failed for exactly that reason rather than
    because the ranker was wrong.
    """
    records = {f"widget-{leg}.md": f"## widget-{leg}\n- notes: leg {leg} of the "
                                   f"widget series.\n"
               for leg in ("design", "core", "cache", "tests")}
    for i in range(200):
        records[f"unrelated-{i:03d}.md"] = (
            f"## unrelated-{i:03d}\n- notes: common work, routine and shared.\n")
    root = _mind(
        tmp_path,
        {"feature/flywheel/widget_coupling.md": "# Widget coupling\n\nThe plan.\n",
         "feature/flywheel/routine_shared_work.md": "# Routine shared\n\nA task.\n"},
        records,
    )
    res = _intake.reconcile(root)
    assert "draft/feature/flywheel/widget_coupling.md" in _paths(res)
    assert "draft/feature/flywheel/routine_shared_work.md" not in _paths(res)


def test_shared_rare_identifiers_rank_by_how_many_are_shared(tmp_path):
    """What a human grader actually reads. One shared identifier is a
    coincidence; several is the record describing this prompt's deliverable."""
    idents = [f"`_flywheel_helper_{i}`" for i in range(6)]
    root = _mind(
        tmp_path,
        {"feature/flywheel/many.md": "# Many\n\n" + " ".join(idents) + "\n",
         "feature/flywheel/one.md": "# One\n\n" + idents[0] + "\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: "
                                + " ".join(idents) + "\n"},
    )
    res = _intake.reconcile(root)
    many = _score(res, "many.md")
    assert many is not None, "six shared identifiers must be a suspect"
    assert _score(res, "one.md") is None, "one shared identifier is not evidence"


def test_an_identifier_in_every_record_is_vocabulary_not_evidence(tmp_path):
    """`Array2D` appears everywhere; matching on it links nothing."""
    common = "`common_helper_name`"
    records = {f"rec-{i}.md": f"## rec-{i}\n- notes: {common} used here.\n"
               for i in range(8)}
    root = _mind(
        tmp_path,
        {"feature/flywheel/uses_common.md": f"# Uses common\n\n{common}\n"},
        records,
    )
    assert _paths(_intake.reconcile(root)) == set()


# --------------------------------------------------------------------------- #
# the contract that must not change
# --------------------------------------------------------------------------- #
def test_reconcile_never_writes(tmp_path):
    """Retiring a prompt writes to complete/ and stays a human act."""
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md": "# Sprocket wobble\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: sprocket_wobble.md "
                                "shipped to main.\n"},
    )
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    _intake.reconcile(root)
    after = {p: p.read_bytes() for p in root.rglob("*.md")}
    assert before == after


def test_suspects_carry_their_evidence_and_a_band(tmp_path):
    """The output is a review list, so every row must say why it is there."""
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md": "# Sprocket wobble\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: sprocket_wobble.md "
                                "shipped to main.\n"},
    )
    s = _intake.reconcile(root)["suspects"][0]
    assert s["confidence"] in ("high", "medium")
    assert s["findings"] and all(f["kind"] and f["evidence"] for f in s["findings"])
    assert any(f["kind"] == "record-says-shipped" for f in s["findings"])

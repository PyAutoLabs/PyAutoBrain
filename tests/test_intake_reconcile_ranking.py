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


# --------------------------------------------------------------------------- #
# leg 3 — the upstream read (--repo), PyAutoBrain#223
#
# Everything above is Mind-local. Leg 3 adds the one signal that can see a
# prompt with NO Mind-side trace: identifiers it names that already exist in the
# target repo's source. These tests inject a fake source tree through the
# `source_reader` seam, so this file stays hermetic — nothing here clones.
# --------------------------------------------------------------------------- #
def _reader(table):
    """Fake `source_reader`: {ident: [file:line]} for idents in `table`."""
    return lambda idents: {i: table[i] for i in idents if i in table}


def test_upstream_presence_never_produces_a_shipped_verdict(tmp_path):
    """THE acceptance criterion, in miniature.

    `test_mode_bypass_ordered_assertion_ties.md` names five identifiers and ALL
    FIVE are on PyAutoFit main — yet the prompt is confirmed NOT shipped: main
    catches `exc.FitException` in the TEST_MODE bypass, which looks exactly like
    the requested fix, but the catch wraps only the likelihood call while
    `model.instance_from_vector` (where `check_assertions` raises) sits on the
    line BEFORE the `try`.

    A matcher that scored presence as shipped would rank this `high` and be
    wrong. It must land in the weak band, carrying its evidence.
    """
    idents = ["FitException", "check_assertions", "ignore_assertions",
              "instance_for_arguments", "instance_from_vector"]
    body = "# Ordered assertion ties\n\n" + "\n".join(f"- `{i}`" for i in idents)
    root = _mind(tmp_path, {"bug/gearbox/ordered_ties.md": body}, {})
    res = _intake.reconcile(
        root, source_reader=_reader({i: [f"src/{i}.py:1"] for i in idents}))

    s = [x for x in res["suspects"]
         if x["path"] == "draft/bug/gearbox/ordered_ties.md"]
    assert s, "a prompt whose identifiers are all upstream must be surfaced"
    assert s[0]["confidence"] == "needs-review"
    assert s[0]["confidence"] != "high"
    assert any(f["kind"] == "upstream-identifier-present" for f in s[0]["findings"])


def test_upstream_evidence_cannot_inflate_a_mind_local_band(tmp_path):
    """The structural defence behind the test above: upstream hits are scored on
    their own key and never added to `overlap_score`, so no number of them can
    push a prompt up into `high`."""
    idents = [f"`_gearbox_part_{i}`" for i in range(9)]
    root = _mind(tmp_path,
                 {"bug/gearbox/ordered_ties.md": "# Ties\n\n" + "\n".join(idents)},
                 {})
    table = {f"_gearbox_part_{i}": [f"src/p{i}.py:1"] for i in range(9)}
    res = _intake.reconcile(root, source_reader=_reader(table))
    s = res["suspects"][0]
    assert s["confidence"] == "needs-review"
    assert s["overlap_score"] == 0.0        # Mind-local score untouched
    assert s["upstream_score"] > 0.0


def test_one_upstream_identifier_is_not_a_signal(tmp_path):
    """A single shared name is a coincidence — the same bar the Mind-local
    identifier leg sets at two."""
    root = _mind(tmp_path,
                 {"bug/gearbox/ordered_ties.md": "# Ties\n\n`_lone_helper`\n"}, {})
    res = _intake.reconcile(
        root, source_reader=_reader({"_lone_helper": ["src/a.py:1"]}))
    assert _paths(res) == set()


def test_builtins_and_repo_names_are_not_upstream_evidence(tmp_path):
    """Measured noise from the first real run: `TypeError` is in 37 files of
    PyAutoFit and `autofit_workspace` in 26. Every repo names its siblings and
    every codebase raises builtins; neither says a prompt shipped.

    Filtering on upstream file-spread instead was tried and rejected — the
    counts do not separate (`instance_from_vector` is a real signal at 22 files,
    just under `autofit_workspace` at 26)."""
    body = "# Noise only\n\n`TypeError`\n`autofit_workspace`\n`autolens_workspace`\n"
    root = _mind(tmp_path, {"bug/gearbox/noise_only.md": body}, {})
    res = _intake.reconcile(root, source_reader=_reader({
        "TypeError": ["src/a.py:1"],
        "autofit_workspace": ["README.md:6"],
        "autolens_workspace": ["README.md:7"],
    }))
    assert _paths(res) == set()


def test_default_path_makes_no_network_access(tmp_path, monkeypatch):
    """PyAutoBrain is otherwise stdlib-only and offline. `--repo` is opt-in, and
    the default path must stay provably offline — so detonate on any attempt to
    clone or open a socket when no reader was passed."""
    import socket
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("default reconcile path attempted network access")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    root = _mind(
        tmp_path,
        {"bug/flywheel/sprocket_wobble.md": "# Sprocket wobble\n\nIt wobbles.\n"},
        {"gadget-alignment.md": "## gadget-alignment\n- notes: sprocket_wobble.md "
                                "shipped to main.\n"},
    )
    assert _intake.reconcile(root)["suspects"]       # ran, and stayed offline


def test_upstream_mode_still_never_writes(tmp_path):
    """The read-only contract holds on the new leg too."""
    root = _mind(tmp_path,
                 {"bug/gearbox/ordered_ties.md": "# Ties\n\n`_a_helper`\n`_b_helper`\n"},
                 {})
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    _intake.reconcile(root, source_reader=_reader(
        {"_a_helper": ["src/a.py:1"], "_b_helper": ["src/b.py:2"]}))
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_a_multi_repo_target_is_refused_not_guessed(tmp_path):
    """`workspaces`, `health_fixes`, `priors` and `graphical_ep` are topic
    clusters, not repos — and among the largest buckets in draft/. Guessing one
    repo for them would produce confident nonsense over the biggest part of the
    backlog."""
    root = _mind(tmp_path,
                 {"bug/health_fixes/a_broken_thing.md":
                  "# Broken\n\nSee @PyAutoFit/autofit/x.py and @PyAutoArray/y.py\n"},
                 {})
    slug, err = _intake.resolve_repo(root, "health_fixes")
    assert slug == ""
    assert "not a single repository" in err
    assert "autofit" in err and "autoarray" in err     # names the real candidates


def test_a_real_repo_target_resolves_to_its_slug(tmp_path):
    """The other side of the same door: a genuine target resolves via the body
    map, through the same `normalise_repo` aliases the sizing faculty uses."""
    for target in ("autofit", "PyAutoFit", "pyautofit"):
        slug, err = _intake.resolve_repo(tmp_path, target)
        assert err == ""
        assert slug == "PyAutoLabs/PyAutoFit"

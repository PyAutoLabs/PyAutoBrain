"""Tests for `agents/conductors/hygiene/_hygiene_condemned.py` — the one
parser of the Mind's `condemned.md` ledger.

PyAutoGut's board and its void workflow import this module from a checked-out
Brain, so the ledger is read one way everywhere. `ref_name` is the piece they
lean on hardest: a void is keyed by the ref name in `archive-ref`, never by
the `##` heading (the two differ in the real ledger).
"""

import datetime
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN_HOME / "agents" / "conductors" / "hygiene"))

import _hygiene_condemned as hc  # noqa: E402

LEDGER = """\
# Condemned material

## Entry schema

- `type` — `branch` | `stash`

<!--
## example-entry
- type: branch
- archive-ref: refs/heads/archive/condemned/example @ 0de4514
-->

## team/old-spike
- type: branch
- locator: feature/old-spike
- sweep-after: 2026-08-12
- archive-ref: refs/heads/archive/condemned/team-old-spike @ 0de4514

## history/kept
- type: branch
- locator: master
- sweep-after: never — void only on explicit human request
- archive-ref: `refs/heads/archive/condemned/history-kept` on SomeGut origin (55da101c, 442 commits)

## purge/datasets
- type: file
- locator: dataset/old
- sweep-after: 2026-08-29
- archive-ref: n/a — committed deletion; pre-purge SHA `8625a1de`
"""


def test_parse_manifest_skips_prose_sections_and_commented_examples():
    entries = hc.parse_manifest(LEDGER)
    assert [e["name"] for e in entries] == [
        "team/old-spike", "history/kept", "purge/datasets"]


def test_classify_splits_due_pending_and_undated():
    entries = hc.parse_manifest(LEDGER)
    due, pending, undated = hc.classify(entries, datetime.date(2026, 8, 20))
    assert [e["name"] for e in due] == ["team/old-spike"]
    assert [e["name"] for e in pending] == ["purge/datasets"]
    assert [e["name"] for e in undated] == ["history/kept"]


def test_ref_name_reads_archive_ref_not_the_heading():
    entries = {e["name"]: e for e in hc.parse_manifest(LEDGER)}
    assert hc.ref_name(entries["team/old-spike"]) == "team-old-spike"
    assert hc.ref_name(entries["history/kept"]) == "history-kept"


def test_ref_name_is_none_for_history_only_entries():
    for text in ("n/a — committed deletion; pre-purge SHA `8625a1de`",
                 "`n/a` — committed deletion",
                 "permanent local mirror backups ~/backups/x.git",
                 ""):
        assert hc.ref_name({"archive-ref": text}) is None, text
    assert hc.ref_name({}) is None


def test_ref_name_tolerates_the_decorations_the_ledger_carries():
    cases = {
        "refs/heads/archive/condemned/a-b @ 0de4514": "a-b",
        "`refs/heads/archive/condemned/a-b` @ `e6e72cc2`": "a-b",
        "refs/heads/archive/condemned/a-b on SomeRepo origin (9dc61c5)": "a-b",
        "refs/heads/archive/condemned/team/inference @ c8b6058 (SomeGut)":
            "team/inference",
        "see refs/heads/archive/condemned/tail-dot.": "tail-dot",
    }
    for text, want in cases.items():
        assert hc.ref_name({"archive-ref": text}) == want, text


def test_ref_name_keeps_a_batch_glob_for_the_caller_to_expand():
    entry = {"archive-ref": "37 refs under `refs/heads/archive/condemned/"
                            "batch-*` on SomeGut origin — all verified"}
    assert hc.ref_name(entry) == "batch-*"

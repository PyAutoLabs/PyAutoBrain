"""tests/test_batch_slice.py — `batch slice`, the decomposition pass.

The verb renders and judges a DECLARED decomposition; these tests pin the seam
rules (witness, count, order), that the parent is never touched, and that only
`--apply` writes — the children and the epics.md entry.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents" / "faculties" / "sizing"))
_spec = importlib.util.spec_from_file_location(
    "_batch_slice_under_test", BRAIN / "agents" / "conductors" / "batch" / "_batch.py")
_batch = importlib.util.module_from_spec(_spec)
sys.modules["_batch_slice_under_test"] = _batch
_spec.loader.exec_module(_batch)
import _slice  # noqa: E402  (importable once _batch set sys.path)

PARENT = "draft/feature/autofit/big_thing.md"

HEADER = """# A big thing

Type: feature
Target: PyAutoThing
Repos:
- PyAutoThing
- autothing_workspace
Themes:
- mind-workflow
Difficulty: too-large
Autonomy: supervised
Priority: normal
Status: draft
Unattended: needs-slicing

Do a great deal of work.

## Slices

"""

LIB = ("1. **Library core.** Add the thing. *Repos:* PyAutoThing\n"
       "   *Witness:* `pytest test_autofit/thing` passes. *Consequence:* glance.\n")
WS = ("2. **Workspace example.** Show it in autothing_workspace. *Witness:* the\n"
      "   example runs in smoke. *Depends:* 1\n")
DOCS = ("3. **Docs page.** Document it in autothing_workspace. *Witness:* the docs "
        "build passes. *Depends:* 1\n")
NO_WITNESS = "3. **Tidy up.** Clean the rest of PyAutoThing. *Repos:* PyAutoThing\n"


def mind(tmp_path: Path, slices: str, *, epics: str = "# Epics\n") -> Path:
    root = tmp_path / "PyAutoMind"
    f = root / PARENT
    f.parent.mkdir(parents=True)
    f.write_text(HEADER + slices + "\n## After\n\nNot a slice.\n", encoding="utf-8")
    (root / "epics.md").write_text(epics, encoding="utf-8")
    return root


def run(root: Path, *extra, capsys):
    rc = _batch.main(["slice", PARENT, "--mind", str(root), "--json", *extra])
    return rc, json.loads(capsys.readouterr().out)


def digest(root: Path) -> str:
    return hashlib.sha256((root / PARENT).read_bytes()).hexdigest()


def test_two_children_with_explicit_seams(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS)
    rc, d = run(root, capsys=capsys)
    assert rc == 0 and d["ok"], d
    assert [c["index"] for c in d["children"]] == [1, 2]
    one, two = d["children"]
    assert one["repos"] == ["PyAutoThing"]
    assert two["repos"] == ["autothing_workspace"]   # named in the item's text
    assert "before slice 2" in one["seam"]
    assert "after slice 1" in two["seam"] and "slice(s) 1 merged" in two["seam"]
    assert "Witness: `pytest test_autofit/thing` passes." in one["text"]
    assert "Epic: big-thing" in two["text"] and "Phase: 2" in two["text"]
    assert "Target: autothing_workspace" in two["text"]
    assert "## Seam" in one["text"]
    assert d["written"] == []
    assert not (root / one["path"]).exists()        # proposal writes nothing


def test_four_children_accepted(tmp_path, capsys):
    four = LIB + WS + DOCS + ("4. **Second docs page.** In autothing_workspace. "
                              "*Witness:* the page renders.\n")
    rc, d = run(mind(tmp_path, four), capsys=capsys)
    assert rc == 0 and len(d["children"]) == 4


def test_a_child_with_no_witness_is_refused(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS + NO_WITNESS)
    rc, d = run(root, "--apply", capsys=capsys)
    assert rc == 1 and not d["ok"]
    bad = d["children"][2]
    assert any("a smaller judge task, not a slice" in r for r in bad["refusals"])
    assert not d["children"][0]["refusals"]
    assert d["written"] == []
    assert not any((root / c["path"]).exists() for c in d["children"])


@pytest.mark.parametrize("slices", [LIB, LIB + WS + DOCS + (
    "4. **Four.** In PyAutoThing. *Witness:* a. \n"
    "5. **Five.** In PyAutoThing. *Witness:* b.\n")])
def test_fewer_than_two_or_more_than_four_is_refused(tmp_path, capsys, slices):
    rc, d = run(mind(tmp_path, slices), capsys=capsys)
    assert rc == 1
    assert any("2 to 4 children" in r for r in d["refusals"])


def test_a_dependency_on_a_later_slice_is_refused(tmp_path, capsys):
    early = LIB.replace("*Consequence:* glance.", "*Depends:* 2")
    rc, d = run(mind(tmp_path, early + WS), capsys=capsys)
    assert rc == 1
    assert any("not before it" in r for r in d["children"][0]["refusals"])


def test_a_parent_that_declares_no_slices_is_refused_not_invented(tmp_path, capsys):
    rc, d = run(mind(tmp_path, ""), capsys=capsys)
    assert rc == 1 and d["children"] == []
    assert any("does not invent one" in r for r in d["refusals"])


def test_only_a_needs_slicing_parent_is_sliced(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS)
    f = root / PARENT
    f.write_text(f.read_text().replace("Unattended: needs-slicing",
                                       "Unattended: ready"))
    rc, d = run(root, capsys=capsys)
    assert rc == 1
    assert any("not needs-slicing" in r for r in d["refusals"])


def test_slices_file_replaces_the_parents_section(tmp_path, capsys):
    root = mind(tmp_path, NO_WITNESS)      # the parent's own cut is bad
    plan = tmp_path / "plan.md"
    plan.write_text(LIB + WS)               # no heading needed in a plan file
    rc, d = run(root, "--slices", str(plan), capsys=capsys)
    assert rc == 0 and len(d["children"]) == 2
    assert d["source"].startswith("--slices")


def test_apply_writes_children_and_epic_entry_and_leaves_the_parent(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS)
    before = digest(root)
    rc, d = run(root, "--apply", capsys=capsys)
    assert rc == 0
    paths = [c["path"] for c in d["children"]]
    assert d["written"] == paths + ["epics.md"]
    for c in d["children"]:
        assert (root / c["path"]).read_text() == c["text"]
        assert Path(c["path"]).parent == Path(PARENT).parent   # beside the parent
    epics = (root / "epics.md").read_text()
    assert "## big-thing" in epics
    assert f"- ledger: {PARENT}" in epics
    assert digest(root) == before                             # parent untouched
    assert sorted(p.name for p in (root / PARENT).parent.iterdir()) == sorted(
        [Path(PARENT).name] + [Path(p).name for p in paths])

    # A second apply refuses rather than overwriting, and still leaves the parent.
    rc, d = run(root, "--apply", capsys=capsys)
    assert rc == 1 and d["written"] == []
    assert any("already exists" in r for r in d["children"][0]["refusals"])
    assert digest(root) == before


def test_a_parent_already_an_epic_gets_no_second_entry(tmp_path, capsys):
    epics = f"# Epics\n\n## big\n- title: Big\n- ledger: {PARENT}\n"
    root = mind(tmp_path, LIB + WS, epics=epics)
    rc, d = run(root, "--apply", capsys=capsys)
    assert rc == 0 and d["epic"] == "big" and d["epic_exists"]
    assert "epics.md" not in d["written"]
    assert (root / "epics.md").read_text() == epics
    assert "Epic: big\n" in d["children"][0]["text"]


def test_the_human_report_says_nothing_was_written(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS)
    rc = _batch.main(["slice", PARENT, "--mind", str(root)])
    out = capsys.readouterr().out
    assert rc == 0 and "PROPOSED" in out and "Nothing written" in out


def test_slice_needs_a_prompt(tmp_path, capsys):
    root = mind(tmp_path, LIB + WS)
    assert _batch.main(["slice", "--mind", str(root)]) == _batch.RC_USAGE


def test_intake_offers_slice_only_for_needs_slicing():
    spec = importlib.util.spec_from_file_location(
        "_intake_slice_offer", BRAIN / "agents" / "conductors" / "intake" / "_intake.py")
    intake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(intake)
    offer = intake.slice_offer("draft/feature/x/y.md", "needs-slicing")
    assert "pyauto-brain batch slice draft/feature/x/y.md" in offer
    assert intake.slice_offer("draft/feature/x/y.md", "ready") == ""
    d = intake.analyse("Type: feature\nTarget: PyAutoThing\nUnattended: needs-slicing"
                       "\n\nBuild a huge thing across PyAutoThing.\n", "test")
    assert "batch slice" in d["slice_offer"]

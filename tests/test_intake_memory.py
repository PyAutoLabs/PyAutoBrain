"""tests/test_intake_memory.py — every filed prompt carries its Memory citations.

The doctrine says every plan consults PyAutoMemory. The record says it was
consulted about six times in 1,547 completed tasks, because consulting it was a
step a human had to remember. Intake now does it mechanically: `write_prompt`
runs the memory faculty's own ranking function over the prompt's text and
writes the top PyAutoMemory pages as a `Memory:` header line.

Pinned here: the line is written and points at real pages; it is PyAutoMemory
only; and NO line is written when there are no hits or no checkout — an empty
`Memory:` would claim nothing is known, which intake has no standing to say.

Hermetic: a fictional Mind and a fictional PyAutoMemory in tmp_path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_intake_memory_under_test",
    BRAIN_HOME / "agents" / "conductors" / "intake" / "_intake.py")
_intake = importlib.util.module_from_spec(_spec)
sys.modules["_intake_memory_under_test"] = _intake
_spec.loader.exec_module(_intake)

RAW = ("Add a substructure lensing subhalo mass function fit so the subhalo "
       "detection sensitivity map can be produced from a fitted lens model.")


def _mind(tmp_path: Path) -> Path:
    mind = tmp_path / "PyAutoMind"
    (mind / "draft").mkdir(parents=True)
    return mind


def _memory(tmp_path: Path) -> Path:
    mem = tmp_path / "PyAutoMemory"
    (mem / "wiki" / "lensing" / "concepts").mkdir(parents=True)
    (mem / "wiki" / "methods" / "sources").mkdir(parents=True)
    (mem / "wiki" / "lensing" / "concepts" / "subhalo.md").write_text(
        "# Subhalo\n\nsubhalo subhalo substructure lensing detection "
        "sensitivity\n", encoding="utf-8")
    (mem / "wiki" / "methods" / "sources" / "sensitivity.md").write_text(
        "# Sensitivity mapping\n\nsensitivity mapping for substructure\n",
        encoding="utf-8")
    return mem


def _file_one(mind: Path, raw: str = RAW) -> str:
    decision = _intake.analyse(raw, "test")
    rel = _intake.write_prompt(mind, decision, raw, "test")
    return (mind / rel).read_text(encoding="utf-8")


def _memory_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Memory:"):
            return line
    return ""


def test_a_filed_prompt_cites_pyautomemory(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _memory(tmp_path)
    text = _file_one(mind)

    line = _memory_line(text)
    assert line, "a prompt filed beside a PyAutoMemory must carry its citations"
    pages = [p.strip() for p in line[len("Memory:"):].split(";")]
    assert "wiki/lensing/concepts/subhalo.md" in pages
    assert all(p.startswith("wiki/") for p in pages), pages
    assert len(pages) <= _intake.MEMORY_CITATIONS
    # under the optional keys, and still parsed back out of the header
    assert text.index("Priority:") < text.index("Memory:")
    assert _intake.parse_header(text)["memory"] == line[len("Memory: "):]


def test_no_memory_checkout_writes_no_line(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)          # deliberately no PyAutoMemory beside it
    text = _file_one(mind)
    assert "Memory:" not in text
    # ...and the prompt is otherwise a normal, complete filing
    header = _intake.parse_header(text)
    assert header["status"] == "formalised"
    assert header["priority"]


def test_no_hits_writes_no_line(tmp_path, monkeypatch):
    """An empty `Memory:` would read as "nothing is known"."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    mem = _memory(tmp_path)
    for page in mem.rglob("*.md"):
        page.write_text("# unrelated\n\nphotometry calibration\n",
                        encoding="utf-8")
    text = _file_one(mind, "Bump the packaging wheel metadata.")
    assert "Memory:" not in text


def test_mind_history_is_not_cited(tmp_path, monkeypatch):
    """PyAutoMemory only: `complete/` records are operational recall, not
    what the science says, and the faculty's other two surfaces would drown
    the wiki pages the line exists to surface."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _memory(tmp_path)
    record = mind / "complete" / "2026" / "01"
    record.mkdir(parents=True)
    (record / "subhalo_thing.md").write_text(
        "subhalo subhalo subhalo substructure lensing sensitivity detection\n" * 20,
        encoding="utf-8")
    line = _memory_line(_file_one(mind))
    assert line and "complete/" not in line


def test_seed_stubs_are_never_cited(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    mem = _memory(tmp_path)
    seed = mem / "wiki" / "lensing" / "seed"
    seed.mkdir()
    (seed / "unverified.md").write_text(
        "subhalo substructure lensing sensitivity detection\n" * 50,
        encoding="utf-8")
    line = _memory_line(_file_one(mind))
    assert line and "seed/" not in line

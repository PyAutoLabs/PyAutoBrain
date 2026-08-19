"""tests/test_memory_surfaces.py — the memory faculty's corpus (PyAutoBrain#239).

First regression net for `agents/faculties/memory/_memory.py`. What matters:
the root entry surfaces (index.md, reading-queue.md, bibliography/README.md,
wiki/CLAUDE.md) are part of the corpus — they were invisible before #239 even
though PyAutoMemory/AGENTS.md tells every agent to index them first; surface
labels stay repo-name-first (digest()'s exit-4 logic splits on '/'); ranking
and the no-hits path behave; and the conductors' printed PyAutoMemory pointers
name paths that exist under the wiki/<domain>/ layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "agents" / "faculties" / "memory"))

import _memory  # noqa: E402


def _memory_repo(tmp_path: Path) -> Path:
    m = tmp_path / "PyAutoMemory"
    (m / "wiki" / "demo" / "concepts").mkdir(parents=True)
    (m / "bibliography").mkdir()
    (m / "index.md").write_text("# Index\nthe entry surface mentions quasars\n")
    (m / "reading-queue.md").write_text("# Reading queue\n\nquasar paper one\n")
    (m / "bibliography" / "README.md").write_text("# Bib\nadding a quasar paper\n")
    (m / "wiki" / "CLAUDE.md").write_text("# Schema\nstatus flags\n")
    (m / "wiki" / "demo" / "concepts" / "quasars.md").write_text(
        "---\nstatus: drafted\n---\nquasars lens light\n")
    return m


def test_root_entry_surfaces_are_in_the_corpus(tmp_path):
    m = _memory_repo(tmp_path)
    triples = list(_memory.surfaces(m, None, None))
    root_files = {f.name for name, _, f in triples if name == "PyAutoMemory/root"}
    assert root_files == {"index.md", "reading-queue.md", "README.md", "CLAUDE.md"}
    # the wiki pages still arrive under their sub-wiki label
    assert any(name == "PyAutoMemory/demo" for name, _, _ in triples)


def test_labels_stay_repo_name_first(tmp_path):
    m = _memory_repo(tmp_path)
    for name, _, _ in _memory.surfaces(m, None, None):
        assert name.split("/")[0] == "PyAutoMemory"


def test_digest_ranks_and_cites_the_queue(tmp_path):
    m = _memory_repo(tmp_path)
    d = _memory.digest("quasar reading queue", m, None, None, limit=8)
    assert d["surfaces_present"] == ["PyAutoMemory"]
    pages = {p["page"] for p in d["pages"]}
    assert "reading-queue.md" in pages
    assert all(p["hits"] >= 1 and p["snippets"] for p in d["pages"])


def test_no_hits_yields_empty_pages(tmp_path):
    m = _memory_repo(tmp_path)
    d = _memory.digest("nonexistent-elephant-topic", m, None, None, limit=8)
    assert d["pages"] == [] and d["surfaces_present"] == ["PyAutoMemory"]


def test_bib_file_itself_is_not_a_surface(tmp_path):
    m = _memory_repo(tmp_path)
    (m / "bibliography" / "demo.bib").write_text("@article{Quasar2020}\n")
    files = {f.name for _, _, f in _memory.surfaces(m, None, None)}
    assert "demo.bib" not in files  # metadata, not digest text (by design)


def test_conductor_pointers_name_real_layout_paths(tmp_path):
    """The feature/bug conductors print `PyAutoMemory/wiki/<d>/index.md`
    pointers built from the policy wiki names — those names must be the
    wiki/<domain>/ layout, and the printed shape must resolve in a real
    checkout when one is present."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "agents" / "faculties" / "sizing"))
    import _sizing
    live = Path(__file__).resolve().parents[2] / "PyAutoMemory"
    for wiki in _sizing.MEMORY_WIKIS:
        assert not wiki.endswith("_wiki")
        if live.is_dir():
            assert (live / "wiki" / wiki / "index.md").is_file(), (
                f"policy names sub-wiki '{wiki}' but "
                f"PyAutoMemory/wiki/{wiki}/index.md does not exist")

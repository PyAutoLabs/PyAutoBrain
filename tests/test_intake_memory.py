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
        "sensitivity function\n", encoding="utf-8")
    (mem / "wiki" / "methods" / "sources" / "sensitivity.md").write_text(
        "# Sensitivity mapping\n\nsensitivity mapping for substructure\n",
        encoding="utf-8")
    # The rest of a real digest: many pages sharing the generic vocabulary of
    # any modelling prompt, so those words are not distinctive of any page.
    galaxies = mem / "wiki" / "galaxies" / "sources"
    galaxies.mkdir(parents=True)
    for i in range(20):
        (galaxies / f"galaxy_{i}.md").write_text(
            f"# Galaxy {i}\n\n" + GENERIC * 5, encoding="utf-8")
    return mem


GENERIC = ("model fit fitted profile light mass lens galaxy data cost report "
           "from can add produced map write\n")


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


def _declared(target: str) -> str:
    return (f"# Subhalo sensitivity map\n\nType: feature\nTarget: {target}\n"
            f"Repos:\n- {target}\n\n{RAW}\n")


def test_organ_target_gets_no_memory_line(tmp_path, monkeypatch):
    """An organ-targeted prompt is about the organism's own machinery: there is
    no science question, and the digest only matches on shared vocabulary."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _memory(tmp_path)
    organs = ("PyAutoBrain", "PyAutoMind", "PyAutoCortex", "PyAutoHeart",
              "PyAutoHands", "PyAutoNerves", "PyAutoEyes", "PyAutoPulse",
              "PyAutoInsight", "PyAutoMemory", "PyAutoBroca", "PyAutoGut",
              "PyAutoDNA", "PyAutoEars")
    # plus every non-organ repo the body map checks out under organs/
    extra = tuple(sorted(_intake._ORGANS_DIR_REPOS - _intake.ORGANISM_REPOS))
    assert extra, "expected a non-organ repo under organs/ in repos.yaml"
    organs = organs + extra
    for organ in organs:
        raw = _declared(organ)
        decision = _intake.analyse(raw, "test")
        assert decision["target_source"] == "declared", organ
        rel = _intake.write_prompt(mind, decision, raw, "test")
        text = (mind / rel).read_text(encoding="utf-8")
        assert "Memory:" not in text, organ
        assert decision["memory"] == [], organ
        # the gate holds at `_with_memory` itself, not only in write_prompt
        assert _intake._with_memory("Priority: normal", ["wiki/x.md"],
                                    decision["target"]) == "Priority: normal"


def test_library_target_with_hits_still_gets_memory_line(tmp_path, monkeypatch):
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _memory(tmp_path)
    raw = _declared(sorted(_intake.LIBRARY_REPOS)[0])  # any library, read from repos.yaml
    decision = _intake.analyse(raw, "test")
    assert decision["target_source"] == "declared"
    rel = _intake.write_prompt(mind, decision, raw, "test")
    line = _memory_line((mind / rel).read_text(encoding="utf-8"))
    assert "wiki/lensing/concepts/subhalo.md" in line


def test_organ_target_spellings_get_no_memory_line(tmp_path, monkeypatch):
    """`Target:` is matched case-insensitively and through an @-mention: a
    hand-written `pyautobrain` or `@PyAutoBrain` is still an organ target.
    The loop also covers every repo the body map checks out under organs/
    without `category: organ` (read from repos.yaml, never named here — the
    tenant firewall keeps instance facts out of test files)."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _memory(tmp_path)
    organs_dir_only = sorted(_intake._ORGANS_DIR_REPOS - _intake.ORGANISM_REPOS)
    assert organs_dir_only, "repos.yaml should hold an organs/ repo outside category: organ"
    for spelling in ("pyautobrain", "@PyAutoBrain", "PYAUTOMIND",
                     "@pyautoheart", *organs_dir_only):
        assert not _intake._cites_memory(spelling), spelling
        assert _intake._with_memory("Priority: normal", ["wiki/x.md"],
                                    spelling) == "Priority: normal", spelling
        raw = _declared(spelling)
        decision = _intake.analyse(raw, "test")
        rel = _intake.write_prompt(mind, decision, raw, "test")
        text = (mind / rel).read_text(encoding="utf-8")
        assert "Memory:" not in text, spelling
    # a library target spelled the same loose ways still cites
    library = sorted(_intake.LIBRARY_REPOS)[0]
    for spelling in (library.lower(), "@" + library):
        assert _intake._cites_memory(spelling), spelling
        assert _intake._with_memory("Priority: normal", ["wiki/x.md"],
                                    spelling).endswith("Memory: wiki/x.md")


# --- the score floor ------------------------------------------------------------
# The digest ranks by raw term counts, so a long page dense in "model",
# "profile" and "fit" topped it for any prompt and got cited on tooling prompts
# with no science question. A page is now cited only when the query terms it
# shares are distinctive in PyAutoMemory (on few of its pages) and weigh enough.

TOOLING = ("Write compile_repeats from the jax_compile tooling so the model "
           "fit profile can report its compile cost.")


def _declared_raw(body: str) -> str:
    library = sorted(_intake.LIBRARY_REPOS)[0]  # any library, read from repos.yaml
    return (f"# Library task\n\nType: feature\nTarget: {library}\n"
            f"Repos:\n- {library}\n\n{body}\n")


def _floor_memory(tmp_path: Path) -> Path:
    mem = _memory(tmp_path)
    # the page that dominates raw counts for any modelling prompt
    (mem / "wiki" / "galaxies" / "sources" / "massive-ellipticals.md").write_text(
        "# Massive ellipticals\n\n" + GENERIC * 200, encoding="utf-8")
    (mem / "wiki" / "methods" / "concepts").mkdir(parents=True)
    (mem / "wiki" / "methods" / "concepts" / "expectation-propagation.md"
     ).write_text("# Expectation propagation\n\nexpectation propagation "
                  "cavity moment matching loggaussian factor graphical\n"
                  + GENERIC, encoding="utf-8")
    return mem


def test_vocabulary_only_overlap_gets_no_memory_line(tmp_path, monkeypatch):
    """Witness: a library-targeted tooling prompt whose only overlap with the
    digest is generic words is filed with no `Memory:` line, even though the
    raw-count ranking has hits (massive-ellipticals.md tops it)."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    mem = _floor_memory(tmp_path)
    raw = _declared_raw(TOOLING)
    ranked = _intake._memory.digest(TOOLING, mem, None, None, 3)["pages"]
    assert ranked[0]["page"].endswith("massive-ellipticals.md")
    decision = _intake.analyse(raw, "test")
    assert _intake._cites_memory(decision["target"])
    rel = _intake.write_prompt(mind, decision, raw, "test")
    assert "Memory:" not in (mind / rel).read_text(encoding="utf-8")
    assert decision["memory"] == []


def test_distinctive_terms_still_get_memory_line(tmp_path, monkeypatch):
    """...while a prompt naming a page's distinctive terms still cites it, and
    only it: the generic-vocabulary pages stay below the floor."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    _floor_memory(tmp_path)
    raw = _declared_raw("Fix the expectation propagation cavity moment matching "
                        "for a loggaussian factor so the model fit converges.")
    decision = _intake.analyse(raw, "test")
    rel = _intake.write_prompt(mind, decision, raw, "test")
    line = _memory_line((mind / rel).read_text(encoding="utf-8"))
    assert line == "Memory: wiki/methods/concepts/expectation-propagation.md"


def test_navigation_pages_are_never_cited(tmp_path, monkeypatch):
    """reading-queue.md, index.md and a wiki's log.md list sources; they are
    not one, however many distinctive terms they share with the prompt."""
    monkeypatch.delenv("PYAUTO_MEMORY", raising=False)
    mind = _mind(tmp_path)
    mem = _memory(tmp_path)
    query = "Einstein ring quasar microlensing caustic crossing"
    navs = ("reading-queue.md", "index.md", "wiki/lensing/log.md")
    for i, rel in enumerate(navs):
        (mem / rel).write_text(f"# Nav {i}\n\n{query}\n" * 10, encoding="utf-8")
    assert len(_intake._memory.digest(query, mem, None, None, 9)["pages"]) == 3
    assert _intake.memory_citations(mind, "", query) == []
    # the same text on a source page is cited
    (mem / "wiki" / "lensing" / "concepts" / "caustics.md").write_text(
        f"# Caustics\n\n{query}\n", encoding="utf-8")
    for rel in navs:
        (mem / rel).unlink()
    assert _intake.memory_citations(mind, "", query) == [
        "wiki/lensing/concepts/caustics.md"]

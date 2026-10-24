"""Contracts for the two user-facing writing guides and their routing."""

from pathlib import Path


BRAIN_HOME = Path(__file__).resolve().parents[1]


def test_docs_entry_routes_people_pages_and_tutorials_separately():
    docs_entry = (BRAIN_HOME / "skills" / "docs" / "docs.md").read_text()

    assert "../WRITING_STYLE.md" in docs_entry
    assert "../TUTORIAL_WRITING_STYLE.md" in docs_entry
    assert "Mixed documents" in docs_entry


def test_review_faculty_checks_both_writing_surfaces():
    review = (
        BRAIN_HOME / "agents" / "faculties" / "review" / "AGENTS.md"
    ).read_text()

    assert "../../../skills/WRITING_STYLE.md" in review
    assert "../../../skills/TUTORIAL_WRITING_STYLE.md" in review


def test_tutorial_guide_keeps_notebook_and_ai_conventions_canonical():
    tutorial = (BRAIN_HOME / "skills" / "TUTORIAL_WRITING_STYLE.md").read_text()

    assert "__Contents__" in tutorial
    assert '\"\"\"__Section__\"\"\"' in tutorial
    assert "**🤖 Ask AI:**" in tutorial
    assert "**🤖 Ask Gemini:**" not in tutorial

"""tests/test_intake_declared_fields.py — intake honours declared Type, Target, Repos.

PyAutoBrain#472. The Intake (Conception) Agent honoured a declared Difficulty,
Autonomy and Priority but mishandled the rest of a pasted header block:

1. an unknown `Type:` (``hygiene``) was dropped silently and the type inferred;
2. a declared `Target:` was overridden by the first library named in prose;
3. a declared `Repos:` list was re-sorted and padded with prose mentions,
   including the phantom ``workspaces`` bucket;
4. a header block opening the input became the title/slug, and was echoed into
   the written body below the real header.

Unknown Types are deliberately NOT a hard error — an `intake ideas` batch must
not abort on one bad bullet — so they surface as a visible risk note, mapped
through a small alias table or filed to triage/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "conductors" / "intake"))
import _intake  # noqa: E402
from _intake import analyse, write_prompt  # noqa: E402

BODY = "The autoarray grid passed into the light profile is wrong for ellipse fits."


def _notes(d: dict) -> str:
    return "\n".join(d["risks"])


# --- 1. Type ------------------------------------------------------------------

def test_unknown_declared_type_is_flagged_not_silently_dropped():
    d = analyse("Type: vibes\n\nRemove the stale comments from the config yaml "
                "files and update the docs readme to match.", "test")
    # Not silently replaced by an inferred folder: it goes to triage/ ...
    assert d["proposed_path"].startswith("draft/triage/")
    # ... and the note names what was declared and the valid set.
    notes = _notes(d)
    assert "vibes" in notes
    for valid in ("feature", "bug", "maintenance", "docs"):
        assert valid in notes


def test_hygiene_maps_to_maintenance_with_a_visible_note():
    d = analyse("Type: hygiene\n\nRemove the stale comments from the config yaml "
                "files and update the docs readme in @PyAutoFit to match.", "test")
    assert d["work_type"] == "maintenance"
    assert d["work_type_source"] == "declared"
    assert d["proposed_path"].startswith("draft/maintenance/autofit/")
    assert "Type: maintenance" in d["header"]
    assert any("hygiene" in r and "maintenance" in r for r in d["risks"])


# --- 2. Target ----------------------------------------------------------------

@pytest.mark.parametrize("declared, folder, display", [
    ("autogalaxy", "autogalaxy", "PyAutoGalaxy"),
    ("autofit", "autofit", "PyAutoFit"),
    ("workspaces", "workspaces", "workspaces"),
])
def test_declared_target_is_honoured_and_homes_the_file(declared, folder, display):
    # The prose names PyAutoArray (a library) first — the scraper's pick.
    text = f"Type: bug\nTarget: {declared}\n\n{BODY} See @PyAutoArray and @PyAutoFit."
    d = analyse(text, "test")
    assert d["target"] == folder
    assert d["target_source"] == "declared"
    assert d["proposed_path"].startswith(f"draft/bug/{folder}/")
    assert f"Target: {display}" in d["header"]


def test_unknown_declared_target_falls_back_with_a_note():
    d = analyse(f"Type: bug\nTarget: NotARepo\n\n{BODY}", "test")
    assert d["target"] == "autoarray"
    assert d["target_source"] == "inferred"
    assert "NotARepo" in _notes(d)


# --- 3. Repos -----------------------------------------------------------------

def test_declared_repos_taken_as_written_in_order():
    text = ("Type: maintenance\nTarget: autofit\nRepos:\n- PyAutoFit\n- PyAutoConf\n\n"
            "The priors config drifts between autofit and autoarray; the "
            "workspaces also carry stale copies.")
    d = analyse(text, "test")
    # Order kept, no prose superset (autoarray), no phantom `workspaces`.
    assert d["repos_affected"] == ["autofit", "autonerves"]
    assert d["repos_source"] == "declared"
    assert "Repos:\n- PyAutoFit\n- PyAutoNerves\n" in d["header"]


def test_declared_repos_reject_unknown_names_with_a_note():
    text = ("Type: bug\nTarget: autofit\nRepos:\n- PyAutoFit\n- NotARepo\n\n"
            "Something in @PyAutoArray is broken.")
    d = analyse(text, "test")
    assert d["repos_affected"] == ["autofit"]
    assert "NotARepo" in _notes(d)


# --- 4. Header block vs title / body -----------------------------------------

def test_leading_header_block_is_not_the_title_or_slug():
    d = analyse("Target: autogalaxy\nType: bug\nDifficulty: small\n\n"
                "Ellipse fitting crashes when the mask is empty in autogalaxy.",
                "test")
    assert d["title"] == "Ellipse fitting crashes when the mask is empty in autogalaxy"
    assert "target" not in d["proposed_path"].split("/")[-1]
    assert d["proposed_path"].startswith("draft/bug/autogalaxy/ellipse_fitting")


def test_prose_first_line_with_a_header_key_is_not_eaten():
    # "Status:" is a header key, but this is a sentence opening a paragraph.
    text = ("Status: the dashboard renders stale rows after a merge in "
            "@PyAutoMind.\nIt should re-render on every push.")
    head, header_lines, body = _intake._split_header(text)
    assert head == "" and header_lines == []
    assert body == text
    assert analyse(text, "test")["title"].startswith("Status: the dashboard")


def test_header_block_is_not_echoed_into_the_body(tmp_path, monkeypatch):
    monkeypatch.setattr(_intake, "memory_citations", lambda *a, **k: [])
    text = ("# Ellipse crash\n\nType: bug\nTarget: autogalaxy\nDifficulty: small\n\n"
            "Ellipse fitting crashes when the mask is empty.")
    d = analyse(text, "test")
    rel = write_prompt(tmp_path, d, text, "test")
    written = (tmp_path / rel).read_text(encoding="utf-8")
    assert written.count("Type:") == 1
    assert written.count("Target:") == 1
    assert written.count("# Ellipse crash") == 1
    assert "Ellipse fitting crashes when the mask is empty." in written

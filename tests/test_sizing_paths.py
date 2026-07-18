"""tests/test_sizing_paths.py — parse_prompt vs the Mind lifecycle layout.

Locks the two path regimes the 2026-07-15/16 misroutes exposed (the Feature
Agent read `draft/bug/...` as work-type=draft, and `active/<name>.md` as
work-type=active): draft/ strips its state folder, active/ is flat and falls
back to the prompt's Type:/Target: header lines.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "faculties" / "sizing"))
from _sizing import parse_prompt  # noqa: E402

HEADER = """# A task

Type: bug
Target: PyAutoHands
Repos:
- PyAutoHands
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised

Body mentioning @PyAutoHands.
"""


def _write(mind: Path, rel: str) -> Path:
    p = mind / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER)
    return p


def test_draft_path_strips_state_folder(tmp_path):
    p = _write(tmp_path, "draft/bug/pyautohands/some_task.md")
    out = parse_prompt(p, tmp_path)
    assert out["work_type"] == "bug"
    assert out["target"] == "pyautohands"


def test_active_flat_path_falls_back_to_headers(tmp_path):
    p = _write(tmp_path, "active/some_task.md")
    out = parse_prompt(p, tmp_path)
    assert out["work_type"] == "bug"          # from Type: header
    assert out["target"] == "pyautohands"     # from Target: header
    assert "pyautohands" in out["repos"]


def test_legacy_flat_taxonomy_path_still_resolves(tmp_path):
    p = _write(tmp_path, "bug/pyautohands/some_task.md")
    out = parse_prompt(p, tmp_path)
    assert out["work_type"] == "bug"
    assert out["target"] == "pyautohands"


def test_header_never_overrides_a_valid_path_taxonomy(tmp_path):
    # Path says refactor/workspaces; header says bug/PyAutoHands — the path's
    # valid taxonomy wins (header is a fallback, not an override).
    p = _write(tmp_path, "draft/refactor/workspaces/some_task.md")
    out = parse_prompt(p, tmp_path)
    assert out["work_type"] == "refactor"
    assert out["target"] == "workspaces"

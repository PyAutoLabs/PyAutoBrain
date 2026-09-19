"""Hygiene workspace scanners include repositories one family level down."""

import runpy
from pathlib import Path

import pytest


HYG = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "hygiene"


@pytest.mark.parametrize("module", [
    "_hygiene_docstrings.py", "_hygiene_escapes.py", "_hygiene_refs.py",
])
def test_grouped_repository_discovery(tmp_path, module):
    repo = tmp_path / "science" / "demo_workspace"
    (repo / ".git").mkdir(parents=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "example.py").write_text("pass\n")
    functions = runpy.run_path(str(HYG / module))
    assert functions["repository_paths"](tmp_path) == [repo]
    assert "1 repo" in functions["row_for"](tmp_path)["summary"]

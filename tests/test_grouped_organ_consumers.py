"""Runtime callers use organ placement while the marker stays at the outer root."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN / "agents"))


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, BRAIN / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _grouped(tmp_path: Path) -> Path:
    (tmp_path / ".pyauto-root").touch()
    organs = tmp_path / "organs"
    for name in ("PyAutoBrain", "PyAutoMind", "PyAutoMemory", "PyAutoHeart"):
        (organs / name).mkdir(parents=True)
        (organs / name / ".git").mkdir()
    return organs


def test_intake_memory_finds_grouped_checkout(tmp_path, monkeypatch):
    organs = _grouped(tmp_path)
    (organs / "PyAutoMind" / "repos.yaml").write_text(
        (BRAIN.parent / "PyAutoMind" / "repos.yaml").read_text())
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path))
    intake = _load("grouped_intake", "agents/conductors/intake/_intake.py")
    assert intake._memory_home(organs / "PyAutoMind") == organs / "PyAutoMemory"


def test_hygiene_map_and_heart_board_find_grouped_checkouts(tmp_path, monkeypatch):
    organs = _grouped(tmp_path)
    (organs / "PyAutoMind" / "repos.yaml").write_text("repos:\n")
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path))
    repos = _load("grouped_hygiene_repos", "agents/conductors/hygiene/_hygiene_repos.py")
    assert repos.resolve_map() == organs / "PyAutoMind" / "repos.yaml"
    ci = _load("grouped_hygiene_ci", "agents/conductors/hygiene/_hygiene_ci.py")
    assert str(organs / "PyAutoHeart" / "board" / "board.json") in ci.candidate_sources(None, "PyAutoHeart")


def test_hygiene_config_reads_grouped_nerves(tmp_path):
    organs = _grouped(tmp_path)
    source = organs / "PyAutoNerves" / "autonerves" / "config"
    source.mkdir(parents=True)
    (organs / "PyAutoNerves" / ".git").mkdir()
    (source / "general.yaml").write_text("test: true\n")
    config = _load("grouped_hygiene_config", "agents/conductors/hygiene/_hygiene_config.py")
    assert "general.yaml" in config.library_config_relpaths(str(tmp_path), [("PyAutoNerves", "autonerves")])


def test_batch_root_uses_outer_marker(tmp_path, monkeypatch):
    _grouped(tmp_path)
    monkeypatch.setenv("PYAUTO_ROOT", str(tmp_path))
    batch = _load("grouped_integration", "agents/conductors/batch/_integration.py")
    assert batch.workspace_root() == tmp_path

"""Workspace-local discovery preserves user state and needs no optional organs."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('starter_discovery', ROOT / 'bin/project_discovery.py')
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


@pytest.fixture
def workspace(tmp_path):
    for repo, skill in [('PyAutoBrain', 'feature'), ('PyAutoMind', 'create_issue')]:
        path = tmp_path / repo / 'skills' / skill
        path.mkdir(parents=True)
        (path / 'SKILL.md').write_text(f'---\nname: {skill.replace("_", "-")}\ndescription: Example skill\n---\nRead local instructions.\n')
    (tmp_path / 'PyAutoMind/repos.yaml').write_text('repos:\n  PyAutoBrain:\n    category: organ\n  PyAutoMind:\n    category: organ\n')
    return tmp_path


def test_check_write_idempotence_and_preservation(workspace, tmp_path):
    assert discovery.starter(workspace, False) == 1
    assert not (workspace / '.claude').exists()
    assert discovery.starter(workspace, True) == 0
    target = workspace / '.claude/skills/feature'
    assert target.is_symlink()
    assert not target.readlink().is_absolute()
    assert target.resolve() == workspace / 'PyAutoBrain/skills/feature'
    personal = workspace / '.claude/skills/personal'
    personal.mkdir()
    (personal / 'SKILL.md').write_text('user owned')
    assert discovery.starter(workspace, False) == 0
    assert discovery.starter(workspace, True) == 0
    assert (personal / 'SKILL.md').read_text() == 'user owned'
    assert not (workspace / '.codex').exists()
    assert not (workspace / 'PyAutoBrain/.claude').exists()
    assert not (workspace / 'PyAutoMind/.claude').exists()


@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'parent'])
def test_conflict_prevents_all_writes(workspace, kind):
    dest = workspace / '.claude/skills/create_issue'
    dest.parent.mkdir(parents=True)
    if kind == 'file':
        dest.write_text('preserve')
    elif kind == 'directory':
        dest.mkdir()
    elif kind == 'symlink':
        dest.symlink_to(workspace / 'absent')
    else:
        dest.parent.rmdir()
        dest.parent.symlink_to(workspace / 'PyAutoMind', target_is_directory=True)
    with pytest.raises(ValueError, match='protected'):
        discovery.starter(workspace, True)
    assert not (workspace / '.claude/skills/feature').exists()


def test_missing_registration_rejected(workspace):
    (workspace / 'PyAutoMind/repos.yaml').write_text('repos: {}\n')
    with pytest.raises(ValueError, match='registered'):
        discovery.starter(workspace, True)
    assert not (workspace / '.claude').exists()


def test_duplicate_skill_rejected(workspace):
    path = workspace / 'PyAutoMind/skills/feature'
    path.mkdir()
    (path / 'SKILL.md').write_text('---\nname: feature\ndescription: Example\n---\n')
    with pytest.raises(ValueError, match='collision'):
        discovery.starter(workspace, True)
    assert not (workspace / '.claude').exists()

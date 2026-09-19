"""Protect local instructions while migrating known context-heavy sections."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

BRAIN = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workspace_instructions', BRAIN / 'bin/workspace_instructions.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SECTIONS = json.loads((module.POLICY / 'workspace_sections.json').read_text())
LEGACY = json.loads((module.POLICY / 'workspace_sections_legacy.json').read_text())


def original():
    return '# Workspace\n\n' + '\n'.join(LEGACY.values()) + '\n## Local additions\nKeep this rule and historical `PyAutoBuild/skills/pre_build`.\n'


def test_migration_is_idempotent_and_preserves_unowned_sections():
    source = original().replace('## Development workflow', '## Safety rules\nNever rewrite pushed history.\n\n## Development workflow', 1)
    updated = module.render(source, SECTIONS, LEGACY)
    assert '## Safety rules\nNever rewrite pushed history.' in updated
    assert '## Local additions\nKeep this rule and historical `PyAutoBuild/skills/pre_build`.' in updated
    assert module.render(updated, SECTIONS, LEGACY) == updated
    assert len(updated) < len(source)


def test_unknown_local_edits_and_duplicate_sections_fail_closed():
    import pytest
    with pytest.raises(ValueError, match='unrecognized local edits'):
        module.render(original().replace('This workspace contains', 'Keep custom wording. This workspace contains'), SECTIONS, LEGACY)
    with pytest.raises(ValueError, match='expected one section'):
        module.render(original() + next(iter(SECTIONS)) + '\n', SECTIONS, LEGACY)


def test_check_never_writes_and_write_preserves_symlink(tmp_path):
    target = tmp_path / 'shared.md'
    target.write_text(original())
    link = tmp_path / 'AGENTS.md'
    link.symlink_to(target)
    cmd = [sys.executable, str(BRAIN / 'bin/workspace_instructions.py'), '--root', str(tmp_path)]
    assert subprocess.run(cmd, capture_output=True).returncode == 1
    assert target.read_text() == original()
    assert subprocess.run(cmd + ['--write'], capture_output=True).returncode == 0
    assert link.is_symlink()
    assert subprocess.run(cmd, capture_output=True).returncode == 0

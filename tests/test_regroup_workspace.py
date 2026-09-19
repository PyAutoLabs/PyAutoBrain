"""Exercise real Git administration and reversible data/link preservation."""
import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agents'))
spec = importlib.util.spec_from_file_location('regroup_under_test', ROOT / 'bin/regroup_workspace.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def fixture(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / '.pyauto-root').touch()
    (root / 'PyAutoMind').mkdir()
    (root / 'PyAutoMind/repos.yaml').write_text('repos:\n  Demo:\n    path: science/Demo\n    package: demo\n')
    repo = root / 'Demo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'test@example.org')
    git(repo, 'config', 'user.name', 'Test')
    (repo / '.gitignore').write_text('output/\n')
    git(repo, 'add', '.gitignore')
    git(repo, 'commit', '-qm', 'initial')
    (repo / 'output').mkdir()
    (repo / 'output/result.bin').write_bytes(b'irreplaceable result')
    (repo / 'untracked.txt').write_text('user work')
    bundles = tmp_path / 'bundles'
    task = bundles / 'task'
    task.mkdir(parents=True)
    git(repo, 'worktree', 'add', '-qb', 'task', str(task / 'Demo'))
    (task / 'activate.sh').write_text('export PYAUTO_ROOT=' + str(task) + '\n')
    dependency = bundles / 'other'
    dependency.mkdir()
    (dependency / 'Demo').symlink_to(repo, target_is_directory=True)
    (root / '.idea').mkdir()
    (root / '.idea/vcs.xml').write_text('<path value="$PROJECT_DIR$/Demo"/>')
    (root / '.claude').mkdir()
    (root / '.claude/settings.json').write_text('{"hook": "${CLAUDE_PROJECT_DIR}/Demo/hook.py"}')
    return root, repo, bundles, task


def test_apply_and_rollback_preserve_dirty_data_and_linked_worktree(tmp_path):
    root, repo, bundles, task = fixture(tmp_path)
    journal = tmp_path / 'journal.json'
    data = migration.plan(root, journal, bundles)
    before = migration.snapshot(repo)
    migration.apply(journal, data)
    new = root / 'science/Demo'
    assert not repo.exists()
    assert (new / 'output/result.bin').read_bytes() == b'irreplaceable result'
    assert (new / 'untracked.txt').read_text() == 'user work'
    assert migration.snapshot(new) == before
    assert git(task / 'Demo', 'branch', '--show-current') == 'task'
    assert (bundles / 'other/Demo').resolve() == new
    assert 'science/Demo' in (root / '.idea/vcs.xml').read_text()
    assert '${CLAUDE_PROJECT_DIR}/science/Demo/hook.py' in (root / '.claude/settings.json').read_text()
    import json
    assert json.loads((root / '.claude/settings.json').read_text())['env']['PYTHONPATH'] == str(new)
    assert f'export PYAUTO_MIND={task}/PyAutoMind' in (task / 'activate.sh').read_text()
    migration.rollback(journal, data)
    assert 'PYAUTO_MIND=' not in (task / 'activate.sh').read_text()
    assert migration.snapshot(repo) == before
    assert not new.exists()
    assert (bundles / 'other/Demo').resolve() == repo
    assert git(task / 'Demo', 'branch', '--show-current') == 'task'
    assert 'science/Demo' not in (root / '.idea/vcs.xml').read_text()
    assert '${CLAUDE_PROJECT_DIR}/Demo/hook.py' in (root / '.claude/settings.json').read_text()


def test_stale_plan_cannot_overwrite_new_user_work(tmp_path):
    import pytest
    root, repo, bundles, _ = fixture(tmp_path)
    journal = tmp_path / 'journal.json'
    data = migration.plan(root, journal, bundles)
    (repo / 'new-work.txt').write_text('arrived after plan')
    with pytest.raises(ValueError, match='source changed'):
        migration.apply(journal, data)
    assert repo.exists()
    assert not (root / 'science/Demo').exists()


def test_destination_family_cannot_redirect_move(tmp_path):
    import pytest
    root, repo, bundles, _ = fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    journal = tmp_path / 'journal.json'
    data = migration.plan(root, journal, bundles)
    (root / 'science').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='family must be a real directory'):
        migration.apply(journal, data)
    assert repo.exists()
    assert not (outside / 'Demo').exists()


def test_journal_does_not_follow_preexisting_temp_link(tmp_path):
    journal = tmp_path / 'journal.json'
    important = tmp_path / 'important.txt'
    important.write_text('KEEP')
    journal.with_suffix('.json.tmp').symlink_to(important)
    migration.save(journal, {'stage': 'planned'})
    assert important.read_text() == 'KEEP'
    assert 'planned' in journal.read_text()


def test_moving_manifest_checkout_keeps_journal_and_rollback_working(tmp_path):
    import pytest
    root, _, bundles, _ = fixture(tmp_path)
    mind = root / 'PyAutoMind'
    manifest = mind / 'repos.yaml'
    manifest.write_text(manifest.read_text() + '  PyAutoMind:\n    path: organs/PyAutoMind\n')
    git(mind, 'init', '-q')
    git(mind, 'config', 'user.email', 'test@example.org')
    git(mind, 'config', 'user.name', 'Test')
    git(mind, 'add', 'repos.yaml')
    git(mind, 'commit', '-qm', 'manifest')
    with pytest.raises(ValueError, match='journal must be outside'):
        migration.plan(root, mind / 'journal.json', bundles)
    journal = tmp_path / 'journal.json'
    data = migration.plan(root, journal, bundles)
    migration.apply(journal, data)
    assert migration.manifest_paths(root)['Demo'] == Path('science/Demo')
    assert not mind.exists()
    assert journal.exists()
    migration.verify(data)
    migration.rollback(journal, data)
    assert manifest.exists()

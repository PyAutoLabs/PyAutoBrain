"""Repository identity survives grouped canonical trees and flat task/CI trees."""
from pathlib import Path
import subprocess

import pytest

from _helpers import load_module

MODULE = Path(__file__).resolve().parents[1] / 'agents' / '_repo_paths.py'
paths = load_module('repo_paths_under_test', MODULE, register=False)


def manifest(root, body='  Demo:\n    path: science/Demo\n'):
    (root / 'PyAutoMind').mkdir(exist_ok=True)
    (root / 'PyAutoMind' / 'repos.yaml').write_text('repos:\n' + body)


def checkout(path):
    (path / '.git').mkdir(parents=True)
    return path


@pytest.mark.parametrize('layout', ['flat', 'grouped'])
def test_context_owns_checkout(tmp_path, layout):
    manifest(tmp_path)
    actual = checkout(tmp_path / ('science/Demo' if layout == 'grouped' else 'Demo'))
    assert paths.repo_path(tmp_path, 'Demo', required=True) == actual
    assert actual in paths.iter_checkouts(tmp_path)


def test_flat_bundle_symlink_uses_its_own_context(tmp_path):
    canonical = tmp_path / 'canonical'
    canonical.mkdir()
    manifest(canonical)
    target = checkout(canonical / 'science/Demo')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'PyAutoMind').symlink_to(canonical / 'PyAutoMind', target_is_directory=True)
    (bundle / 'Demo').symlink_to(target, target_is_directory=True)
    assert paths.repo_path(bundle, 'Demo', required=True) == bundle / 'Demo'
    assert paths.repo_paths(bundle)['Demo'] == bundle / 'Demo'


def test_missing_repo_stays_in_coverage(tmp_path):
    manifest(tmp_path)
    assert paths.repo_paths(tmp_path) == {'Demo': tmp_path / 'science/Demo'}
    with pytest.raises(FileNotFoundError, match='Demo'):
        paths.repo_path(tmp_path, 'Demo', required=True)


def test_plain_directory_does_not_prove_a_checkout(tmp_path):
    (tmp_path / 'Demo').mkdir()
    assert paths.iter_checkouts(tmp_path) == []
    with pytest.raises(FileNotFoundError):
        paths.repo_path(tmp_path, 'Demo', required=True)


def test_ambiguity_is_not_silently_resolved(tmp_path):
    checkout(tmp_path / 'Demo')
    checkout(tmp_path / 'science/Demo')
    with pytest.raises(ValueError, match='ambiguous'):
        paths.repo_path(tmp_path, 'Demo')
    with pytest.raises(ValueError, match='ambiguous'):
        paths.iter_checkouts(tmp_path)


def test_alias_to_same_checkout_is_unambiguous(tmp_path):
    target = checkout(tmp_path / 'science/Demo')
    (tmp_path / 'Demo').symlink_to(target, target_is_directory=True)
    assert paths.repo_path(tmp_path, 'Demo') == tmp_path / 'Demo'
    assert len(paths.iter_checkouts(tmp_path)) == 1


def test_enumeration_stops_at_git_boundary(tmp_path):
    top = checkout(tmp_path / 'science/Demo')
    checkout(top / 'dataset/HiddenClone')
    assert paths.iter_checkouts(tmp_path) == [top]


@pytest.mark.parametrize('value', ['/outside/Demo', '../Demo', 'science/../Demo', 'science/Wrong', 'a/b/Demo'])
def test_rejects_unsafe_placement(tmp_path, value):
    manifest(tmp_path, f'  Demo:\n    path: {value}\n')
    with pytest.raises(ValueError):
        paths.repo_path(tmp_path, 'Demo')


def test_shell_and_python_agree(tmp_path):
    manifest(tmp_path)
    actual = checkout(tmp_path / 'science/Demo')
    shell = MODULE.parents[1] / 'bin/_repo_paths.sh'
    result = subprocess.run(['bash', '-c', 'source "$1"; pyauto_repo_path Demo "$2"', 'test', str(shell), str(tmp_path)], text=True, capture_output=True, check=True)
    assert result.stdout.strip() == str(actual)


def test_declared_family_cannot_escape_via_symlink(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    manifest(root)
    external = tmp_path / 'outside'
    checkout(external / 'Demo')
    (root / 'science').symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='family must not be a symlink'):
        paths.repo_path(root, 'Demo', required=True)


def test_pythonpath_follows_manifest_package_order(tmp_path):
    manifest(tmp_path, '  Demo:\n    path: science/Demo\n    package: demo\n  Other:\n    package: other\n')
    first = checkout(tmp_path / 'science/Demo')
    second = checkout(tmp_path / 'Other')
    assert paths.package_paths(tmp_path) == [first, second]


def test_grouped_mind_bootstraps_its_own_manifest(tmp_path):
    bootstrap_repo_path = paths.bootstrap_repo_path
    manifest_paths = paths.manifest_paths
    package_paths = paths.package_paths
    mind = tmp_path / 'organs/PyAutoMind'
    mind.mkdir(parents=True)
    (mind / '.git').mkdir()
    (mind / 'repos.yaml').write_text('repos:\n  PyAutoMind:\n    path: organs/PyAutoMind\n  Demo:\n    path: science/Demo\n    package: demo\n')
    assert bootstrap_repo_path(tmp_path, 'PyAutoMind', required=True) == mind
    assert manifest_paths(tmp_path)['Demo'] == Path('science/Demo')
    assert package_paths(tmp_path) == [tmp_path / 'science/Demo']
    (tmp_path / 'PyAutoMind').mkdir()
    with pytest.raises(ValueError, match='ambiguous'):
        manifest_paths(tmp_path)


# ---------------------------------------------- the one body-map reader ---
BODY_MAP = '''# header comment
categories:
  library:
    category: not-a-repo
repos:
  # --- organs ---
  PyAutoMind:   # the Mind
    github: "Org/PyAutoMind"  # quoted, commented
    path: 'organs/PyAutoMind'

  autofit_tool:
    # a comment inside an entry
    category: library # trailing
    package: autofit
smoke_bootstrap_rollout: true
later:
  Ghost:
    category: organ
'''


def test_manifest_field_reads_only_the_repos_block_raw():
    module = paths
    assert module.manifest_repos(BODY_MAP) == ['PyAutoMind', 'autofit_tool']
    assert module.manifest_field(BODY_MAP, 'category') == {'autofit_tool': 'library # trailing'}
    assert module.manifest_field(BODY_MAP, 'github') == {
        'PyAutoMind': '"Org/PyAutoMind"  # quoted, commented'}
    assert module.manifest_field(BODY_MAP, 'path') == {'PyAutoMind': "'organs/PyAutoMind'"}
    assert module.manifest_field(BODY_MAP, 'package') == {'autofit_tool': 'autofit'}


def test_manifest_homes_and_majority_owner():
    module = paths
    text = ('repos:\n  A:\n    github: Org/A\n  B:\n    github: Org/B  # c\n'
            '  C:\n    github: Org/C\n  D:\n    github: Other/D\n')
    assert module.manifest_homes(text) == ['Org/A', 'Org/C', 'Other/D']
    assert module.majority_owner(module.manifest_homes(text)) == 'Org'
    assert module.majority_owner([]) is None


def test_the_reader_needs_no_pyyaml():
    source = MODULE.read_text()
    assert 'import yaml' not in source and 'from yaml' not in source

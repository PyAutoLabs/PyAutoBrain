#!/usr/bin/env python3
"""Plan/apply/rollback local checkout placement declared by the body map.

No git content is edited. Renames preserve ignored data and untracked files.
The durable journal records original symlinks and local configuration; every
mutation can be reversed with rollback. Run plan first and inspect its summary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from _repo_paths import manifest_paths, package_paths, repo_path


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def remap(path, moves):
    path = Path(os.path.abspath(path))
    for old, new in moves:
        try:
            return Path(new) / path.relative_to(old)
        except ValueError:
            pass
    return path


def snapshot(path):
    stat = path.stat()
    return {'head': git(path, 'rev-parse', 'HEAD'),
            'status': git(path, 'status', '--porcelain', '--untracked-files=all'),
            'device': stat.st_dev, 'inode': stat.st_ino}


def symlinks(roots):
    seen = set()
    for root in roots:
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('.git', '.git-salvage')]
            for name in dirs + files:
                path = Path(current) / name
                if path.is_symlink() and str(path) not in seen:
                    seen.add(str(path))
                    yield path


def save(state, data):
    state.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=state.name + '.', dir=state.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(state)
    finally:
        if temporary.exists():
            temporary.unlink()



def validate_destination(root, new):
    root, new = Path(root).absolute(), Path(new).absolute()
    if new.parent.parent != root:
        raise ValueError(f'destination must be inside one workspace family: {new}')
    family = new.parent
    if family.is_symlink() or (family.exists() and not family.is_dir()) or (family / '.git').exists():
        raise ValueError(f'destination family must be a real directory, not a symlink or checkout: {family}')


def plan(root, state, bundles_root=None, manifest_root=None):
    root = root.absolute()
    if not (root / '.pyauto-root').is_file():
        raise ValueError('the canonical workspace must carry .pyauto-root')
    if state.exists():
        raise ValueError(f'refusing to overwrite migration journal: {state}')
    moves, records = [], []
    for name, relative in manifest_paths(manifest_root or root).items():
        old = repo_path(root, name, required=True).absolute()
        new = root / relative
        if old == new:
            continue
        if old.is_symlink() or old.parent != root:
            raise ValueError(f'{name}: source must be a canonical flat checkout: {old}')
        validate_destination(root, new)
        if new.exists() or new.is_symlink():
            raise ValueError(f'{name}: destination already exists: {new}')
        if not (old / '.git').is_dir():
            raise ValueError(f'{name}: refusing to move a linked worktree as canonical')
        worktrees = [line[9:] for line in git(old, 'worktree', 'list', '--porcelain').splitlines()
                     if line.startswith('worktree ')]
        records.append({'name': name, 'old': str(old), 'new': str(new),
                        'before': snapshot(old), 'worktrees': worktrees})
        moves.append((str(old), str(new)))
    if any(state.absolute().is_relative_to(Path(old)) for old, _ in moves):
        raise ValueError('migration journal must be outside every checkout being moved')
    roots = [root]
    if bundles_root is not None and bundles_root.exists():
        roots.append(bundles_root.absolute())
    # Git may register task roots elsewhere: include only their immediate
    # dependency links; never recursively walk arbitrary parents like /tmp.
    links = list(symlinks(roots))
    known = {str(p) for p in links}
    for row in records:
        for wt in row['worktrees']:
            parent = Path(wt).parent
            if parent not in roots and parent.is_dir():
                for p in parent.iterdir():
                    if p.is_symlink() and str(p) not in known:
                        links.append(p)
                        known.add(str(p))
    link_changes = []
    for path in links:
        raw = os.readlink(path)
        target = Path(raw) if os.path.isabs(raw) else path.parent / raw
        relocated = remap(path, moves)
        new_target = remap(target, moves)
        if relocated == path and new_target == Path(os.path.abspath(target)):
            continue
        new_raw = str(new_target) if os.path.isabs(raw) else os.path.relpath(new_target, relocated.parent)
        if new_raw != raw:
            link_changes.append({'old_path': str(path), 'new_path': str(relocated),
                                 'old': raw, 'new': new_raw})
    configs = []
    # These are local, workspace-owned paths, not versioned source or shell RCs.
    config_paths = list((root / '.idea').glob('*.xml')) + list((root / '.idea').glob('*.iml'))
    config_paths += [root / '.claude/settings.json', root / '.codex/hooks.json',
                     root / 'AGENTS.md', root / 'CLAUDE.md']
    for path in config_paths:
        if not path.is_file() or path.is_symlink():
            continue
        before = path.read_text()
        after = before
        for old, new in sorted(moves, key=lambda pair: len(pair[0]), reverse=True):
            # Absolute paths and IDE-relative paths both have repo boundaries.
            name = Path(old).name
            relative = str(Path(new).relative_to(root))
            after = re.sub(re.escape(old) + r'(?=[/"\s:<]|$)', lambda _: new, after)
            for prefix in ('$PROJECT_DIR$/', '$MODULE_DIR$/', './', '${CLAUDE_PROJECT_DIR}/', '$CLAUDE_PROJECT_DIR/', '${PYAUTO_ROOT}/', '$PYAUTO_ROOT/'):
                after = re.sub(re.escape(prefix + name) + r'(?=[/"\s<]|$)', lambda _, p=prefix, r=relative: p+r, after)
            if path.name in ('AGENTS.md', 'CLAUDE.md'):
                after = re.sub(r'(?<![\w/])' + re.escape(name) + r'(?=/)', lambda _, r=relative: r, after)
        if path == root / '.claude/settings.json':
            settings = json.loads(after)
            import_roots = [str(remap(p, moves)) for p in package_paths(root)]
            if import_roots:
                if repo_path(root, 'PyAutoHeart').is_dir():
                    import_roots.append(str(remap(repo_path(root, 'PyAutoHeart'), moves)))
                environment = settings.setdefault('env', {})
                previous = environment.get('PYTHONPATH', '')
                environment['PYTHONPATH'] = os.pathsep.join(import_roots + ([previous] if previous else []))
                after = json.dumps(settings, indent=2) + '\n'
        if before != after:
            configs.append({'path': str(path), 'old': before, 'new': after})
    # Older bundles predate organ environment overrides. Sourcing them after
    # the canonical activation must select their own flat dependency links.
    task_roots = {Path(wt).parent for row in records for wt in row['worktrees']
                  if wt != row['old']}
    if bundles_root is not None and bundles_root.is_dir():
        task_roots.update(p for p in bundles_root.iterdir() if p.is_dir() and not p.is_symlink())
    import shlex
    for task_root in sorted(task_roots):
        task_activation = task_root / 'activate.sh'
        if not task_activation.is_file() or task_activation.is_symlink():
            continue
        before = task_activation.read_text()
        exports = '\n# Select this bundle after a canonical workspace activation.\n'
        for variable, name in [('BRAIN', 'PyAutoBrain'), ('MIND', 'PyAutoMind'),
                               ('HEART', 'PyAutoHeart'), ('HANDS', 'PyAutoHands')]:
            exports += f'export PYAUTO_{variable}={shlex.quote(str(task_root / name))}\n'
        exports += 'export PATH="$PYAUTO_BRAIN/bin:$PYAUTO_HEART/bin:$PYAUTO_HANDS/bin:$PATH"\n'
        configs.append({'path': str(task_activation), 'old': before, 'new': before + exports})
    activation = root / 'activate.sh'
    brain_relative = str(remap(repo_path(root, 'PyAutoBrain'), moves).relative_to(root))
    heart_relative = str(remap(repo_path(root, 'PyAutoHeart'), moves).relative_to(root))
    mind_relative = str(remap(repo_path(root, 'PyAutoMind'), moves).relative_to(root))
    hands_relative = str(remap(repo_path(root, 'PyAutoHands'), moves).relative_to(root))
    activate_text = '''# Source this file after opening a shell in the grouped workspace.
_pyauto_activation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYAUTO_ROOT="$_pyauto_activation_root"
export PYAUTO_BRAIN="$PYAUTO_ROOT/@BRAIN@"
export PYAUTO_MIND="$PYAUTO_ROOT/@MIND@"
export PYAUTO_HEART="$PYAUTO_ROOT/@HEART@"
export PYAUTO_HANDS="$PYAUTO_ROOT/@HANDS@"
export PATH="$PYAUTO_BRAIN/bin:$PYAUTO_HEART/bin:$PYAUTO_HANDS/bin:$PATH"
_pyauto_import_paths="$(python3 "$PYAUTO_ROOT/@BRAIN@/agents/_repo_paths.py" pythonpath --root "$PYAUTO_ROOT")" || return
export PYTHONPATH="$_pyauto_import_paths:$PYAUTO_ROOT/@HEART@${PYTHONPATH:+:$PYTHONPATH}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/tmp/numba_cache}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/matplotlib}"
mkdir -p "$NUMBA_CACHE_DIR" "$MPLCONFIGDIR"
unset _pyauto_activation_root _pyauto_import_paths _pyauto_import_repo _pyauto_import_dir
'''.replace('@BRAIN@', brain_relative).replace('@HEART@', heart_relative).replace('@MIND@', mind_relative).replace('@HANDS@', hands_relative)
    configs.append({'path': str(activation), 'old': activation.read_text() if activation.exists() else None,
                    'new': activate_text})
    data = {'root': str(root), 'stage': 'planned', 'repos': records,
            'links': link_changes, 'configs': configs, 'completed': []}
    save(state, data)
    return data


def verify(data):
    for row in data['repos']:
        new = Path(row['new'])
        if snapshot(new) != row['before']:
            raise ValueError(f'{row["name"]}: checkout content or identity changed during migration')
        for old_wt in row['worktrees']:
            wt = new if old_wt == row['old'] else Path(old_wt)
            git(wt, 'rev-parse', '--git-common-dir')
            git(wt, 'status', '--porcelain', '--untracked-files=no')
    for row in data['links']:
        if os.readlink(row['new_path']) != row['new']:
            raise ValueError(f'link was not repaired: {row["new_path"]}')


def replace_link(path, target):
    path = Path(path)
    temporary = path.with_name(path.name + '.regroup-link')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError(f'link staging path already exists: {temporary}')
    temporary.symlink_to(target)
    temporary.replace(path)


def read_optional(path):
    path = Path(path)
    return path.read_text() if path.exists() else None


def rollback(state, data):
    for row in reversed(data['configs']):
        path = Path(row['path'])
        if read_optional(path) == row['new']:
            if row['old'] is None:
                path.unlink()
            else:
                path.write_text(row['old'])
        elif read_optional(path) != row['old']:
            raise ValueError(f'local configuration changed since migration: {path}')
    for row in reversed(data['links']):
        path = Path(row['new_path'])
        if not path.is_symlink():
            path = Path(row['old_path'])
        if path.is_symlink() and os.readlink(path) == row['new']:
            replace_link(path, row['old'])
    for row in reversed(data['repos']):
        old, new = Path(row['old']), Path(row['new'])
        if new.exists() and not old.exists():
            new.rename(old)
            git(old, 'worktree', 'repair')
    for parent in {Path(row['new']).parent for row in data['repos']}:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    data['stage'] = 'rolled-back'
    save(state, data)


def apply(state, data):
    if data['stage'] != 'planned':
        raise ValueError(f'journal is {data["stage"]}; expected planned')
    # Validate every source before changing any of them.
    for row in data['repos']:
        validate_destination(data['root'], row['new'])
        if Path(row['new']).exists() or Path(row['new']).is_symlink():
            raise ValueError(f'destination appeared since planning: {row["new"]}')
        if snapshot(Path(row['old'])) != row['before']:
            raise ValueError(f'{row["name"]}: source changed since planning; make a fresh plan')
    for row in data['links']:
        if os.readlink(row['old_path']) != row['old']:
            raise ValueError(f'link changed since planning: {row["old_path"]}')
    for row in data['configs']:
        if read_optional(row['path']) != row['old']:
            raise ValueError(f'configuration changed since planning: {row["path"]}')
    data['stage'] = 'applying'
    save(state, data)
    try:
        for row in data['repos']:
            old, new = Path(row['old']), Path(row['new'])
            validate_destination(data['root'], new)
            new.parent.mkdir(exist_ok=True)
            old.rename(new)
            data['completed'].append(row['name'])
            save(state, data)
            git(new, 'worktree', 'repair')
        for row in data['links']:
            path = Path(row['new_path'])
            replace_link(path, row['new'])
        for row in data['configs']:
            if read_optional(row['path']) != row['old']:
                raise ValueError(f'configuration changed during migration: {row["path"]}')
            Path(row['path']).write_text(row['new'])
        verify(data)
    except Exception:
        rollback(state, data)
        raise
    data['stage'] = 'applied'
    save(state, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'apply', 'verify', 'rollback'])
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--bundles-root', type=Path)
    parser.add_argument('--manifest-root', type=Path)
    args = parser.parse_args()
    if args.command == 'plan':
        if args.root is None:
            parser.error('plan requires --root')
        data = plan(args.root, args.state, args.bundles_root, args.manifest_root)
    else:
        data = json.loads(args.state.read_text())
        if args.command == 'apply':
            apply(args.state, data)
        elif args.command == 'verify':
            verify(data)
        else:
            rollback(args.state, data)
    print(f'{data["stage"]}: {len(data["repos"])} repos, {len(data["links"])} symlinks, {len(data["configs"])} local configs')
    if args.command == 'plan':
        for row in data['repos']:
            print(f'  {row["old"]} -> {row["new"]}')


if __name__ == '__main__':
    main()

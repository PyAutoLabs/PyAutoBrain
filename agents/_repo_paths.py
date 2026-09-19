#!/usr/bin/env python3
"""Repository placement, independent of a workspace's physical layout.

Mind's repos.yaml declares preferred canonical paths. Actual context wins: CI
and task bundles can still place those same repositories side by side. Discovery
stops at checkout boundaries and rejects ambiguity rather than selecting another
checkout silently. Missing optional paths are returned for callers which inspect
partial clones; callers requiring a repository use required=True.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import re
import sys


def _name(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
        raise ValueError(f'unsafe repository identity: {name!r}')
    return name


def _placement(name: str, value: str) -> Path:
    if not isinstance(value, str) or '\\' in value:
        raise ValueError(f'{name}: invalid repository path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not path.parts or path.name != name:
        raise ValueError(f'{name}: unsafe repository path: {value!r}')
    if len(path.parts) > 2 or any(p.startswith('.') for p in path.parts[:-1]):
        raise ValueError(f'{name}: expected a repository at root or in one family directory: {value!r}')
    return Path(*path.parts)


def manifest_paths(root: Path) -> dict[str, Path]:
    """Read only identity and placement from the body's simple YAML mapping.

    This bootstrap must work before PyYAML is installed. Accept the manifest's
    two/four-space mapping grammar, including quoted path scalars, and validate
    every explicit placement. Other metadata is deliberately not interpreted.
    """
    manifest = bootstrap_repo_path(Path(root), 'PyAutoMind') / 'repos.yaml'
    if not manifest.is_file():
        return {}
    paths: dict[str, Path] = {}
    active = False
    current = None
    for line in manifest.read_text().splitlines():
        if line.strip() == 'repos:':
            active = True
            continue
        if not active or not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):
            break
        match = re.fullmatch(r'  ([A-Za-z0-9_.-]+):\s*(?:#.*)?', line)
        if match:
            current = _name(match[1])
            if current in paths:
                raise ValueError(f'duplicate repository identity: {current}')
            paths[current] = Path(current)
            continue
        if current and re.match(r'    path\s*:', line):
            raw = line.split(':', 1)[1].strip()
            if raw.startswith(('"', "'")):
                quote = raw[0]
                end = raw.find(quote, 1)
                if end < 0 or (raw[end + 1:].strip() and not raw[end + 1:].strip().startswith('#')):
                    raise ValueError(f'{current}: invalid path scalar: {raw!r}')
                value = raw[1:end]
            else:
                value = raw.split(' #', 1)[0].strip()
            paths[current] = _placement(current, value)
    by_path: dict[Path, str] = {}
    for name, path in paths.items():
        if path in by_path:
            raise ValueError(f'duplicate repository placement: {by_path[path]} and {name}')
        by_path[path] = name
    return paths


def is_checkout(path: Path) -> bool:
    return path.is_dir() and (path / '.git').exists()


def _families(root: Path):
    if root.is_dir():
        for path in sorted(root.iterdir()):
            if (path.is_dir() and not path.is_symlink()
                    and not path.name.startswith('.') and not is_checkout(path)):
                yield path


def bootstrap_repo_path(root: Path, name: str, required: bool = False) -> Path:
    """Find an infrastructure checkout before its manifest can be loaded.

    Bounded discovery uses the same flat/one-family boundary as normal lookup,
    without consulting Mind (which may itself be the repository being located).
    """
    root = Path(root)
    name = _name(name)
    candidates = [root / name]
    candidates.extend(family / name for family in _families(root)
                      if is_checkout(family / name)
                      or (not (root / name).is_dir() and name == 'PyAutoMind'
                          and (family / name / 'repos.yaml').is_file()))
    existing = {}
    for path in candidates:
        if path.is_dir():
            existing.setdefault(path.resolve(), path)
    if len(existing) > 1:
        raise ValueError(f'{name}: ambiguous checkouts: ' + ', '.join(map(str, existing.values())))
    result = next(iter(existing.values()), root / name)
    if required and not is_checkout(result):
        raise FileNotFoundError(f'{name}: repository checkout missing at {result}')
    return result


def iter_checkouts(root: Path) -> list[Path]:
    """Actual flat or family checkouts, including symlinked bundle dependencies.

    Never recursively search inside a repository (datasets can contain clones).
    Each logical identity must have exactly one physical target in this context.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    found = [p for p in sorted(root.iterdir()) if is_checkout(p)]
    for family in _families(root):
        found.extend(p for p in sorted(family.iterdir()) if is_checkout(p))
    unique: dict[str, Path] = {}
    for path in found:
        previous = unique.get(path.name)
        if previous is not None and previous.resolve() != path.resolve():
            raise ValueError(f'{path.name}: ambiguous checkouts: {previous}, {path}')
        unique.setdefault(path.name, path)
    return sorted(unique.values(), key=lambda p: p.name)


def repo_path(root: Path, name: str, required: bool = False) -> Path:
    """Locate a repo within the specified context, never a different workspace.

    Existing directories remain usable for partial fixtures and bootstrap writes;
    only required=True establishes checkout presence, through the .git marker.
    Missing paths retain their declared placement for precise error messages.
    """
    root = Path(root)
    name = _name(name)
    declared = manifest_paths(root).get(name, Path(name))
    if len(declared.parts) > 1 and (root / declared.parts[0]).is_symlink():
        raise ValueError(f'{name}: repository family must not be a symlink: {root / declared.parts[0]}')
    candidates = [root / name, root / declared]
    candidates.extend(family / name for family in _families(root)
                      if is_checkout(family / name))
    existing: dict[Path, Path] = {}
    for path in candidates:
        if path.is_dir():
            existing.setdefault(path.resolve(), path)
    if len(existing) > 1:
        raise ValueError(f'{name}: ambiguous checkouts: ' + ', '.join(map(str, existing.values())))
    result = next(iter(existing.values()), root / declared)
    if required and not is_checkout(result):
        raise FileNotFoundError(f'{name}: repository checkout missing at {result}')
    return result


def repo_paths(root: Path) -> dict[str, Path]:
    """All manifest identities, retaining missing paths so coverage cannot shrink."""
    return {name: repo_path(root, name) for name in manifest_paths(Path(root))}


def package_paths(root: Path) -> list[Path]:
    """Import roots for packages declared by the body map, in manifest order."""
    root = Path(root)
    declared = manifest_paths(root)
    manifest = bootstrap_repo_path(root, 'PyAutoMind') / 'repos.yaml'
    if not manifest.is_file():
        return []
    names = []
    current = None
    active = False
    for line in manifest.read_text().splitlines():
        if line.strip() == 'repos:':
            active = True
            continue
        if not active or not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):
            break
        match = re.fullmatch(r'  ([A-Za-z0-9_.-]+):\s*(?:#.*)?', line)
        if match:
            current = match[1]
        elif current in declared and re.match(r'    package:\s*\S+', line):
            names.append(current)
    return [repo_path(root, name) for name in names]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('path')
    one.add_argument('name')
    one.add_argument('--required', action='store_true')
    for cmd in (one, commands.add_parser('list'), commands.add_parser('pythonpath')):
        cmd.add_argument('--root', type=Path, default=Path(os.environ.get('PYAUTO_ROOT', '.')))
    args = parser.parse_args(argv)
    try:
        if args.command == 'path':
            print(repo_path(args.root, args.name, args.required))
        elif args.command == 'pythonpath':
            print(os.pathsep.join(str(p) for p in package_paths(args.root) if p.is_dir()))
        else:
            for path in iter_checkouts(args.root):
                print(f'{path.name}\t{path}')
    except (ValueError, OSError) as error:
        print(f'repository lookup: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

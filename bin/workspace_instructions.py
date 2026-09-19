#!/usr/bin/env python3
"""Update only recognized workspace instruction sections, preserving local additions."""
import argparse
import json
from pathlib import Path
import sys

POLICY = Path(__file__).resolve().parents[1] / 'policy'


def render(text, sections, legacy):
    """Refuse unexpected edits instead of overwriting a user's instructions."""
    replacements = []
    for heading, body in sections.items():
        lines = text.splitlines(keepends=True)
        matches = [i for i, line in enumerate(lines) if line.rstrip() == heading]
        if len(matches) != 1:
            raise ValueError(f'expected one section: {heading}')
        first = matches[0]
        end = next((i for i in range(first + 1, len(lines))
                    if lines[i].startswith('## ')), len(lines))
        current = ''.join(lines[first:end]).strip() + '\n'
        if current not in (body.strip() + '\n', legacy[heading]):
            raise ValueError(f'unrecognized local edits in {heading}; reconcile explicitly')
        replacements.append((sum(map(len, lines[:first])),
                             sum(map(len, lines[:end])), body.rstrip() + '\n\n'))
    for first, end, body in sorted(replacements, reverse=True):
        text = text[:first] + body + text[end:]
    return text.rstrip() + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--write', action='store_true', help='otherwise check only')
    args = parser.parse_args(argv)
    target = (args.root / 'AGENTS.md').resolve()  # preserve a task-bundle symlink
    try:
        original = target.read_text()
        updated = render(original, json.loads((POLICY / 'workspace_sections.json').read_text()),
                         json.loads((POLICY / 'workspace_sections_legacy.json').read_text()))
    except (OSError, ValueError, KeyError) as exc:
        print(f'workspace instructions: {exc}', file=sys.stderr)
        return 2
    if original == updated:
        print(f'OK: {target}')
        return 0
    if not args.write:
        print(f'DRIFT: {target}; run with --write after reviewing the change')
        return 1
    target.write_text(updated)
    print(f'updated: {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

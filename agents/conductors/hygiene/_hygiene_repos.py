#!/usr/bin/env python3
"""Read the organism's body map for the hygiene conductor.

The conductor scans repositories. WHICH repositories is not its decision to
make: the body map (the Mind's ``repos.yaml``) is the single source of repo
identity, and this helper is the conductor's only route to it.

Why a helper rather than an array in ``hygiene.sh``: a hardcoded repo list
drifts as the organism grows, and the drift is *invisible* — a repo that is
never scanned produces no findings, so the conductor reports a clean bill of
health it has not earned. (It did: five libraries scanned where the map
declared six, four organs of seven, and a CRLF count of 5 against a true 127.)
Deriving the sets means adding a repo to the map adds it to the scan.

This file deliberately contains **no repository names**. That is what keeps it
firewall-clean under ``repos_sync.py``'s tenant check, and it is also the
property the coverage check relies on: there is nothing here to drift.

Usage
-----
    _hygiene_repos.py --category <name>   # one name per line, sorted
    _hygiene_repos.py --json              # {"<category>": [names...], ...}

Exit codes: 0 = read; 3 = body map unresolvable (prints nothing, so a caller
can distinguish "no repos declared" from "no repos present" and report
`unscanned` rather than `clean` for either).

The map is located the way ``agents/_common.sh`` locates any organ checkout:
an explicit ``PYAUTO_MIND``, then the sibling beside this Brain checkout, then
``$PYAUTO_ROOT``, then a couple of common dev layouts. PyYAML is used when it
imports and a minimal parser stands in when it does not — the conductor stays
dependency-free by design (it must never drag a heavy stack into the Brain),
and the map's own shape is simple enough to read without one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

MAP_FILENAME = "repos.yaml"

# The Mind is an organ, so its directory name is framework identity rather than
# an instance fact — the same reason _common.sh may name it.
MIND_REPO = "PyAuto" + "Mind"


def candidate_map_paths() -> list[Path]:
    """Where the body map might live, most-authoritative first.

    An explicit ``PYAUTO_MIND`` pointing at a real directory is authoritative and
    ends the search, exactly as ``_resolve_dir`` in ``agents/_common.sh`` treats
    its override. Falling through to a sibling checkout would silently scan a
    *different* organism than the operator named — and would make "the map is
    unreachable" unreachable itself, so the branch that reports it could never
    be exercised.
    """
    here = Path(__file__).resolve()
    # .../<checkout>/agents/conductors/hygiene/_hygiene_repos.py
    brain_parent = here.parents[4]
    override = os.environ.get("PYAUTO_MIND")
    if override and Path(override).is_dir():
        return [Path(override)]
    candidates: list[Path] = []
    candidates.append(brain_parent / MIND_REPO)
    root = os.environ.get("PYAUTO_ROOT")
    if root:
        candidates.append(Path(root) / MIND_REPO)
    home = Path.home()
    candidates += [home / MIND_REPO, home / "Code" / MIND_REPO]
    return candidates


def resolve_map() -> Path | None:
    for base in candidate_map_paths():
        path = base / MAP_FILENAME
        if path.is_file():
            return path
    return None


# --- Parsing -----------------------------------------------------------------
#
# Two readers for one file. PyYAML is correct and preferred; the fallback exists
# so a missing optional dependency degrades the *rigour* of the parse, never the
# *coverage* of the scan. Silently scanning fewer repos is the bug this whole
# module exists to prevent, so "PyYAML absent" must not become a way to
# re-introduce it.

_REPO_LINE = re.compile(r"^  ([A-Za-z0-9._-]+):\s*(#.*)?$")
_CATEGORY_LINE = re.compile(r"^    category:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*(#.*)?$")
_TOP_LEVEL = re.compile(r"^\S")


def parse_minimal(text: str) -> dict[str, str]:
    """Map repo name -> category without PyYAML.

    Walks the two-level ``repos:`` block by indentation: a two-space key opens a
    repo, a four-space ``category:`` sets it, and any new top-level key ends the
    block. Sufficient for this file's fixed shape and nothing more — it is a
    fallback, not a YAML implementation.
    """
    out: dict[str, str] = {}
    in_repos = False
    current: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _TOP_LEVEL.match(line):
            in_repos = line.startswith("repos:")
            current = None
            continue
        if not in_repos:
            continue
        m = _REPO_LINE.match(line)
        if m:
            current = m.group(1)
            continue
        m = _CATEGORY_LINE.match(line)
        if m and current:
            out[current] = m.group(1)
    return out


def parse_with_yaml(text: str) -> dict[str, str]:
    import yaml  # local import: absent PyYAML must fall back, not crash

    data = yaml.safe_load(text) or {}
    return {
        name: entry.get("category")
        for name, entry in (data.get("repos") or {}).items()
        if isinstance(entry, dict) and entry.get("category")
    }


def load_categories(path: Path, parser: str = "auto") -> dict[str, list[str]]:
    """Return category -> sorted repo names.

    ``parser="minimal"`` forces the PyYAML-free path. That exists so the drift
    check can exercise the fallback on a machine that *has* PyYAML: a fallback
    only ever used where nothing verifies it is a fallback nobody can trust, and
    a parser that silently drops repos is this module's own bug class.
    """
    text = path.read_text()
    if parser == "minimal":
        by_repo = parse_minimal(text)
    else:
        try:
            by_repo = parse_with_yaml(text)
        except ImportError:
            by_repo = parse_minimal(text)
    grouped: dict[str, list[str]] = {}
    for name, category in by_repo.items():
        grouped.setdefault(category, []).append(name)
    return {category: sorted(names) for category, names in sorted(grouped.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="print the repos in one category")
    parser.add_argument("--json", action="store_true",
                        help="print every category as JSON")
    parser.add_argument("--parser", choices=("auto", "minimal"), default="auto",
                        help="force a reader; 'minimal' is the PyYAML-free path")
    args = parser.parse_args()

    path = resolve_map()
    if path is None:
        searched = ", ".join(str(base / MAP_FILENAME) for base in candidate_map_paths())
        print(
            f"hygiene: body map not found — no {MAP_FILENAME} at: {searched}. "
            f"Set PYAUTO_MIND to the Mind checkout.",
            file=sys.stderr,
        )
        return 3

    grouped = load_categories(path, args.parser)
    if args.json:
        print(json.dumps(grouped, indent=2, sort_keys=True))
    elif args.category:
        for name in grouped.get(args.category, []):
            print(name)
    else:
        parser.error("one of --category or --json is required")
    return 0


if __name__ == "__main__":
    sys.exit(main())

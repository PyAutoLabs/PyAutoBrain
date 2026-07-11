#!/usr/bin/env python3
"""_hygiene_config.py — count library config keys missing from the matching
workspace config, for the hygiene conductor's `config` mode.

The "mirror new library config keys into the workspace configs" chore: when a
library adds a key to one of its `config/*.yaml` files, the workspace config
(which overrides library defaults) should usually gain it too. This does a
*recursive* key-path diff (top-level-only would miss nested drift, which is
where it happens) for the shared config files in each library↔workspace pair.

Stdlib + PyYAML only — never imports the science stack. Emits one `count|summary`
line for the `config` prescan; exits non-zero (no output) if PyYAML is absent so
the conductor falls back gracefully. It is a *surface* signal: a missing key may
be an intentional workspace omission — the count is "keys to review", not bugs.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

try:
    import yaml
except Exception:
    sys.exit(1)  # no PyYAML → conductor falls back

PAIRS = [
    ("PyAutoFit/autofit/config", "autofit_workspace/config"),
    ("PyAutoGalaxy/autogalaxy/config", "autogalaxy_workspace/config"),
    ("PyAutoLens/autolens/config", "autolens_workspace/config"),
]


def key_paths(node, prefix: str = "") -> set[str]:
    """Every nested dict key path in `node` (dotted)."""
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            out |= key_paths(v, p)
    return out


def load(path: str):
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def diff(root: str, pairs=PAIRS) -> tuple[int, list[str]]:
    total = 0
    detail: list[str] = []
    for lib_rel, ws_rel in pairs:
        lib_dir = os.path.join(root, lib_rel)
        ws_dir = os.path.join(root, ws_rel)
        if not (os.path.isdir(lib_dir) and os.path.isdir(ws_dir)):
            continue
        missing = 0
        for lib_yaml in glob.glob(os.path.join(lib_dir, "*.yaml")):
            ws_yaml = os.path.join(ws_dir, os.path.basename(lib_yaml))
            if not os.path.isfile(ws_yaml):
                continue  # workspace may intentionally not copy this file
            lib_data, ws_data = load(lib_yaml), load(ws_yaml)
            if lib_data is None or ws_data is None:
                continue
            missing += len(key_paths(lib_data) - key_paths(ws_data))
        if missing:
            total += missing
            detail.append(f"{ws_rel.split('/')[0]}:{missing}")
    return total, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/Code/PyAutoLabs"))
    ns = ap.parse_args()
    total, detail = diff(ns.root)
    print(f"{total}|{total} library config keys absent downstream (review/mirror): "
          f"{' '.join(detail)}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())

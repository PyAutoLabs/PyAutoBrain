#!/usr/bin/env python3
"""_hygiene_config.py — the hygiene conductor's `config` prescan: two drift
signals over the workspace config tree, folded into one `count|summary` line.

1. **Key-mirror drift** (`diff`): when a library adds a key to one of its
   `config/*.yaml` files, the workspace config (which overrides library
   defaults) should usually gain it too. A *recursive* key-path diff
   (top-level-only would miss nested drift, which is where it happens) over the
   shared config files in each library↔workspace pair.

2. **Orphan config files** (`orphan_files`): a workspace `config/**/*.yaml` with
   **no library counterpart** at the same relative path. This is the signal the
   key-mirror diff is structurally blind to — it skips any file lacking a
   workspace *or* library counterpart, so a workspace file the libraries never
   shipped is invisible. That blind spot let a dead `config/grids.yaml` survive
   in 10 repos for ~a year (autolens_workspace#317).

   The honest test of a config file is **reachability** — does anything read it
   — not filename similarity. A pure filename check is far too noisy (~120 hits,
   nearly all legitimate) because whole config subtrees are owned by something
   *other* than the libraries and legitimately have no library default. Those
   owners are named in ``ORPHAN_OWNERS`` and suppressed; what remains is the
   review list. The library's *own* shipped set encodes the reachability verdict
   for us: e.g. it ships ``non_linear/GridSearch.yaml`` (live —
   ``conf.instance["non_linear"]["gridsearch"]``) but not
   ``non_linear/{nest,mle,mcmc}.yaml`` (dead — searches take their defaults from
   Python signatures), so the orphan pass keeps the first and surfaces the rest
   without any per-file rule.

Stdlib + PyYAML only — never imports the science stack. Emits one `count|summary`
line; exits non-zero (no output) if PyYAML is absent so the conductor falls back
gracefully. It is a *surface* signal — the count is "items to review", not bugs.
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

# The library packages whose shipped `config/` tree is the reachability
# reference: a workspace config file is an orphan iff no library ships one at the
# same relative path. (repo dir, package dir).
LIBRARIES = [
    ("PyAutoFit", "autofit"),
    ("PyAutoGalaxy", "autogalaxy"),
    ("PyAutoLens", "autolens"),
    ("PyAutoArray", "autoarray"),
    ("PyAutoCTI", "autocti"),
    ("PyAutoNerves", "autonerves"),
]

# Config subtrees owned by something OTHER than the libraries, so a workspace
# copy with no library counterpart is expected, not drift. Keyed by the top path
# segment under `config/`; the value names the owner and is documentation for the
# summary, not logic. Keep this list small and justified — every entry is a
# reachability claim ("something reads these, just not a library default").
ORPHAN_OWNERS = {
    "build": "PyAutoHands (release tooling reads workspace config/build/*)",
    "priors": "JSONPriorConfig (prior configs resolved by class path; "
              "workspace/user-defined classes have no library default)",
}


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


def _yaml_relpaths(config_dir: str) -> set[str]:
    """Relative paths of every `*.yaml` under `config_dir` (recursively),
    forward-slash-normalised so a dict lookup is platform-stable."""
    out: set[str] = set()
    for f in glob.glob(os.path.join(config_dir, "**", "*.yaml"), recursive=True):
        out.add(os.path.relpath(f, config_dir).replace(os.sep, "/"))
    return out


def library_config_relpaths(root: str, libraries=LIBRARIES) -> set[str]:
    """The union of every config-file relative path the libraries ship — the
    reachability reference the orphan check compares against."""
    out: set[str] = set()
    for repo, pkg in libraries:
        cfg = os.path.join(root, repo, pkg, "config")
        if os.path.isdir(cfg):
            out |= _yaml_relpaths(cfg)
    return out


def _suppressed(relpath: str) -> bool:
    """True if `relpath`'s top segment under config/ is an owned subtree
    (ORPHAN_OWNERS) — a workspace copy there is expected, not drift."""
    return relpath.split("/")[0] in ORPHAN_OWNERS


def orphan_files(root: str, libraries=LIBRARIES, lib_relpaths=None,
                 owners=ORPHAN_OWNERS) -> tuple[int, list[str]]:
    """Workspace config files with no library counterpart, after owner-map
    suppression.

    Only repos whose `config/` *mirrors* the library tree (shares ≥1 file with
    the library set) are scanned — that self-scopes to the workspace/tutorial/
    test/assistant repos and excludes organ repos (Brain/Heart/Mind) whose
    `config/` is their own thing, without a hardcoded repo list to go stale.
    """
    if lib_relpaths is None:
        lib_relpaths = library_config_relpaths(root, libraries)
    lib_repos = {repo for repo, _ in libraries}
    total = 0
    detail: list[str] = []
    for name in sorted(os.listdir(root)):
        if name in lib_repos:
            continue
        cfg = os.path.join(root, name, "config")
        if not os.path.isdir(cfg):
            continue
        rels = _yaml_relpaths(cfg)
        if not (rels & lib_relpaths):
            continue  # not a library-config mirror (organ-internal config) — skip
        orphans = {r for r in (rels - lib_relpaths)
                   if not (r.split("/")[0] in owners)}
        if orphans:
            total += len(orphans)
            detail.append(f"{name}:{len(orphans)}")
    return total, detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/Code/PyAutoLabs"))
    ns = ap.parse_args()
    keys, key_detail = diff(ns.root)
    orphans, orphan_detail = orphan_files(ns.root)
    total = keys + orphans
    parts = []
    if keys:
        parts.append(f"{keys} library config keys absent downstream "
                     f"(review/mirror): {' '.join(key_detail)}")
    if orphans:
        parts.append(f"{orphans} orphan config files with no library counterpart "
                     f"(review/remove): {' '.join(orphan_detail)}")
    summary = "; ".join(parts) or "config in sync (no key drift or orphan files)"
    print(f"{total}|{summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

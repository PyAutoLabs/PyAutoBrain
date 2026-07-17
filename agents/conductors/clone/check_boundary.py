#!/usr/bin/env python
"""Assert every tracked file in a reference assistant falls on one side of the
template boundary.

`_clone.py`'s partition already refuses to birth a newborn while any reference
file is unclassified — deliberate pressure that keeps the boundary notes
complete. But that pressure only lands when someone tries to give birth, which
is rare, and by then the person blocked is not the person who added the file:
they must go and classify someone else's work in a repo they may not know.

This runs the same check at PR time in the reference's own CI, so the author who
adds a file classifies it while they still remember whether it is framework or
science. Three features (the euclid mode, the JOSS paper, the results-inspector
MCP wiring) each landed unclassified and silently blocked every future birth
before this existed.

Usage:
    python check_boundary.py <reference-checkout> [--reference <name>]

`--reference` defaults to the checkout's directory name, which is how the
profiles are keyed. A checkout with no profile is not a clone reference and has
no boundary to grade, so it *skips* — this matters because a newborn inherits
this check in its `.github/` and is not itself a reference until someone adds a
profile for it. An explicitly-passed `--reference` that has no profile is still
an error, so a typo cannot pass silently.

Exit codes: `0` boundary complete (or not a reference) · `1` unclassified
files · `4` bad inputs.
"""

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_clone():
    spec = importlib.util.spec_from_file_location(
        "_clone_boundary", Path(__file__).resolve().parent / "_clone.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", help="path to the reference assistant checkout")
    parser.add_argument(
        "--reference",
        default=None,
        help="profile name to grade against (default: the checkout's dir name)",
    )
    args = parser.parse_args()

    root = Path(args.checkout).resolve()
    if not (root / ".git").exists():
        print(f"check_boundary: not a git checkout: {root}", file=sys.stderr)
        return 4

    clone = _load_clone()
    name = args.reference or root.name
    profile = clone.REFERENCE_PROFILES.get(name)
    if profile is None:
        if args.reference is not None:
            # Explicitly named: a typo must not pass silently.
            print(
                f"check_boundary: no clone profile for '{name}' — supported: "
                f"{', '.join(sorted(clone.REFERENCE_PROFILES))}",
                file=sys.stderr,
            )
            return 4
        # Inferred: this repo is not a clone reference, so it has no boundary to
        # grade. A newborn inherits this check and lands here until (and unless)
        # it is promoted to a reference with a profile of its own.
        print(f"check_boundary: {name} is not a clone reference — nothing to grade")
        return 0

    sets = clone.partition(root, profile)
    unclassified = sets["unclassified"]
    if not unclassified:
        print(
            f"check_boundary: {name} boundary complete — "
            f"generic {len(sets['generic'])} · domain {len(sets['domain'])} · "
            f"mixed {len(sets['mixed'])}"
        )
        return 0

    print(
        f"check_boundary: {len(unclassified)} file(s) in {name} fall on neither "
        f"side of the template boundary:\n",
        file=sys.stderr,
    )
    for path in unclassified:
        print(f"  ✗ {path}", file=sys.stderr)
    print(
        "\nEvery tracked file must be classified, because the Clone Agent "
        "refuses to birth a\nnewborn while any is unclassified — leaving these "
        "blocks every future assistant birth.\nDecide what each file is, then "
        "record it in BOTH places, which must agree:\n\n"
        "  1. modes/maintainer.md, '## Assistant-as-template' — the prose that "
        "OWNS the boundary\n"
        "  2. PyAutoBrain agents/conductors/clone/_clone.py — REFERENCE_PROFILES"
        f"['{name}']\n\n"
        "  generic — framework that clones to any domain near-verbatim\n"
        "  domain  — this field's science; a newborn regrows its own\n"
        "  mixed   — generic structure, domain-specific values\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

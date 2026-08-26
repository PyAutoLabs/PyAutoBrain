#!/usr/bin/env python3
"""Which repos the org-wide branch sweep may touch — derived, never listed.

The obvious implementation is a file listing the repos. It was written that
way first, and the tenant firewall rejected it: the framework organs must stay
adoptable as a config-diff fork, so instance facts (repo names, GitHub owners)
may not appear in Brain code outside the declared config surfaces. A hardcoded
list of `<owner>/<repo>` slugs is precisely that leak — and because the
firewall only scans `.py` and `.sh`, putting the list in a `.txt` did not make
it clean, it only made it invisible. (Nor is prose exempt: the firewall reads
comments too, and rightly — a docstring naming satellite repos is still
something an adopting fork has to rewrite.)

The hygiene conductor already had the answer, recorded in the firewall
allowlist next to the entry it deleted: *"derives its repo sets from the body
map, so it names no instance fact at all."* Same here. Policy is expressed as
**categories**, which every organism has; the repos filling them are whatever
that organism's body map says.

The two exclusions fall out of the categories rather than needing names:

  assistant   science workspaces, not dev repos — one of the two repos on the
              skill's Never-touched list sits here
  pipeline    the other one
  project     publication surfaces; swept by hand if at all
  admin       personal repos, often a different owner whose PAT scope is
              unverified

And the Mind and the Brain drop out by *organ role*, not by name: each hosts
its own `branch_sweep.yml` and sweeps itself with its own `GITHUB_TOKEN`.
Sweeping them centrally too would put two sweepers on one repo with different
credentials. "Mind" and "Brain" are organism roles present in any fork, so
naming them here is not an instance fact.

The self-sweeping exclusion is the *sweep's* boundary, not the body map's, so
a second consumer can ask for it back. `--include-self-sweeping` yields every
development repo including the Mind and the Brain — what the repo-settings
sweep wants, because "delete the head branch on merge" is a per-repo setting
that has to be on in those two as much as anywhere else, and no second sweeper
collides over a settings PATCH.

Usage:
    branch_sweep_targets.py <path-to-repos.yaml>   # one owner/repo per line
    branch_sweep_targets.py --include-self-sweeping <path-to-repos.yaml>
"""

from __future__ import annotations

import sys
from pathlib import Path

# Categories whose repos are ordinary development repos: agent-driven, branch
# churn from the dev workflow, nothing a sweep would surprise. Widening this
# set is a reviewed decision — it is the whole boundary.
SWEEPABLE_CATEGORIES = frozenset(
    {"organ", "library", "workspace", "workspace_test", "workspace_developer", "howto"}
)

# Organ roles that sweep themselves. Roles, not repo names — an adopting fork
# has a Mind and a Brain too, whatever it calls them.
SELF_SWEEPING_ORGANS = frozenset({"Mind", "Brain"})


def targets(body_map: dict, include_self_sweeping: bool = False) -> list[str]:
    """The development `owner/repo` slugs, in body-map order.

    `include_self_sweeping` keeps the organs that host their own branch
    sweeper. Only the branch sweep needs them dropped (two sweepers on one
    repo would contend); a consumer that flips a repo setting does not.
    """
    out = []
    for entry in body_map["repos"].values():
        if entry.get("category") not in SWEEPABLE_CATEGORIES:
            continue
        if not include_self_sweeping and entry.get("organ") in SELF_SWEEPING_ORGANS:
            continue
        out.append(entry["github"])
    return out


def main(argv: list[str]) -> int:
    args = argv[1:]
    include_self_sweeping = False
    if "--include-self-sweeping" in args:
        include_self_sweeping = True
        args = [a for a in args if a != "--include-self-sweeping"]
    if len(args) != 1 or args[0].startswith("-"):
        print(
            f"usage: {Path(argv[0]).name} [--include-self-sweeping] <path-to-repos.yaml>",
            file=sys.stderr,
        )
        return 2
    import yaml

    path = Path(args[0])
    if not path.is_file():
        print(f"branch_sweep_targets: no body map at {path}", file=sys.stderr)
        return 1
    for slug in targets(yaml.safe_load(path.read_text()), include_self_sweeping):
        print(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

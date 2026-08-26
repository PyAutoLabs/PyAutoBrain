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

## The second consumer reads the body map for its *complement*

`repo_settings.yml` turns on "delete the head branch on merge". It used to take
a widened version of the set above, and that was wrong in a way the category
boundary cannot fix: a repo is created *before* anyone registers it in the body
map, so a body-map-derived sweep is structurally blind to exactly the repos
that most need the setting. It now enumerates the organisation from the GitHub
API instead, where a new repo appears the moment it exists.

What that enumeration *cannot* see is a body-map repo under some other owner.
`--outside-owner <owner>` yields those, and only those — the complement of the
org listing. It applies **no category filter**, deliberately: the org
enumeration has none either, so filtering the complement would be a boundary
that exists on one side of the union and not the other. (In practice the
categories that end up outside an organisation's own account are the personal
ones, which the category set above excludes — so filtering here would yield
nothing at all and silently drop the repos this flag exists to find.)

Usage:
    branch_sweep_targets.py <path-to-repos.yaml>   # one owner/repo per line
    branch_sweep_targets.py --outside-owner <owner> <path-to-repos.yaml>
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


def targets(body_map: dict) -> list[str]:
    """The development `owner/repo` slugs, in body-map order."""
    out = []
    for entry in body_map["repos"].values():
        if entry.get("category") not in SWEEPABLE_CATEGORIES:
            continue
        if entry.get("organ") in SELF_SWEEPING_ORGANS:
            continue
        out.append(entry["github"])
    return out


def outside_owner(body_map: dict, owner: str) -> list[str]:
    """Body-map slugs whose owner is not `owner`, in body-map order.

    The complement of a `GET /orgs/<owner>/repos` listing: what a settings
    sweep would miss if it trusted the API enumeration alone. No category
    filter — see the module docstring for why that asymmetry is deliberate.
    """
    return [
        entry["github"]
        for entry in body_map["repos"].values()
        if entry["github"].split("/", 1)[0] != owner
    ]


def main(argv: list[str]) -> int:
    args = argv[1:]
    owner = None
    if "--outside-owner" in args:
        i = args.index("--outside-owner")
        # The flag needs a value, and the value must not be the body-map path
        # arriving by accident — a missing value would otherwise swallow it and
        # report "no repos outside <path>", which reads as a clean empty run.
        if i + 1 >= len(args) or args[i + 1].startswith("-"):
            print("branch_sweep_targets: --outside-owner needs an owner", file=sys.stderr)
            return 2
        owner = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if len(args) != 1 or args[0].startswith("-"):
        print(
            f"usage: {Path(argv[0]).name} [--outside-owner <owner>] <path-to-repos.yaml>",
            file=sys.stderr,
        )
        return 2
    import yaml

    path = Path(args[0])
    if not path.is_file():
        print(f"branch_sweep_targets: no body map at {path}", file=sys.stderr)
        return 1
    body_map = yaml.safe_load(path.read_text())
    slugs = outside_owner(body_map, owner) if owner is not None else targets(body_map)
    for slug in slugs:
        print(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

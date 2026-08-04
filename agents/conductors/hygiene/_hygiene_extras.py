"""
Hygiene pre-scan: optional dependencies a PyAuto library declares that the
workspace-validation SMOKE leg never installs.

``workspace-validation.yml`` runs the same script matrix in both modes — only
the install differs. ``mode=release`` installs every library's ``[optional]``
extra explicitly, so a script needing an optional package works. ``mode=smoke``
installs the published ``autolens[optional]`` and leans on the extras chain,
but that chain only ever reaches each library's own ``[jax]`` extra, never a
sibling's ``[optional]``::

    autolens[optional] -> autolens[jax] -> autogalaxy[jax]
                       -> autofit[jax]  -> autonerves[jax]

So anything declared in a *sibling's* ``[optional]`` — ``autoarray[optional]``,
``autofit[optional]`` — has to be hand-added to the smoke leg, and nothing
enforces that. The gap is invisible until a nightly smoke run goes red against
a script that passes release validation, and the failure looks like a broken
script rather than a missing install (2026-08-03: ``tfp-nightly``, needed by
the JAX Matern-kernel regularization path, was in ``autoarray[optional]`` only;
two scripts red in smoke, both green in release).

The remedy is always the install set, never the script: a script that passes
release validation is correct, and parking or skip-guarding it destroys the
coverage it exists to provide. This scan therefore reports MISSING INSTALLS,
and is deliberately the complement of ``optdeps``, which reports scripts that
genuinely should carry a skip guard.

Resolution is modelled the way pip resolves it: from the smoke leg's declared
roots, follow each PyAuto library's base ``dependencies`` and any requested
extra, and collect every third-party distribution reached. Expected coverage is
the union of every library's ``[optional]`` closure — the set ``mode=release``
guarantees. The difference is the drift.

*Which* libraries those are is DERIVED, never hard-coded: ``mode=release`` names
them (it installs each one's ``[optional]`` extra), so the same workflow defines
both sides of the comparison, and a library added to that leg is picked up here
instead of silently falling out of the scan. Each distribution it names is
resolved to a checkout by the ``project.name`` in that checkout's
``pyproject.toml`` — folder names carry no meaning. This also keeps organ code
free of tenant instance facts (the ``PyAutoMind/scripts/repos_sync.py`` tenant
firewall), the same way ``PyAutoHeart/heart/checks/release_run.py`` derives its
own release channel.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

# The extra mode=release installs for every library, and therefore the coverage
# mode=smoke is expected to match.
RELEASE_EXTRA = "optional"

WORKFLOW = Path("PyAutoHeart/.github/workflows/workspace-validation.yml")

# The install step whose requirement roots define the smoke leg's coverage, and
# the one that names the libraries (and therefore the coverage to match).
SMOKE_STEP = re.compile(r"^\s*-\s*name:.*\[mode=smoke\]", re.IGNORECASE)
RELEASE_STEP = re.compile(r"^\s*-\s*name:.*\[mode=release\]", re.IGNORECASE)
NEXT_STEP = re.compile(r"^\s*-\s*name:")
PIP_INSTALL = re.compile(r"\bpip\s+install\b(?P<rest>.*)$")
# A requirement's distribution name and its optional extras: "autoarray[optional]",
# "nufftax>=0.6.1,<0.7.0", "tfp-nightly==0.26.0.dev20260713".
REQUIREMENT = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[(?P<extras>[^\]]*)\])?")


def canonical(name: str) -> str:
    """PEP 503 normalisation — `tfp_nightly`, `TFP.Nightly` and `tfp-nightly` are one."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def parse_requirement(token: str) -> tuple[str, tuple[str, ...]] | None:
    """('autoarray[optional]') -> ('autoarray', ('optional',)); None if not a requirement."""
    match = REQUIREMENT.match(token.strip().strip("\"'"))
    if not match:
        return None
    raw = match.group("extras") or ""
    extras = tuple(sorted({canonical(e) for e in raw.split(",") if e.strip()}))
    return canonical(match.group("name")), extras


def libraries(root: Path) -> dict[str, tuple[str, dict]]:
    """Map canonical distribution name -> (checkout dir, parsed pyproject).

    The library set is whatever `mode=release` installs — see the module
    docstring — so a checkout counts iff the distribution it DECLARES
    (`project.name`) is one that step names. Directory names are never matched
    against, which is what keeps the list derived rather than hard-coded.
    """
    declared = {name for name, _ in install_roots(root, RELEASE_STEP)}
    if not declared:
        return {}

    found: dict[str, tuple[str, dict]] = {}
    for checkout in sorted(p for p in root.iterdir() if p.is_dir()):
        pyproject = checkout / "pyproject.toml"
        try:
            data = tomllib.loads(pyproject.read_text())
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            continue  # absent, unreadable, or malformed — the packaging mode's problem
        name = data.get("project", {}).get("name")
        if name and canonical(name) in declared:
            found[canonical(name)] = (checkout.name, data)
    return found


def install_roots(
    root: Path, step: re.Pattern[str]
) -> list[tuple[str, tuple[str, ...]]]:
    """Requirement roots the given install step passes to pip, in order."""
    workflow = root / WORKFLOW
    if not workflow.exists():
        return []

    lines = workflow.read_text().splitlines()
    block: list[str] = []
    inside = False
    for line in lines:
        if step.match(line):
            inside = True
            continue
        if inside and NEXT_STEP.match(line):
            inside = False
            continue
        if inside:
            block.append(line)

    # Rejoin backslash continuations so a multi-line `pip install a \\\n b` is
    # read as one command (the release leg is written that way).
    joined: list[str] = []
    buffer = ""
    for line in block:
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        joined.append(buffer + stripped)
        buffer = ""
    if buffer:
        joined.append(buffer)

    roots: list[tuple[str, tuple[str, ...]]] = []
    for line in joined:
        match = PIP_INSTALL.search(line)
        if not match:
            continue
        for token in match.group("rest").split():
            if token.startswith("-"):
                continue  # a flag (--index-url, --no-deps, ...)
            requirement = parse_requirement(token)
            if requirement:
                roots.append(requirement)
    return roots


def closure(
    roots: list[tuple[str, tuple[str, ...]]], libs: dict[str, dict]
) -> set[str]:
    """Third-party distributions pip would install from `roots`.

    A PyAuto library contributes its base `dependencies` (always installed) plus
    the requirement list of each extra actually requested; everything else is a
    third-party distribution and is recorded.
    """
    reached: set[str] = set()
    based: set[str] = set()
    seen_extras: set[tuple[str, str]] = set()
    queue = list(roots)

    while queue:
        name, extras = queue.pop()

        if name not in libs:
            reached.add(name)
            continue

        project = libs[name].get("project", {})
        if name not in based:
            based.add(name)
            for requirement in project.get("dependencies", []) or []:
                parsed = parse_requirement(requirement)
                if parsed:
                    queue.append(parsed)

        declared = project.get("optional-dependencies", {}) or {}
        # Extra names normalise the same way distribution names do (PEP 685).
        by_extra = {canonical(key): value for key, value in declared.items()}
        for extra in extras:
            if (name, extra) in seen_extras:
                continue
            seen_extras.add((name, extra))
            for requirement in by_extra.get(extra, []) or []:
                parsed = parse_requirement(requirement)
                if parsed:
                    queue.append(parsed)

    return reached


def missing(root: Path) -> tuple[list[dict], str | None]:
    """Return (findings, skip-reason). A skip-reason means nothing was scannable."""
    if not (root / WORKFLOW).exists():
        return [], f"{WORKFLOW} is not present under the scan root"

    checkouts = libraries(root)
    if not checkouts:
        return [], (
            f"no library checkout matches the [mode=release] install set in {WORKFLOW}"
        )
    # The closure only needs each library's metadata; the checkout dir is
    # carried alongside so a finding can name the repo to fix.
    libs = {name: data for name, (_, data) in checkouts.items()}

    roots = install_roots(root, SMOKE_STEP)
    if not roots:
        return [], f"no smoke install step found in {WORKFLOW}"

    reached = closure(roots, libs)

    findings: list[dict] = []
    for name, (repo, data) in sorted(checkouts.items()):
        if RELEASE_EXTRA not in {
            canonical(key)
            for key in (data.get("project", {}).get("optional-dependencies", {}) or {})
        }:
            continue

        for dist in sorted(closure([(name, (RELEASE_EXTRA,))], libs) - reached):
            findings.append(
                {
                    "dependency": dist,
                    "declared_by": f"{name}[{RELEASE_EXTRA}]",
                    "repo": repo,
                }
            )

    # A package can be declared optional by more than one library; report the
    # missing install once, naming every declarer.
    merged: dict[str, dict] = {}
    for finding in findings:
        entry = merged.setdefault(
            finding["dependency"],
            {"dependency": finding["dependency"], "declared_by": [], "repos": []},
        )
        entry["declared_by"].append(finding["declared_by"])
        entry["repos"].append(finding["repo"])

    return [merged[key] for key in sorted(merged)], None


def summarise(findings: list[dict], skipped: str | None) -> str:
    if skipped:
        return f"0|not scannable here: {skipped}"
    if not findings:
        return (
            "0|clean: the smoke install set reaches every dependency the "
            "libraries declare optional"
        )
    detail = ", ".join(
        f"{f['dependency']} ({'/'.join(f['declared_by'])})" for f in findings
    )
    subject = "dependency is" if len(findings) == 1 else "dependencies are"
    return (
        f"{len(findings)}|{len(findings)} optional {subject} declared by a library "
        f"but never installed by the workspace-validation smoke leg ({detail}) — "
        f"red in smoke, green in release"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json-row", action="store_true")
    output.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    findings, skipped = missing(args.root)

    if args.summary:
        print(summarise(findings, skipped))
        return 0

    if args.json_row:
        # Must carry the same envelope as every other mode's row — the default
        # --json scan keys the rows by "mode", so omitting it breaks the whole
        # decision document, not just this row.
        print(
            json.dumps(
                {
                    "count": len(findings),
                    "delegate": "/bug",
                    "findings": findings,
                    "kind": "finding",
                    "mode": "extras",
                    "status": "clean" if not findings else "finding",
                    "summary": summarise(findings, skipped).split("|", 1)[1],
                },
                sort_keys=True,
            )
        )
        return 0

    if skipped:
        print(f"Optional-dependency exposure not scannable here: {skipped}.")
        return 0

    if not findings:
        print(
            "No exposure drift: every dependency the libraries declare optional is "
            "reachable from the workspace-validation smoke install set."
        )
        return 0

    print(
        f"{len(findings)} optional dependency(ies) the smoke leg never installs:\n"
    )
    for finding in findings:
        print(f"  {finding['dependency']}")
        print(
            f"      declared by {', '.join(finding['declared_by'])} "
            f"({', '.join(finding['repos'])}); installed in mode=release, "
            f"absent in mode=smoke"
        )
    print(
        f"\nAdd each to the smoke install step in {WORKFLOW}.\n\n"
        "PIN THE PACKAGE, don't add the declaring library's [optional] extra: this\n"
        "leg installs PUBLISHED wheels, so a library extra resolves the RELEASED\n"
        "metadata, which lags the source pyproject this scan reads. A stale pin in\n"
        "that extra can silently downgrade a package the step pinned deliberately\n"
        "(autoarray 2026.7.29.2[optional] pinning nufftax<0.5.0 did exactly that).\n"
        "This scan is what covers future additions — that is why it exists.\n\n"
        "Do NOT skip-guard or park the failing script: it passes mode=release, so "
        "the script is correct and the install set is the defect. Route to /bug."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Hygiene pre-scan: smoke-listed scripts that need an optional-dependency skip
guard but do not have one.

A workspace script that constructs an API requiring an optional package fails
hard when that package is absent. For most scripts that is correct — the user
should get the library's error. But a script listed in ``smoke_tests.txt`` runs
in CI matrices that deliberately omit the optional extras, where the same
failure is a false red.

The house fix is the skip guard::

    if importlib.util.find_spec("<dep>") is None:
        print("Skipping ...")
        sys.exit(0)

which exits 0 (a PASS for the script runner) and is recognised in notebooks by
``PyAutoHands`` ``build_util.is_clean_skip_exit``.

Nothing enforces that pairing, so it drifts: it is hand-added per script, and a
newly smoke-listed script silently becomes a matrix failure. This flags exactly
the gap — smoke-listed AND uses a gated symbol AND has no guard.

Deliberately narrow. Scripts NOT in ``smoke_tests.txt`` are never reported: they
are not in CI, and a real error is the right behaviour there.

Symbol matches are AST-confirmed. These workspaces carry long prose blocks as
module-level string expressions, so a plain grep for ``TransformerNUFFT`` hits
documentation far more often than code; only executable references count.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import warnings
from pathlib import Path

# Workspace prose blocks contain LaTeX (\sigma, \epsilon, ...), so parsing them
# emits a SyntaxWarning per occurrence. That is the scanned repo's business, not
# a signal from this scan, and it would bury the report.
warnings.filterwarnings("ignore", category=SyntaxWarning)

# Optional package -> the symbols whose *construction* requires it. Extend this
# as new optional-dependency-gated APIs appear.
GATED_SYMBOLS: dict[str, tuple[str, ...]] = {
    "nufftax": ("TransformerNUFFT",),
    "blackjax": ("BlackJAXNUTS",),
}

WORKSPACES = (
    "autolens_workspace",
    "autogalaxy_workspace",
    "autofit_workspace",
    "autocti_workspace",
    "HowToLens",
    "HowToGalaxy",
    "HowToFit",
)


def prose_lines(tree: ast.Module) -> set[int]:
    """Line numbers spanned by bare string-expression statements (doc blocks)."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def smoke_entries(workspace: Path) -> list[str]:
    listing = workspace / "smoke_tests.txt"
    if not listing.exists():
        return []
    return [
        line.strip()
        for line in listing.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def unguarded(root: Path) -> list[dict]:
    """Return one record per smoke-listed script missing a needed skip guard."""
    findings: list[dict] = []

    for name in WORKSPACES:
        workspace = root / name
        if not (workspace / ".git").exists():
            continue

        for entry in smoke_entries(workspace):
            script = workspace / "scripts" / entry
            if not script.exists():
                continue
            try:
                source = script.read_text()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue  # a parse failure is the CLI-noise/lint modes' problem

            skip = prose_lines(tree)
            code = [
                line
                for number, line in enumerate(source.splitlines(), 1)
                if number not in skip
            ]
            executable = "\n".join(code)

            for dep, symbols in GATED_SYMBOLS.items():
                used = [s for s in symbols if s in executable]
                if not used:
                    continue
                if f'find_spec("{dep}")' in source:
                    continue
                findings.append(
                    {
                        "workspace": name,
                        "script": entry,
                        "dependency": dep,
                        "symbols": sorted(used),
                    }
                )

    return sorted(findings, key=lambda f: (f["workspace"], f["script"]))


def summarise(findings: list[dict]) -> str:
    if not findings:
        return "0|clean: every smoke-listed script using a gated API has its skip guard"
    per_dep: dict[str, int] = {}
    for finding in findings:
        per_dep[finding["dependency"]] = per_dep.get(finding["dependency"], 0) + 1
    detail = " ".join(f"{dep}:{count}" for dep, count in sorted(per_dep.items()))
    subject = "script uses" if len(findings) == 1 else "scripts use"
    return (
        f"{len(findings)}|{len(findings)} smoke-listed {subject} a gated API "
        f"with no optional-dependency skip guard ({detail}) — fails the CI "
        f"matrices that omit the extras"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json-row", action="store_true")
    output.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    findings = unguarded(args.root)

    if args.summary:
        print(summarise(findings))
        return 0

    if args.json_row:
        # Must carry the same envelope as every other mode's row — the default
        # --json scan keys the rows by "mode", so omitting it breaks the whole
        # decision document, not just this row.
        print(
            json.dumps(
                {
                    "count": len(findings),
                    "delegate": "/refactor",
                    "findings": findings,
                    "kind": "finding",
                    "mode": "optdeps",
                    "status": "clean" if not findings else "finding",
                    "summary": summarise(findings).split("|", 1)[1],
                },
                sort_keys=True,
            )
        )
        return 0

    if not findings:
        print("No unguarded smoke-listed scripts: every gated API use has a skip guard.")
        return 0

    print(f"{len(findings)} smoke-listed script(s) missing an optional-dependency guard:\n")
    for finding in findings:
        print(f"  {finding['workspace']}/scripts/{finding['script']}")
        print(
            f"      uses {', '.join(finding['symbols'])} "
            f"(requires `{finding['dependency']}`) with no "
            f"find_spec(\"{finding['dependency']}\") guard"
        )
    print(
        "\nAdd the house skip guard to each, mirroring "
        "autolens_workspace/scripts/interferometer/modeling.py:\n\n"
        "    import importlib.util\n"
        "    import sys\n\n"
        "    if importlib.util.find_spec(\"<dep>\") is None:\n"
        "        print(\"Skipping ...\")\n"
        "        sys.exit(0)\n\n"
        "Route the exact findings to /refactor; Hygiene never edits source."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

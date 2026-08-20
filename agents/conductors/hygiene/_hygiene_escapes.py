#!/usr/bin/env python3
"""Read-only scanner for LaTeX corrupted by Python's string-escape handling.

Workspace tutorial prose carries LaTeX in module-level docstrings. Unless the
docstring is raw, Python's escape handling damages it in two INDEPENDENT ways,
and a scan that looks for only the first reports a clean sweep over a corpus
full of the second:

warned  ``\\s``, ``\\l``, ``\\[`` -- escapes Python does NOT recognise. It keeps
        them literal but warns on every compile, and they are slated to become a
        SyntaxError.
silent  ``\\t`` in ``\\theta``, ``\\f`` in ``\\frac``, ``\\r`` in ``\\rm``,
        ``\\b`` in ``\\beta``. Escapes Python DOES recognise: the value is
        corrupted and there is NO diagnostic of any kind. ``\\theta_E`` becomes
        a TAB followed by ``heta_E``.

TWO INTERPRETER TRAPS, both of which have already produced a false "clean":

1. Invalid escapes are a ``SyntaxWarning`` only on Python 3.12+; on 3.11 and
   earlier they are a ``DeprecationWarning``. A ``SyntaxWarning``-only sweep
   returns zero on 3.11 and is indistinguishable from "already fixed". Both
   categories are collected here, so the scan is interpreter-independent.
2. ``compileall`` needs ``-f``, or ``__pycache__`` suppresses recompilation and
   the counts silently drop. This module compiles from source text and never
   consults a cache.

Read-only, stdlib-only, and consistent with the rest of the Hygiene Agent: it
reports and delegates to /refactor; it never edits a file.
"""

from __future__ import annotations

import argparse
import ast
import json
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_PARTS = {".git", "__pycache__", "build", "dist", ".ipynb_checkpoints"}
# A newline in a string value is ordinary text, not evidence of a mangled macro.
CONTROL_EXCEPT_NEWLINE = "\n"


@dataclass(frozen=True)
class Finding:
    repo: str
    file: str
    warned: int
    silent: int


@dataclass(frozen=True)
class ParseError:
    repo: str
    file: str
    message: str


def repository_paths(root: Path) -> list[Path]:
    """Return user-facing ``*_workspace`` and ``HowTo*`` repositories."""
    candidates = [*root.glob("*_workspace"), *root.glob("HowTo*")]
    return sorted(
        {path.resolve() for path in candidates if (path / "scripts").is_dir()},
        key=lambda path: path.name.lower(),
    )


def warned_count(source: str, path: Path) -> int:
    """Escapes Python does not recognise, on ANY interpreter version."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(source, str(path), "exec")
        except SyntaxError:
            return 0
    return sum(
        1
        for item in caught
        # Both categories: SyntaxWarning on 3.12+, DeprecationWarning on <=3.11.
        if issubclass(item.category, (SyntaxWarning, DeprecationWarning))
        and "invalid escape sequence" in str(item.message)
    )


def silent_count(source: str) -> int:
    """Escapes Python DOES recognise, which corrupt the value with no warning.

    A non-raw literal whose SOURCE carries a backslash but whose VALUE carries a
    control character has had a macro eaten -- ``\\theta`` became TAB + ``heta``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    total = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if "\\" not in segment:
            continue
        if segment[:1] in "rR" or segment[:2].lower() in ("br", "rb", "fr", "rf"):
            continue  # already raw: the escape never happened
        if any(
            ord(char) < 32 and char != CONTROL_EXCEPT_NEWLINE for char in node.value
        ):
            total += 1
    return total


def scan(root: Path) -> tuple[list[Finding], list[ParseError], int]:
    findings: list[Finding] = []
    errors: list[ParseError] = []
    repositories = repository_paths(root)
    for repository in repositories:
        for script in sorted((repository / "scripts").rglob("*.py")):
            if SKIP_PARTS & set(script.parts):
                continue
            try:
                source = script.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                errors.append(
                    ParseError(repository.name, str(script.relative_to(repository)), str(error))
                )
                continue
            warned, silent = warned_count(source, script), silent_count(source)
            if warned or silent:
                findings.append(
                    Finding(
                        repository.name,
                        str(script.relative_to(repository)),
                        warned,
                        silent,
                    )
                )
    return findings, errors, len(repositories)


def summary_for(findings: list[Finding], errors: list[ParseError], repos: int) -> str:
    warned = sum(finding.warned for finding in findings)
    silent = sum(finding.silent for finding in findings)
    silent_only = sum(1 for finding in findings if finding.silent and not finding.warned)
    return (
        f"{len(findings)} script(s) across {repos} repo(s) with LaTeX damaged by "
        f"string escapes: {warned} warned, {silent} silent "
        f"({silent_only} file(s) have ONLY silent damage, which a warning-only "
        f"sweep would miss); {len(errors)} read error(s)"
    )


def row_for(root: Path) -> dict:
    findings, errors, repository_count = scan(root)
    if errors:
        status = "partial"
    elif findings:
        status = "finding"
    else:
        status = "clean"
    return {
        "mode": "escapes",
        "kind": "finding",
        "status": status,
        "count": len(findings),
        "summary": summary_for(findings, errors, repository_count),
        "delegate": "/refactor",
        "findings": [asdict(finding) for finding in findings],
        "parse_errors": [asdict(error) for error in errors],
    }


def render_human(row: dict) -> None:
    print(row["summary"])
    for finding in row["findings"]:
        marker = "  <- silent only" if finding["silent"] and not finding["warned"] else ""
        print(
            f"  {finding['repo']}/{finding['file']}: "
            f"{finding['warned']} warned, {finding['silent']} silent{marker}"
        )
    if row["parse_errors"]:
        print("Read errors (scan incomplete):")
        for error in row["parse_errors"]:
            print(f"  {error['repo']}/{error['file']}: {error['message']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json-row", action="store_true")
    output.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    row = row_for(args.root.resolve())
    if args.json_row:
        print(json.dumps(row, sort_keys=True))
    elif args.summary:
        print(f"{row['count']}|{row['summary']}")
    else:
        render_human(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

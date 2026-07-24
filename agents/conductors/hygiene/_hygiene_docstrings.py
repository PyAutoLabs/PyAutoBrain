#!/usr/bin/env python3
"""Read-only scanner for adjacent top-level script documentation blocks."""

from __future__ import annotations

import argparse
import ast
import json
import re
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path


TRIPLE_QUOTE = re.compile(r"(?i)^[ruf]*(?:\"\"\"|''')")


@dataclass(frozen=True)
class Finding:
    repo: str
    file: str
    first_line: int
    first_end_line: int
    second_line: int
    second_end_line: int


@dataclass(frozen=True)
class ParseError:
    repo: str
    file: str
    error: str
    line: int | None
    message: str


def repository_paths(root: Path) -> list[Path]:
    """Return user-facing ``*_workspace`` and ``HowTo*`` repositories."""
    candidates = [*root.glob("*_workspace"), *root.glob("HowTo*")]
    return sorted(
        {path.resolve() for path in candidates if (path / "scripts").is_dir()},
        key=lambda path: path.name.lower(),
    )


def _line_offsets(source: str) -> tuple[list[str], list[int]]:
    lines = source.splitlines(keepends=True)
    offsets: list[int] = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    return lines, offsets


def _source_offset(
    lines: list[str], offsets: list[int], lineno: int, byte_col: int
) -> int:
    """Convert an AST UTF-8 byte column into a Python string offset."""
    line = lines[lineno - 1]
    char_col = len(line.encode("utf-8")[:byte_col].decode("utf-8"))
    return offsets[lineno - 1] + char_col


def _source_segment(
    source: str, lines: list[str], offsets: list[int], node: ast.AST
) -> str:
    start = _source_offset(lines, offsets, node.lineno, node.col_offset)
    end = _source_offset(lines, offsets, node.end_lineno, node.end_col_offset)
    return source[start:end]


def _is_triple_quoted_string_expr(
    source: str, lines: list[str], offsets: list[int], node: ast.AST
) -> bool:
    if not (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return False
    literal = _source_segment(source, lines, offsets, node.value)
    return TRIPLE_QUOTE.match(literal) is not None


def findings_in_source(source: str, repo: str, file: str) -> list[Finding]:
    """Find adjacent top-level triple-quoted expressions in one Python file."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=file)

    lines, offsets = _line_offsets(source)
    findings: list[Finding] = []
    for first, second in zip(tree.body, tree.body[1:]):
        if not _is_triple_quoted_string_expr(source, lines, offsets, first):
            continue
        if not _is_triple_quoted_string_expr(source, lines, offsets, second):
            continue

        first_end = _source_offset(
            lines, offsets, first.end_lineno, first.end_col_offset
        )
        second_start = _source_offset(
            lines, offsets, second.lineno, second.col_offset
        )
        if source[first_end:second_start].strip():
            continue

        findings.append(
            Finding(
                repo=repo,
                file=file,
                first_line=first.lineno,
                first_end_line=first.end_lineno,
                second_line=second.lineno,
                second_end_line=second.end_lineno,
            )
        )
    return findings


def scan(root: Path) -> tuple[list[Finding], list[ParseError], int]:
    findings: list[Finding] = []
    errors: list[ParseError] = []
    repositories = repository_paths(root)

    for repository in repositories:
        for path in sorted((repository / "scripts").rglob("*.py")):
            relative = path.relative_to(repository).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
                findings.extend(findings_in_source(source, repository.name, relative))
            except (OSError, UnicodeError, SyntaxError) as error:
                errors.append(
                    ParseError(
                        repo=repository.name,
                        file=relative,
                        error=type(error).__name__,
                        line=getattr(error, "lineno", None),
                        message=str(error),
                    )
                )
    return findings, errors, len(repositories)


def summary_for(
    findings: list[Finding], errors: list[ParseError], repository_count: int
) -> str:
    file_count = len({(finding.repo, finding.file) for finding in findings})
    affected_repositories = len({finding.repo for finding in findings})
    file_label = "file" if file_count == 1 else "files"
    return (
        f"{len(findings)} adjacent documentation boundaries in {file_count} {file_label} "
        f"across {affected_repositories}/{repository_count} repos; "
        f"{len(errors)} parse errors"
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
        "mode": "docstrings",
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
        print(
            "  "
            f"{finding['repo']}/{finding['file']}:"
            f"{finding['first_end_line']} -> {finding['second_line']}"
        )
    if row["parse_errors"]:
        print("Parse errors (scan incomplete):")
        for error in row["parse_errors"]:
            location = f":{error['line']}" if error["line"] is not None else ""
            print(
                f"  {error['repo']}/{error['file']}{location}: "
                f"{error['error']}: {error['message']}"
            )


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

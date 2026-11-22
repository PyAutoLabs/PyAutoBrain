"""Shared plumbing for the workspace-script scanners.

`_hygiene_docstrings.py`, `_hygiene_escapes.py` and `_hygiene_refs.py` each
scan the same repositories, emit the same row shape and answer the same three
output flags. That part lives here, once; what each scanner looks for stays in
its own file. Stdlib only, like every hygiene helper.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _repo_paths import iter_checkouts  # noqa: E402


def repository_paths(root: Path) -> list[Path]:
    """Return user-facing ``*_workspace`` and ``HowTo*`` repositories."""
    candidates = [*iter_checkouts(root), *root.glob("*_workspace"), *root.glob("HowTo*")]
    candidates = [p for p in candidates if p.name.endswith("_workspace") or p.name.startswith("HowTo")]
    return sorted(
        {path.resolve() for path in candidates if (path / "scripts").is_dir()},
        key=lambda path: path.name.lower(),
    )


def finding_row(mode: str, findings: list, summary: str, errors: list | None = None) -> dict:
    """The `/refactor`-delegated row a scanner reports. `errors` is passed only
    by a scanner that can fail to read a file: any error makes the scan
    `partial`, and the row then carries `parse_errors`."""
    if errors:
        status = "partial"
    elif findings:
        status = "finding"
    else:
        status = "clean"
    row = {
        "mode": mode,
        "kind": "finding",
        "status": status,
        "count": len(findings),
        "summary": summary,
        "delegate": "/refactor",
        "findings": [asdict(finding) for finding in findings],
    }
    if errors is not None:
        row["parse_errors"] = [asdict(error) for error in errors]
    return row


def main(row_for, render_human) -> int:
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

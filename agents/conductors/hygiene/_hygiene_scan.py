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
from _repo_paths import iter_checkouts, manifest_text, repo_path  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hygiene_repos import parse_minimal  # noqa: E402

#: The body-map categories whose repositories these scanners read: the
#: user-facing workspaces and the HowTo courses. Category names are framework
#: vocabulary (the body map's schema), not instance facts.
USER_FACING_CATEGORIES = ("workspace", "howto")


def declared_names(root: Path) -> list[str] | None:
    """The scan set the body map under ``root`` declares, or None without one.

    The set is DECLARED, never inferred from the disk: the laptop and the cloud
    board must scan the same repositories (PyAutoBrain#735 — on 2026-11-27 the
    cloud scanned 5 and the laptop 8, because the board's CI clone step skipped
    a category the laptop happened to have on disk).
    """
    try:
        text = manifest_text(root)
    except (OSError, ValueError):
        return None
    if not text:
        return None
    return sorted(
        (name for name, category in parse_minimal(text).items()
         if category in USER_FACING_CATEGORIES),
        key=str.lower,
    )


def _discovered(root: Path) -> list[Path]:
    """Disk discovery: the fallback for a root that carries no body map (test
    fixtures, a bare scan root). Workspace-shaped names only."""
    candidates = [*iter_checkouts(root), *root.glob("*_workspace"), *root.glob("HowTo*")]
    candidates = [p for p in candidates if p.name.endswith("_workspace") or p.name.startswith("HowTo")]
    return sorted(
        {path.resolve() for path in candidates if (path / "scripts").is_dir()},
        key=lambda path: path.name.lower(),
    )


def scan_set(root: Path) -> tuple[list[Path], list[str]]:
    """``(present repository paths, declared names missing on disk)``.

    A declared repository without a ``scripts/`` directory under ``root`` is
    returned as NOT SCANNED, never silently dropped: a repo that is never read
    produces no findings, and a zero would then claim a clean bill of health.
    """
    declared = declared_names(root)
    if declared is None:
        return _discovered(root), []
    present: list[Path] = []
    missing: list[str] = []
    for name in declared:
        try:
            path = repo_path(root, name)
        except ValueError:
            missing.append(name)
            continue
        if (path / "scripts").is_dir():
            present.append(path.resolve())
        else:
            missing.append(name)
    return sorted(present, key=lambda path: path.name.lower()), missing


def repository_paths(root: Path) -> list[Path]:
    """Return the user-facing ``*_workspace`` and ``HowTo*`` repositories present."""
    return scan_set(root)[0]


def not_scanned_note(missing: list[str]) -> str:
    """The summary suffix naming declared repositories that were not read."""
    if not missing:
        return ""
    return f"; NOT SCANNED (declared, missing on disk): {', '.join(missing)}"


def finding_row(mode: str, findings: list, summary: str, errors: list | None = None,
                not_scanned: list[str] | None = None) -> dict:
    """The `/refactor`-delegated row a scanner reports. `errors` is passed only
    by a scanner that can fail to read a file: any error makes the scan
    `partial`, and the row then carries `parse_errors`. `not_scanned` names
    declared repositories missing on disk: with no findings that is `partial`
    too, never `clean`, and the row carries the names."""
    if errors:
        status = "partial"
    elif findings:
        status = "finding"
    elif not_scanned:
        status = "partial"
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
    if not_scanned is not None:
        row["not_scanned"] = list(not_scanned)
        row["summary"] = summary + not_scanned_note(not_scanned)
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

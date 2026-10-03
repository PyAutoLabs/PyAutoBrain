#!/usr/bin/env python3
"""Build a standalone assistant skill from Brain's canonical feedback resources.

Write the reference assistant, then use clone sync for sibling propagation.
This does not install skills globally or change any harness configuration.
"""
from __future__ import annotations

import argparse
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "skills" / "feedback"


def render(source: Path = SOURCE) -> str:
    metadata = (source / "SKILL.md").read_text().split("---", 2)[1].strip()
    workflow = (source / "feedback.md").read_text()
    workflow = workflow.replace("[template.md](template.md)", "[report template](#report-template)")
    workflow = workflow.replace("[invitation.md](invitation.md)", "[portable invitation](#portable-invitation)")
    template = (source / "template.md").read_text().split("\n", 1)[1].lstrip()
    invitation = (source / "invitation.md").read_text().split("\n", 1)[1].lstrip()
    return (
        f"---\n{metadata}\n---\n\n"
        "<!-- Generated from PyAutoBrain:skills/feedback/ by bin/sync_feedback.py. "
        "Edit those canonical sources and regenerate; use clone sync for siblings. -->\n\n"
        "This is a feedback-drafting skill, not a science-code skill. Its output is\n"
        "a user-reviewed draft, not a script or a wiki entry. All resources are\n"
        "embedded below; using this skill needs no Brain checkout or setup.\n\n"
        + workflow.rstrip() + "\n\n## Report template\n\n" + template.rstrip()
        + "\n\n## Portable invitation\n\n" + invitation.rstrip() + "\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assistant", type=Path, nargs="+", help="explicit assistant checkout(s)")
    parser.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = parser.parse_args(argv)
    expected = render()
    failed = False
    for root in args.assistant:
        if not (root / "skills").is_dir() or not (root / "AGENTS.md").is_file():
            parser.error(f"not an assistant checkout: {root}")
        path = root / "skills" / "feedback.md"
        if path.is_symlink():
            parser.error(f"refusing to write through a skill symlink: {path}")
        current = path.read_text() if path.is_file() else None
        if current == expected:
            print(f"current: {path}")
        elif args.check:
            print(f"drift: {path}")
            failed = True
        else:
            path.write_text(expected)
            print(f"wrote: {path}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""One line naming what failed in a validation stage report, for the page text.

`nightly.sh` pages Slack when a stage fails. The page is far more useful if it
names the failures, so this reads the stage report the run produced and prints a
single line; printing nothing (exit 0) means "no report, or nothing nameable" and
the caller pages without detail.

The report separates two kinds of failure, and conflating them is what made the
old inline version misread:

* ``summary`` counts SCRIPTS — ``{"failed": 1, "passed": 654, "timeout": 0, …}``.
* ``failures`` lists script failures (each with a ``project``) AND non-script
  legs, which carry ``project: null`` and a ``reason`` — e.g.
  ``{"project": null, "script": "verify_install", "reason": "verify_install FAILED"}``.

A non-script leg is NOT in ``summary.failed``, so listing it beside the scripts
produced "1 failed: <two things>" — a count that reads as a bug in the reporter
— and ``f"{f['project']} …"`` stringified the null as a literal "None"
("None verify_install", 2026-08-04). Both kinds are worth paging, so neither is
dropped; they are reported as separate segments instead.

Usage: stage_failure_summary.py <stage_report.json>
"""

from __future__ import annotations

import json
import sys

# Long pages get truncated by chat clients; name enough to act on, then count.
MAX_NAMED = 3


def summarise(report: dict) -> str:
    """The page's detail line — '' when the report names nothing useful."""
    summary = report.get("summary") or {}
    counts = []
    for key in ("failed", "timeout"):
        try:
            value = int(summary.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue  # a malformed count must not cost us the whole page
        if value:
            counts.append(f"{value} {key}")

    scripts: list[str] = []
    checks: list[str] = []
    for failure in report.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        project = failure.get("project")
        script = str(failure.get("script") or "").rstrip("/")
        if project:
            # The tail is enough to identify a script; the full runner path is
            # noise in a chat message.
            tail = "/".join(script.split("/")[-2:])
            scripts.append(f"{project} {tail}".strip())
        else:
            checks.append(str(failure.get("reason") or script or "unnamed check"))

    segments = []
    if counts or scripts:
        head = ", ".join(counts) if counts else "failures"
        if scripts:
            head += ": " + ", ".join(scripts[:MAX_NAMED])
            if len(scripts) > MAX_NAMED:
                head += f", +{len(scripts) - MAX_NAMED} more"
        segments.append(head)
    segments.extend(checks[:MAX_NAMED])
    if len(checks) > MAX_NAMED:
        segments.append(f"+{len(checks) - MAX_NAMED} more checks")

    return "; ".join(segments)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 0  # no path given: the caller pages without detail
    try:
        with open(argv[1]) as handle:
            report = json.load(handle)
    except (OSError, ValueError):
        return 0  # absent or malformed report is not itself a paging failure
    if not isinstance(report, dict):
        return 0
    line = summarise(report)
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""board/_state.py — the organ cockpit feed contract (state.json, v1).

Every organ board already publishes two machine surfaces: badge.json (the
one-line headline the umbrella router reads) and board.json (the organ's own
detail, whose shape only that organ understands). Neither is enough for a
cockpit that shows ALL organs at once: badge.json has no rows to act on, and
board.json has a different shape per organ. state.json is the third surface —
one shape for every organ — carrying a status, a headline, a timestamp and the
actionable rows, each with its GitHub link and its copy-for-Claude payload.
The cockpit and the phone read it; nothing else is needed to render an organ.

The contract is documented in board/state_schema.json and enforced HERE.
Stdlib only and free of package-relative imports on purpose: sibling organ
workflows check PyAutoBrain out and run

    python PyAutoBrain/board/_state.py _site/state.json

from their own cwd to validate what they are about to publish. A contract
whose validator needs an install is a contract nobody runs.

Exit codes (CLI): 0 valid · 1 invalid or unreadable.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

SCHEMA_VERSION = 1
STATUSES = ("green", "yellow", "red", "stale", "grey")
SEVERITIES = ("red", "yellow", "info")
REQUIRED = ("schema_version", "organ", "repo", "status", "headline",
            "updated", "pages_url", "items")
ITEM_REQUIRED = ("severity", "text")
ITEM_OPTIONAL = ("url", "prompt")


def _is_utc_iso(value):
    """True for an ISO-8601 timestamp that says, explicitly, it is UTC.

    A naive timestamp is ambiguous across the dev box, CI runners and the
    phone; a cockpit comparing ages across organs needs one clock, so only a
    `Z` or `+00:00` suffix passes.
    """
    if not isinstance(value, str):
        return False
    if value.endswith("Z"):
        text = value[:-1] + "+00:00"
    elif value.endswith("+00:00"):
        text = value
    else:
        return False
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def _one_line(value):
    return isinstance(value, str) and value.strip() != "" and "\n" not in value \
        and "\r" not in value


def validate_state(obj):
    """Every way `obj` breaks the v1 contract, as readable strings.

    An empty list means valid. Errors are collected rather than raised one at
    a time so a publishing workflow can show the whole problem in one run.
    """
    if not isinstance(obj, dict):
        return ["top level must be a JSON object"]
    errors = [f"missing required key: {k}" for k in REQUIRED if k not in obj]

    if "schema_version" in obj:
        sv = obj["schema_version"]
        if isinstance(sv, bool) or sv != SCHEMA_VERSION:
            errors.append(f"schema_version must be {SCHEMA_VERSION} (got {sv!r})")
    for key in ("organ", "repo", "pages_url"):
        if key in obj and not (isinstance(obj[key], str) and obj[key].strip()):
            errors.append(f"{key} must be a non-empty string")
    if "status" in obj and obj["status"] not in STATUSES:
        errors.append(f"status must be one of {'|'.join(STATUSES)} "
                      f"(got {obj['status']!r})")
    if "headline" in obj and not _one_line(obj["headline"]):
        errors.append("headline must be a single non-empty line")
    if "updated" in obj and not _is_utc_iso(obj["updated"]):
        errors.append("updated must be an ISO-8601 UTC timestamp ending in Z "
                      f"or +00:00 (got {obj['updated']!r})")

    items = obj.get("items")
    if "items" in obj and not isinstance(items, list):
        errors.append("items must be a list")
        items = []
    for i, item in enumerate(items or []):
        where = f"items[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        errors += [f"{where} missing required key: {k}"
                   for k in ITEM_REQUIRED if k not in item]
        if "severity" in item and item["severity"] not in SEVERITIES:
            errors.append(f"{where}.severity must be one of "
                          f"{'|'.join(SEVERITIES)} (got {item['severity']!r})")
        if "text" in item and not _one_line(item["text"]):
            errors.append(f"{where}.text must be a single non-empty line")
        for k in ITEM_OPTIONAL:
            if item.get(k) is not None and not isinstance(item[k], str):
                errors.append(f"{where}.{k} must be a string or null")
    return errors


def build_state(organ, repo, status, headline, updated, pages_url, items=()):
    """A validated v1 state dict — the one constructor organs should use.

    Raises ValueError listing every contract break, so a renderer cannot
    publish a feed the cockpit would reject.
    """
    state = {
        "schema_version": SCHEMA_VERSION,
        "organ": organ,
        "repo": repo,
        "status": status,
        "headline": headline,
        "updated": updated,
        "pages_url": pages_url,
        "items": [dict(item) for item in items],
    }
    errors = validate_state(state)
    if errors:
        raise ValueError("invalid state: " + "; ".join(errors))
    return state


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: _state.py <state.json | ->", file=sys.stderr)
        return 1
    source = argv[0]
    try:
        text = sys.stdin.read() if source == "-" else \
            open(source, encoding="utf-8").read()
        obj = json.loads(text)
    except (OSError, ValueError) as e:
        print(f"state: unreadable ({e})")
        return 1
    errors = validate_state(obj)
    for err in errors:
        print(f"state: {err}")
    if errors:
        return 1
    print("state: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

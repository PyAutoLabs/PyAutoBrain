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
ITEM_STATES = ("healthy", "active", "stale", "blocked", "failed",
               "action_required", "unknown")
ACTION_KINDS = ("link", "command", "prompt")
ACTION_SAFETY = ("read_only", "requires_approval", "scientific_judgement",
                 "never_automatic", "unclassified")
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


def _item_metadata(item, where):
    """Optional v1 additions; absence means unknown, never authorization."""
    errors = []
    for key in ("id", "reason", "decision", "recommended_action_id"):
        if key in item and not _one_line(item[key]):
            errors.append(f"{where}.{key} must be a non-empty single line")
    if "state" in item and item["state"] not in ITEM_STATES:
        errors.append(f"{where}.state must be one of {'|'.join(ITEM_STATES)}")
    if "requires_human_decision" in item:
        if not isinstance(item["requires_human_decision"], bool):
            errors.append(f"{where}.requires_human_decision must be boolean")
        elif item["requires_human_decision"] and not _one_line(item.get("decision")):
            errors.append(f"{where}.decision is required for a human decision")
    actions = item.get("actions", [])
    if not isinstance(actions, list):
        return errors + [f"{where}.actions must be a list"]
    ids = []
    for n, action in enumerate(actions):
        loc = f"{where}.actions[{n}]"
        if not isinstance(action, dict):
            errors.append(f"{loc} must be an object")
            continue
        for key in ("id", "label", "target"):
            if not _one_line(action.get(key)):
                errors.append(f"{loc}.{key} must be a non-empty single line")
        if action.get("kind") not in ACTION_KINDS:
            errors.append(f"{loc}.kind must be one of {'|'.join(ACTION_KINDS)}")
        if "safety" in action and action["safety"] not in ACTION_SAFETY:
            errors.append(f"{loc}.safety must be one of {'|'.join(ACTION_SAFETY)}")
        if action.get("kind") == "link":
            from urllib.parse import urlsplit
            try:
                url = urlsplit(action.get("target", ""))
                valid = url.scheme in ("http", "https") and bool(url.netloc)
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                errors.append(f"{loc}.target must be an HTTP(S) URL")
        aid = action.get("id")
        if isinstance(aid, str):
            if aid in ids:
                errors.append(f"{loc}.id must be unique within the item")
            ids.append(aid)
    if "recommended_action_id" in item and item["recommended_action_id"] not in ids:
        errors.append(f"{where}.recommended_action_id must name an action")
    return errors


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
    if "valid_until" in obj:
        if not _is_utc_iso(obj["valid_until"]):
            errors.append("valid_until must be an ISO-8601 UTC timestamp")
        elif _is_utc_iso(obj.get("updated")) and \
                datetime.fromisoformat(obj["valid_until"].replace("Z", "+00:00")) < \
                datetime.fromisoformat(obj["updated"].replace("Z", "+00:00")):
            errors.append("valid_until must not precede updated")

    items = obj.get("items")
    if "items" in obj and not isinstance(items, list):
        errors.append("items must be a list")
        items = []
    ids = []
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
        errors.extend(_item_metadata(item, where))
        if isinstance(item.get("id"), str):
            if item["id"] in ids:
                errors.append(f"{where}.id must be unique within the feed")
            ids.append(item["id"])
    return errors


def build_state(organ, repo, status, headline, updated, pages_url, items=(), *,
                valid_until=None):
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
    if valid_until is not None:
        state["valid_until"] = valid_until
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

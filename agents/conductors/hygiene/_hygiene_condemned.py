#!/usr/bin/env python3
"""Read PyAutoMind/condemned.md for the hygiene conductor's `sweep` mode.

The hygiene conductor drives PyAutoGut but owns none of the storage: it reads
the `condemned.md` manifest (the Mind catalog of condemned self-material) and
classifies each entry by its transit clock — **due** (sweep-after date reached,
ready to void) vs **pending** (still in the transit window, recoverable). It
emits a plan; the actual void is delegated to `pyauto-gut void`. Stdlib only —
the conductor never drags a dependency into the Brain.

Usage:
    _hygiene_condemned.py --manifest <path/to/condemned.md> [--json]

Exit 0 always (an absent/empty manifest is "nothing condemned", not an error).
"""

import argparse
import datetime
import json
import re
import sys

# One "## <name>" block per condemned item; "- key: value" fields beneath it.
# HTML-commented blocks (the schema's illustrative example) are stripped first
# so they never read as live condemnations.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$")          # '## name' (not '###')
FIELD_RE = re.compile(r"^-\s*([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$")

FIELDS = ("type", "locator", "confidence", "reason", "merged",
          "condemned", "sweep-after", "breaks-if-wrong", "archive-ref")


def parse_manifest(text):
    """Return a list of entry dicts. Only '##' blocks that carry at least a
    `type` or `locator` field count as entries (the file's prose '##' sections
    — Lifecycle, Entry schema — carry neither)."""
    text = COMMENT_RE.sub("", text)
    entries, cur = [], None
    for line in text.splitlines():
        h = HEADING_RE.match(line)
        if h:
            if cur and (cur.get("type") or cur.get("locator")):
                entries.append(cur)
            cur = {"name": h.group(1)}
            continue
        if cur is None:
            continue
        f = FIELD_RE.match(line)
        if f and f.group(1).lower() in FIELDS:
            cur[f.group(1).lower()] = f.group(2)
    if cur and (cur.get("type") or cur.get("locator")):
        entries.append(cur)
    return entries


def _parse_date(s):
    try:
        return datetime.date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def classify(entries, today):
    """Split entries into (due, pending, undated). `due` = sweep-after reached."""
    due, pending, undated = [], [], []
    for e in entries:
        d = _parse_date(e.get("sweep-after"))
        if d is None:
            undated.append(e)
        elif d <= today:
            due.append(e)
        else:
            pending.append(e)
    return due, pending, undated


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--json", action="store_true", dest="as_json")
    # --today lets a test pin the reference date; defaults to the real today.
    ap.add_argument("--today", default="")
    a = ap.parse_args(argv)

    today = _parse_date(a.today) or datetime.date.today()
    try:
        with open(a.manifest, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    entries = parse_manifest(text)
    due, pending, undated = classify(entries, today)

    if a.as_json:
        print(json.dumps({
            "manifest": a.manifest, "today": today.isoformat(),
            "total": len(entries),
            "due": due, "pending": pending, "undated": undated,
        }))
        return 0

    print(f"condemned.md: {len(entries)} entr(y/ies) — "
          f"{len(due)} due, {len(pending)} pending, {len(undated)} undated "
          f"(as of {today.isoformat()})")
    for label, group in (("DUE (void)", due), ("pending", pending),
                         ("undated", undated)):
        for e in group:
            print(f"  [{label}] {e['name']} — type={e.get('type','?')} "
                  f"locator={e.get('locator','?')} "
                  f"sweep-after={e.get('sweep-after','-')} "
                  f"archive-ref={e.get('archive-ref','-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

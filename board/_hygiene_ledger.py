#!/usr/bin/env python3
"""The hygiene ledger: one line per UTC day of the board's hygiene pre-scan.

The Brain board scans hygiene on every render and used to keep nothing, so a
count could only ever be read as "now". This ledger keeps the trend and, for
each finding, a stable key the maintenance orchestrator (Phase 14.5) dedupes on.

Format — append-only JSONL, one line per UTC day::

    {"date": "2026-11-27", "sha": "<brain commit>",
     "rows": {"<mode>": <count or null>, ...},
     "findings": {"<mode>": ["<mode>:<repo>:<file>:<reference>", ...], ...}}

A re-run on the same day REPLACES that day's line (idempotent); it never adds
a second. Keys carry no line numbers, so a finding keeps its key while the
lines around it move. ``finding_key`` documents the key per mode.

Write path (PyAutoBrain#735): a published SIDECAR, not a commit. The board
workflow fetches yesterday's ``hygiene_ledger.jsonl`` from its own Pages site,
the render upserts today's line, and the file is published beside board.json.
That needs no permission the workflow does not already hold (``contents: read``,
``pages: write``); a ledger-only commit step would need a contents-write token
able to push to ``main``. The cost of a sidecar is durability, so ``fetch``
fails closed: a fetch error other than "not published yet" (404) stops the job
before deploy, and the live site keeps its ledger rather than being replaced
by a shorter one.

Stdlib only, like every board helper.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

LEDGER_NAME = "hygiene_ledger.jsonl"
#: How many days of history the board carries in board.json and draws.
HISTORY_DAYS = 30
SPARK_CHARS = "▁▂▃▄▅▆▇█"

# Modes whose findings carry no `reference`: the segment names the defect the
# file carries, so one key stands for "this file has this defect". These modes
# report per-file (escapes) or per-pair-of-line-numbers (docstrings) findings,
# and line numbers are exactly what a stable key must not contain.
FILE_LEVEL_DEFECT = {
    "docstrings": "adjacent-docstrings",
    "escapes": "latex-escapes",
}


def finding_key(mode: str, finding: dict) -> str:
    """``<mode>:<repo>:<file>:<reference>`` — no line numbers, ever.

    Per mode:

    * ``refs`` — ``repo``, ``file``, ``reference`` as reported (an undocumented
      folder's reference is ``<name>/ (folder exists, README never names it)``).
    * ``docstrings`` / ``escapes`` — ``repo``, ``file`` and a fixed defect label
      (``adjacent-docstrings`` / ``latex-escapes``): the file is the most
      specific stable field, so several findings in one file share one key.
    * ``optdeps`` — ``workspace``, ``script``, ``dependency``.
    * ``extras`` — the declaring repos joined by ``+``, ``pyproject.toml``,
      ``dependency``.
    * any other mode — ``repo``, ``file``, ``reference`` when present, else
      the remaining non-line fields as sorted ``k=v`` pairs.
    """
    if mode in FILE_LEVEL_DEFECT:
        parts = (finding.get("repo"), finding.get("file"), FILE_LEVEL_DEFECT[mode])
    elif mode == "optdeps":
        parts = (finding.get("workspace"), finding.get("script"), finding.get("dependency"))
    elif mode == "extras":
        repos = finding.get("repos") or [finding.get("repo")]
        repos = repos if isinstance(repos, list) else [repos]
        parts = ("+".join(sorted({str(r) for r in repos if r})), "pyproject.toml",
                 finding.get("dependency"))
    elif "reference" in finding:
        parts = (finding.get("repo"), finding.get("file"), finding.get("reference"))
    else:
        rest = sorted(f"{k}={v}" for k, v in finding.items()
                      if k not in ("repo", "file") and "line" not in k)
        parts = (finding.get("repo"), finding.get("file"), ",".join(rest))
    return ":".join([mode, *("" if p is None else str(p) for p in parts)])


def day_line(rows: list[dict], date: str, sha: str | None) -> dict:
    """Today's ledger line from a HygieneDecision's rows (with findings)."""
    counts: dict[str, int | None] = {}
    findings: dict[str, list[str]] = {}
    for row in rows:
        mode = row.get("mode")
        if not mode:
            continue
        count = row.get("count")
        counts[mode] = count if isinstance(count, int) else None
        if isinstance(row.get("findings"), list):
            findings[mode] = sorted({finding_key(mode, f) for f in row["findings"]
                                     if isinstance(f, dict)})
    return {"date": date, "sha": sha, "rows": counts, "findings": findings}


def read_ledger(path: Path) -> list[dict]:
    """Every well-formed line, oldest first; a malformed line is dropped, not
    fatal (one bad write must not cost the whole trend)."""
    if not path or not Path(path).is_file():
        return []
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("date"), str):
            lines.append(entry)
    return sorted(lines, key=lambda e: e["date"])


def upsert(lines: list[dict], line: dict) -> list[dict]:
    """``lines`` with ``line`` replacing any same-day entry, date-ordered."""
    kept = [e for e in lines if e.get("date") != line["date"]]
    return sorted([*kept, line], key=lambda e: e["date"])


def write_ledger(path: Path, lines: list[dict]) -> None:
    """Atomic rewrite: one compact JSON object per line."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n" for e in lines)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(tmp, path)


def record(path: Path, rows: list[dict], date: str, sha: str | None) -> list[dict]:
    """Upsert today's line into the ledger at ``path``; return the new ledger."""
    lines = upsert(read_ledger(path), day_line(rows, date, sha))
    write_ledger(path, lines)
    return lines


def history(lines: list[dict], days: int = HISTORY_DAYS) -> list[dict]:
    """board.json's ``history``: the last ``days`` lines without finding keys
    (the keys stay in the sidecar; the board carries only the trend)."""
    return [{"date": e["date"], "sha": e.get("sha"), "rows": dict(e.get("rows") or {})}
            for e in lines[-days:]]


def series(hist: list[dict], mode: str) -> list:
    return [(e.get("rows") or {}).get(mode) for e in hist]


def sparkline(values) -> str:
    """A unicode sparkline; "" under two numeric points (one point is no
    trend). The same ramp and rules as Heart's board sparkline."""
    nums = [float(v) for v in (values or []) if isinstance(v, (int, float))
            and not isinstance(v, bool)]
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    if hi <= lo:
        return SPARK_CHARS[len(SPARK_CHARS) // 2] * len(nums)
    last = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[min(last, int((n - lo) / (hi - lo) * len(SPARK_CHARS)))]
                   for n in nums)


def fetch(url: str, out: Path, opener=urllib.request.urlopen) -> str:
    """Fetch the published ledger to ``out``.

    Returns ``"fetched"`` or ``"absent"`` (HTTP 404: not published yet, start an
    empty ledger). Any other failure raises, so the workflow stops BEFORE its
    deploy and the live ledger survives — publishing after a failed read would
    replace the whole trend with a single day.
    """
    try:
        with opener(url, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            Path(out).write_text("", encoding="utf-8")
            return "absent"
        raise
    Path(out).write_bytes(body)
    return "fetched"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="fetch the published ledger (fails closed)")
    f.add_argument("--url", required=True)
    f.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        outcome = fetch(args.url, args.out)
    except (urllib.error.URLError, OSError, ValueError) as error:
        print(f"::error::hygiene ledger fetch failed ({error}); refusing to publish "
              "a board that would replace the live ledger", file=sys.stderr)
        return 1
    lines = len(read_ledger(args.out))
    print(f"hygiene ledger: {outcome} ({lines} day(s)) from {args.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

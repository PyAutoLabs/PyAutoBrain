#!/usr/bin/env python3
"""The hygiene ledger: one line per UTC day of the board's hygiene pre-scan.

The Brain board scans hygiene on every render and used to keep nothing, so a
count could only ever be read as "now". This ledger keeps the trend and, for
each finding, a stable key the maintenance orchestrator (Phase 14.5) dedupes on.

Format — append-only JSONL, one line per UTC day::

    {"date": "2026-11-27", "sha": "<Brain commit that rendered>",
     "rows": {"<mode>": <count or null>, ...},
     "status": {"<mode>": "<the row's status>", ...},
     "not_scanned": {"<mode>": ["<declared repo missing on disk>", ...], ...},
     "unkeyed": ["<non-clean mode with no per-finding keys>", ...],
     "findings": {"<mode>": ["<mode>:<repo>:<file>:<reference>", ...], ...},
     "evidence": {"<key>": {...}, ...}}

``sha`` is the Brain commit that rendered the board, NOT the scanned repos'
commits. A re-run on the same day REPLACES that day's line (idempotent), except
that an incomplete mode never overwrites a complete one (``merge_same_day``).
Keys carry no line numbers, so a finding keeps its key while the lines around it
move. ``finding_key`` documents the key per mode; ``KEYED_MODES`` lists the
modes that carry per-finding keys at all.

Write path (PyAutoBrain#735): a published SIDECAR, not a commit. The board
workflow fetches the live ``hygiene_ledger.jsonl`` from its own Pages site, the
render upserts today's line, and the file is published beside board.json. That
needs no permission the workflow does not already hold (``contents: read``,
``pages: write``); a ledger-only commit would need a contents-write token able
to push to the ruleset-protected ``main``. The cost of a sidecar is durability,
so every step fails closed (``fetch``, ``read_ledger(strict=True)``,
``check_publish``): the job stops before deploy and the live site keeps its
ledger rather than being replaced by a shorter one. A failed fetch therefore
blocks that day's board refresh — intended.

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
BOARD_NAME = "board.json"
#: Written by ``fetch`` beside the ledger: how many days it fetched, so the
#: publish step can refuse a ledger that lost some.
MARKER_SUFFIX = ".fetched.json"
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
#: The modes whose rows carry per-finding detail, hence keys. Every other mode
#: (tidy, crlf, artifacts, packaging, deps, docs, config, tokens, perf, noise)
#: reports a count only; when such a mode is not clean it is `unkeyed`.
KEYED_MODES = ("refs", "docstrings", "escapes", "optdeps", "extras")
#: Row statuses that mean the scan did not read everything it should have.
INCOMPLETE_STATUSES = frozenset({"partial", "unscanned", "error", "deferred"})


class LedgerError(Exception):
    """The ledger cannot be read or published without losing days."""


def finding_key(mode: str, finding: dict) -> str:
    """``<mode>:<repo>:<file>:<reference>`` — no line numbers, ever.

    Per mode:

    * ``refs`` — ``repo``, ``file``, ``reference`` as reported (an undocumented
      folder's reference is ``<name>/ (folder exists, README never names it)``).
    * ``docstrings`` / ``escapes`` — ``repo``, ``file`` and a fixed defect label
      (``adjacent-docstrings`` / ``latex-escapes``): the file is the most
      specific stable field, so several findings in one file share one key.
    * ``optdeps`` — ``workspace``, ``script``, ``dependency``.
    * ``extras`` — ``extras:::<dependency>``: the missing install is ONE defect
      however many libraries declare it, so the declaring repos are evidence
      (the line's ``evidence``), not part of the key.
    * any other mode — ``repo``, ``file``, ``reference`` when present, else
      the remaining non-line fields as sorted ``k=v`` pairs.
    """
    if mode in FILE_LEVEL_DEFECT:
        parts = (finding.get("repo"), finding.get("file"), FILE_LEVEL_DEFECT[mode])
    elif mode == "optdeps":
        parts = (finding.get("workspace"), finding.get("script"), finding.get("dependency"))
    elif mode == "extras":
        parts = ("", "", finding.get("dependency"))
    elif "reference" in finding:
        parts = (finding.get("repo"), finding.get("file"), finding.get("reference"))
    else:
        rest = sorted(f"{k}={v}" for k, v in finding.items()
                      if k not in ("repo", "file") and "line" not in k)
        parts = (finding.get("repo"), finding.get("file"), ",".join(rest))
    return ":".join([mode, *("" if p is None else str(p) for p in parts)])


def _evidence(mode: str, finding: dict) -> dict | None:
    if mode == "extras":
        return {k: finding[k] for k in ("repos", "declared_by") if k in finding}
    return None


def day_line(rows: list[dict], date: str, sha: str | None) -> dict:
    """Today's ledger line from a HygieneDecision's rows (with findings)."""
    counts: dict[str, int | None] = {}
    status: dict[str, str] = {}
    not_scanned: dict[str, list[str]] = {}
    unkeyed: list[str] = []
    findings: dict[str, list[str]] = {}
    evidence: dict[str, dict] = {}
    for row in rows:
        mode = row.get("mode")
        if not mode:
            continue
        count = row.get("count")
        counts[mode] = count if isinstance(count, int) and not isinstance(count, bool) else None
        status[mode] = str(row.get("status") or "")
        if row.get("not_scanned"):
            not_scanned[mode] = sorted(str(n) for n in row["not_scanned"])
        if isinstance(row.get("findings"), list):
            keys = set()
            for finding in row["findings"]:
                if not isinstance(finding, dict):
                    continue
                key = finding_key(mode, finding)
                keys.add(key)
                extra = _evidence(mode, finding)
                if extra:
                    evidence[key] = extra
            findings[mode] = sorted(keys)
        elif status[mode] != "clean":
            unkeyed.append(mode)
    return {"date": date, "sha": sha, "rows": counts, "status": status,
            "not_scanned": not_scanned, "unkeyed": sorted(unkeyed),
            "findings": findings, "evidence": evidence}


def mode_complete(line: dict, mode: str) -> bool:
    """Whether ``line`` holds a COMPLETE scan of ``mode``: keyed, every
    declared repo read, and a status that is a verdict rather than a gap."""
    status = (line.get("status") or {}).get(mode)
    return (mode in (line.get("findings") or {})
            and mode not in (line.get("unkeyed") or [])
            and not (line.get("not_scanned") or {}).get(mode)
            and status not in INCOMPLETE_STATUSES)


def merge_same_day(old: dict, new: dict) -> dict:
    """``new`` replacing ``old`` (same day), except per mode: an incomplete
    mode in ``new`` never replaces a complete one in ``old`` — the earlier
    keys, status and count are kept, so a re-run that lost a repo or a helper
    cannot make findings look fixed."""
    merged = json.loads(json.dumps(new))
    for key in ("rows", "status", "not_scanned", "findings", "evidence"):
        merged.setdefault(key, {})
    merged.setdefault("unkeyed", [])
    modes = set(old.get("rows") or {}) | set(old.get("findings") or {})
    for mode in modes:
        if not mode_complete(old, mode) or mode_complete(new, mode):
            continue
        merged["rows"][mode] = (old.get("rows") or {}).get(mode)
        merged["status"][mode] = (old.get("status") or {}).get(mode)
        merged["findings"][mode] = list(old["findings"][mode])
        merged["not_scanned"].pop(mode, None)
        merged["unkeyed"] = [m for m in merged["unkeyed"] if m != mode]
        for key in old["findings"][mode]:
            if key in (old.get("evidence") or {}):
                merged["evidence"][key] = old["evidence"][key]
    return merged


def _parse(text: str) -> tuple[list[dict], int]:
    """``(well-formed lines, non-blank line count)``."""
    lines, nonblank = [], 0
    for raw in text.splitlines():
        if not raw.strip():
            continue
        nonblank += 1
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("date"), str):
            lines.append(entry)
    return lines, nonblank


def read_ledger(path: Path, strict: bool = False) -> list[dict]:
    """Every well-formed line, oldest first. ``strict``: any malformed line
    raises ``LedgerError`` (the writer must not drop days); otherwise a bad
    line is skipped (a reader must not crash on one)."""
    if not path or not Path(path).is_file():
        return []
    lines, nonblank = _parse(Path(path).read_text(encoding="utf-8"))
    if strict and len(lines) != nonblank:
        raise LedgerError(f"{path}: {nonblank - len(lines)} malformed line(s); "
                          "refusing to rewrite a ledger that would lose days")
    return sorted(lines, key=lambda e: e["date"])


def upsert(lines: list[dict], line: dict) -> list[dict]:
    """``lines`` with ``line`` merged into any same-day entry, date-ordered."""
    same = [e for e in lines if e.get("date") == line["date"]]
    if same:
        line = merge_same_day(same[-1], line)
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
    """Upsert today's line into the ledger at ``path``; return the new ledger.
    Raises ``LedgerError`` (writing nothing) when the file has malformed lines."""
    before = read_ledger(path, strict=True)
    lines = upsert(before, day_line(rows, date, sha))
    if len(lines) < len(before):  # cannot happen by construction; guarded anyway
        raise LedgerError("upsert lost days")
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


# ------------------------------------------------------------------- fetch --


def _get(url: str, opener) -> bytes:
    """GET with the Pages CDN cache bypassed (the workflow also adds a
    per-run query string)."""
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache",
                                                   "Pragma": "no-cache"})
    with opener(request, timeout=30) as response:
        return response.read()


def sibling_url(url: str, name: str) -> str:
    """``url`` with its last path segment replaced by ``name`` (query kept)."""
    base, _, query = url.partition("?")
    return base.rsplit("/", 1)[0] + "/" + name + (f"?{query}" if query else "")


def _board_has_history(url: str, opener) -> bool:
    """Whether the live board.json beside ``url`` carries history. A 404 is a
    true first publish (False); any other failure raises."""
    try:
        body = _get(sibling_url(url, BOARD_NAME), opener)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    try:
        board = json.loads(body)
    except json.JSONDecodeError as error:
        raise LedgerError(f"live {BOARD_NAME} is not JSON ({error})") from error
    return bool(isinstance(board, dict) and board.get("history"))


def _write_marker(out: Path, days: int, outcome: str) -> None:
    Path(str(out) + MARKER_SUFFIX).write_text(
        json.dumps({"days": days, "outcome": outcome}) + "\n", encoding="utf-8")


def fetch(url: str, out: Path, opener=urllib.request.urlopen, reset: bool = False) -> str:
    """Fetch the published ledger to ``out`` and record how many days it held.

    Returns ``"fetched"``, ``"absent"`` (a true first publish: the ledger is 404
    AND the live board.json is 404 or has no history) or ``"reset"`` (explicit).
    Raises — so the workflow stops BEFORE its deploy and the live ledger
    survives — on any other failure: a non-404 error, a 404 ledger beside a
    board that has history (the ledger was lost, not new), or a 200 body with
    malformed lines (an HTML error page, a truncated file).
    """
    if reset:
        Path(out).write_text("", encoding="utf-8")
        _write_marker(out, 0, "reset")
        return "reset"
    try:
        body = _get(url, opener)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        if _board_has_history(url, opener):
            raise LedgerError(
                f"{LEDGER_NAME} is 404 but the live {BOARD_NAME} has history: the "
                "ledger was lost, not new. Re-run with --reset to start over") from error
        Path(out).write_text("", encoding="utf-8")
        _write_marker(out, 0, "absent")
        return "absent"
    text = body.decode("utf-8", "replace")
    lines, nonblank = _parse(text)
    if len(lines) != nonblank:
        raise LedgerError(f"fetched ledger has {nonblank - len(lines)} malformed of "
                          f"{nonblank} line(s) (an error page or a truncated file)")
    Path(out).write_bytes(body)
    _write_marker(out, len({e['date'] for e in lines}), "fetched")
    return "fetched"


def check_publish(path: Path) -> int:
    """Refuse to publish a ledger holding fewer days than ``fetch`` read.
    Returns the day count; raises ``LedgerError``. No marker (a local render
    that never fetched): nothing to compare against."""
    lines = read_ledger(path, strict=True)
    days = len({e["date"] for e in lines})
    marker = Path(str(path) + MARKER_SUFFIX)
    if marker.is_file():
        fetched = int(json.loads(marker.read_text(encoding="utf-8")).get("days") or 0)
        if days < fetched:
            raise LedgerError(f"ledger has {days} day(s) but {fetched} were fetched; "
                              "refusing to publish a shorter ledger")
    return days


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="fetch the published ledger (fails closed)")
    f.add_argument("--url", required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--reset", action="store_true",
                   help="start an empty ledger on purpose (discards the live one)")
    args = parser.parse_args(argv)
    try:
        outcome = fetch(args.url, args.out, reset=args.reset)
    except (urllib.error.URLError, OSError, ValueError, LedgerError) as error:
        print(f"::error::hygiene ledger fetch failed ({error}); refusing to publish "
              "a board that would replace the live ledger", file=sys.stderr)
        return 1
    lines = len(read_ledger(args.out))
    print(f"hygiene ledger: {outcome} ({lines} day(s)) from {args.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

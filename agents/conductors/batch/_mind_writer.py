"""One Mind writer per shift (AUTONOMY.md, 2026-11-03) — the orchestrator's side.

Workers never commit to PyAutoMind. They describe each change as an *op file*
in the shift's `ledger/` directory (`bin/shift_ledger.py` writes them); the
orchestrator applies every pending op in a **temporary detached worktree** on
`origin/main`, commits once, and pushes. A rejected push means someone else
moved `main` (another session, the dashboard self-heal bot): the ops are
replayed on the new `origin/main` — a rebase of operations, not of diffs — at
most `PUSH_TRIES` times. The canonical checkout's working tree is never read
or written, nothing is reset, and nothing is forced.

Ops (one JSON object per file, applied in file-name order):

    {"op": "append",       "path": "active.md", "text": "..."}
    {"op": "write",        "path": "complete/2026/11/x.md", "text": "..."}   # must not exist
    {"op": "move",         "path": "draft/a/b/x.md", "to": "active/x.md"}
    {"op": "remove",       "path": "active/x.md"}
    {"op": "drop-section", "path": "active.md", "section": "task-name"}
    {"op": "table-append", "path": "autonomy_log.md", "heading": "## Unattended …", "row": "| … |"}
    {"op": "set-header",   "path": "draft/a/b/x.md", "key": "Verified", "value": "2026-11-12 abc123 (Repo)"}
    {"op": "jsonl-upsert", "path": "batches/pilot/pilot.jsonl", "key": "slot", "row": {...}}
    {"op": "table-upsert", "path": "batches/pilot/pilot.md", "key": "<slot>", "row": "| … |", "header": "…"}
    {"op": "record-key",   "path": "batches/<slot>.md", "key": "live", "value": "…"}

`jsonl-upsert` keeps one JSON line per `row[key]`: the line with that key is
replaced (its other fields kept), else the row is appended. `table-upsert`
does the same for a Markdown table row keyed by its first cell, keeping any
old cell where the new one is `?` (the human's cells), and writes `header`
first into a missing file. Both are how the shift watcher writes its one pilot
row per shift and amends it on a late arrival (PyAutoBrain#610).

`record-key` sets one top-level `- key: value` line of a batch record — the
key's own line replaced, else inserted after `- issue:` (else `- review-at:`).
The watcher writes the dashboard's `- live:` status line this way
(PyAutoBrain#622); a record no longer on main is skipped, like `set-header`.

`set-header` sets one `Key: value` line in a prompt's header block (replacing
the key's line if present) — how a shift worker records the premise check's
`Verified:` stamp (`batch premise --record`) without touching the file itself.

Every path must be *ledger* by PyAutoMind's own rule (`scripts/ledger_merge.py`
`is_ledger_path`, default deny), so a worker cannot route code through here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

OPS = ("append", "write", "move", "remove", "drop-section", "table-append",
       "set-header", "jsonl-upsert", "table-upsert", "record-key")
PUSH_TRIES = 3
LEDGER_DIR = "ledger"
COMMITTED_DIR = "committed"


class MindWriteError(RuntimeError):
    pass


def _ledger_merge(mind_repo: Path):
    """PyAutoMind's own `ledger_merge` module, from the checkout we write to.

    Compiled from source rather than imported: an import writes
    `scripts/__pycache__/` into the canonical checkout, and this module's
    promise is that the canonical working tree is never written."""
    path = Path(mind_repo) / "scripts" / "ledger_merge.py"
    if not path.is_file():
        raise MindWriteError(f"no scripts/ledger_merge.py under {mind_repo}")
    name = "_mind_ledger_merge"
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    sys.modules[name] = mod  # dataclasses and friends look the module up by name
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def validate_op(op: dict, lm) -> list[str]:
    """Problems with one op; empty when it may be applied."""
    errs = []
    kind = op.get("op")
    if kind not in OPS:
        return [f"op: {kind!r} is not one of {', '.join(OPS)}"]
    paths = [op.get("path")] + ([op.get("to")] if kind == "move" else [])
    for p in paths:
        if not isinstance(p, str) or not p:
            errs.append(f"{kind}: a path is missing")
        elif p.startswith("/") or not lm.is_ledger_path(p):
            errs.append(f"{kind}: {p} is not a ledger path (scripts/ledger_merge.py)")
    if kind in ("append", "write") and not isinstance(op.get("text"), str):
        errs.append(f"{kind}: text is missing")
    if kind == "drop-section":
        if not op.get("section"):
            errs.append("drop-section: section is missing")
        elif op.get("path") not in lm.ENTRY_MERGED_FILES:
            errs.append(f"drop-section: {op.get('path')} is not a `## slug` registry")
    if kind == "table-append":
        if not str(op.get("heading", "")).startswith("## "):
            errs.append("table-append: heading must be a `## ` line")
        row = op.get("row")
        if not isinstance(row, str) or not row.startswith("|") or "\n" in row:
            errs.append("table-append: row must be one `| … |` line")
    if kind == "jsonl-upsert":
        row, key = op.get("row"), op.get("key")
        if not str(op.get("path", "")).endswith(".jsonl"):
            errs.append("jsonl-upsert: path must be a .jsonl file")
        if not isinstance(key, str) or not isinstance(row, dict) \
                or not isinstance(row.get(key), str) or not row.get(key):
            errs.append("jsonl-upsert: row must be an object carrying its key")
    if kind == "table-upsert":
        row = op.get("row")
        if not str(op.get("path", "")).endswith(".md"):
            errs.append("table-upsert: path must be a .md file")
        if not isinstance(row, str) or not row.startswith("|") or "\n" in row:
            errs.append("table-upsert: row must be one `| … |` line")
        elif _cells(row)[0] != op.get("key"):
            errs.append("table-upsert: the row's first cell must be its key")
    if kind == "record-key":
        key, value, path = op.get("key"), op.get("value"), str(op.get("path", ""))
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", key):
            errs.append("record-key: key must be one lower-case record key")
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            errs.append("record-key: value must be one non-empty line")
        if not (path.startswith("batches/") and path.endswith(".md")):
            errs.append("record-key: path must be a batch record (batches/*.md)")
    if kind == "set-header":
        key, value = op.get("key"), op.get("value")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Z][A-Za-z-]*", key):
            errs.append("set-header: key must be one capitalised header word")
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            errs.append("set-header: value must be one non-empty line")
        if not str(op.get("path", "")).endswith(".md"):
            errs.append("set-header: path must be a prompt (.md)")
    return errs


def apply_op(tree: Path, op: dict, lm) -> str | None:
    """Apply one validated op inside `tree`; raises MindWriteError if it cannot.

    Returns a note when the op was deliberately skipped. Only `set-header`
    skips: it is a stamp, and a draft moved or retired on main since the
    check ran must not hold every other op of the shift pending for ever."""
    target = tree / op["path"]
    kind = op["op"]
    if kind == "append":
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        sep = "" if not old or old.endswith("\n") else "\n"
        target.write_text(old + sep + op["text"], encoding="utf-8")
    elif kind == "write":
        if target.exists():
            raise MindWriteError(f"write: {op['path']} already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op["text"], encoding="utf-8")
    elif kind == "move":
        dest = tree / op["to"]
        if not target.exists():
            raise MindWriteError(f"move: {op['path']} does not exist")
        if dest.exists():
            raise MindWriteError(f"move: {op['to']} already exists")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(tree, "mv", op["path"], op["to"])
    elif kind == "remove":
        if not target.exists():
            raise MindWriteError(f"remove: {op['path']} does not exist")
        _git(tree, "rm", "-q", op["path"])
    elif kind == "drop-section":
        preamble, entries = lm.split_entries(target.read_text(encoding="utf-8"))
        kept = [(s, b) for s, b in entries if s != f"## {op['section']}"]
        if len(kept) == len(entries):
            raise MindWriteError(f"drop-section: no `## {op['section']}` in {op['path']}")
        target.write_text(lm.join_entries(preamble, kept), encoding="utf-8")
    elif kind == "set-header":
        if not target.exists():
            return (f"set-header: {op['path']} is not on main (moved or retired "
                    f"since the check) — {op['key']}: skipped")
        target.write_text(set_header(target.read_text(encoding="utf-8"),
                                     op["key"], op["value"]), encoding="utf-8")
    elif kind == "record-key":
        if not target.exists():
            return f"record-key: {op['path']} is not on main — {op['key']}: skipped"
        target.write_text(record_key(target.read_text(encoding="utf-8"),
                                     op["key"], op["value"]), encoding="utf-8")
    elif kind == "table-append":
        target.write_text(table_append(target.read_text(encoding="utf-8")
                                       if target.exists() else "",
                                       op["heading"], op["row"]), encoding="utf-8")
    elif kind == "jsonl-upsert":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(jsonl_upsert(target.read_text(encoding="utf-8")
                                       if target.exists() else "",
                                       op["key"], op["row"]), encoding="utf-8")
    elif kind == "table-upsert":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(table_upsert(target.read_text(encoding="utf-8")
                                       if target.exists() else "",
                                       op["key"], op["row"], op.get("header", "")),
                          encoding="utf-8")


def record_key(text: str, key: str, value: str,
               after: tuple[str, ...] = ("issue", "review-at")) -> str:
    """`text` with one top-level `- key: value` line above the first `## `
    heading: the key's line replaced if present, else inserted after the
    first of `after` present, else after the title. Every other line is kept."""
    lines = text.split("\n")
    end = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    new = f"- {key}: {value}"
    for i in range(end):
        if lines[i].startswith(f"- {key}:"):
            lines[i] = new
            return "\n".join(lines)
    at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
    for anchor in after:
        hit = next((i for i in range(end) if lines[i].startswith(f"- {anchor}:")), None)
        if hit is not None:
            at = hit + 1
            break
    lines.insert(at, new)
    return "\n".join(lines)


def table_append(text: str, heading: str, row: str) -> str:
    """`row` inserted after the last table line under the `## ` heading that
    starts with `heading` — whatever follows that section stays where it is."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        raise MindWriteError(f"table-append: no heading {heading!r}")
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")),
               len(lines))
    rows = [i for i in range(start + 1, end) if lines[i].startswith("|")]
    if not rows:
        raise MindWriteError(f"table-append: no table under {heading!r}")
    lines.insert(rows[-1] + 1, row)
    return "\n".join(lines) + "\n"


def jsonl_upsert(text: str, key: str, row: dict) -> str:
    """`text` (JSON lines) with exactly one line whose `key` is `row[key]`."""
    out, hit = [], False
    for line in text.splitlines():
        try:
            old = json.loads(line)
        except ValueError:
            old = None
        if isinstance(old, dict) and old.get(key) == row[key]:
            if not hit:
                out.append(json.dumps({**old, **row}, sort_keys=True))
                hit = True
            continue  # a duplicate from before: dropped, one line per key
        out.append(line)
    if not hit:
        out.append(json.dumps(row, sort_keys=True))
    return "\n".join(out) + "\n"


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table_upsert(text: str, key: str, row: str, header: str = "") -> str:
    """`text` with the table row whose first cell is `key` replaced by `row`
    (an old cell kept wherever the new one is `?`), else `row` appended."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and _cells(line)[0] == key:
            old, new = _cells(line), _cells(row)
            if len(old) == len(new):
                new = [o if n == "?" else n for o, n in zip(old, new)]
            lines[i] = "| " + " | ".join(new) + " |"
            return "\n".join(lines) + "\n"
    if not text.strip():
        return header + row + "\n"
    return text + ("" if text.endswith("\n") else "\n") + row + "\n"


_HEADER_LINE_RE = re.compile(r"^[A-Z][A-Za-z-]*:(\s|$)")


def header_span(lines: list[str]) -> tuple[int, int] | None:
    """`(start, end)` of a prompt's header block: the contiguous `Key: value`
    lines (with their `- item` continuations) below the `# ` title, ending at
    the first blank line. None when the prompt has no header block."""
    i = 0
    while i < len(lines) and not _HEADER_LINE_RE.match(lines[i]):
        if i > 6 and lines[i].strip() and not lines[i].startswith("#"):
            return None  # prose before any header: there is no block
        i += 1
    if i >= len(lines):
        return None
    end = i
    while end < len(lines) and lines[end].strip() and (
            _HEADER_LINE_RE.match(lines[end]) or lines[end].startswith(("- ", "  "))):
        end += 1
    return i, end


def set_header(text: str, key: str, value: str,
               after: tuple[str, ...] = ("Unattended", "Review-minutes")) -> str:
    """`text` with `key: value` in its header block — the key's own line
    replaced if present, else inserted after the first of `after` present,
    else at the end of the block. A prompt with no block gets one under its
    title. Every other line is left byte-for-byte as it was."""
    lines = text.split("\n")
    new = f"{key}: {value}"
    span = header_span(lines)
    if span is None:
        at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)
        return "\n".join(lines[:at] + ([""] if at else []) + [new]
                         + ([""] if at < len(lines) and lines[at].strip() else [])
                         + lines[at:])
    start, end = span
    for i in range(start, end):
        if lines[i].lower().startswith(key.lower() + ":"):
            lines[i] = new
            return "\n".join(lines)
    at = end
    for anchor in after:
        hit = next((i for i in range(start, end)
                    if lines[i].lower().startswith(anchor.lower() + ":")), None)
        if hit is not None:
            at = hit + 1
            while at < end and lines[at].startswith(("- ", "  ")):
                at += 1
            break
    lines.insert(at, new)
    return "\n".join(lines)


def _git(cwd: Path, *args, check=True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise MindWriteError(f"git {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
    return res


def queue_op(ledger_dir: Path, op: dict) -> Path:
    """Write one op file into a ledger directory, atomically, in arrival order."""
    import os
    import time
    d = Path(ledger_dir)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{os.getpid()}-{op['op']}.json"
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(op, indent=2), encoding="utf-8")
    tmp.replace(d / name)
    return d / name


def pending_ops(slot: Path) -> list[Path]:
    d = Path(slot) / LEDGER_DIR
    return sorted(f for f in d.glob("*.json")) if d.is_dir() else []


def commit_ledger(slot: Path, mind_repo: Path, message: str,
                  remote: str = "origin", branch: str = "main") -> dict:
    """Commit every pending op in `<slot>/ledger/` to PyAutoMind as one commit.

    Returns {"committed": sha | None, "ops": n, "tries": k}. Ops that fail
    validation are refused before anything is touched; an op that cannot apply
    on the current `origin/main` stops the run and stays pending.
    """
    mind_repo = Path(mind_repo)
    files = pending_ops(slot)
    if not files:
        return {"committed": None, "ops": 0, "tries": 0}
    lm = _ledger_merge(mind_repo)
    ops = []
    for f in files:
        try:
            op = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            raise MindWriteError(f"{f.name}: not JSON ({e})") from e
        errs = validate_op(op, lm)
        if errs:
            raise MindWriteError(f"{f.name}: " + "; ".join(errs))
        ops.append(op)

    for attempt in range(1, PUSH_TRIES + 1):
        _git(mind_repo, "fetch", "-q", remote, branch)
        tmp = Path(tempfile.mkdtemp(prefix="mind-writer-"))
        tree = tmp / "tree"
        try:
            _git(mind_repo, "worktree", "add", "-q", "--detach", str(tree),
                 f"{remote}/{branch}")
            notes = [n for op in ops if (n := apply_op(tree, op, lm))]
            for n in notes:
                print(f"mind-writer: {n}", file=sys.stderr)
            _git(tree, "add", "-A")
            if not _git(tree, "status", "--porcelain").stdout.strip():
                sha = None  # every op was already true on main
            else:
                _git(tree, "commit", "-q", "-m", message)
                sha = _git(tree, "rev-parse", "HEAD").stdout.strip()
                pushed = _git(tree, "push", "-q", remote, f"HEAD:{branch}", check=False)
                if pushed.returncode != 0:
                    continue  # main moved: replay the ops on the new origin/main
            done = Path(slot) / LEDGER_DIR / COMMITTED_DIR
            done.mkdir(parents=True, exist_ok=True)
            for f in files:
                f.replace(done / f.name)
            return {"committed": sha, "ops": len(ops), "tries": attempt,
                    "skipped": notes}
        finally:
            # Our own throwaway tree. A failed apply can leave it dirty, so
            # delete the directory and prune the registration, no force flag.
            if _git(mind_repo, "worktree", "remove", str(tree), check=False).returncode:
                shutil.rmtree(tmp, ignore_errors=True)
                _git(mind_repo, "worktree", "prune", check=False)
            shutil.rmtree(tmp, ignore_errors=True)
    raise MindWriteError(f"push rejected {PUSH_TRIES} times; ops left pending")

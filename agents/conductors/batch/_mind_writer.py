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

One bad op never strands the rest (PyAutoBrain#632, B1 — a re-dispatched
worker re-queued its claim's `draft→active` move and every later op of the
shift stayed pending):

- a *repeat* is a skipped note — only a re-dispatched task's own claim (the
  caller names those tasks, `own_tasks`) whose earlier op this shift already
  committed (`ledger/committed/`) and whose content on main matches it: a
  `move` whose source is gone and destination present, a `## slug` section an
  `active.md` append already finds there;
- the same shape from anyone else is a *conflict*, set aside loudly;
- any other worker op that fails validation or cannot apply is *set aside* —
  moved to `ledger/set_aside/` with its reason — and the rest still commit;
- a *critical* op (`CRITICAL_OPS`: the digest and late lines on a batch
  record, the pilot row, the live line, a stage-2 row) is never set aside: it
  is *held* pending and retried on every tick.

Every note, set-aside, conflict and first hold is appended to
`ledger/report.jsonl`, which the digest and the late sweep read: none of them
lives only in `tick.log`. Only a push rejected `PUSH_TRIES` times leaves every
op pending.
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
#: Ops that could not apply (or were invalid), kept for the human with their
#: reason (`<op file>.why`) — never retried, never blocking the others.
SET_ASIDE_DIR = "set_aside"
#: What the writer did besides commit, one JSON line each (#632 review).
REPORT_FILE = "report.jsonl"
#: Op kinds only the watcher writes, and an `append` to a batch record: the
#: shift's own record (digest, late lines), pilot row, live line and stage-2
#: rows. Never set aside — held pending and retried (#632 review).
CRITICAL_KINDS = ("record-key", "jsonl-upsert", "table-upsert", "table-append")


def is_critical(op) -> bool:
    return isinstance(op, dict) and (
        op.get("op") in CRITICAL_KINDS
        or (op.get("op") == "append" and str(op.get("path", "")).startswith("batches/")))


class ConflictError(RuntimeError):
    """A claim that looks already done, but not by this shift's own task."""


class MindWriteError(RuntimeError):
    pass


def fetch(mind_repo: Path, remote: str = "origin", branch: str = "main") -> None:
    """The writer's one network read: `git fetch` of Mind `main` (refs and
    objects only — the working tree is never touched). The watcher also calls
    it once per shift before its first plan (#632, F4)."""
    _git(Path(mind_repo), "fetch", "-q", remote, branch)


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
        if "unique" in op and (not isinstance(op["unique"], str) or not op["unique"]
                               or "\n" in op["unique"]):
            errs.append("table-append: unique must be one non-empty line")
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


def apply_op(tree: Path, op: dict, lm, ctx: dict | None = None) -> str | None:
    """Apply one validated op inside `tree`; raises MindWriteError if it cannot,
    ConflictError for a claim that is already on main but not this shift's own.

    Returns a note when the op was deliberately skipped: a `set-header` or
    `record-key` on a file no longer on main (a stamp must not hold the shift),
    a `table-append` whose `unique` key a row already carries, and a
    re-dispatched task's own repeat of a claim this shift already committed
    (`ctx`: {"own": task names, "prior": this shift's committed ops}, #632)."""
    target = tree / op["path"]
    kind = op["op"]
    ctx = ctx or {"own": set(), "prior": []}
    if kind == "append":
        target.parent.mkdir(parents=True, exist_ok=True)
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        text, note = op["text"], None
        if op["path"] in getattr(lm, "ENTRY_MERGED_FILES", ()) and old:
            text, note = _new_sections(old, text, op["path"], lm, ctx)
            if not text:
                return note
        sep = "" if not old or old.endswith("\n") else "\n"
        target.write_text(old + sep + text, encoding="utf-8")
        return note
    elif kind == "write":
        if target.exists():
            raise MindWriteError(f"write: {op['path']} already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op["text"], encoding="utf-8")
    elif kind == "move":
        dest = tree / op["to"]
        if not target.exists() and dest.exists():
            # A re-dispatched worker re-queues its predecessor's claim (#632):
            # a repeat only when this shift itself committed that very move.
            task = Path(op["path"]).stem
            if task in ctx["own"] and any(
                    p.get("op") == "move" and p.get("path") == op["path"]
                    and p.get("to") == op["to"] for p in ctx["prior"]):
                return (f"move: {op['path']} → {op['to']} is already on main from this "
                        f"shift's own claim (re-dispatch of {task}) — skipped")
            raise ConflictError(f"move: {op['path']} is gone and {op['to']} exists on "
                                f"main, not from this shift's own claim of {task} — conflict")
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
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        if op.get("unique") and _section_has(text, op["heading"], op["unique"]):
            # A row re-queued after a crash between queue and counters (#632).
            return f"table-append: a row with {op['unique']!r} is already there — skipped"
        target.write_text(table_append(text, op["heading"], op["row"]), encoding="utf-8")
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


def _new_sections(old: str, text: str, path: str, lm,
                  ctx: dict) -> tuple[str, str | None]:
    """`text` without the `## slug` sections `old` already has, and a note
    naming them; ("", note) when every section is already there. Text with
    no `## ` section is appended as it is. A section already there is a
    repeat only when its task is a re-dispatch of this shift (`ctx["own"]`)
    and main's section is exactly the one this shift committed before
    (`ctx["prior"]`); any other is a ConflictError (#632 review)."""
    pre, entries = lm.split_entries(text)
    if not entries:
        return text, None
    have = dict(lm.split_entries(old)[1])
    dup = [slug for slug, _ in entries if slug in have]
    if not dup:
        return text, None
    ours = {}
    for p in ctx["prior"]:
        if p.get("op") == "append" and p.get("path") == path:
            ours.update(lm.split_entries(p.get("text") or "")[1])
    bad = [slug for slug in dup if slug[3:].strip() not in ctx["own"]
           or ours.get(slug) != have[slug]]
    if bad:
        raise ConflictError(f"append: {', '.join(bad)} already in {path}, not this "
                            "shift's own claim — conflict")
    note = (f"append: {', '.join(dup)} already in {path} from this shift's own claim "
            "— skipped")
    rest = [body for slug, body in entries if slug not in have]
    return (pre + "".join(rest) if rest else ""), note


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


def _section_has(text: str, heading: str, needle: str) -> bool:
    """Whether a table row under the `## ` heading starting `heading` holds `needle`."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    if start is None:
        return False
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if ln.startswith("|") and needle in ln:
            return True
    return False


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


def _set_aside(slot: Path, f: Path, why: str) -> dict:
    """Move one op file out of the way with its reason; returns its record."""
    d = Path(slot) / LEDGER_DIR / SET_ASIDE_DIR
    d.mkdir(parents=True, exist_ok=True)
    op = _op_of(f)
    (d / (f.name + ".why")).write_text(why + "\n", encoding="utf-8")
    f.replace(d / f.name)
    return {"file": f.name, "op": op.get("op"), "path": op.get("path"), "why": why}


def _op_of(f: Path) -> dict:
    try:
        op = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return op if isinstance(op, dict) else {}


def report(slot: Path) -> list[dict]:
    """Every entry of `ledger/report.jsonl`, oldest first: {kind: skipped |
    set-aside | conflict | held, file, op, path, why}."""
    f = Path(slot) / LEDGER_DIR / REPORT_FILE
    out = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.is_file() else ()):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _report(slot: Path, entries: list[dict]) -> None:
    if not entries:
        return
    f = Path(slot) / LEDGER_DIR / REPORT_FILE
    with open(f, "a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, sort_keys=True) + "\n")


def committed_ops(slot: Path) -> list[dict]:
    """The ops this shift has already committed (`ledger/committed/`)."""
    d = Path(slot) / LEDGER_DIR / COMMITTED_DIR
    return [op for f in sorted(d.glob("*.json"))
            if (op := _op_of(f))] if d.is_dir() else []


def commit_ledger(slot: Path, mind_repo: Path, message: str,
                  remote: str = "origin", branch: str = "main",
                  own_tasks=()) -> dict:
    """Commit every pending op in `<slot>/ledger/` to PyAutoMind as one commit.

    Returns {"committed": sha | None, "ops": n, "tries": k, "skipped": notes,
    "set_aside": [{file, op, path, why, kind}], "held": [...]}. `own_tasks`
    are the tasks this shift re-dispatched: only their repeated claims may be
    skipped as already done (#632 review). A worker op that is invalid or
    cannot apply is set aside (a claim already on main from someone else as a
    `conflict`); a critical op is held pending instead. Only a push rejected
    `PUSH_TRIES` times raises, with every op left pending.
    """
    mind_repo = Path(mind_repo)
    files = pending_ops(slot)
    if not files:
        return {"committed": None, "ops": 0, "tries": 0}
    lm = _ledger_merge(mind_repo)
    ctx = {"own": set(own_tasks), "prior": committed_ops(slot)}
    ops, invalid, unready = [], {}, {}
    for f in files:
        try:
            op = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            invalid[f] = ("set-aside", f"not JSON ({e})")
            continue
        errs = validate_op(op, lm) if isinstance(op, dict) else ["not a JSON object"]
        if errs:
            (unready if is_critical(op) else invalid)[f] = (
                "held" if is_critical(op) else "set-aside", "; ".join(errs))
            continue
        ops.append((f, op))
    seen_held = {(e.get("file"), e.get("kind")) for e in report(slot)}

    for attempt in range(1, PUSH_TRIES + 1):
        fetch(mind_repo, remote, branch)
        tmp = Path(tempfile.mkdtemp(prefix="mind-writer-"))
        tree = tmp / "tree"
        try:
            _git(mind_repo, "worktree", "add", "-q", "--detach", str(tree),
                 f"{remote}/{branch}")
            notes, failed, held = [], dict(invalid), dict(unready)
            for f, op in ops:
                try:
                    note = apply_op(tree, op, lm, ctx)
                except ConflictError as e:
                    (held if is_critical(op) else failed)[f] = (
                        "held" if is_critical(op) else "conflict", str(e))
                    continue
                except (MindWriteError, OSError, KeyError, TypeError, ValueError) as e:
                    (held if is_critical(op) else failed)[f] = (
                        "held" if is_critical(op) else "set-aside",
                        str(e) or type(e).__name__)
                    continue
                if note:
                    notes.append((f, op, note))
            _git(tree, "add", "-A")
            if not _git(tree, "status", "--porcelain").stdout.strip():
                sha = None  # every op was already true on main (or set aside)
            else:
                _git(tree, "commit", "-q", "-m", message)
                sha = _git(tree, "rev-parse", "HEAD").stdout.strip()
                pushed = _git(tree, "push", "-q", remote, f"HEAD:{branch}", check=False)
                if pushed.returncode != 0:
                    continue  # main moved: replay the ops on the new origin/main
            aside = []
            for f, (kind, why) in sorted(failed.items()):
                aside.append({**_set_aside(slot, f, why), "kind": kind})
            held_out = [{"file": f.name, "op": _op_of(f).get("op"),
                         "path": _op_of(f).get("path"), "why": why, "kind": "held"}
                        for f, (_k, why) in sorted(held.items())]
            _report(slot, [{"kind": "skipped", "file": f.name, "op": op.get("op"),
                            "path": op.get("path"), "why": n} for f, op, n in notes]
                    + aside + [h for h in held_out if (h["file"], "held") not in seen_held])
            for a in aside + held_out:
                print(f"mind-writer: {a['kind']} {a['file']}: {a['why']}", file=sys.stderr)
            done = Path(slot) / LEDGER_DIR / COMMITTED_DIR
            done.mkdir(parents=True, exist_ok=True)
            for f in files:
                if f not in failed and f not in held:
                    f.replace(done / f.name)
            return {"committed": sha, "ops": len(files) - len(failed) - len(held),
                    "tries": attempt, "skipped": [n for _f, _o, n in notes],
                    "set_aside": aside, "held": held_out}
        finally:
            # Our own throwaway tree. A failed apply can leave it dirty, so
            # delete the directory and prune the registration, no force flag.
            if _git(mind_repo, "worktree", "remove", str(tree), check=False).returncode:
                shutil.rmtree(tmp, ignore_errors=True)
                _git(mind_repo, "worktree", "prune", check=False)
            shutil.rmtree(tmp, ignore_errors=True)
    raise MindWriteError(f"push rejected {PUSH_TRIES} times; ops left pending")

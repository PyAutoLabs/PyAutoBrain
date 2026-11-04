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

Every path must be *ledger* by PyAutoMind's own rule (`scripts/ledger_merge.py`
`is_ledger_path`, default deny), so a worker cannot route code through here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

OPS = ("append", "write", "move", "remove", "drop-section")
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
    return errs


def apply_op(tree: Path, op: dict, lm) -> None:
    """Apply one validated op inside `tree`; raises MindWriteError if it cannot."""
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
            for op in ops:
                apply_op(tree, op, lm)
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
            return {"committed": sha, "ops": len(ops), "tries": attempt}
        finally:
            # Our own throwaway tree. A failed apply can leave it dirty, so
            # delete the directory and prune the registration, no force flag.
            if _git(mind_repo, "worktree", "remove", str(tree), check=False).returncode:
                shutil.rmtree(tmp, ignore_errors=True)
                _git(mind_repo, "worktree", "prune", check=False)
            shutil.rmtree(tmp, ignore_errors=True)
    raise MindWriteError(f"push rejected {PUSH_TRIES} times; ops left pending")

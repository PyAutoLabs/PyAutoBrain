#!/usr/bin/env python3
"""Hand a PyAutoMind change to the shift orchestrator instead of committing it.

A shift worker never commits to PyAutoMind (AUTONOMY.md "One Mind writer per
shift"); it writes one op file per change here and the orchestrator commits
them all from a temporary worktree. Paths are PyAutoMind-relative and must be
ledger paths (`draft/`, `active/`, `complete/`, `batches/`, the registries).
A shift worker names its task on every op (`--task`): a task's ops land
together, and its completion record is held while any of them is set aside.

    shift_ledger.py --task T append  active.md --text-file entry.md
    shift_ledger.py --task T write   complete/2026/11/x.md --text-file record.md   # creates only
    shift_ledger.py --task T edit    draft/feature/x/y.md --old-file was.txt --new-file now.txt
    shift_ledger.py --task T move    draft/feature/x/y.md active/y.md
    shift_ledger.py --task T remove  active/y.md
    shift_ledger.py --task T drop-section active.md my-task
    shift_ledger.py --task T set-header draft/x/y.md Verified --text "2026-11-12 abc1234 (Repo)"
    shift_ledger.py --task T table-append autonomy_log.md "## Calibration runs" --text "| … |"
    shift_ledger.py --task T queue-retire queue.md y.md --text "<PR url> → complete/2026/11/y.md (2026-11-14)"

`write` refuses a path that already exists; `edit` replaces `--old`, which must
appear exactly once in the file as it is on Mind origin/main, with `--new`.
Queue edits first and the complete record last. Each op is checked against
Mind `origin/main` before it is queued (`--mind`, else `$PYAUTO_MIND`, else
the PyAutoMind checkout beside this Brain); a refused op is not queued.

The ledger directory is `$PYAUTO_SHIFT_LEDGER_DIR` (set for every worker).
"""
import argparse
import os
import sys
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BATCH))
import _mind_writer as mw  # noqa: E402


def _mind(given) -> Path | None:
    """The Mind checkout to check ops against: `--mind`, `$PYAUTO_MIND`, else
    the PyAutoMind beside this Brain (organs layout) when it has the script."""
    if given:
        return Path(given)
    sibling = Path(__file__).resolve().parents[2] / "PyAutoMind"
    return sibling if (sibling / "scripts" / "ledger_merge.py").is_file() else None


def _text(inline, path):
    return path.read_text(encoding="utf-8") if path else inline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="shift_ledger", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=mw.OPS)
    ap.add_argument("path")
    ap.add_argument("arg", nargs="?", help="move: destination; drop-section: section; "
                         "set-header: the header key; queue-retire: the prompt file name; "
                         "table-append: the `## ` heading of the table")
    ap.add_argument("--task", help="the task this op belongs to (required for a shift worker)")
    ap.add_argument("--text-file", type=Path)
    ap.add_argument("--text")
    ap.add_argument("--old", help="edit: the exact text to replace (must appear once)")
    ap.add_argument("--old-file", type=Path)
    ap.add_argument("--new", help="edit: the text to put in its place")
    ap.add_argument("--new-file", type=Path)
    ap.add_argument("--unique", nargs="?", const=True,
                    help="table-append: skip if a row under the heading already holds "
                         "this text (bare: the row itself)")
    ap.add_argument("--mind", type=Path, default=os.environ.get("PYAUTO_MIND"),
                    help="PyAutoMind checkout to validate paths against (read only)")
    a = ap.parse_args(argv)
    ledger = os.environ.get("PYAUTO_SHIFT_LEDGER_DIR")
    if not ledger:
        print("shift_ledger: PYAUTO_SHIFT_LEDGER_DIR is not set — this is for "
              "shift workers only", file=sys.stderr)
        return 2
    if not a.task and os.environ.get("PYAUTO_SHIFT_WORKER") == "1":
        print("shift_ledger: refused — a shift worker names its task on every op: "
              f"`shift_ledger.py --task <your task> {a.op} {a.path} …` (the task "
              "name your brief gave you), so its ops land together", file=sys.stderr)
        return 2
    op = {"op": a.op, "path": a.path}
    if a.task:
        op["task"] = a.task
    if a.op == "move":
        op["to"] = a.arg
    if a.op == "drop-section":
        op["section"] = a.arg
    if a.op == "set-header":
        op["key"], op["value"] = a.arg, (a.text or "")
    if a.op == "queue-retire":
        op["prompt"], op["shipped_as"] = a.arg, (a.text or "")
    if a.op in ("append", "write"):
        op["text"] = _text(a.text or "", a.text_file)
    if a.op == "edit":
        op["old"], op["new"] = _text(a.old, a.old_file), _text(a.new, a.new_file)
    if a.op == "table-append":
        op["heading"] = a.arg
        op["row"] = (_text(a.text, a.text_file) or "").rstrip("\n")
        if a.unique:
            op["unique"] = op["row"] if a.unique is True else a.unique
    mind = _mind(a.mind)
    if mind:
        errs = mw.validate_op(op, mw._ledger_merge(mind))
        errs = errs or mw.queue_refusals(mind, op, Path(ledger))
        if errs:
            print("shift_ledger: refused — " + "; ".join(errs), file=sys.stderr)
            return 1
    queued = mw.queue_op(Path(ledger), op)
    print(f"shift_ledger: queued {a.op} {a.path} → {queued}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

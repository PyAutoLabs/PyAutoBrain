#!/usr/bin/env python3
"""Hand a PyAutoMind change to the shift orchestrator instead of committing it.

A shift worker never commits to PyAutoMind (AUTONOMY.md "One Mind writer per
shift"); it writes one op file per change here and the orchestrator commits
them all from a temporary worktree. Paths are PyAutoMind-relative and must be
ledger paths (`draft/`, `active/`, `complete/`, `batches/`, the registries).

    shift_ledger.py append  active.md --text-file entry.md
    shift_ledger.py write   complete/2026/11/x.md --text-file record.md
    shift_ledger.py move    draft/feature/x/y.md active/y.md
    shift_ledger.py remove  active/y.md
    shift_ledger.py drop-section active.md my-task

The ledger directory is `$PYAUTO_SHIFT_LEDGER_DIR` (set for every worker).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BATCH))
import _mind_writer as mw  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="shift_ledger", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("op", choices=mw.OPS)
    ap.add_argument("path")
    ap.add_argument("arg", nargs="?", help="move: destination; drop-section: section")
    ap.add_argument("--text-file", type=Path)
    ap.add_argument("--text")
    ap.add_argument("--mind", type=Path, default=os.environ.get("PYAUTO_MIND"),
                    help="PyAutoMind checkout to validate paths against (read only)")
    a = ap.parse_args(argv)
    ledger = os.environ.get("PYAUTO_SHIFT_LEDGER_DIR")
    if not ledger:
        print("shift_ledger: PYAUTO_SHIFT_LEDGER_DIR is not set — this is for "
              "shift workers only", file=sys.stderr)
        return 2
    op = {"op": a.op, "path": a.path}
    if a.op == "move":
        op["to"] = a.arg
    if a.op == "drop-section":
        op["section"] = a.arg
    if a.op in ("append", "write"):
        op["text"] = a.text_file.read_text(encoding="utf-8") if a.text_file else (a.text or "")
    if a.mind:
        errs = mw.validate_op(op, mw._ledger_merge(a.mind))
        if errs:
            print("shift_ledger: refused — " + "; ".join(errs), file=sys.stderr)
            return 1
    d = Path(ledger)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{os.getpid()}-{a.op}.json"
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(op, indent=2), encoding="utf-8")
    tmp.replace(d / name)
    print(f"shift_ledger: queued {a.op} {a.path} → {d / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

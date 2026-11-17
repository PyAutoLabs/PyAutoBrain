#!/usr/bin/env python3
"""bin/merge_slot.py — take, release or show a shift's merge slot (PyAutoBrain#661).

    pyauto-brain merge-slot take <pr>
    pyauto-brain merge-slot release <pr> [--why <text>]
    pyauto-brain merge-slot status [<pr>]

WHY. AUTONOMY.md "`notify` merges under `--auto` and inside a shift —
2026-11-17" (ruling R3): inside a shift every merge counts against the brief's
`merge-cap:`. A worker runs `take` as its own bare call, then — only on exit 0 —
a bare `gh pr merge`. This never wraps the merge: the permission layer must
still see exactly one `gh pr merge` call.

WHERE. A shift worker's environment carries `PYAUTO_SHIFT_WORKER=1` and
`PYAUTO_SHIFT_LEDGER_DIR` (`_orchestrator.worker_env`); the shift's slot
directory is that ledger directory's parent, and the counter is its
`merge_slots.json` (`agents/conductors/batch/_merge_slots.py`).

EXIT. 0 = the slot is taken (or already held for this PR), or this is not a
shift, so nothing is counted; 1 = refused (no slot left, the shift is paused,
or no cap published) — do not merge, leave the PR for `/prm`; 2 = cannot tell
(the slot directory or its file cannot be read) — do not merge either.
`release` exits 0 when it freed this caller's slot, 1 when there was none to
free. `status` prints the count and exits 0.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BATCH))
import _merge_slots  # noqa: E402

#: Every worker and close-out session takes as one holder class; the watcher
#: takes as `_merge_slots.WATCHER`, so no session can free a close-out's slot.
WORKER = "worker"


def _slot() -> Path | None:
    """The shift slot directory, or None outside a shift."""
    ledger = os.environ.get("PYAUTO_SHIFT_LEDGER_DIR", "").strip()
    if not os.environ.get("PYAUTO_SHIFT_WORKER") or not ledger:
        return None
    return Path(ledger).parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pyauto-brain merge-slot",
                                 description="A shift's merge slot (AUTONOMY.md ruling R3).")
    ap.add_argument("action", choices=("take", "release", "status"))
    ap.add_argument("pr", nargs="?", default="", help="the PR URL")
    ap.add_argument("--task", default="", help="the task slug, recorded with the slot")
    ap.add_argument("--why", default="", help="release: why the slot is freed")
    args = ap.parse_args(argv)
    if args.action in ("take", "release") and not args.pr:
        ap.error(f"{args.action} needs a PR URL")

    slot = _slot()
    if slot is None:
        print("not in a shift (no PYAUTO_SHIFT_WORKER / PYAUTO_SHIFT_LEDGER_DIR): "
              "no merge slot is counted")
        return 0
    task = args.task or os.environ.get("PYAUTO_SHIFT_TASK", "")
    try:
        if args.action == "take":
            ok, why = _merge_slots.take(slot, args.pr, WORKER, task)
            print(("taken: " if ok else "refused: ") + why)
            return 0 if ok else 1
        if args.action == "release":
            freed = _merge_slots.release(slot, args.pr, WORKER, args.why)
            print(f"released {args.pr}" if freed
                  else f"no merge slot of yours held for {args.pr}")
            return 0 if freed else 1
        data = _merge_slots.state(slot)
        cap = data.get("cap")
        line = (f"{len(data['slots'])} of merge-cap {cap if cap is not None else '(none published)'}"
                + (" — paused" if data.get("paused") else ""))
        print(line)
        if args.pr:
            held = data["slots"].get(args.pr)
            print(f"{args.pr}: " + (f"held by {held.get('by', '?')}" if held
                                    else _merge_slots.why_unmerged(slot, args.pr)
                                    or "no slot, no refusal recorded"))
        return 0
    except (_merge_slots.MergeSlotError, OSError) as e:
        print(f"cannot tell: {e} — do not merge; leave the PR for /prm")
        return 2


if __name__ == "__main__":
    sys.exit(main())

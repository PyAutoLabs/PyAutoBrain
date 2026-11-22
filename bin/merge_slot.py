#!/usr/bin/env python3
"""bin/merge_slot.py — take, release or show a shift's merge slot.

    pyauto-brain merge-slot take <pr-url> --task <slug>
    pyauto-brain merge-slot release <pr-url> --task <slug> [--why <text>]
    pyauto-brain merge-slot status [<pr-url>]

`<pr-url>` is `https://github.com/<owner>/<repo>/pull/<n>` (a trailing `/`,
`/files` or `#…` is dropped); anything else cannot be told apart from another
repo's PR of the same number and exits 2. `--task` (or `PYAUTO_SHIFT_TASK`) is
required for a take in a shift: a held slot answers yes again only to the same
task — the worker that took it, or the close-out session of the task the
watcher took it for (before a branch update). A merge close-out session takes
its own slot here as a bare call immediately before its merge.

WHY. AUTONOMY.md "`notify` merges under `--auto` and inside a shift": inside a
shift every merge counts against the brief's
`merge-cap:`. A worker runs `take` as its own bare call, then — only on exit 0 —
a bare `gh pr merge`. This never wraps the merge: the permission layer must
still see exactly one `gh pr merge` call.

WHERE. A shift worker's environment carries `PYAUTO_SHIFT_WORKER=1` and
`PYAUTO_SHIFT_LEDGER_DIR` (`_orchestrator.worker_env`); the shift's slot
directory is that ledger directory's parent, and the counter is its
`merge_slots.json` (`agents/conductors/batch/_merge_slots.py`).

EXIT. 0 = the slot is taken (or already held for this PR and task), or this
is not a shift, so nothing is counted; 1 = refused (no slot left, the shift is
paused, no cap published, the PR's slot is another task's, or an earlier PR of
the shift on the same library is still open: merge order) — do not merge,
leave the PR for `/prm` or the close-out; 2 = cannot tell (not a PR URL, no task named, or the
slot directory or its file cannot be read) — do not merge either.
`release` (task required, as for `take`) exits 0 when it freed this task's
slot, 1 when there was none to free (the holder is named). `status` prints the
count and exits 0.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BATCH = Path(__file__).resolve().parents[1] / "agents" / "conductors" / "batch"
sys.path.insert(0, str(BATCH))
import _merge_slots  # noqa: E402

#: The take's message when an earlier PR of the shift must merge first.
ORDER_REFUSAL = ("{blockers} of this shift on the same library is still open and merges "
                 "first — do not merge; end at PR-open (list the PR without `merged`): the "
                 "close-out updates it from main and merges it in order")


def _order_blockers(slot: Path, pr: str) -> list[str]:
    """The earlier shift PRs this in-turn merge would jump."""
    brain = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(brain / "agents" / "faculties" / "sizing"))
    import _orchestrator  # noqa: E402 — deferred: only a take reads the order
    return _orchestrator.in_turn_merge_blockers(slot, pr)

#: Every worker and close-out session takes as one holder class; the watcher
#: takes as `_merge_slots.WATCHER` (before a branch-update session), so no
#: session can free a slot the watcher holds. A merge close-out takes its own
#: slot here, immediately before its merge.
WORKER = _merge_slots.SESSION


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
    if args.pr and _merge_slots.pr_key(args.pr) is None:
        if _slot() is None and args.action == "take":
            print("not in a shift (no PYAUTO_SHIFT_WORKER / PYAUTO_SHIFT_LEDGER_DIR): "
                  "no merge slot is counted")
            return 0
        print(f"cannot tell: {args.pr!r} is not a https://github.com/<owner>/<repo>/pull/<n> "
              "URL — do not merge; leave the PR for /prm")
        return 2

    slot = _slot()
    if slot is None:
        print("not in a shift (no PYAUTO_SHIFT_WORKER / PYAUTO_SHIFT_LEDGER_DIR): "
              "no merge slot is counted")
        return 0
    task = args.task or os.environ.get("PYAUTO_SHIFT_TASK", "")
    if args.action in ("take", "release") and not task:
        print(f"cannot tell: a {args.action} in a shift names its task (--task <slug>) — "
              "do not merge; leave the PR for /prm")
        return 2
    try:
        if args.action == "take":
            # Merge order: an earlier PR of this shift on the same library
            # merges first, whatever path this PR would merge by.
            try:
                blockers = _order_blockers(slot, args.pr)
            except (OSError, ValueError) as e:
                print(f"cannot tell the merge order: {e} — do not merge; leave the PR for /prm")
                return 2
            if blockers:
                print("refused: " + ORDER_REFUSAL.format(blockers=", ".join(blockers)))
                return 1
            ok, why = _merge_slots.take(slot, args.pr, WORKER, task)
            print(("taken: " if ok else "refused: ") + why)
            return 0 if ok else 1
        if args.action == "release":
            freed = _merge_slots.release(slot, args.pr, WORKER, args.why, task=task)
            if freed:
                print(f"released {args.pr}")
                return 0
            held = _merge_slots.state(slot)["slots"].get(_merge_slots.pr_key(args.pr))
            print(f"no merge slot of task {task} held for {args.pr}"
                  + (f" — it is held by {held.get('by', '?')} for task {held.get('task') or '?'}"
                     if held else ""))
            return 1
        data = _merge_slots.state(slot)
        cap = data.get("cap")
        line = (f"{len(data['slots'])} of merge-cap {cap if cap is not None else '(none published)'}"
                + (" — paused" if data.get("paused") else ""))
        print(line)
        if args.pr:
            key = _merge_slots.pr_key(args.pr)
            held = data["slots"].get(key)
            print(f"{key}: " + (f"held by {held.get('by', '?')} for task {held.get('task') or '?'}"
                                if held
                                    else _merge_slots.why_unmerged(slot, args.pr)
                                    or "no slot, no refusal recorded"))
        return 0
    except (_merge_slots.MergeSlotError, OSError) as e:
        print(f"cannot tell: {e} — do not merge; leave the PR for /prm")
        return 2


if __name__ == "__main__":
    sys.exit(main())

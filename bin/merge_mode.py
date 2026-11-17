#!/usr/bin/env python3
"""bin/merge_mode.py — one prompt's effective level and merge mode, one line
(PyAutoBrain#661).

    pyauto-brain merge-mode <prompt> [--auto] [--in-shift] [--mind <root>]

prints exactly

    effective level: <level>; merge mode: <mode>

WHY. Shift 2026-11-16-pm: two workers on the same `bug · safe · notify`
header did opposite things — one stopped at decide-and-flag because the `bug`
cap lowered it to `supervised`, the other merged in-turn. `start_dev` step 3
prints this line before work starts, so a worker and a reader see the same
answer. The level is `_sizing.effective_autonomy` (`min(header, cap)`); the
mode is `_sizing.merge_mode` (AUTONOMY.md "Merge authority follows
Consequence — 2026-10-02" and ruling R3 of 2026-11-17). Read-only.

`--auto` is an explicit `--auto` launch; `--in-shift` a shift worker (a shift
is an `--auto` launch, and its merges first take a merge slot).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SIZING = Path(__file__).resolve().parents[1] / "agents" / "faculties" / "sizing"
sys.path.insert(0, str(SIZING))
import _sizing  # noqa: E402


def _mind_of(prompt: Path) -> Path:
    """The Mind root the prompt sits in (the folder above its `draft/` or
    `active/`), else the sibling checkout `pyauto-brain sizing` reads."""
    for parent in prompt.parents:
        if parent.name in ("draft", "active"):
            return parent.parent
    return _sizing.BODY_MAP_PATH.parent


def line(prompt: Path, *, auto: bool = False, in_shift: bool = False,
         mind: Path | None = None) -> str:
    prompt = Path(prompt).resolve()
    p = _sizing.parse_prompt(prompt, (mind or _mind_of(prompt)).resolve())
    difficulty = _sizing.effective_difficulty(p)[0]
    level = _sizing.effective_autonomy(p, difficulty)[0]
    mode = _sizing.merge_mode(p, level, auto=auto, in_shift=in_shift)
    return f"effective level: {level}; merge mode: {mode}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pyauto-brain merge-mode",
                                 description="One prompt's effective level and merge mode.")
    ap.add_argument("prompt", help="path to a PyAutoMind prompt (.md)")
    ap.add_argument("--auto", action="store_true", help="an explicit --auto launch")
    ap.add_argument("--in-shift", action="store_true", dest="in_shift",
                    help="a shift worker: merges first take a merge slot")
    ap.add_argument("--mind", type=Path, default=None, help="PyAutoMind root")
    args = ap.parse_args(argv)
    if not Path(args.prompt).is_file():
        print(f"merge-mode: no prompt file at {args.prompt}", file=sys.stderr)
        return 2
    print(line(Path(args.prompt), auto=args.auto, in_shift=args.in_shift, mind=args.mind))
    return 0


if __name__ == "__main__":
    sys.exit(main())

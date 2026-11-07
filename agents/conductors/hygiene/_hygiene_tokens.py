#!/usr/bin/env python3
"""tokens: the organism's token-load budgets, read as a hygiene finding.

Two measurements that already exist, composed into one `count|summary` row:

- PyAutoMind `scripts/token_load.py report --json` — the four organs'
  AGENTS.md tokens, the start_dev / prm procedure lines and the
  completion-record median, with the budgets its `check` verb enforces;
- PyAutoBrain `bin/check_skill_line_counts.sh` — every skill's mandatory load
  (SKILL.md + body) against the 200-line budget.

The count is the number of budgets broken: token_load violations (a file the
scan root simply lacks is reported, not counted) plus skills over 200 lines.
Read-only and stdlib only; it never edits a skill. Route a breach to
/refactor (move detail verbatim into the skill's `reference.md`); the budget
history is PyAutoMind `draft/maintenance/organs/reduce_session_token_load.md`.

Usage: _hygiene_tokens.py --root ROOT --mind MIND_CHECKOUT [--detail]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[3]
SKILL_LINES = BRAIN / "bin" / "check_skill_line_counts.sh"


def token_load(root: Path, mind: Path) -> dict | None:
    script = mind / "scripts" / "token_load.py"
    if not script.is_file():
        return None
    proc = subprocess.run(
        [sys.executable, str(script), "report", "--json", "--root", str(root)],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def skills_over(root: Path) -> list[str] | None:
    env = {**os.environ, "PYAUTO_ROOT": str(root)}
    try:
        proc = subprocess.run(
            ["bash", str(SKILL_LINES)], capture_output=True, text=True,
            env=env, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "OK:" not in proc.stdout and "FAIL:" not in proc.stdout:
        return None
    return [
        " ".join(line.split()[1:3])  # "<lines> <skill dir>"
        for line in proc.stdout.splitlines() if line.startswith("OVER")
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mind", type=Path, required=True)
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args(argv)

    load = token_load(args.root, args.mind)
    if load is None:
        print("-1|token_load.py unavailable (no PyAutoMind checkout under the "
              "scan root) — nothing measured")
        return 0
    breaches = [v for v in load.get("violations", [])
                if not v.startswith("missing:")]
    over = skills_over(args.root)
    totals = load.get("totals", {})
    count = len(breaches) + len(over or [])

    parts = [
        f"start_dev {totals.get('start_dev_lines', '?')} / "
        f"prm {totals.get('prm_lines', '?')} procedure lines",
        f"organ AGENTS ~{totals.get('organ_agents_tokens_approx', '?')} tokens",
    ]
    records = totals.get("completion_records")
    if records:
        parts.append(f"record median {records['median_lines']} lines")
    if over is None:
        parts.append("skill line budget unmeasured")
    else:
        parts.append(f"{len(over)} skills over 200 lines")
    print(f"{count}|{count} token-load budgets broken: " + "; ".join(parts)
          + " (route breaches to /refactor)")

    if args.detail:
        for breach in breaches:
            print(f"  budget  {breach}")
        for skill in over or []:
            print(f"  skill   {skill} (SKILL.md + body > 200 lines)")
        missing = [v for v in load.get("violations", []) if v.startswith("missing:")]
        for item in missing:
            print(f"  absent  {item[len('missing: '):]} (not counted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

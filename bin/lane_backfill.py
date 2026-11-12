#!/usr/bin/env python3
"""Propose — and, only when told, write — a `Lane:` for every lane-less draft.

Programme task M1.3, slice 2 (PyAutoBrain#608). `Lane:` was on 12 of ~270
drafts and an absent Lane reads as `any`, so a draft whose Witness needs RAL or
an A100 is planned into a cloud session that cannot run it. Intake has
inferred a lane at filing since 2026-11-03; the older backlog was never
backfilled. This is the one scripted pass.

    lane_backfill.py [--mind DIR] [--all] [--out proposals.md] [--json]
    lane_backfill.py --apply [--from proposals.md] [--mind DIR]

Without `--apply` it only READS the Mind and writes the proposal table (to
`--out`, else stdout) for a human to skim at the block gate: one row per draft
with the proposed lane and the words that proposed it. Everything that names
no resource gets an explicit `any`.

`--apply` writes `Lane: <lane>` into each draft's header block (after
`Unattended:`, where intake writes it) and commits nothing. With `--from` it
applies the table as the human left it — edit a row's lane to overrule it,
delete the row to skip it — rather than re-proposing.

Why here, in the Brain, and not in the Mind's `scripts/`: the proposal must
use the SAME signal table intake files with (`_intake.LANE_SIGNALS`) and the
SAME pool the planner draws from (`_batch.planner_pool`); a Mind copy of either
would drift from the one the planner actually runs.

Scope: the planner pool (every gate but the session's lane) by default;
`--all` covers every draft.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
for sub in ("agents/faculties/sizing", "agents/conductors/intake",
            "agents/conductors/batch"):
    sys.path.insert(0, str(BRAIN / sub))
import _batch  # noqa: E402
import _intake  # noqa: E402
import _mind_writer  # noqa: E402
from _sizing import LANE_VALUES, declared_header  # noqa: E402

_ROW_RE = re.compile(r"^\|\s*`?([^|`]+?\.md)`?\s*\|\s*`?([a-z-]+)`?\s*\|")


def lane_less(mind: Path, *, every: bool = False) -> list[dict]:
    """Drafts (the planner pool, or all with `every`) with no valid `Lane:`."""
    records = _batch.survey(mind)
    scope = records if every else _batch.planner_pool(records)
    out = []
    for r in scope:
        text = (mind / r["path"]).read_text(encoding="utf-8", errors="replace")
        h = declared_header(text)
        if h.get("lane"):
            continue
        out.append({"path": r["path"], "text": text,
                    "invalid": h.get("lane_invalid") or ""})
    return out


def propose(mind: Path, *, every: bool = False) -> list[dict]:
    rows = []
    for d in lane_less(mind, every=every):
        lane, snippet = _intake.infer_lane_evidence(d["text"])
        rows.append({"path": d["path"], "lane": lane, "evidence": snippet,
                     "invalid": d["invalid"]})
    return sorted(rows, key=lambda r: (r["lane"] == "any", r["lane"], r["path"]))


def counts(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["lane"]] = out.get(r["lane"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def table(rows: list[dict], *, scope: str, stamp: str = "") -> str:
    c = counts(rows)
    lines = [
        "# Lane backfill — proposals",
        "",
        f"Scope: {scope}. {len(rows)} draft(s) without a valid `Lane:`."
        + (f" Read from {stamp}." if stamp else ""),
        "",
        "Counts: " + ", ".join(f"`{k}` {v}" for k, v in c.items()) + ".",
        "",
        "Skim the non-`any` rows: a keyword hit is an upper bound, and a draft",
        "that only *mentions* RAL or a GPU as context should be `any`. Edit the",
        "lane column to overrule a row, delete the row to skip it, then run",
        "`lane_backfill.py --apply --from <this file>`.",
        "",
        "| draft | lane | evidence |",
        "|---|---|---|",
    ]
    for r in rows:
        ev = r["evidence"].replace("|", "\\|").replace("`", "'")
        if r["invalid"]:
            ev = (f"replaces invalid `Lane: {r['invalid']}`; " + ev).strip("; ")
        lines.append(f"| `{r['path']}` | `{r['lane']}` | {ev or '—'} |")
    return "\n".join(lines) + "\n"


def read_table(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line)
        if m and m.group(1) != "draft":
            rows.append({"path": m.group(1).strip(), "lane": m.group(2).strip()})
    return rows


def apply(mind: Path, rows: list[dict]) -> tuple[list[str], list[str]]:
    """Write each row's `Lane:`. Returns (written, refused)."""
    written, refused = [], []
    for r in rows:
        if r["lane"] not in LANE_VALUES:
            refused.append(f"{r['path']}: {r['lane']} is not a lane")
            continue
        f = mind / r["path"]
        if not f.is_file():
            refused.append(f"{r['path']}: no such draft")
            continue
        text = f.read_text(encoding="utf-8")
        if declared_header(text).get("lane"):
            refused.append(f"{r['path']}: already declares a lane")
            continue
        f.write_text(_mind_writer.set_header(text, "Lane", r["lane"]), encoding="utf-8")
        written.append(r["path"])
    return written, refused


def _mind_stamp(mind: Path) -> str:
    """`PyAutoMind@<sha> <date>` when the Mind is a git checkout — so the human
    knows which backlog the table was read from."""
    import datetime as _dt
    import subprocess
    try:
        res = subprocess.run(["git", "-C", str(mind), "log", "-1", "--format=%h"],
                             capture_output=True, text=True, timeout=30)
        sha = res.stdout.strip() if res.returncode == 0 else ""
    except OSError:
        sha = ""
    today = _dt.date.today().isoformat()
    return f"PyAutoMind@{sha} on {today}" if sha else f"on {today}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lane_backfill", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mind", type=Path,
                    default=Path(os.environ.get("PYAUTO_MIND")
                                 or _batch.BODY_MAP_PATH.parent))
    ap.add_argument("--all", action="store_true", dest="every",
                    help="every draft, not only the planner pool")
    ap.add_argument("--out", type=Path, help="write the proposal table here")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--apply", action="store_true",
                    help="write the Lane: headers (commits nothing)")
    ap.add_argument("--from", type=Path, dest="table",
                    help="--apply: the (human-edited) proposal table to apply")
    a = ap.parse_args(argv)
    mind = a.mind.resolve()
    if not (mind / "draft").is_dir():
        print(f"lane_backfill: no PyAutoMind backlog at {mind}", file=sys.stderr)
        return 4
    if a.table and not a.apply:
        print("lane_backfill: --from belongs to --apply", file=sys.stderr)
        return 2
    if a.apply:
        rows = read_table(a.table) if a.table else propose(mind, every=a.every)
        written, refused = apply(mind, rows)
        print(f"lane_backfill: wrote Lane: into {len(written)} draft(s) "
              f"(not committed); refused {len(refused)}")
        for r in refused:
            print(f"  ✗ {r}")
        return 1 if refused else 0
    rows = propose(mind, every=a.every)
    scope = "every draft" if a.every else "the planner pool (every gate but the lane)"
    if a.as_json:
        print(json.dumps({"scope": scope, "counts": counts(rows), "rows": rows},
                         indent=2))
        return 0
    out = table(rows, scope=scope, stamp=_mind_stamp(mind))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(out, encoding="utf-8")
        print(f"lane_backfill: {len(rows)} proposal(s) → {a.out} — "
              + ", ".join(f"{k} {v}" for k, v in counts(rows).items()))
    else:
        print(out, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())

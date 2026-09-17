#!/usr/bin/env python3
"""_vitals.py — the vitals faculty when the Heart CLI is not here.

WHY. `vitals.sh` drives `pyauto-heart`, and a web/mobile session never has the
PyAutoHeart checkout — so `resolve_heart` failed and the faculty exited, which
meant the ship gate ran with NO verdict at all rather than a qualified one. The
Heart already publishes its board to GitHub Pages and the Brain board already
reads it; this reads the same two files and answers from them.

WHAT IT IS NOT. A published board is not a live tick: it is as fresh as the
Heart's last publish, and every line of output says so. When the CLI is
present, `vitals.sh` still drives it for the organism-wide read.

SCOPE. `--scope <repo>[,<repo>...]` answers the question a branch actually has:
"is anything blocking MY repo?". The organism-wide verdict is one number over
every repo, so a library branch was acknowledging a RED raised by a workspace
smoke failure three repos away — one it could not have caused and cannot fix.
The scoped verdict keeps both: GREEN in scope, RED organism-wide, both printed.

The fetch and the blocker extraction are NOT reimplemented here — they are
`board/_board.py`'s (`fetch_badge`, `fetch_heart_board`,
`extract_heart_blockers`), imported, so the Brain reads the Heart's surface
through exactly one parser.

Exit: 0 a verdict was read · 2 usage · 3 the published board is unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BRAIN_HOME / "board"))

import _board  # noqa: E402

# Heart's tiers, worst first. The scoped verdict is the worst severity among
# the in-scope blockers, so it needs their order — the same precedence Heart
# applies in `readiness.py` (red dominates yellow dominates stale).
SEVERITY_RANK = {"red": 3, "yellow": 2, "amber": 2, "stale": 1}
VERDICTS = ("RED", "YELLOW", "STALE", "GREEN")


def pages_source():
    """(pages_base, heart_repo) — resolved exactly as the Brain board does.

    `BOARD_PAGES_BASE` wins, so a test (or a mirror) can point this elsewhere
    without a checkout; otherwise the org comes from the Mind's body map.
    """
    cfg = _board.load_policy()
    heart_repo = cfg.get("heart_board", "PyAutoHeart")
    base = os.environ.get("BOARD_PAGES_BASE")
    if not base:
        org = _board.derive_org(_board.repo_homes())
        if org is None:
            return None, heart_repo
        base = f"https://{org.lower()}.github.io"
    return base, heart_repo


def read_published(pages_base, heart_repo):
    """(badge, board, degraded) from the Heart's published Pages surface."""
    degraded: list[str] = []
    badge = _board.fetch_badge(pages_base, heart_repo)
    board = _board.fetch_heart_board(pages_base, heart_repo, degraded)
    return badge, board, degraded


def verdict_of(badge, board):
    """The organism-wide verdict word. The badge's `message` is the headline
    contract every board publishes (`GREEN`, `RED 3 blockers`, ...); a board
    that carries its own `verdict` is the fallback for a badge that did not
    arrive."""
    message = str((badge or {}).get("message", "") or "").strip()
    head = message.split()[0].upper() if message else ""
    if head in VERDICTS:
        return head
    own = str((board or {}).get("verdict", "") or "").strip().upper()
    return own if own in VERDICTS else "UNKNOWN"


def board_timestamp(board):
    """When the published board was generated. Heart's key has changed name
    across schema versions, so accept any of them rather than pinning one."""
    for key in ("generated", "generated_at", "ts", "timestamp", "as_of", "updated"):
        value = (board or {}).get(key)
        if value:
            return str(value)
    return "unknown"


def parse_scope(raw):
    """`--scope a,b` / repeated `--scope` -> a lowercased list of repo names."""
    names = []
    for chunk in raw or []:
        for name in str(chunk).split(","):
            name = name.strip()
            if name and name.lower() not in names:
                names.append(name.lower())
    return names


def in_scope(blocker, scope):
    """Does this blocker name one of the scoped repos?

    A blocker carries a `repo` field, but not always (an organism-wide gap has
    none) — and its `text` is what a reader recognises. So match either: the
    repo field exactly, or the repo name anywhere in the text. Matching the
    text is deliberately generous; missing a blocker that IS yours is the
    expensive direction.
    """
    repo = str(blocker.get("repo") or "").lower()
    text = str(blocker.get("text") or "").lower()
    return any(name == repo or name in text for name in scope)


def worst(blockers):
    """The worst severity among these blockers, as a verdict word."""
    rank = max((SEVERITY_RANK.get(str(b.get("severity") or "").lower(), 0)
                for b in blockers), default=0)
    if rank == 0:
        # Blockers with no severity Heart recognises are still blockers; they
        # must not read as GREEN.
        return "YELLOW" if blockers else "GREEN"
    return {3: "RED", 2: "YELLOW", 1: "STALE"}[rank]


def render_blocker(b):
    sev = f"[{b['severity']}] " if b.get("severity") else ""
    line = f"  {sev}{b.get('text', '')}"
    if b.get("run_url"):
        line += f" — {b['run_url']}"
    return line


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="_vitals.py",
        description="Read the Heart's PUBLISHED board (no pyauto-heart needed).")
    p.add_argument("--scope", action="append", metavar="REPO[,REPO...]",
                   help="filter blockers to these repos and print a scoped verdict")
    p.add_argument("--json", action="store_true", help="machine output")
    args = p.parse_args(argv)
    scope = parse_scope(args.scope)

    pages_base, heart_repo = pages_source()
    if pages_base is None:
        print("verdict: UNKNOWN (Pages unreachable: cannot derive the GitHub "
              "org — no body map and no git remote)")
        return 3

    badge, board, degraded = read_published(pages_base, heart_repo)
    if badge is None and board is None:
        why = degraded[0] if degraded else "unreachable"
        print(f"verdict: UNKNOWN (Pages unreachable: {why})")
        return 3

    organism = verdict_of(badge, board)
    blockers = _board.extract_heart_blockers(board)
    # Scope filters the board's RAW blockers before extraction, not the
    # extracted five: `extract_heart_blockers` caps the list for a morning
    # glance, and a cap that silently drops the one blocker that IS yours
    # would turn a scoped read into a lie. Same extractor, narrower input.
    if scope:
        raw = [b for b in ((board or {}).get("blockers") or [])
               if in_scope(b, scope)]
        scoped = _board.extract_heart_blockers({"blockers": raw})
        scoped_verdict = worst(scoped)
    else:
        scoped, scoped_verdict = blockers, organism
    source = f"{pages_base}/{heart_repo}/"
    note = ("this is the PUBLISHED Heart board, not a live tick — it is as "
            "fresh as the Heart's last publish")

    if args.json:
        print(json.dumps({
            "verdict": organism,
            "scope": scope,
            "scoped_verdict": scoped_verdict,
            "blockers": blockers,
            "scoped_blockers": scoped,
            "generated": board_timestamp(board),
            "source": source,
            "published": True,
            "note": note,
            "degraded": degraded,
        }, indent=2))
        return 0

    print(f"== vitals faculty: the published Heart board ({source}) ==")
    print(f"note:      {note}")
    print(f"verdict:   {organism}")
    print(f"generated: {board_timestamp(board)}")
    if scope:
        print(f"scope:     {', '.join(scope)}")
        print(f"scoped verdict: {scoped_verdict}   (organism-wide: {organism})")
    rows = scoped if scope else blockers
    label = "in-scope blockers" if scope else "blockers"
    if rows:
        print(f"{label} ({len(rows)}):")
        for b in rows:
            print(render_blocker(b))
    else:
        print(f"{label}: none")
    for row in degraded:
        print(f"degraded:  {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

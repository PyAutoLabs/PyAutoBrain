#!/usr/bin/env python3
"""bin/heart_feed.py — the Heart at the door (read-only, fast).

WHY. The Heart gate used to be consulted only at ship time, so a session could
plan and build a whole branch on top of a RED organism and only learn it at the
end. The human's rule is "fix Heart before development"; this helper is what
`start_dev` / `start_bundle` / `route` run FIRST (step 0a "Heart at the door")
so the verdict is on screen before any plan is made.

WHAT IT READS. The Heart's published organ-cockpit feed — `state.json`, the v1
contract in `board/_state.py` — at `<pages base>/<heart board>/state.json`. The
heart board comes from `config/policy.yaml` (`board: heart_board`) and the pages
base from the Mind's body map (`board/_board.py`'s `repo_homes` / `derive_org`,
imported, never re-derived); `BOARD_PAGES_BASE` overrides the base, as it does
for the board and the vitals faculty. No org is named here.

FALLBACK. When the published feed is unreachable or unreadable (offline, a
blocked network, a malformed publish) — or with `--offline` — it asks the local
Heart CLI, `pyauto-heart readiness --json` (PATH first, then the sibling
checkout's `bin/`), and maps that verdict into the same shape.

WHAT IT IS NOT. It never runs a Heart tick and never refreshes anything: a
reader at the door must be fast and must not mutate state. The vitals faculty
remains the live, authoritative read at ship time.

Output: `Heart: RED — <headline> (updated 2h ago)` then one line per red/yellow
item (info items too when the status is not green and nothing is red/yellow).
`--json` prints the same summary as one JSON object for the skill seams.

Exit: 0 green · 1 yellow/stale · 2 red · 3 grey/unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BRAIN_HOME = Path(__file__).resolve().parents[1]
POLICY_PATH = BRAIN_HOME / "config" / "policy.yaml"
TIMEOUT = 5  # seconds — the door must never stall a session
FALLBACK_TIMEOUT = 30

STATUSES = ("green", "yellow", "red", "stale", "grey")
EXIT = {"green": 0, "yellow": 1, "stale": 1, "red": 2, "grey": 3}
SEVERITY_ORDER = {"red": 0, "yellow": 1, "info": 2}


# ----------------------------------------------------------------- source ---


def _board():
    """board/_board.py, imported lazily (the URL derivation lives there)."""
    sys.path.insert(0, str(BRAIN_HOME / "board"))
    import _board  # noqa: PLC0415
    return _board


def heart_board_repo(policy_path=POLICY_PATH):
    """`board: heart_board` from the policy, by a stdlib regex (no PyYAML —
    the same one-pair-per-line parse the Mind renderer uses on this block)."""
    try:
        text = Path(policy_path).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^\s+heart_board:\s*([A-Za-z0-9_.-]+)\s*$", text, re.M)
    return m.group(1) if m else None


def feed_url():
    """(url, why) — the published state.json URL, or (None, reason)."""
    repo = heart_board_repo()
    if not repo:
        return None, "no `board: heart_board` in config/policy.yaml"
    base = os.environ.get("BOARD_PAGES_BASE")
    if not base:
        try:
            board = _board()
            org = board.derive_org(board.repo_homes())
        except Exception as exc:  # noqa: BLE001 — the door degrades, never crashes
            return None, f"cannot derive the pages base ({exc})"
        if org is None:
            return None, "cannot derive the GitHub org (no body map, no git remote)"
        base = f"https://{org.lower()}.github.io"
    return f"{base.rstrip('/')}/{repo}/state.json", None


def _reason(exc):
    try:
        return _board()._fetch_reason(exc)
    except Exception:  # noqa: BLE001
        return str(exc)[:80] or exc.__class__.__name__


def fetch_feed(url, timeout=TIMEOUT):
    """(feed, why) — the parsed, sanity-checked feed or (None, reason)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, ValueError, OSError) as exc:
        return None, _reason(exc)
    problem = feed_problem(obj)
    if problem:
        return None, f"served a feed that is not state.json v1 ({problem})"
    return obj, None


def feed_problem(obj):
    """The one reason this cannot be read as a Heart state, or None.

    Deliberately lenient: the full contract is `_state.validate_state`, but a
    door that refused a RED feed over a missing `pages_url` would hide the RED.
    Only what the door itself prints is required.
    """
    if not isinstance(obj, dict):
        return "top level is not an object"
    if obj.get("status") not in STATUSES:
        return f"status {obj.get('status')!r} is not one of {'/'.join(STATUSES)}"
    if not isinstance(obj.get("items", []), list):
        return "items is not a list"
    return None


# --------------------------------------------------------------- fallback ---


def resolve_heart_cli():
    """`pyauto-heart` on PATH, else the sibling checkout's bin/ (the same
    order as agents/_common.sh `resolve_heart`). None when neither exists."""
    found = shutil.which("pyauto-heart")
    if found:
        return found
    try:
        sys.path.insert(0, str(BRAIN_HOME / "agents"))
        import _pyauto_root  # noqa: PLC0415
        from _repo_paths import repo_path  # noqa: PLC0415
        root, _ = _pyauto_root.workspace_root_reason()
        heart_repo = heart_board_repo() or ""
        if heart_repo:
            cand = repo_path(root, heart_repo) / "bin" / "pyauto-heart"
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
    except Exception:  # noqa: BLE001
        pass
    return None


def from_readiness(r):
    """Map `pyauto-heart readiness --json` into the state.json shape."""
    verdict = str(r.get("verdict", "")).lower()
    status = verdict if verdict in STATUSES else "grey"
    items = ([{"severity": "red", "text": t} for t in r.get("red_reasons") or []]
             + [{"severity": "yellow", "text": t} for t in r.get("yellow_reasons") or []]
             + [{"severity": "info", "text": t} for t in r.get("stale_reasons") or []])
    headline = items[0]["text"] if items else (
        "all checks green" if status == "green" else f"verdict {verdict or 'unknown'}")
    return {"status": status, "headline": headline, "updated": r.get("ts"),
            "items": items}


def read_local(timeout=FALLBACK_TIMEOUT):
    """(state, why) from the local Heart CLI's readiness verdict (no tick)."""
    cli = resolve_heart_cli()
    if cli is None:
        return None, "no pyauto-heart on PATH or in the sibling checkout"
    try:
        proc = subprocess.run([cli, "readiness", "--json"], capture_output=True,
                              text=True, timeout=timeout)
        return from_readiness(json.loads(proc.stdout)), None
    except subprocess.TimeoutExpired:
        return None, f"pyauto-heart readiness timed out after {timeout}s"
    except (OSError, ValueError, AttributeError) as exc:
        return None, f"pyauto-heart readiness unreadable ({str(exc)[:80]})"


# ----------------------------------------------------------------- render ---


def age_of(updated, now=None):
    """'2h ago' for an ISO timestamp; None when it cannot be parsed."""
    if not isinstance(updated, str) or not updated:
        return None
    try:
        then = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = max(0, int(((now or datetime.now(timezone.utc)) - then).total_seconds()))
    if secs < 60:
        return "just now"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{secs // size}{unit} ago"
    return "just now"


def door_items(state):
    """The rows printed under the headline: red/yellow always; info only when
    the status is not green and nothing louder exists (a STALE door)."""
    items = [i for i in state.get("items") or [] if isinstance(i, dict)]
    loud = [i for i in items if i.get("severity") in ("red", "yellow")]
    if not loud and state.get("status") != "green":
        loud = [i for i in items if i.get("severity") == "info"]
    return sorted(loud, key=lambda i: SEVERITY_ORDER.get(i.get("severity"), 3))


def summarise(state, source, url=None, fallback_reason=None):
    status = state.get("status") if state else "grey"
    return {
        "status": status,
        "exit": EXIT.get(status, 3),
        "headline": (state or {}).get("headline") or "",
        "updated": (state or {}).get("updated"),
        "age": age_of((state or {}).get("updated")),
        "items": [{"severity": i.get("severity"), "text": i.get("text", ""),
                   "url": i.get("url")} for i in door_items(state or {})],
        "source": source,
        "url": url,
        "fallback_reason": fallback_reason,
    }


def render(s):
    if s["status"] == "grey" and s["source"] == "none":
        lines = [f"Heart: GREY — unreachable ({s['fallback_reason']})"]
    else:
        age = f" (updated {s['age']})" if s["age"] else ""
        lines = [f"Heart: {s['status'].upper()} — {s['headline']}{age}"]
    for i in s["items"]:
        line = f"  [{i['severity']}] {i['text']}"
        if i.get("url"):
            line += f" — {i['url']}"
        lines.append(line)
    if s["source"] == "local-readiness":
        lines.append(f"  (from local `pyauto-heart readiness`; published feed: "
                     f"{s['fallback_reason']})")
    return "\n".join(lines)


def read(url=None, offline=False):
    """The door's summary — published feed first, local readiness second."""
    why = "--offline"
    if not offline:
        if url is None:
            url, why = feed_url()
        if url is not None:
            feed, why = fetch_feed(url)
            if feed is not None:
                return summarise(feed, "published", url)
    local, local_why = read_local()
    if local is not None:
        return summarise(local, "local-readiness", url, why)
    return summarise(None, "none", url, f"{why}; {local_why}")


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="heart_feed.py",
        description="Read the Heart's published state.json (read-only; never ticks).")
    p.add_argument("--json", action="store_true", help="machine output")
    p.add_argument("--url", help="read this state.json URL instead (tests, mirrors)")
    p.add_argument("--offline", action="store_true",
                   help="skip the published feed; ask local pyauto-heart readiness")
    args = p.parse_args(argv)
    s = read(url=args.url, offline=args.offline)
    print(json.dumps(s, indent=2) if args.json else render(s))
    return s["exit"]


if __name__ == "__main__":
    sys.exit(main())

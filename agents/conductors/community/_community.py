#!/usr/bin/env python3
"""agents/conductors/community/_community.py — core for the Community Agent.

The Ears — the organism's receptive language function (Wernicke to the
Workspace Agent's Broca/Voice: that agent speaks through examples; this one
hears the community). It reads the outside world's GitHub issues and emits
deterministic surfaces the /community skill reasons over:

  scan     every repos.yaml repo -> open issues raised by non-self humans,
           with awaiting-response detection and waiting-time ranking
           (the /wake_up community sensory leg)
  triage   one issue -> context-sufficiency signals + routing surface
           (the judgment — actionable vs ask-for-more — stays in the session)

The conductor NEVER posts, labels or edits anything on GitHub and never writes
files. Every outward message is drafted in the /community skill session and
gated on the human; dev work routes through /start_dev_for_user.

Stdlib-only. GitHub access is the `gh` CLI (override with COMMUNITY_GH for
hermetic tests). Exit codes: 0 surface emitted · 4 inputs unresolvable ·
5 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PYAUTO_ROOT = Path(os.environ.get("PYAUTO_ROOT", Path.home() / "Code" / "PyAutoLabs"))
GH = os.environ.get("COMMUNITY_GH", "gh")
SELF_LOGINS = [
    s.strip()
    for s in os.environ.get("COMMUNITY_SELF", "Jammy2211").split(",")
    if s.strip()
]
PRIMARY_ORG = "PyAutoLabs"
SCAN_DETAIL_CAP = 30  # issues that get a per-issue last-commenter lookup

# Context signals a well-formed report tends to carry. Each is (key, ask) —
# the ask is the clarifying-question seed the skill session redrafts in its
# own words when the signal is missing.
TRIAGE_SIGNALS = (
    ("code_block", "a runnable snippet or the script that triggers this"),
    ("traceback", "the full traceback / error output"),
    ("version", "the installed PyAuto* versions (e.g. `pip show autolens`)"),
    ("expected_vs_actual", "what you expected to happen vs what actually happened"),
    ("data_pointer", "a pointer to (or description of) the dataset involved"),
)


def fail(code, msg):
    print(f"community: {msg}", file=sys.stderr)
    sys.exit(code)


def gh_json(args):
    """Run `gh api ...` and parse JSON; None on any failure (the surface
    degrades honestly rather than inventing content)."""
    try:
        r = subprocess.run(
            [GH, "api", *args], capture_output=True, text=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        fail(4, f"cannot run '{GH} api': {e}")
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def repo_homes():
    """Every `github:` home in PyAutoMind/repos.yaml (regex, stdlib-only —
    no yaml dependency in the Brain)."""
    body_map = PYAUTO_ROOT / "PyAutoMind" / "repos.yaml"
    if not body_map.is_file():
        fail(4, f"body map not found: {body_map} (set PYAUTO_ROOT)")
    homes = re.findall(
        r"^\s+github:\s*(\S+)\s*$", body_map.read_text(encoding="utf-8"), re.M
    )
    if not homes:
        fail(4, f"no `github:` entries parsed from {body_map}")
    return homes


def is_bot(user):
    login = (user or {}).get("login", "")
    return (user or {}).get("type") == "Bot" or login.endswith("[bot]")


def is_self(user):
    return (user or {}).get("login") in SELF_LOGINS


def days_since(iso):
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return round((datetime.now(timezone.utc) - then).total_seconds() / 86400, 1)


def search_external_issues(qualifier):
    q = f"{qualifier} is:issue is:open " + " ".join(
        f"-author:{login}" for login in SELF_LOGINS
    )
    data = gh_json(["-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=50"])
    if data is None:
        return None
    return data.get("items", [])


def last_commenter(owner_repo, number):
    """Login of the newest comment's author; None when uncommented/unreadable."""
    comments = gh_json([f"repos/{owner_repo}/issues/{number}/comments", "-f", "per_page=100"])
    if not comments:
        return None
    return (comments[-1].get("user") or {}).get("login")


def issue_repo(item):
    # search/issues items carry the repo only inside repository_url.
    return "/".join(item.get("repository_url", "").split("/")[-2:])


def build_scan():
    homes = repo_homes()
    extra = [h for h in homes if not h.startswith(f"{PRIMARY_ORG}/")]

    items, degraded = [], []
    org_items = search_external_issues(f"org:{PRIMARY_ORG}")
    if org_items is None:
        degraded.append(f"org:{PRIMARY_ORG} search failed (gh auth? rate limit?)")
    else:
        items += org_items
    if extra:
        extra_items = search_external_issues(" ".join(f"repo:{h}" for h in extra))
        if extra_items is None:
            degraded.append("non-org repo search failed")
        else:
            items += extra_items

    issues = []
    for item in items:
        if is_bot(item.get("user")):
            continue
        repo = issue_repo(item)
        entry = {
            "repo": repo,
            "number": item.get("number"),
            "title": item.get("title", ""),
            "author": (item.get("user") or {}).get("login"),
            "url": item.get("html_url"),
            "labels": [l.get("name") for l in item.get("labels", [])],
            "comments": item.get("comments", 0),
            "updated_at": item.get("updated_at"),
            "waiting_days": days_since(item.get("updated_at")),
            "last_actor": None,
            "awaiting_response": None,
        }
        issues.append(entry)

    # Awaiting-response = the conversation's last word is not ours. Cap the
    # per-issue lookups; uncapped entries keep awaiting_response=None (unknown).
    for entry in sorted(issues, key=lambda e: e["updated_at"] or "", reverse=True)[
        :SCAN_DETAIL_CAP
    ]:
        actor = (
            entry["author"]
            if entry["comments"] == 0
            else last_commenter(entry["repo"], entry["number"])
        )
        entry["last_actor"] = actor
        entry["awaiting_response"] = actor is not None and actor not in SELF_LOGINS

    awaiting = [e for e in issues if e["awaiting_response"]]
    awaiting.sort(key=lambda e: e["waiting_days"] or 0, reverse=True)
    return {
        "self_logins": SELF_LOGINS,
        "org": PRIMARY_ORG,
        "extra_repos": extra,
        "open_external_issues": issues,
        "awaiting_response": awaiting,
        "counts": {
            "open_external": len(issues),
            "awaiting_response": len(awaiting),
        },
        "degraded": degraded,
        "next_action": (
            "pick an issue -> `community triage <ref>` -> the /community session "
            "assesses context, drafts the reply for human approval, and routes "
            "actionable work via /start_dev_for_user; this surface posts nothing"
        ),
    }


def print_scan(s):
    print("== CommunityScan — the Ears (reads only; posts nothing) ==")
    print(f"Self logins:          {', '.join(s['self_logins'])}")
    print(f"Searched:             org:{s['org']}"
          + (f" + {len(s['extra_repos'])} non-org repo(s)" if s["extra_repos"] else ""))
    for d in s["degraded"]:
        print(f"DEGRADED:             {d}")
    c = s["counts"]
    print(f"Open external issues: {c['open_external']}  (awaiting our response: {c['awaiting_response']})")
    for e in s["awaiting_response"]:
        days = f"{e['waiting_days']:.0f}d" if e["waiting_days"] is not None else "?"
        print(f"  ! {e['repo']}#{e['number']} [{days} waiting] @{e['author']}: {e['title'][:70]}")
    for e in s["open_external_issues"]:
        if not e["awaiting_response"]:
            state = "ours-to-watch" if e["awaiting_response"] is False else "unchecked"
            print(f"  - {e['repo']}#{e['number']} ({state}) @{e['author']}: {e['title'][:70]}")
    print(f"Next action:          {s['next_action']}")


def parse_issue_ref(ref):
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/issues/(\d+)", ref)
    if m:
        return m.group(1), int(m.group(2))
    m = re.match(r"([^/#\s]+/[^/#\s]+)#(\d+)$", ref)
    if m:
        return m.group(1), int(m.group(2))
    fail(5, f"cannot parse issue ref '{ref}' — use a full URL or owner/repo#N")


def build_triage(ref):
    owner_repo, number = parse_issue_ref(ref)
    issue = gh_json([f"repos/{owner_repo}/issues/{number}"])
    if issue is None:
        fail(4, f"cannot fetch {owner_repo}#{number} (gh auth? does it exist?)")
    body = issue.get("body") or ""

    low = body.lower()
    present = {
        "code_block": "```" in body,
        "traceback": "traceback (most recent call last)" in low or "error:" in low,
        "version": bool(re.search(r"version|(\bauto(lens|fit|galaxy|array)\S*\s*==)", low)),
        "expected_vs_actual": bool(re.search(r"expect|should\b|instead\b", low)),
        "data_pointer": bool(re.search(r"\.fits\b|zenodo|drive\.google|dataset", low)),
    }
    missing = [
        {"signal": key, "ask": ask}
        for key, ask in TRIAGE_SIGNALS
        if not present[key]
    ]

    comments = gh_json([f"repos/{owner_repo}/issues/{number}/comments", "-f", "per_page=100"]) or []
    tail = [
        {
            "author": (c.get("user") or {}).get("login"),
            "created_at": c.get("created_at"),
            "excerpt": (c.get("body") or "")[:400],
        }
        for c in comments[-3:]
    ]
    last = tail[-1]["author"] if tail else (issue.get("user") or {}).get("login")

    return {
        "repo": owner_repo,
        "number": number,
        "url": issue.get("html_url"),
        "title": issue.get("title", ""),
        "author": (issue.get("user") or {}).get("login"),
        "author_is_external": not is_self(issue.get("user")),
        "state": issue.get("state"),
        "labels": [l.get("name") for l in issue.get("labels", [])],
        "body": body,
        "signals_present": present,
        "signals_missing": missing,
        "comment_tail": tail,
        "awaiting_response": last not in SELF_LOGINS,
        "route": f"/start_dev_for_user {issue.get('html_url')}",
        "reminders": [
            "the session judges sufficiency — these signals are heuristics, not a verdict",
            "every outward comment is drafted and shown to the human before posting",
            "actionable -> /start_dev_for_user (it owns receipt/plan/milestone comments); "
            "unclear -> one consolidated clarifying comment + needs-info label",
            "update cadence: ~5 milestones for bugs, ~4 for features",
        ],
    }


def print_triage(t):
    print(f"== CommunityTriage — {t['repo']}#{t['number']} ==")
    print(f"Title:                {t['title']}")
    print(f"Author:               @{t['author']}"
          + (" (external)" if t["author_is_external"] else " (self)"))
    print(f"State:                {t['state']}   Labels: {', '.join(t['labels']) or '(none)'}")
    print(f"Awaiting response:    {t['awaiting_response']}")
    print("Context signals:")
    for key, ok in t["signals_present"].items():
        print(f"  {'+' if ok else '-'} {key}")
    if t["signals_missing"]:
        print("Missing (clarifying-question seeds — redraft in the session's words):")
        for m in t["signals_missing"]:
            print(f"  ? {m['ask']}")
    if t["comment_tail"]:
        print("Comment tail:")
        for c in t["comment_tail"]:
            print(f"  @{c['author']} ({c['created_at']}): {c['excerpt'][:100]}")
    print(f"Route:                {t['route']}")
    for r in t["reminders"]:
        print(f"Reminder:             {r}")


def main():
    argv = sys.argv[1:]
    parser = argparse.ArgumentParser(prog="community", description=__doc__)
    parser.add_argument("mode", nargs="?", default="scan",
                        help="scan (default) | triage <issue-ref>")
    parser.add_argument("ref", nargs="?", default=None,
                        help="triage only: issue URL or owner/repo#N")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "scan":
        surface = build_scan()
        print(json.dumps(surface, indent=2)) if args.json else print_scan(surface)
    elif args.mode == "triage":
        if not args.ref:
            fail(5, "triage needs an issue ref — a full URL or owner/repo#N")
        surface = build_triage(args.ref)
        print(json.dumps(surface, indent=2)) if args.json else print_triage(surface)
    else:
        fail(5, f"unknown mode '{args.mode}' — use scan or triage <ref>")
    sys.exit(0)


if __name__ == "__main__":
    main()

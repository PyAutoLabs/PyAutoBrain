#!/usr/bin/env python3
"""agents/conductors/community/_community.py — core for the Community Agent.

The Ears — the organism's receptive language function (Wernicke to the
Workspace Agent's Broca/Voice: that agent speaks through examples; this one
hears the community). It reads the outside world's GitHub threads — the
Discussions hub where users ask (PyAutoMind/policy/community_surface.md) and
the issues/PRs outsiders still file — and emits deterministic surfaces the
/community skill reasons over:

  scan     the hub's open discussions (unanswered = no accepted answer and
           the last word is not ours, except broadcast categories) + every repos.yaml repo -> open issues
           AND pull requests raised by non-self humans (awaiting-response
           detection, waiting-time ranking) + open PRs with review requested
           from a self login (the board's community sensory leg)
  triage   one discussion, issue or PR -> context-sufficiency signals +
           routing surface; PR refs additionally carry the change-shape block
           (draft, files, additions/deletions, requested reviewers, mergeable
           state) (the judgment — actionable vs ask-for-more — stays in the
           session)

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
import time
from datetime import datetime, timezone
from pathlib import Path

# Workspace root via the one shared resolver (agents/_pyauto_root.py, mirrored
# by bin/_pyauto_root.sh): PYAUTO_ROOT, else the nearest ancestor holding a
# .pyauto-root marker, else beside this checkout, else the parent anyway. Naming an absolute workspace path as the *default* here
# resolved into
# a non-existent tree in a remote session and reported empty rather than
# failing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _repo_paths import repo_path
import _pyauto_root  # noqa: E402

PYAUTO_ROOT = _pyauto_root.pyauto_root()
GH = os.environ.get("COMMUNITY_GH", "gh")
SELF_LOGINS = [
    s.strip()
    for s in os.environ.get("COMMUNITY_SELF", "Jammy2211").split(",")
    if s.strip()
]
PRIMARY_ORG = "PyAutoLabs"
# The one Discussions hub users post to (PyAutoMind/policy/community_surface.md,
# decision 1): the org's Discussions, hosted on the neutral profile repo
# PyAutoLabs/.github. Every library and workspace points here; the repos
# themselves keep Discussions off.
HUB = os.environ.get("COMMUNITY_HUB", "PyAutoLabs/.github")
BROADCAST_CATEGORIES = {"Announcements", "Show and tell"}
SCAN_DETAIL_CAP = 30  # issues that get a per-issue last-commenter lookup
# Pause between search-API calls — the scan makes up to six, and GitHub's
# secondary rate limit trips on rapid bursts (hermetic tests set it to 0).
SEARCH_PAUSE_S = float(os.environ.get("COMMUNITY_SEARCH_PAUSE", "2"))

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
    body_map = repo_path(PYAUTO_ROOT, "PyAutoMind") / "repos.yaml"
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


def search_open(qualifier, kind, extra_quals=""):
    """Open issues or PRs (`kind` = issue|pr) matching the qualifier; None on
    a failed search."""
    q = f"{qualifier} is:{kind} is:open"
    if extra_quals:
        q += f" {extra_quals}"
    if SEARCH_PAUSE_S:
        time.sleep(SEARCH_PAUSE_S)
    data = gh_json(["-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=50"])
    if data is None:
        return None
    return data.get("items", [])


def search_external(qualifier, kind):
    not_self = " ".join(f"-author:{login}" for login in SELF_LOGINS)
    return search_open(qualifier, kind, not_self)


def last_commenter(owner_repo, number):
    """Login of the newest comment's author; None when uncommented/unreadable."""
    comments = gh_json([f"repos/{owner_repo}/issues/{number}/comments", "-f", "per_page=100"])
    if not comments:
        return None
    return (comments[-1].get("user") or {}).get("login")


def issue_repo(item):
    # search/issues items carry the repo only inside repository_url.
    return "/".join(item.get("repository_url", "").split("/")[-2:])


def list_discussions(hub):
    """The hub's open discussions (REST, read-only — the only Discussions
    surface a remote session is served); None when unreadable."""
    return gh_json([f"repos/{hub}/discussions", "-f", "per_page=100", "-f", "state=open"])


def discussion_last_commenter(hub, number):
    comments = gh_json([f"repos/{hub}/discussions/{number}/comments", "-f", "per_page=100"])
    if not comments:
        return None
    return (comments[-1].get("user") or {}).get("login")


def _discussion_entry(d, hub):
    return {
        "type": "discussion",
        "repo": hub,
        "number": d.get("number"),
        "title": d.get("title", ""),
        "author": (d.get("user") or {}).get("login"),
        "url": d.get("html_url"),
        "category": (d.get("category") or {}).get("name"),
        "answered": d.get("answer_chosen_at") is not None,
        "labels": [l.get("name") for l in d.get("labels", []) or []],
        "comments": d.get("comments", 0),
        "updated_at": d.get("updated_at"),
        "waiting_days": days_since(d.get("updated_at")),
        "last_actor": None,
        "awaiting_response": None,
    }


def hub_discussions(hub, degraded):
    """Open, unlocked, human-authored threads on the hub. An accepted answer
    settles a thread (awaiting_response=False without a comment lookup);
    broadcast categories remain ours to watch; otherwise the last word
    decides, exactly as for an issue."""
    items = list_discussions(hub)
    if items is None:
        degraded.append(f"{hub} discussions listing failed (gh auth? Discussions off?)")
        return []
    entries = []
    for d in items:
        if d.get("state", "open") != "open" or d.get("locked") or is_bot(d.get("user")):
            continue
        entries.append(_discussion_entry(d, hub))
    return entries


def _entry(item, kind):
    return {
        "type": kind,
        "repo": issue_repo(item),
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


def _searched(qualifiers, kind, degraded, external=True):
    """Run one search per qualifier group, folding failures into `degraded`."""
    entries = []
    tag = kind if external else "review-requested"
    for label, qualifier in qualifiers:
        items = (
            search_external(qualifier, kind)
            if external
            else search_open(qualifier, kind, "review-requested:" + SELF_LOGINS[0])
        )
        if items is None:
            degraded.append(f"{label} {tag} search failed (gh auth? rate limit?)")
            continue
        entries += [_entry(i, kind) for i in items if not is_bot(i.get("user"))]
    return entries


def build_scan():
    homes = repo_homes()
    extra = [h for h in homes if not h.startswith(f"{PRIMARY_ORG}/")]
    qualifiers = [(f"org:{PRIMARY_ORG}", f"org:{PRIMARY_ORG}")]
    if extra:
        qualifiers.append(("non-org", " ".join(f"repo:{h}" for h in extra)))

    degraded = []
    issues = _searched(qualifiers, "issue", degraded)
    prs = _searched(qualifiers, "pr", degraded)
    # Review requests target a self login regardless of author (a bot's PR
    # asking for review is still ours to answer, so no external filter).
    review_requested = _searched(qualifiers, "pr", degraded, external=False)

    # Awaiting-response = the conversation's last word is not ours. Cap the
    # per-item lookups; uncapped entries keep awaiting_response=None (unknown).
    # Uses issue-conversation comments (PR review-thread comments are a known
    # v2 limit, recorded in AGENTS.md).
    discussions = hub_discussions(HUB, degraded)
    for entry in discussions:
        if entry["answered"] or entry["category"] in BROADCAST_CATEGORIES:
            entry["awaiting_response"] = False
    conversations = issues + prs + [
        d for d in discussions if d["awaiting_response"] is None
    ]
    for entry in sorted(
        conversations, key=lambda e: e["updated_at"] or "", reverse=True
    )[:SCAN_DETAIL_CAP]:
        if entry["comments"] == 0:
            actor = entry["author"]
        elif entry["type"] == "discussion":
            actor = discussion_last_commenter(entry["repo"], entry["number"])
        else:
            actor = last_commenter(entry["repo"], entry["number"])
        entry["last_actor"] = actor
        entry["awaiting_response"] = actor is not None and actor not in SELF_LOGINS

    awaiting = [e for e in issues + prs + discussions if e["awaiting_response"]]
    awaiting.sort(key=lambda e: e["waiting_days"] or 0, reverse=True)
    return {
        "self_logins": SELF_LOGINS,
        "org": PRIMARY_ORG,
        "hub": HUB,
        "extra_repos": extra,
        "open_discussions": discussions,
        "open_external_issues": issues,
        "open_external_prs": prs,
        "awaiting_review": review_requested,
        "awaiting_response": awaiting,
        "counts": {
            "open_discussions": len(discussions),
            "open_external": len(issues),
            "open_external_prs": len(prs),
            "awaiting_review": len(review_requested),
            "awaiting_response": len(awaiting),
        },
        "degraded": degraded,
        "next_action": (
            "pick an item -> `community triage <ref>` -> the /community session "
            "assesses context, drafts the reply for human approval (a discussion "
            "is answered in its thread; a confirmed bug gets an issue with a link "
            "back), and routes actionable work via /start_dev_for_user; this "
            "surface posts nothing"
        ),
    }


def print_scan(s):
    print("== CommunityScan — the Ears (reads only; posts nothing) ==")
    print(f"Self logins:          {', '.join(s['self_logins'])}")
    print(f"Hub (discussions):    {s['hub']}")
    print(f"Searched:             org:{s['org']}"
          + (f" + {len(s['extra_repos'])} non-org repo(s)" if s["extra_repos"] else ""))
    for d in s["degraded"]:
        print(f"DEGRADED:             {d}")
    c = s["counts"]
    print(f"Open discussions:     {c['open_discussions']} on the hub")
    print(f"Open external:        {c['open_external']} issue(s), {c['open_external_prs']} PR(s)"
          f"  (awaiting our response: {c['awaiting_response']} incl. discussions)")
    for e in s["awaiting_response"]:
        days = f"{e['waiting_days']:.0f}d" if e["waiting_days"] is not None else "?"
        print(f"  ! {ref_label(e)} [{days} waiting] @{e['author']}: {e['title'][:70]}")
    for e in s["open_external_issues"] + s["open_external_prs"] + s["open_discussions"]:
        if not e["awaiting_response"]:
            state = "ours-to-watch" if e["awaiting_response"] is False else "unchecked"
            print(f"  - {ref_label(e)} ({state}) @{e['author']}: {e['title'][:70]}")
    if s["awaiting_review"]:
        print(f"Review requested:     {c['awaiting_review']}")
        for e in s["awaiting_review"]:
            print(f"  * {e['repo']}#{e['number']} @{e['author']}: {e['title'][:70]}")
    print(f"Next action:          {s['next_action']}")


def ref_label(entry):
    """How a conversation is named on a surface (and pasted back into
    `community triage`): `owner/repo#N` for an issue, `PR owner/repo#N` for
    a PR, the full URL for a discussion (`#N` would read as an issue)."""
    if entry["type"] == "discussion":
        return entry["url"] or f"{entry['repo']}/discussions/{entry['number']}"
    kind = "PR " if entry["type"] == "pr" else ""
    return f"{kind}{entry['repo']}#{entry['number']}"


def parse_ref(ref):
    """(owner/repo, number, kind) — kind is 'discussion' for a discussion
    ref, else 'conversation' (issue or PR; the fetch tells them apart)."""
    m = re.match(r"(?:https?://github\.com/)?([^/#\s]+/[^/#\s]+)/discussions/(\d+)/?$", ref)
    if m:
        return m.group(1), int(m.group(2)), "discussion"
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)", ref)
    if m:
        return m.group(1), int(m.group(2)), "conversation"
    m = re.match(r"([^/#\s]+/[^/#\s]+)#(\d+)$", ref)
    if m:
        return m.group(1), int(m.group(2)), "conversation"
    fail(5, f"cannot parse ref '{ref}' — use a full issue/PR/discussion URL or owner/repo#N")


def parse_issue_ref(ref):
    owner_repo, number, _ = parse_ref(ref)
    return owner_repo, number


def pr_block(owner_repo, number):
    """The change-shape block for a PR ref; None when the pulls endpoint is
    unreadable (surface degrades, never invents)."""
    pr = gh_json([f"repos/{owner_repo}/pulls/{number}"])
    if pr is None:
        return None
    return {
        "draft": pr.get("draft"),
        "changed_files": pr.get("changed_files"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "mergeable_state": pr.get("mergeable_state"),
        "requested_reviewers": [
            (u or {}).get("login") for u in pr.get("requested_reviewers", [])
        ],
        "base": (pr.get("base") or {}).get("ref"),
        "head": (pr.get("head") or {}).get("ref"),
    }


def _signals(body):
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
    return present, missing


def _tail(comments):
    return [
        {
            "author": (c.get("user") or {}).get("login"),
            "created_at": c.get("created_at"),
            "excerpt": (c.get("body") or "")[:400],
        }
        for c in comments[-3:]
    ]


def build_discussion_triage(owner_repo, number):
    d = gh_json([f"repos/{owner_repo}/discussions/{number}"])
    if d is None:
        fail(4, f"cannot fetch discussion {owner_repo}/discussions/{number} "
                "(gh auth? Discussions enabled there?)")
    body = d.get("body") or ""
    present, missing = _signals(body)
    comments = gh_json([f"repos/{owner_repo}/discussions/{number}/comments", "-f", "per_page=100"]) or []
    tail = _tail(comments)
    last = tail[-1]["author"] if tail else (d.get("user") or {}).get("login")
    answered = d.get("answer_chosen_at") is not None
    category = (d.get("category") or {}).get("name")
    return {
        "type": "discussion",
        "pr": None,
        "repo": owner_repo,
        "number": number,
        "url": d.get("html_url"),
        "title": d.get("title", ""),
        "author": (d.get("user") or {}).get("login"),
        "author_is_external": not is_self(d.get("user")),
        "state": d.get("state"),
        "category": category,
        "answered": answered,
        "labels": [l.get("name") for l in d.get("labels", []) or []],
        "body": body,
        "signals_present": present,
        "signals_missing": missing,
        "comment_tail": tail,
        "awaiting_response": (
            not answered and category not in BROADCAST_CATEGORIES
            and last is not None and last not in SELF_LOGINS
        ),
        "route": (
            f"answer in the thread {d.get('html_url')} — the session drafts the "
            "reply, the human posts it and, in an answerable category, marks "
            "the settling answer; a confirmed bug or accepted proposal -> "
            "open the issue on the target repo with a link back, route it via "
            "/start_dev_for_user. For Proposals, mark the verdict comment "
            "(acceptance with the issue link, or a recorded no) as the answer"
        ),
        "reminders": [
            "the session judges sufficiency — these signals are heuristics, not a verdict",
            "every outward reply is drafted and shown to the human before posting",
            "a discussion is the user's surface: never convert it to an issue in place — "
            "open the issue (reproducer required) and link both ways",
            "no session can post to, answer or convert a Discussion (REST is read-only, "
            "GraphQL is refused) — the human's click is the last step",
        ],
    }


def build_triage(ref):
    owner_repo, number, kind = parse_ref(ref)
    if kind == "discussion":
        return build_discussion_triage(owner_repo, number)
    issue = gh_json([f"repos/{owner_repo}/issues/{number}"])
    if issue is None:
        fail(4, f"cannot fetch {owner_repo}#{number} (gh auth? does it exist?)")
    body = issue.get("body") or ""

    present, missing = _signals(body)

    comments = gh_json([f"repos/{owner_repo}/issues/{number}/comments", "-f", "per_page=100"]) or []
    tail = _tail(comments)
    last = tail[-1]["author"] if tail else (issue.get("user") or {}).get("login")

    is_pr = "pull_request" in issue
    return {
        "type": "pr" if is_pr else "issue",
        "pr": pr_block(owner_repo, number) if is_pr else None,
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
        "route": (
            f"human review of PR {issue.get('html_url')} — session drafts the "
            f"review comments (this is NOT the ship-gate review faculty)"
            if is_pr
            else f"/start_dev_for_user {issue.get('html_url')}"
        ),
        "reminders": [
            "the session judges sufficiency — these signals are heuristics, not a verdict",
            "every outward comment is drafted and shown to the human before posting",
            "actionable -> /start_dev_for_user (it owns receipt/plan/milestone comments); "
            "unclear -> one consolidated clarifying comment + needs-info label",
            "update cadence: ~5 milestones for bugs, ~4 for features",
        ],
    }


def print_triage(t):
    kind = t["type"] if t["type"] == "discussion" else ("PR" if t["type"] == "pr" else "issue")
    print(f"== CommunityTriage — {t['repo']}#{t['number']} ({kind}) ==")
    print(f"Title:                {t['title']}")
    print(f"Author:               @{t['author']}"
          + (" (external)" if t["author_is_external"] else " (self)"))
    print(f"State:                {t['state']}   Labels: {', '.join(t['labels']) or '(none)'}")
    if t["type"] == "discussion":
        print(f"Category:             {t['category'] or '(none)'}   Answered: {t['answered']}")
    if t["pr"]:
        p = t["pr"]
        reviewers = ", ".join(p["requested_reviewers"]) or "(none)"
        print(f"PR shape:             {p['changed_files']} file(s), +{p['additions']}/-{p['deletions']}"
              f"   draft={p['draft']}   mergeable={p['mergeable_state']}   {p['head']} -> {p['base']}")
        print(f"Review requested:     {reviewers}")
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
                        help="triage only: issue/PR/discussion URL or owner/repo#N")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "scan":
        surface = build_scan()
        print(json.dumps(surface, indent=2)) if args.json else print_scan(surface)
    elif args.mode == "triage":
        if not args.ref:
            fail(5, "triage needs a ref — an issue/PR/discussion URL or owner/repo#N")
        surface = build_triage(args.ref)
        print(json.dumps(surface, indent=2)) if args.json else print_triage(surface)
    else:
        fail(5, f"unknown mode '{args.mode}' — use scan or triage <ref>")
    sys.exit(0)


if __name__ == "__main__":
    main()

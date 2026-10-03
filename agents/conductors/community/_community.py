#!/usr/bin/env python3
"""agents/conductors/community/_community.py — core for the Community Agent.

Brain's community judgement conductor (Wernicke to the
Workspace Agent's Broca/Voice: that agent speaks through examples; this one
hears the community). It reads the outside world's GitHub threads — the
Discussions hub where users ask (PyAutoMind/policy/community_surface.md) and
the issues/PRs outsiders still file — and emits deterministic surfaces the
/community skill reasons over:

  scan     published PyAutoEars snapshot/state -> legacy scan JSON; source
           coverage and freshness remain explicit, with no GitHub rescan
  triage   one discussion, issue or PR -> context-sufficiency signals +
           routing surface; PR refs additionally carry the change-shape block
           (draft, files, additions/deletions, requested reviewers, mergeable
           state) (the judgment — actionable vs ask-for-more — stays in the
           session)

The conductor NEVER posts, labels or edits anything on GitHub and never writes
files. Every outward message is drafted in the /community skill session and
gated on the human; dev work routes through /start_dev_for_user.

Stdlib-only. Scan reads the public Ears feed (COMMUNITY_EARS_URL override).
Triage GitHub access is the `gh` CLI (override with COMMUNITY_GH for
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

# Workspace root via the one shared resolver (agents/_pyauto_root.py, mirrored
# by bin/_pyauto_root.sh): PYAUTO_ROOT, else the nearest ancestor holding a
# .pyauto-root marker, else beside this checkout, else the parent anyway. Naming an absolute workspace path as the *default* here
# resolved into
# a non-existent tree in a remote session and reported empty rather than
# failing.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
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
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def is_self(user):
    return ((user or {}).get("login") or "").casefold() in {s.casefold() for s in SELF_LOGINS}


def days_since(iso):
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return round((datetime.now(timezone.utc) - then).total_seconds() / 86400, 1)


def build_scan(base=None):
    """Compatibility surface over Ears' published evidence; no GitHub scan."""
    from _ears_feed import load
    base = base or os.environ.get(
        "COMMUNITY_EARS_URL", f"https://{PRIMARY_ORG.lower()}.github.io/PyAutoEars")
    try:
        return load(base, SELF_LOGINS, PRIMARY_ORG, HUB)
    except ValueError as exc:
        fail(4, str(exc))


def print_scan(s):
    print("== CommunityScan — the Ears (reads only; posts nothing) ==")
    print(f"Self logins:          {', '.join(s['self_logins'])}")
    print(f"Hub (discussions):    {s['hub']}")
    print(f"Ears observed:        {s['generated']}")
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


def _signals(body, category=None):
    low = body.lower()
    present = {
        "code_block": "```" in body,
        "traceback": "traceback (most recent call last)" in low or "error:" in low,
        "version": bool(re.search(r"version|(\bauto(lens|fit|galaxy|array)\S*\s*==)", low)),
        "expected_vs_actual": bool(re.search(r"expect|should\b|instead\b", low)),
        "data_pointer": bool(re.search(r"\.fits\b|zenodo|drive\.google|dataset", low)),
    }
    present.update({
        "assumptions": bool(re.search(r"assum|prior|model", low)),
        "inference_goal": bool(re.search(r"infer|measure|constrain|estimate|scientific question", low)),
        "use_case": bool(re.search(r"use.case|workflow|currently|need to", low)),
        "desired_outcome": bool(re.search(r"would like|goal|outcome|enable|so that", low)),
    })
    signals = TRIAGE_SIGNALS
    if category == "Help & Questions":
        signals = (
            ("assumptions", "the scientific assumptions or model you are using"),
            ("data_pointer", "the data and relevant characteristics of the dataset"),
            ("inference_goal", "the inference goal and what you are trying to understand"),
        )
    elif category == "Ideas & Proposals":
        signals = (
            ("use_case", "the use case and current workflow this would improve"),
            ("desired_outcome", "the desired outcome and how you would judge success"),
        )
    elif category in BROADCAST_CATEGORIES:
        signals = ()
    present = {key: present[key] for key, _ in signals}
    missing = [
        {"signal": key, "ask": ask}
        for key, ask in signals
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


def _comments(owner_repo, number, kind, thread):
    """One bounded GET only. Discussion replies and PR reviews are not read here."""
    raw = gh_json([f"repos/{owner_repo}/{kind}/{number}/comments",
                   "-X", "GET", "-f", "per_page=100"])
    valid = isinstance(raw, list) and all(isinstance(c, dict) for c in raw)
    comments = raw[:100] if valid else []
    reasons = []
    count = thread.get("comments")
    if not valid:
        reasons.append("comments unavailable or malformed")
    elif len(raw) >= 100:
        reasons.append("100-comment bound reached; later comments may be missing")
    elif not isinstance(count, int) or isinstance(count, bool) or count != len(raw):
        reasons.append("reported comment count missing or differs from bounded read")
    if kind == "discussions":
        reasons.append("nested Discussion replies are not covered by this bounded read")
    if "pull_request" in thread:
        reasons.append("PR reviews and inline review threads are not covered by this bounded read")
    if any(not (c.get("user") or {}).get("login") for c in comments):
        reasons.append("comment author deleted or unknown")
    tail = _tail(comments)
    last = comments[-1].get("user") if comments else thread.get("user")
    if not (last or {}).get("login"):
        reasons.append("latest author deleted or unknown")
    return tail, {
        "status": "unavailable" if not valid else "partial" if reasons else "complete",
        "limit": 100, "observed": len(comments), "reported": count,
        "tail_scope": "last three of the bounded read, not necessarily latest in thread",
        "reasons": reasons,
    }, None if reasons else not is_self(last)


def build_discussion_triage(owner_repo, number):
    d = gh_json([f"repos/{owner_repo}/discussions/{number}"])
    if d is None:
        fail(4, f"cannot fetch discussion {owner_repo}/discussions/{number} "
                "(gh auth? Discussions enabled there?)")
    body = d.get("body") or ""
    category = (d.get("category") or {}).get("name")
    present, missing = _signals(body, category)
    tail, coverage, awaiting = _comments(owner_repo, number, "discussions", d)
    answered = d.get("answer_chosen_at") is not None
    return {
        "type": "discussion",
        "pr": None,
        "repo": owner_repo,
        "number": number,
        "url": d.get("html_url"),
        "title": d.get("title", ""),
        "author": (d.get("user") or {}).get("login"),
        "author_is_external": not is_self(d.get("user")) if (d.get("user") or {}).get("login") else None,
        "state": d.get("state"),
        "category": category,
        "answered": answered,
        "labels": [l.get("name") for l in d.get("labels", []) or []],
        "body": body,
        "signals_present": present,
        "signals_missing": missing,
        "comment_tail": tail,
        "comment_coverage": coverage,
        "awaiting_response": False if answered or category in BROADCAST_CATEGORIES else awaiting,
        "delivery_state": "unknown",
        "route": (
            f"answer in the thread {d.get('html_url')} — the session drafts the "
            "reply, the human posts it and, in an answerable category, marks "
            "the settling answer; a confirmed bug or accepted proposal -> "
            "open the issue on the target repo with a link back, route it via "
            "/start_dev_for_user. In Ideas & Proposals, mark the verdict comment "
            "(acceptance with the issue link, or a recorded no) as the answer; "
            "acceptance is a decision, not evidence of implementation or delivery"
        ),
        "reminders": [
            "the session judges sufficiency — these signals are heuristics, not a verdict",
            "every outward reply is drafted and shown to the human before posting",
            "a discussion is the user's surface: never convert it to an issue in place — "
            "open the issue (reproducer for bugs; use case and outcome for proposals) and link both ways",
            "a remote/proxied session cannot post to, answer or convert a Discussion "
            "(REST is read-only, the proxy refuses GraphQL) — there the human clicks; a local "
            "CLI with authenticated gh can, via GraphQL, once the human has approved the text",
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

    tail, coverage, awaiting = _comments(owner_repo, number, "issues", issue)

    is_pr = "pull_request" in issue
    return {
        "type": "pr" if is_pr else "issue",
        "pr": pr_block(owner_repo, number) if is_pr else None,
        "repo": owner_repo,
        "number": number,
        "url": issue.get("html_url"),
        "title": issue.get("title", ""),
        "author": (issue.get("user") or {}).get("login"),
        "author_is_external": not is_self(issue.get("user")) if (issue.get("user") or {}).get("login") else None,
        "state": issue.get("state"),
        "labels": [l.get("name") for l in issue.get("labels", [])],
        "body": body,
        "signals_present": present,
        "signals_missing": missing,
        "comment_tail": tail,
        "comment_coverage": coverage,
        "awaiting_response": awaiting,
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
          + (" (unknown)" if t["author_is_external"] is None else
             " (external)" if t["author_is_external"] else " (self)"))
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
    print(f"Comment coverage:     {t['comment_coverage']['status']} (bounded to 100)")
    for reason in t["comment_coverage"]["reasons"]:
        print(f"Coverage gap:         {reason}")
    print("Context signals:")
    for key, ok in t["signals_present"].items():
        print(f"  {'+' if ok else '-'} {key}")
    if t["signals_missing"]:
        print("Missing (clarifying-question seeds — redraft in the session's words):")
        for m in t["signals_missing"]:
            print(f"  ? {m['ask']}")
    if t["comment_tail"]:
        print("Comment tail (last three of bounded read):")
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

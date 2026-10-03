"""Read the published Ears v1 evidence; never collect or judge conversations."""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import unquote
from datetime import datetime, timedelta, timezone

MAX_BYTES = 8 * 1024 * 1024
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("missing timezone")
    return parsed.astimezone(timezone.utc)


def read_json(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Ears feed exceeds read budget")
    return json.loads(raw)


def validate(snapshot, state):
    """Check only the consumed read contract, including public provenance/links."""
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        raise ValueError("unsupported Ears snapshot")
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int or state["schema_version"] != 1 or state.get("organ") != "ears":
        raise ValueError("unsupported Ears state")
    generated = timestamp(snapshot["generated"])
    if generated != timestamp(state["updated"]):
        raise ValueError("Ears snapshot/state observation mismatch")
    if timestamp(state["valid_until"]) < generated:
        raise ValueError("invalid Ears freshness interval")
    if state.get("status") not in {"green", "yellow", "red", "grey", "stale"}:
        raise ValueError("invalid Ears status")
    if not isinstance(snapshot.get("receipts"), list) or not isinstance(snapshot.get("conversations"), list):
        raise ValueError("missing Ears evidence")
    public = set()
    for receipt in snapshot["receipts"]:
        if not isinstance(receipt, dict) or not REPO.fullmatch(receipt.get("repo", "")):
            raise ValueError("invalid source receipt")
        timestamp(receipt["checked_at"])
        if receipt.get("status") not in {"complete", "partial", "unavailable", "excluded"}:
            raise ValueError("invalid source coverage")
        if not isinstance(receipt.get("gaps"), list) or any(not isinstance(g, str) for g in receipt["gaps"]):
            raise ValueError("invalid coverage gaps")
        if receipt["status"] in {"complete", "partial"} and receipt.get("public_verified") is not True:
            raise ValueError("source not verified public")
        if receipt.get("public_verified") is True:
            public.add(receipt["repo"])
    seen = set()
    for row in snapshot["conversations"]:
        if not isinstance(row, dict) or row.get("repo") not in public:
            raise ValueError("conversation lacks public receipt")
        suffix = {"issue": "issues", "pr": "pull", "discussion": "discussions"}.get(row.get("kind"))
        if not suffix or type(row.get("number")) is not int or row["number"] < 1:
            raise ValueError("invalid conversation identity")
        identity = f"{row['repo']}/{suffix}/{row['number']}"
        if row.get("id") != identity or row.get("url") != f"https://github.com/{identity}" or identity in seen:
            raise ValueError("invalid conversation link or duplicate")
        seen.add(identity)
        for key in ("title", "author", "category"):
            if not isinstance(row.get(key), str):
                raise ValueError("invalid conversation metadata")
        if row.get("coverage") not in {"complete", "partial"}:
            raise ValueError("invalid conversation coverage")
        if row.get("awaiting_response") is not None and type(row["awaiting_response"]) is not bool:
            raise ValueError("invalid response state")
        for key in ("answered", "review_requested", "cached"):
            if type(row.get(key)) is not bool:
                raise ValueError("invalid conversation state")
        if row.get("waiting_since") is not None:
            timestamp(row["waiting_since"])
        if 'closed' in row and type(row['closed']) is not bool:
            raise ValueError('invalid closed state')
    validate_delivery(snapshot.get('follow_through', []), snapshot['conversations'])


def validate_delivery(rows, conversations):
    """Validate the optional projection without depending on an Ears checkout."""
    discussions = {r['url'] for r in conversations if r['kind'] == 'discussion'}
    seen = set()
    if not isinstance(rows, list):
        raise ValueError('invalid delivery projection')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'discussion', 'state', 'update_owed', 'evidence', 'gaps'}:
            raise ValueError('unknown delivery fields')
        if row['discussion'] not in discussions or row['discussion'] in seen:
            raise ValueError('invalid delivery source')
        seen.add(row['discussion'])
        if row['state'] not in {'accepted', 'in_development', 'merged_unreleased', 'available', 'declined', 'unknown'}:
            raise ValueError('invalid delivery state')
        if row['update_owed'] is not None and (type(row['update_owed']) is not bool or row['state'] != 'available'):
            raise ValueError('invalid delivery update')
        if not isinstance(row['gaps'], list) or any(not isinstance(g, str) for g in row['gaps']):
            raise ValueError('invalid delivery gaps')
        if not isinstance(row['evidence'], list):
            raise ValueError('invalid delivery evidence')
        kinds = set()
        for e in row['evidence']:
            if not isinstance(e, dict) or set(e) != {'url', 'repo', 'kind'} or not REPO.fullmatch(e['repo']):
                raise ValueError('invalid delivery reference')
            suffix = {'issue': r'issues/[1-9][0-9]*', 'PR': r'pull/[1-9][0-9]*',
                      'release': r'releases/tag/[A-Za-z0-9_.%/-]+'}.get(e['kind'])
            if not suffix or not re.fullmatch(r'https://github\.com/' + re.escape(e['repo']) + '/' + suffix, e['url']) or '..' in unquote(e['url']).split('/'):
                raise ValueError('unsafe delivery reference')
            kinds.add(e['kind'])
        if row['state'] == 'available' and (kinds != {'issue', 'PR', 'release'} or row['gaps']):
            raise ValueError('available delivery lacks evidence')


def adapt(snapshot, state, self_logins, org, hub, current=None):
    validate(snapshot, state)
    current = current or datetime.now(timezone.utc)
    generated = timestamp(snapshot["generated"])
    stale = (current > timestamp(state["valid_until"]) or
             generated > current + timedelta(minutes=5) or state["status"] == "stale")
    degraded = []
    if stale:
        degraded.append("Ears snapshot is stale; refresh before judging the queue")
    receipts = snapshot["receipts"]
    if not receipts or all(r["status"] in {"excluded", "unavailable"} for r in receipts):
        degraded.append("Ears has no readable public source coverage")
    elif state["status"] == "grey":
        degraded.append("Ears reports unknown listening status")
    for receipt in receipts:
        if receipt["status"] in {"partial", "unavailable"}:
            degraded.append(f"Ears {receipt['repo']}: {receipt['status']} — " + "; ".join(receipt["gaps"]))
    rows = []
    for source in snapshot["conversations"]:
        # Preserve observations as observations. Missing legacy details stay
        # unknown; do not infer a last actor or fetch comments to fill them.
        since = source.get("waiting_since")
        row = {k: source[k] for k in ("repo", "number", "title", "author", "url", "category", "answered", "coverage", "cached")}
        row.update(type=source["kind"], closed=source.get('closed', False), labels=[], comments=None,
                   updated_at=None, last_actor=None,
                   awaiting_response=None if stale or source["cached"] else source["awaiting_response"],
                   waiting_days=round(max(0, (generated - timestamp(since)).total_seconds()) / 86400, 1) if since else None,
                   review_requested=source["review_requested"],
                   observed_awaiting_response=source["awaiting_response"])
        rows.append(row)
    discussions = [r for r in rows if r["type"] == "discussion" and not r['closed']]
    issues = [r for r in rows if r["type"] == "issue"]
    selves = {login.casefold() for login in self_logins}
    prs = [r for r in rows if r["type"] == "pr" and r["author"].casefold() not in selves and not r["author"].endswith("[bot]")]
    reviews = [r for r in rows if r["review_requested"]]
    awaiting = sorted([r for r in rows if r["awaiting_response"]], key=lambda r: r["waiting_days"] or 0, reverse=True)
    unknown = sum(r["awaiting_response"] is None or r["coverage"] != "complete" for r in rows)
    if unknown:
        degraded.append(f"Ears: {unknown} conversation(s) with unknown response state or incomplete coverage")
    delivery = [dict(r, observed_state=r['state'],
                     state='unknown' if stale else r['state'],
                     update_owed=None if stale else r['update_owed'])
                for r in snapshot.get('follow_through', [])]
    if any(r['state'] == 'unknown' for r in delivery):
        degraded.append('Delivery evidence is incomplete; unknown is not delivered')
    return {
        "self_logins": self_logins, "org": org, "hub": hub,
        "extra_repos": [r["repo"] for r in receipts if not r["repo"].startswith(org + "/")],
        "open_discussions": discussions, "open_external_issues": issues,
        "open_external_prs": prs, "awaiting_review": reviews, "awaiting_response": awaiting,
        "counts": {"open_discussions": len(discussions), "open_external": len(issues),
                   "open_external_prs": len(prs), "awaiting_review": len(reviews),
                   "awaiting_response": len(awaiting), "unknown": unknown},
        "degraded": degraded, "generated": snapshot["generated"],
        "stale": stale, "source": "ears", "coverage": receipts,
        "follow_through": delivery,
        "valid_until": state["valid_until"],
        "next_action": "Use community triage <ref> to assess context and draft a reply for human approval; this surface posts nothing",
    }


def load(base, self_logins, org, hub):
    try:
        snapshot = read_json(base.rstrip("/") + "/snapshot.json")
        state = read_json(base.rstrip("/") + "/state.json")
        return adapt(snapshot, state, self_logins, org, hub)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ValueError(f"Ears published evidence unavailable or invalid ({type(exc).__name__})") from exc

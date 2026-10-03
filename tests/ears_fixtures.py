"""Synthetic published Ears evidence for consumer tests (never a collector)."""
import json
from datetime import datetime, timedelta, timezone


def row(kind="issue", number=1, repo="ExampleOrg/RepoA", awaiting=True, **extra):
    suffix = {"issue": "issues", "pr": "pull", "discussion": "discussions"}[kind]
    identity = f"{repo}/{suffix}/{number}"
    return {"id": identity, "repo": repo, "number": number, "kind": kind,
            "url": f"https://github.com/{identity}", "title": "Synthetic feedback",
            "author": "visitor", "category": "", "answered": False,
            "awaiting_response": awaiting, "waiting_since": "2026-01-01T00:00:00Z",
            "review_requested": False, "coverage": "complete", "gaps": [],
            "cached": False, "feedback_report": False, **extra}


def evidence(rows=(), receipts=None, generated=None):
    now = generated or datetime.now(timezone.utc)
    receipts = receipts if receipts is not None else [
        {"repo": repo, "checked_at": now.isoformat(), "status": "complete",
         "public_verified": True, "gaps": []}
        for repo in sorted({r["repo"] for r in rows} or {"ExampleOrg/RepoA"})]
    snapshot = {"schema_version": 1, "generated": now.isoformat(),
                "conversations": list(rows), "receipts": receipts}
    state = {"schema_version": 1, "organ": "ears", "repo": "ExampleOrg/PyAutoEars",
             "updated": now.isoformat(), "valid_until": (now + timedelta(hours=6)).isoformat(),
             "status": "yellow", "headline": "Synthetic test evidence", "items": [],
             "pages_url": "https://example.invalid/PyAutoEars/"}
    return snapshot, state


def write_feed(path, rows=(), **kwargs):
    path.mkdir(parents=True, exist_ok=True)
    snapshot, state = evidence(rows, **kwargs)
    (path / "snapshot.json").write_text(json.dumps(snapshot))
    (path / "state.json").write_text(json.dumps(state))
    return path.as_uri()

"""agents/conductors/release/activity_gate.py — the nightly activity gate.

Pure decision logic for the scheduled-nightly release driver (nightly.sh),
implementing design §4 of ``PyAutoHands/docs/nightly_release_design.md``:

    qualifying activity = at least one commit on ``main``, in any of the
    release-relevant repos, since the last nightly outcome, that is not a
    pipeline self-commit.

The shell driver fetches raw GitHub commit objects; everything judgment-shaped
lives here so it is unit-testable (tests/test_activity_gate.py). No network,
no subprocess — pure functions over the API payloads.

CLI: a single JSON object ``{repo_name: [commit, ...], ...}`` on stdin (values
are GitHub ``GET /repos/{o}/{r}/commits`` list items; ``null`` marks a repo
whose fetch FAILED — the driver must never disguise an error as an empty
list); prints a verdict JSON ``{"active": bool, "counts": {repo: n},
"excluded": n, "fetched": n, "fetch_errors": n, "all_failed": bool,
"summary": str}``. A fetch error is not a quiet repo: ``all_failed`` tells the
driver it could not see GitHub at all (page, never skip — the 2026-07-10
incidents on PyAutoBrain#67).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

# The release-relevant set (design §4): the repos whose merged work a nightly
# release ships or regenerates. Mirrors PyAutoMind/repos.yaml roles and the
# release.yml build/workspace matrices.
def _release_policy() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[3] / "config" / "policy.yaml"
    return yaml.safe_load(path.read_text())["release"]


RELEASE_RELEVANT_REPOS: tuple[str, ...] = tuple(_release_policy()["relevant_repos"])


# Pipeline self-commit contract (design §4) — a release must never count as
# the next night's activity. Post-#118/#120 the pipeline no longer stamps
# versions into the libraries, so its only main commits are notebook
# regeneration / Colab URL bumps / the assistant API baseline, all made with
# the git identity release.yml configures and messaged "Release <version>: …".
# Both signals are pipeline-controlled; tests pin them so drift is caught.
PIPELINE_COMMITTER_NAMES = frozenset({"GitHub Actions bot", "github-actions[bot]"})
PIPELINE_COMMITTER_EMAILS = frozenset({"richard@rghsoftware.co.uk"})
RELEASE_MESSAGE_RE = re.compile(r"^Release \d{4}\.")

# The activity-window anchor format (the NIGHTLY_LAST_WINDOW_END variable and
# the `since=` parameter of the commits API). Anything else — an API error
# body, an empty read, trailing garbage — must fall back to the 24h window
# instead of poisoning the fetch (PyAutoBrain#67, hole 2).
ANCHOR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def valid_anchor(value: str) -> bool:
    """True if ``value`` is a well-formed ISO-8601Z window anchor.

    ``fullmatch``, not ``match``: ``$`` would accept a trailing newline,
    which is exactly what a shell command substitution can leave behind.
    """
    return bool(ANCHOR_RE.fullmatch(value or ""))


def is_pipeline_commit(commit: dict[str, Any]) -> bool:
    """True if a GitHub commit object is a release-pipeline self-commit."""
    body = commit.get("commit") or {}
    message = str(body.get("message") or "")
    if RELEASE_MESSAGE_RE.match(message):
        return True
    for who in (body.get("committer") or {}, body.get("author") or {}):
        if str(who.get("name") or "") in PIPELINE_COMMITTER_NAMES:
            return True
        if str(who.get("email") or "").lower() in PIPELINE_COMMITTER_EMAILS:
            return True
    return False


def qualifying(commits: list[Any]) -> list[dict[str, Any]]:
    """The commits that count as activity (non-pipeline, well-formed)."""
    return [
        c for c in commits
        if isinstance(c, dict) and not is_pipeline_commit(c)
    ]


def judge(commits_by_repo: dict[str, list[Any]]) -> dict[str, Any]:
    """The gate verdict over per-repo commit lists.

    ``counts`` holds only repos with qualifying activity; ``excluded`` is the
    total number of pipeline self-commits filtered out (reported so a night
    that was quiet *only because of exclusions* says so explicitly). A
    non-list repo value is a FETCH ERROR, not a quiet repo: ``fetch_errors``
    counts them, ``fetched`` counts readable repos, and ``all_failed`` is True
    when nothing was readable — the driver pages on it rather than skipping.
    """
    counts: dict[str, int] = {}
    excluded = 0
    fetched = 0
    fetch_errors = 0
    for repo, commits in sorted((commits_by_repo or {}).items()):
        if not isinstance(commits, list):
            fetch_errors += 1
            continue
        fetched += 1
        kept = qualifying(commits)
        excluded += sum(1 for c in commits if isinstance(c, dict)) - len(kept)
        if kept:
            counts[repo] = len(kept)
    active = bool(counts)
    all_failed = fetch_errors > 0 and fetched == 0
    if active:
        summary = "activity: " + ", ".join(f"{r} ({n})" for r, n in counts.items())
    else:
        summary = "no qualifying activity"
        if excluded:
            summary += f" ({excluded} pipeline self-commit(s) excluded)"
    if fetch_errors:
        summary += f" — {fetch_errors} repo(s) UNREADABLE (fetch failed)"
    return {
        "active": active,
        "counts": counts,
        "excluded": excluded,
        "fetched": fetched,
        "fetch_errors": fetch_errors,
        "all_failed": all_failed,
        "summary": summary,
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"activity_gate: unreadable stdin JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("activity_gate: expected a {repo: [commits]} object", file=sys.stderr)
        return 1
    print(json.dumps(judge(payload), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

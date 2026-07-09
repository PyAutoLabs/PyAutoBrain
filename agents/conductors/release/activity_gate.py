"""agents/conductors/release/activity_gate.py — the nightly activity gate.

Pure decision logic for the scheduled-nightly release driver (nightly.sh),
implementing design §4 of ``PyAutoBuild/docs/nightly_release_design.md``:

    qualifying activity = at least one commit on ``main``, in any of the
    release-relevant repos, since the last nightly outcome, that is not a
    pipeline self-commit.

The shell driver fetches raw GitHub commit objects; everything judgment-shaped
lives here so it is unit-testable (tests/test_activity_gate.py). No network,
no subprocess — pure functions over the API payloads.

CLI: a single JSON object ``{repo_name: [commit, ...], ...}`` on stdin (values
are GitHub ``GET /repos/{o}/{r}/commits`` list items); prints a verdict JSON
``{"active": bool, "counts": {repo: n}, "excluded": n, "summary": str}``.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

# The release-relevant set (design §4): the repos whose merged work a nightly
# release ships or regenerates. Mirrors PyAutoMind/repos.yaml roles and the
# release.yml build/workspace matrices.
RELEASE_RELEVANT_REPOS: tuple[str, ...] = (
    "PyAutoConf",
    "PyAutoFit",
    "PyAutoArray",
    "PyAutoGalaxy",
    "PyAutoLens",
    "autofit_workspace",
    "autogalaxy_workspace",
    "autolens_workspace",
    "HowToFit",
    "HowToGalaxy",
    "HowToLens",
)

# Pipeline self-commit contract (design §4) — a release must never count as
# the next night's activity. Post-#118/#120 the pipeline no longer stamps
# versions into the libraries, so its only main commits are notebook
# regeneration / Colab URL bumps / the assistant API baseline, all made with
# the git identity release.yml configures and messaged "Release <version>: …".
# Both signals are pipeline-controlled; tests pin them so drift is caught.
PIPELINE_COMMITTER_NAMES = frozenset({"GitHub Actions bot", "github-actions[bot]"})
PIPELINE_COMMITTER_EMAILS = frozenset({"richard@rghsoftware.co.uk"})
RELEASE_MESSAGE_RE = re.compile(r"^Release \d{4}\.")


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
    that was quiet *only because of exclusions* says so explicitly).
    """
    counts: dict[str, int] = {}
    excluded = 0
    for repo, commits in sorted((commits_by_repo or {}).items()):
        if not isinstance(commits, list):
            continue
        kept = qualifying(commits)
        excluded += sum(1 for c in commits if isinstance(c, dict)) - len(kept)
        if kept:
            counts[repo] = len(kept)
    active = bool(counts)
    if active:
        summary = "activity: " + ", ".join(f"{r} ({n})" for r, n in counts.items())
    else:
        summary = "no qualifying activity"
        if excluded:
            summary += f" ({excluded} pipeline self-commit(s) excluded)"
    return {"active": active, "counts": counts, "excluded": excluded, "summary": summary}


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

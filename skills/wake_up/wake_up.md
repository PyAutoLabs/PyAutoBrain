# /wake_up — superseded by the Brain board (kept as the fallback door)

**The morning routine no longer runs through this skill.** It is now:

1. **Terminal** (local, not a Claude chat): `bash PyAutoBrain/bin/morning.sh` —
   the sync + clean-slate leg (ff-only pull of every repo, git-aware cleanup of
   regenerable artifacts). `--digest` appends the board's markdown digest.
2. **The Brain board** — `https://<org>.github.io/PyAutoBrain/` (rendered by
   `board/_board.py`, refreshed each morning by `brain_board.yml`, also linked
   from the README): overnight scheduled-run conclusions, the Heart's
   readiness headline, version-stamp consistency, community conversations
   awaiting a reply, resume context (in-flight/parked/queued + pending-release
   PRs), and the upkeep doors — each actionable row carrying its one-tap 📋
   Claude payload (`/bug …`, `/health`, `/community triage …`,
   `/start_dev …`, `/prm …`, `/issue_cleanup`, `/hygiene`, `/repo_cleanup`).

Everything this skill used to assemble interactively lives on that page, on
the same "compose, don't recompute" principle: the board reads what the organs
already publish and never re-derives a verdict. `pyauto-brain board` prints
the identical digest in a terminal when a page is not at hand.

## When invoked anyway

`/wake_up` stays a working door, for a stale board or a no-browser session:

1. **Local sync/clean** — run `bash PyAutoBrain/bin/morning.sh` (auto-run is
   safe: both steps are the recoverable, git-aware ones — sync skips repos
   with real uncommitted work; clean-slate deletes only untracked regenerable
   artifacts and reports orphan datasets instead of removing them). Skip with
   a one-line note when there is no local workspace (mobile/codex).
2. **The digest** — run `bin/pyauto-brain board` and relay its markdown digest
   (it needs only an authenticated `gh`; degraded sections are listed
   honestly). If the board CLI cannot run, fall back to the underlying
   scripts it composes: `bin/overnight_status.sh`, `bin/version_drift.sh`,
   `pyauto-brain community scan`.
3. **Anything actionable** routes through the same doors the board's chips
   name — never auto-reply to the community, never close issues, never delete
   from the digest; those stay `/community`, `/issue_cleanup`,
   `/repo_cleanup`'s own human-gated jobs.

Deeper local-only reads the board deliberately leaves to their own doors:
`/health` for the clinician's rich verdict, `/hygiene` for the upkeep sweep.

Interactive/terminal only — the automated morning Slack webhooks
(morning_health / morning_status) are separate and unchanged.

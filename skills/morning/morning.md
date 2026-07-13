# /morning — start the day: sync, clean, and surface what needs you

The human-driven start-of-day door. Run it each morning to bring the workspace to
a clean, current, known-good state and get one prioritized digest of what needs
your attention. A **composition** skill — it drives existing doors and the `bin/`
scripts; it owns no state and reasons about nothing new.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Principle: compose, don't recompute

Every signal here already has an owner. `/morning` **reads and orchestrates** — it
never re-derives what `/health` (Heart's checks) or the automated morning webhooks
already produce. Keep it a thin conductor.

## Guardrail: auto only the safe steps

Auto-run **only the non-destructive steps** (sync, clean-slate — both git-aware
and reversible). Anything that deletes, edits, or bumps (stray cleanup, branch
deletion, version bumps) is **surfaced in the digest for the human to approve**,
never done automatically.

## Environment: local vs remote

`/morning` runs on the CLI **and** on mobile Claude Code chat / Codex — which
often have no local multi-repo checkout. Detect which:

- **Local** — `$PYAUTO_ROOT` (default `~/Code/PyAutoLabs`) contains the sibling
  repos (e.g. both `PyAutoMind/` and `PyAutoLens/` are present). Run everything.
- **Remote (mobile/codex)** — they are not. **Skip the local-only steps** (sync,
  clean-slate, worktree scan, `/hygiene`) with a one-line note, and run the
  gh-API status glance below — it needs only an authenticated `gh`.

## The routine

Run in order, then emit the digest.

### Local-only (skip on mobile/codex)
1. **Sync** — `bash PyAutoBrain/bin/pull_all_main.sh`. Every repo → its default
   branch, ff-only; repos with real uncommitted work are skipped untouched. Note
   any left **off-main / dirty / behind / diverged**.
2. **Clean slate** — `bash PyAutoBrain/bin/clean_slate.sh` (`DRY_RUN=1` to
   preview). Restore shipped datasets, clear `output/`/`scratch/` cruft.

### Everywhere (gh-API — mobile/codex-safe)
3. **Overnight sweep** — `bash PyAutoBrain/bin/overnight_status.sh`: latest
   scheduled-workflow conclusions (nightly-release, heart-health, matrix CI,
   workspace-validation, wiki-currency, spawn-drift, arxiv). The "what ran while I
   slept" glance — a failing `nightly-release` is your release-blocked signal.
4. **Health & release** — **locally**, consult **`/health`** for the rich verdict;
   **remotely**, the overnight sweep's `heart-health` / `nightly-release`
   conclusions are the readiness/release signal.
5. **Version drift** — `bash PyAutoBrain/bin/version_drift.sh`: version-stamp
   consistency across libs + workspaces vs the latest release tag.
6. **Resume context** — pick up where you left off: in-flight / parked / queued
   work (`PyAutoMind/active.md`, `parked.md`, `queue.md`) + open **pending-release
   PRs** (`gh`); **locally** also worktrees with unpushed commits.
7. **Hygiene** *(local)* — consult **`/hygiene`** for cleanup candidates.

### Digest
Emit one prioritized card:
- 🚨 **Blocking** — release blocked, RED readiness, failing overnight jobs / CI.
- ⚠️ **Drifted** — off-main / behind repos, version-pin mismatches.
- 🔄 **Resume** — in-flight / parked tasks, open pending-release PRs.
- 🧹 **Cleanable** — cleanup surfaced *for approval*: list it, never auto-act.
- ✅ **Clear** — say so in one line.

End with a one-line verdict — *"clear to work"* or *"N things need you"* — and, in
remote mode, append *"(remote: local sync/clean/hygiene skipped)"*.

Interactive/terminal only — the automated morning Slack webhooks are separate and
unchanged.

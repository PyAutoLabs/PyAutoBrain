# /morning — start the day: sync, clean, and surface what needs you

The human-driven start-of-day door. Run it each morning to bring the workspace to
a clean, current, known-good state and get one prioritized digest of what needs
your attention. A **composition** skill — it drives existing doors and the two
workspace-ops scripts; it owns no state and reasons about nothing new.

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

## The routine

Run these in order from the workspace root, then emit the digest.

1. **Sync** — `bash PyAutoBrain/bin/pull_all_main.sh`. Every repo → its default
   branch, ff-only; repos with real uncommitted work are skipped untouched. Note
   any repo left **off-main / dirty / behind / diverged**.
2. **Clean slate** — `bash PyAutoBrain/bin/clean_slate.sh`. Restore shipped
   datasets, clear `output/`/`scratch/` cruft. (`DRY_RUN=1` to preview.)
3. **Health & release** — consult **`/health`**: the Heart readiness verdict,
   nightly-release status (blocked ↔ green + any blocking issues), red CI, and
   worktree state. Do not recompute these — adopt Heart's verdict.
4. **Digest** — emit one prioritized card:
   - 🚨 **Blocking** — release blocked, RED readiness, failing CI.
   - ⚠️ **Drifted** — off-main / behind repos, version-pin mismatches.
   - 🧹 **Cleanable** — cleanup surfaced *for approval* (stray files, stale
     branches/worktrees): list it, never auto-act.
   - ✅ **Clear** — everything green; say so in one line.

   End with a one-line verdict: *"clear to work"* or *"N things need you"*.

Interactive/terminal only — the existing automated morning Slack webhooks are
separate and unchanged.

## Scope

Phase 1 (this skill) covers sync + clean-slate + `/health` + digest. Later phases
add an overnight-cron sweep, a version-pin drift sweep, resume-context
(in-flight/parked/queued work + open pending-release PRs), and `/hygiene` cleanup
candidates — see `PyAutoMind/issued/morning_routine.md`.

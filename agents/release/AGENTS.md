# Release agent

A specialist **PyAutoBrain** reasoning agent. It decides whether and when a
release should happen, then drives it through the canonical chain:

```
Brain  →  Heart (gate)  →  Build (execute)
```

## Responsibility

1. Refresh and read PyAutoHeart's authoritative readiness verdict
   (`pyauto-heart readiness --json`).
2. **Reason over it** — block unless the verdict is green:
   - **RED** → a real release blocker; refuse (exit 3).
   - **YELLOW** → caution; refuse unless `--force` (exit 2).
   - **GREEN** → proceed.
3. On green, delegate to the PyAutoBuild executor — `autobuild pre_build`, which
   prepares the workspaces and dispatches `release.yml`.

The agent holds **no health logic and no release mechanics of its own**. The
health decision is Heart's; the execution is Build's. The Brain only reasons
about the verdict and decides to proceed.

## Run

```bash
bin/pyauto-brain release           # reason about readiness, release on green
bin/pyauto-brain release --force   # also proceed on yellow (cautions ack'd)
bin/pyauto-brain release -- 2      # forward `2` (minor_version) to pre_build
```

Exit codes: `0` released/delegated · `2` yellow (use --force) · `3` red blocked
· `1/4` could not obtain a verdict / unknown verdict.

## What this agent must never do

- Re-derive or second-guess the readiness verdict (that is Heart's job).
- Run any packaging/tagging/publish step itself (that is Build's job).
- Write into PyAutoHeart or PyAutoBuild repos.

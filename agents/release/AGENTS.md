# Release agent

Drives a PyAuto release through the canonical chain:

```
Agent  →  Pulse (gate)  →  Build (execute)
```

## Responsibility

1. Refresh and read PyAutoPulse's authoritative readiness verdict
   (`pyauto-pulse readiness --json`).
2. **Block** unless the verdict is green:
   - **RED** → a real release blocker; refuse (exit 3).
   - **YELLOW** → caution; refuse unless `--force` (exit 2).
   - **GREEN** → proceed.
3. On green, delegate to the PyAutoBuild executor — `autobuild pre_build`, which
   prepares the workspaces and dispatches `release.yml`.

The agent holds **no gate logic and no release mechanics of its own**. The
decision is Pulse's; the execution is Build's.

## Run

```bash
bin/pyauto-agent release           # gate, then release on green
bin/pyauto-agent release --force   # also proceed on yellow (cautions ack'd)
bin/pyauto-agent release -- 2      # forward `2` (minor_version) to pre_build
```

Exit codes: `0` released/delegated · `2` yellow (use --force) · `3` red blocked
· `1/4` could not obtain a verdict / unknown verdict.

## What this agent must never do

- Re-derive or second-guess the readiness verdict (that is Pulse's job).
- Run any packaging/tagging/publish step itself (that is Build's job).
- Write into PyAutoPulse or PyAutoBuild repos.

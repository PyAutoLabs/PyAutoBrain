---
name: wake-up
description: Superseded morning door — the routine now lives on the Brain board (Pages) plus the local `bin/morning.sh` sync/clean command. Invoked anyway, it runs that local leg and relays `pyauto-brain board`'s digest. Use only when the board is stale or unreachable, or the user explicitly asks for /wake_up.
---

# Wake Up

Follow [`wake_up.md`](wake_up.md) exactly. The morning routine is now the
**Brain board** (`https://<org>.github.io/PyAutoBrain/`) plus one terminal
command (`bash PyAutoBrain/bin/morning.sh`); this skill is the fallback that
runs the same legs interactively. Auto-run only the non-destructive steps and
surface everything destructive for approval.

---
name: morning
description: Start-of-day routine for the PyAuto workspace — sync every repo to its main branch, clean generated cruft (restoring shipped datasets), consult /health for readiness/release/CI, and emit one prioritized morning digest. Use when starting the day or when asked for a morning status/cleanup pass.
---

# Morning

Follow [`morning.md`](morning.md) exactly. Composition skill — drive the existing
doors (`/health`) and the `bin/` scripts; auto-run only the non-destructive steps
(sync, clean-slate) and surface everything destructive for approval.

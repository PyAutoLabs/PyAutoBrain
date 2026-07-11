---
name: review
description: Prepare a PyAuto feature branch ReviewSurface and apply an independent CLEAN, FINDINGS, or BLOCKED judgment for the autonomous ship gate. Use for dev-workflow branch review, not release readiness or implementation fixes.
---

# Review

Read [`../../agents/faculties/review/AGENTS.md`](../../agents/faculties/review/AGENTS.md)
completely, then run `bin/pyauto-brain review --task <name>`. Judge the returned
surface independently and never fix findings inside the faculty invocation.

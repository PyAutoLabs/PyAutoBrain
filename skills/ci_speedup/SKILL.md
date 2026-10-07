---
name: ci-speedup
description: Find the slowest CI parts on the PyAutoHeart board (smoke scripts, unit tests, workflow gates), and drive speed-ups through the dev flow. Use for "why is CI slow", "speed up the smoke tests", or the CI-cost sweep; never modelling speed (/profiling).
---

# CI speed-up

Follow [`ci_speedup.md`](ci_speedup.md) exactly. The Hygiene Agent's `ci`
mode ranks CI cost from the Heart's published measurements and hands out one
📋 per item; this skill is the executor that takes an item, reads the script or
test, names the cost, and drives the fix through `/start_dev` →
`ship_workspace` / `ship_library`. Measurement stays in Heart, the ranking
stays in the Brain, and no fix ships un-timed.

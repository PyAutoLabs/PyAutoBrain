---
name: ci-speedup
description: Pick the slowest parts of CI off the PyAutoHeart board — smoke scripts, unit tests, workflow gates — name why each is slow, and drive the speed-up through the dev flow (a smoke-profile override, an in-script reduction, a cache or CI change), re-timing under the smoke profile before it ships. Use for "why is CI slow", "speed up the smoke tests", or the periodic CI-cost sweep; never for modelling speed (that is /profiling).
---

# CI speed-up

Follow [`ci_speedup.md`](ci_speedup.md) exactly. The Hygiene Agent's `ci`
mode ranks CI cost from the Heart's published measurements and hands out one
📋 per item; this skill is the executor that takes an item, reads the script or
test, names the cost, and drives the fix through `/start_dev` →
`ship_workspace` / `ship_library`. Measurement stays in Heart, the ranking
stays in the Brain, and no fix ships un-timed.

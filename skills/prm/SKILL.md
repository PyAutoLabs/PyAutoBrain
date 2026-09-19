---
name: prm
description: Judge every CI run and matrix leg, merge human-authorized PRs when green, then close the issue and Mind task and clean the worktree. Use for /prm or merge-and-close requests; preserve library-first and data guards.
---

# /prm — PR, CI green, then merge, then close the task out

Follow [`prm.md`](prm.md) exactly; gh + close-out mechanics in
[`reference.md`](reference.md).

Composition door — it owns no agent and re-derives nothing: merge gates from
`/ship_*`, the CI verdict from GitHub Actions, the lifecycle from PyAutoMind, the
render from `/intake`. Typing `/prm` authorizes the **whole** close-out, so it
runs to the end without asking again — but still refuses on red, pending,
conflicting, an unmerged upstream library PR or sibling branch, and asks once
before deleting a worktree holding irreplaceable data products.

Read only the applicable step/environment from linked references, not all files.
Reuse unchanged instructions already loaded; follow [CONTEXT.md](../CONTEXT.md)
for bounded output and repository paths.

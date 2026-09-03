---
name: prm
description: The last thing you type for a task — "PR, CI green, then merge", then the full close-out. Judges a feature PR's checks — every workflow run and every matrix leg — and merges only when all are green (on mobile or web it judges once, reports and stops; the human re-runs it — no subscription, no timer; library-first gate honoured), closes the issue, moves the PyAutoMind prompt active/ → complete/, reconciles and regenerates the Mind dashboard, removes the task worktree and its local branches. Use when the user says merge this PR once CI is green, close this task out, or types /prm. Runs on any GitHub surface — gh on a local CLI, the GitHub MCP tools in a mobile or web session, Codex.
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

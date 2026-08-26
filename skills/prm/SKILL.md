---
name: prm
description: The last thing you type for a task — "PR, CI green, then merge", then the full close-out. Watches a feature PR's checks until every workflow run and every matrix leg is green, merges (library-first gate honoured), closes the issue, moves the PyAutoMind prompt active/ → complete/, reconciles and regenerates the Mind dashboard, removes the task worktree and its local branches. Use when the user says merge this PR once CI is green, close this task out, or types /prm. Runs on any GitHub surface — gh on a local CLI, the GitHub MCP tools in a mobile or web session, Codex.
---

# /prm — PR, CI green, then merge, then close the task out

Follow [`prm.md`](prm.md) exactly; gh + close-out mechanics in
[`reference.md`](reference.md).

Composition door — it owns no agent and re-derives nothing: the merge gates come
from `/ship_library` / `/ship_workspace`, the CI verdict from GitHub Actions, the
lifecycle from PyAutoMind, the dashboard render from `/intake`. Typing `/prm`
authorizes the **whole** close-out — merge, issue close, `active/` →
`complete/`, the dashboard reconciled and regenerated, worktree and local-branch
removal — so it runs to the end without asking again. It still refuses on red, pending,
conflicting, an unmerged upstream library PR, or an unmerged sibling branch, and
asks once before deleting a worktree that holds irreplaceable data products.

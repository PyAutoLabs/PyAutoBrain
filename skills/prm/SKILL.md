---
name: prm
description: The last thing you type for a task — "PR, CI green, then merge", then the full close-out. Watches a feature PR's checks until every workflow run and every matrix leg is green, merges (library-first gate honoured), closes the issue, moves the PyAutoMind prompt active/ → complete/, removes the task worktree and deletes the merged branches. Use when the user says merge this PR once CI is green, close this task out, or types /prm. Runs anywhere gh is authenticated: CLI, mobile Claude Code chat, Codex.
---

# /prm — PR, CI green, then merge, then close the task out

Follow [`prm.md`](prm.md) exactly; gh + close-out mechanics in
[`reference.md`](reference.md).

Composition door — it owns no agent and re-derives nothing: the merge gates come
from `/ship_library` / `/ship_workspace`, the CI verdict from GitHub Actions, the
lifecycle from PyAutoMind. Typing `/prm` authorizes the **whole** close-out —
merge, issue close, `active/` → `complete/`, worktree and branch removal — so it
runs to the end without asking again. It still refuses on red, pending,
conflicting, an unmerged upstream library PR, or an unmerged sibling branch, and
asks once before deleting a worktree that holds irreplaceable data products.

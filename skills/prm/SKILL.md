---
name: prm
description: The wrap-up shortcut — "PR, CI green, then merge". Watch a feature PR's checks until every workflow run and every matrix leg is green, then merge it (library-first gate honoured) and finish the ship — Mind record, issue comment, cleanup. Use when the user says merge this PR once CI is green, or types /prm. Runs anywhere gh is authenticated: CLI, mobile Claude Code chat, Codex.
---

# /prm — PR, CI green, then merge

Follow [`prm.md`](prm.md) exactly; gh mechanics in [`reference.md`](reference.md).

Composition door — it owns no agent and re-derives nothing: the merge gates come
from `/ship_library` / `/ship_workspace`, the CI verdict from GitHub Actions.
Typing `/prm` **is** the merge authorization; the skill still refuses to merge on
red, pending, conflicting, or an unmerged upstream library PR, and still asks
before closing the issue.

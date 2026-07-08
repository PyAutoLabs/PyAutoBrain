---
name: ship-workspace
description: Ship PyAutoLabs workspace and tutorial changes — validate scripts, commit, push, open pending-release PRs behind the library-first merge gate, and update the issue and PyAutoMind task state.
---

# Ship Workspace

Follow [`ship_workspace.md`](ship_workspace.md) in this directory exactly — the
authoritative workflow body (`reference.md` holds the PR format, merge gate and
issue/Mind formats). Shared context and cross-harness notes:
[`../WORKFLOW.md`](../WORKFLOW.md). Shipping a workspace feature is
**feature-dev** work gated by Heart — not a Build task. Preserve the
`## Scripts Changed` PR-body contract and the **library-first merge gate** for
linked workspace PRs. Do not duplicate or reinterpret the workflow here — if it
changes, edit `ship_workspace.md`.

---
name: ship-workspace
description: Ship PyAutoLabs workspace and tutorial repository changes. Use when Codex needs to validate changed scripts, commit, push, create pending-release workspace PRs, enforce the library-first merge gate, cross-reference upstream library PRs, update GitHub issues, and move PyAutoMind task state.
---

# Ship Workspace

A PyAutoBrain development-workflow entry point. Shipping a workspace feature is
**feature-dev** work: dev-workflow → Health Agent → Heart readiness gate →
commit/push/feature-PR/merge, with PyAutoMind holding task state. It is **not** a
Build task — Build is release/packaging only. Shared organ boundary, the
readiness gate and the execution-environment model are in
[`../WORKFLOW.md`](../WORKFLOW.md).

Use `ship_workspace.md` in this directory as the authoritative workflow body
(`reference.md` holds the PR format, merge gate and issue/Mind formats).

Follow the command file exactly, adapting Claude-specific references to Codex:

- `/ship_workspace` means use this skill.
- Slash-command references such as `/smoke_test` refer to the matching Codex
  skill or shared command body.
- If the command file delegates mechanical execution to a Claude subagent, Codex
  should either use an available subagent tool with the same contract or perform
  the same mechanical steps directly.
- Preserve the `## Scripts Changed` PR-body contract and the library-first merge
  gate for linked workspace PRs.

Do not duplicate or reinterpret the workflow here. If the workflow changes, edit
`ship_workspace.md`.

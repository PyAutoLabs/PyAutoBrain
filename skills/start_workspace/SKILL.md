---
name: start-workspace
description: Set up PyAutoLabs workspace or tutorial repository development. Use when Codex needs to attach or create workspace worktrees, inspect upstream library PR API changes, identify affected scripts, register workspace repos in PyAutoMind, and prepare workspace-only or library-follow-up work.
---

# Start Workspace

A PyAutoBrain development-workflow entry point: sets up the worktree/branch for
workspace/tutorial work and registers state in PyAutoMind. Shared organ boundary
and the execution-environment model are in [`../WORKFLOW.md`](../WORKFLOW.md).

Use `start_workspace.md` in this directory as the authoritative workflow body
(`reference.md` holds the long-form formats).

Follow the command file exactly, adapting Claude-specific references to Codex:

- `/start_workspace` means use this skill.
- Slash-command references such as `/ship_workspace` and `/smoke_test` refer to
  the matching Codex skill or shared command body.
- Maintain the library-first rule: linked workspace work follows the upstream
  library PR and must use that PR's API-change summary.

Do not duplicate or reinterpret the workflow here. If the workflow changes, edit
`start_workspace.md`.

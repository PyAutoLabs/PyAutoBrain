---
name: ship-library
description: Ship PyAutoLabs source-library changes — run tests, commit, push, open pending-release PRs, analyze downstream workspace impact, and update the issue and PyAutoMind task state.
---

# Ship Library

A PyAutoBrain development-workflow entry point. Shipping a library feature is
**feature-dev** work: dev-workflow → vitals faculty → Heart readiness gate →
commit/push/feature-PR, with PyAutoMind holding task state. It is **not** a Build
task — Build is release/packaging only (PyPI/tags/notebooks) and `ship_*` reaches
it solely for the release step. Shared organ boundary, the readiness gate and the
execution-environment model are in [`../WORKFLOW.md`](../WORKFLOW.md).

Use `ship_library.md` in this directory as the authoritative workflow body
(`reference.md` holds the PR format, execution contract and impact analysis).

Follow the command file exactly, adapting Claude-specific references to Codex:

- `/ship_library` means use this skill.
- If the command file delegates mechanical execution to a Claude subagent, Codex
  should either use an available subagent tool with the same contract or perform
  the same mechanical steps directly while preserving the judgment/mechanical
  split in the user-facing workflow.
- Preserve the `## API Changes` PR-body contract because `/start_workspace`,
  release review, and downstream workspace migration depend on it.

Do not duplicate or reinterpret the workflow here. If the workflow changes, edit
`ship_library.md`.

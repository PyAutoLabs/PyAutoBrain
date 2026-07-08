---
name: ship-library
description: Ship PyAutoLabs source-library changes — run tests, commit, push, open pending-release PRs, analyze downstream workspace impact, and update the issue and PyAutoMind task state.
---

# Ship Library

Follow [`ship_library.md`](ship_library.md) in this directory exactly — the
authoritative workflow body (`reference.md` holds the PR format, execution
contract and impact analysis). Shared context and cross-harness notes:
[`../WORKFLOW.md`](../WORKFLOW.md). Shipping a library feature is
**feature-dev** work gated by Heart — not a Build task. Preserve the
`## API Changes` PR-body contract — `/start_workspace`, release review, and
downstream workspace migration depend on it. Do not duplicate or reinterpret
the workflow here — if it changes, edit `ship_library.md`.

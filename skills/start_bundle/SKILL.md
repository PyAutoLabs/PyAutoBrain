---
name: start-bundle
description: Run a PyAutoMind bundle — a set of independent tasks worked in one orchestrated session, with one issue and one PR per member. Use when a dashboard Bundles card is copied in, or when several unrelated prompts in the same repo are to be done in one go.
---

# Start Bundle

Follow [`start_bundle.md`](start_bundle.md) in this directory exactly — the
authoritative orchestration contract. Shared context, the capability ladder and
the subagent prompt contract are in [`../WORKFLOW.md`](../WORKFLOW.md). A bundle
is a set of INDEPENDENT tasks: every member still goes through `/start_dev` and
ships its own PR, so `/prm` closes each one out unchanged. Do not duplicate or
reinterpret the contract here — if it changes, edit `start_bundle.md`.

---
name: batch
description: Compose the next unattended batch through the PyAutoBrain Batch Agent — the BatchDecision, planned against the slot's review-minute budget rather than a task count, with backpressure, lane detection and the one-member-per-library-repo rule. Use when picking what to run in a shift, or asking what fits in a review slot. It proposes; approving it in the slot is what launches a batch.
---

# Batch

Read [`batch.md`](batch.md) in this directory — the authoritative body for the
slot door: how to propose a batch, how to compose one from what the human
pasted or described, how to dispatch it, and how to work through what came
back. Then read
[`../../agents/conductors/batch/AGENTS.md`](../../agents/conductors/batch/AGENTS.md)
for the constraints and why each exists.

The one rule that outranks convenience: **the human's go in the conversation is
what launches a batch** (`../../AUTONOMY.md`, "What a batch launch is"). A
schedule may carry the timing; it never carries the authority.

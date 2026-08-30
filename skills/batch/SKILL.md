---
name: batch
description: Compose the next unattended batch through the PyAutoBrain Batch Agent — the BatchDecision, planned against the slot's review-minute budget rather than a task count, with backpressure, lane detection and the one-member-per-library-repo rule. Use when picking what to run in a shift, or asking what fits in a review slot. It proposes; approving it in the slot is what launches a batch.
---

# Batch

Read [`../../agents/conductors/batch/AGENTS.md`](../../agents/conductors/batch/AGENTS.md)
completely, then run `bin/pyauto-brain batch plan` in the documented mode.

Return the **BatchDecision** as written — members, the review-minutes it spends,
and what it rejected with reasons. Do not re-rank it, do not quietly add a
member the planner excluded, and do not present it as a schedule: it is a
proposal, and the human approving it in their slot is what launches the batch
([`../../AUTONOMY.md`](../../AUTONOMY.md), "What a batch launch is"). A
scheduler may carry the timing; it never carries the authority.

Two parts of the output are the point and must survive into your reply: the
**review-minute total** (the budget is the human's hour, not a task count), and
the **other lane's ready count** when the session cannot plan it — *"4 local-dev
tasks are ready, run this from the laptop"*. An empty batch at the backpressure
cap is a finding, not a deadlock; say which.

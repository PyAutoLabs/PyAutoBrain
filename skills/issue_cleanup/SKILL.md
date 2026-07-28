---
name: issue-cleanup
description: Reconcile the PyAuto GitHub issue trackers — audit every open issue against the PyAutoMind completion records and merged PRs, bucket them (shipped / weak evidence / deliberately open / in flight / external / unreconciled), then close only what a human confirms. Use for tracker drift, stale issue backlogs, or "are any of these already done?".
---

# Issue Cleanup

Thin discovery wrapper. The canonical command body is
[`issue_cleanup.md`](issue_cleanup.md) in this directory — follow it exactly;
the long-form detail (header taxonomy, evidence rules, dashboard layout,
per-bucket execution, regression bar) is in [`reference.md`](reference.md).

The issue-tracker counterpart to `$repo-cleanup`'s git-debris sweep: audit →
bucketed dashboard → per-bucket human confirmation → execute → recap.

**Two things to know before running it:**

- **The record header *key* decides everything.** `issue:` means a PyAutoMind
  record completed that issue; `followup-issue:`, `library-followup-issue:`,
  `parent-issue:`, `upstream-issues-filed:` and `plan:` mean the record
  *spawned* it and it is legitimately open. Treat the completing keys as an
  allowlist — a loose `*issue*:` match closes live follow-ups.
- **Closing requires two independent evidence legs** (record header + merged
  PR) and always a human confirmation. The audit half is read-only and safe to
  run unattended; `$wake-up` does exactly that and reports counts only.

Do not duplicate or reinterpret the workflow here — if it changes, edit
`issue_cleanup.md`.

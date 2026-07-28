# Issue Cleanup — reconcile the GitHub issue trackers

Periodic reconciliation sweep across every PyAuto repo's **GitHub issue
tracker**. Finds issues whose work has demonstrably shipped but which were never
closed, separates them from issues that are deliberately open, still in flight,
or owned by the community, and closes only what a human confirms.

Run it as `$issue-cleanup` (`/issue_cleanup` in Claude) — it needs only an
authenticated `gh` and a readable `PyAutoMind/`, so unlike `$repo-cleanup` it
works on **any harness and any environment**, including mobile Claude Code chat
and Codex, with no local library checkout.

A **PyAutoBrain dev-workflow** hygiene skill — the issue-tracker counterpart to
`$repo-cleanup`'s git-debris sweep. Like that skill it **reasons** about what is
safe to close and then runs its own `gh` mechanics: it reads the PyAutoMind
completion records to know what shipped, cross-checks GitHub for merged PRs, and
executes the closes. Cleanup is not release work, so it never touches
PyAutoHands. Organ boundary + execution-environment model:
[`../WORKFLOW.md`](../WORKFLOW.md).

**Distinct from:** `$repo-cleanup` (branches, refs, stashes, worktrees — git
debris, never issues); `$community` (**external** users' issues awaiting *our
reply* — this skill never touches those, it routes them there); `$create-issue`
and `$update-issue` (single-issue primitives); `$hygiene` (code-quality debt, not
the tracker).

## Why this needs care

The obvious rule — *"a PyAutoMind `complete/` record references this issue, so
close it"* — is **wrong five different ways**. Each was found by verification,
not inspection: four during the 2026-07-28 sweep that took the trackers from 82
open to 47, and the fifth when this skill's own regression bar was first run
against that result. Encode all five or the skill will close live work:

1. **Body mentions are not claims.** Grepping record *files* for an issue URL
   over-matches. `complete/2026/05/many-vis-prep-dft.md` discusses
   `PyAutoArray#326` in its prose while its own `- issue:` header reads
   `(CI-triage cluster G, no GitHub issue)`. **Only the header line is
   evidence.**

2. **The header *key* carries the meaning.** This is the load-bearing rule.
   `issue:` means *this record completes that issue*. The spawn-style keys mean
   the **opposite** — the record *created* that issue and it is legitimately
   open. Full taxonomy in [`reference.md`](reference.md); matching loosely on
   `*issue*:` closes live follow-ups.

3. **Inline annotations override everything.** Records mark deliberate
   exceptions in the text after the URL: `(open — findings census stays as
   reference)`, `(STAYS OPEN — real finding + resumable fit)`. Any `open` token
   means hands off — and these appear on `plan:` lines too, not just `issue:`.

4. **A record in `complete/` does not mean the *work* completed.**
   `ep-hierarchical-scale-collapse.md` carries `Status: issued` — it *filed*
   `PyAutoFit#1405` and reported two defects on it. The record is complete; the
   issue is a live bug. **Read the status field, not the directory.**

5. **A phase-scoped claim does not complete an umbrella issue.** Four separate
   records each claim a *Phase 5 item* of `PyAutoBrain#130` — `(Phase 5 item 4)`,
   `(Phase 5 F5 item)`, and so on. Each finished its piece; none establishes the
   issue is done. Scoped claims go to bucket B for a human, never to A.

And a corroborating sixth: `PyAutoReduce#8`'s record already said `(CLOSED)`
while GitHub still had it open. Closes silently fail to land, which is part of
why reconciling is worth doing at all.

## Safety principles (non-negotiable)

1. **Audit first, act second.** The audit is read-only and safe to run
   unattended. Nothing closes without an explicit per-bucket confirmation.
2. **Two independent evidence legs** before an issue is even *proposed* for
   closing: a completing header key in a record, **and** a merged PR.
3. **Never close an external user's issue.** Author not in the maintainer set →
   bucket E, routed to `$community`, never closed here.
4. **Never close anything claimed** in `PyAutoMind/active.md` / `parked.md`.
5. **Age is not evidence.** A 2700-day issue may still be valid; probe whether
   the API or infrastructure it names still exists (see "Obsolescence" below).
6. **Every close leaves a comment naming its evidence** (record path + PR), so
   the decision is auditable and reversible.

## Scope

**Swept:** every repo in `PyAutoMind/repos.yaml` with an issue tracker — the
organs, the libraries, the workspaces incl. `_test`/`_developer` variants, the
HowTo repos and the assistants.

**Never touched:** pull requests (the issues endpoint returns them too — filter
`select(.pull_request == null)`); issues in bucket C, D or E.

## Steps

### 1. Setup

Confirm `gh auth status`; if unauthenticated, stop. Resolve repo owners from
`PyAutoMind/repos.yaml` — do not hard-code legacy owner defaults.

### 2. Audit (read-only)

Collect every open issue, then build the evidence sets from the PyAutoMind
records. Commands, the header taxonomy, and the annotation rule:
[`reference.md`](reference.md) → "Collect open issues", "Parse the records",
"Evidence legs".

### 3. Dashboard

Present the audit grouped into fixed buckets A–F (omit empty buckets; always
print the Summary counts). Layout: [`reference.md`](reference.md) → "Dashboard
layout".

### 4. Per-bucket confirmation + execution

Work the buckets in the fixed order, printing what will be closed and getting
approval before each destructive step. Recipes: [`reference.md`](reference.md)
→ "Per-bucket execution".

### 5. Recap

Print what closed, what was held back and why, so the next sweep resumes from
there. Format: [`reference.md`](reference.md) → "Recap".

## Obsolescence needs a real check, not an age threshold

The eight oldest issues in the first sweep split on **evidence**, not age:

- The six `PyAutoCTI` ones (2693–2785 days) named `FrameGeometry`, `CIFrame`,
  `CIData`, `ci_data_analysis`, `ci_pattern`, and the `phase.py` / `pipeline`
  module. A grep of `autocti/` returned **zero** for every one — the CTI
  resurrection removed that surface entirely — so they closed `not_planned`.
- `PyAutoHands#16` (test against pre-release deps) and `#17` (fail the build if
  the RTD docs build fails) are the same vintage (~1337 days) but were **left
  open**: no `--pre` workflow and no RTD gating exist in
  `PyAutoHands/.github/workflows/`, so they are still-valid unimplemented asks.

Age correlates with obsolescence; it never establishes it. Probe whether the
named API or infrastructure still exists before proposing a close.

## Notes

- `gh issue close` is broken in this environment — comment, then
  `gh api -X PATCH … -f state=closed`. Full recipe in [`reference.md`](reference.md).
- Bot-authored self-refreshing issues (`[url-check]`, `[heart-health]`) are
  recognised and excluded from staleness ranking — they are a live signal, not
  debris.
- `$wake-up` runs the **audit half only** and reports counts in its digest;
  every close still comes back through this skill's confirmation.
- If a record's claim and GitHub disagree, trust GitHub for *state* and the
  record for *intent* — then reconcile, and say which one was stale.

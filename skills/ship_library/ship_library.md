# Ship Library: Gate, Test, PR

Ship source-library changes (PyAutoNerves, PyAutoFit, PyAutoArray, PyAutoGalaxy,
PyAutoLens) for every library repo touched by the task. This is
**feature-development** work — the commit/push/feature-PR is the dev workflow's
own execution, gated by Heart. It is **not** a Build task (Build is
release/packaging only; `ship_*` reaches it solely for the release step):

```
ship_library → Brain dev-workflow → Brain vitals faculty → Heart (GREEN/YELLOW/RED) → commit / push / feature-PR
```

Workflow entry point — not an agent. Read [`../WORKFLOW.md`](../WORKFLOW.md) for
the organ boundary, the readiness gate, and the execution-environment model.
PR format, the execution contract, and the impact analysis are in
[`reference.md`](reference.md).

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Steps

### 1. Identify affected repos (Mind)

Read `PyAutoMind/active.md` for the task's `worktree:` and `repos:` list.

```bash
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
WT_ROOT=~/Code/PyAutoLabs-wt/<task-name>
source "$WT_ROOT/activate.sh"
```

Legacy entries with no `worktree:` fall back to the main checkouts — warn that
the task pre-dates the worktree flow and is not parallel-safe. In other execution
environments (web-github / ci-only), use the working-directory clones with
`PYTHONPATH` exported (WORKFLOW.md).

### 2. Draft commit message + PR body (reasoning model)

For each repo, inspect the diff against `main` and draft a concise commit message
and the full PR body. Writing the `## API Changes` section is judgement-heavy and
stays in the reasoning model — follow [`reference.md`](reference.md) → "Writing
the `## API Changes` section" and "Full PR format".

### 3. Gate readiness through the vitals faculty → Heart

Consult the Brain vitals faculty, which is the only one that talks to the Heart
organ (do **not** route this through the Build Agent — shipping a feature is not
a release):

```bash
bin/pyauto-brain vitals              # reason over the readiness surface (vitals faculty → Heart)
pyauto-heart readiness --json        # authoritative GREEN / YELLOW / RED
```

The library test suites are part of Heart's verdict — they run as the gate, not
as an ad-hoc step the skill re-judges. **GREEN** → proceed to step 4.
**YELLOW** → surface warnings, proceed only on explicit user acknowledgement.
**RED** → stop and report; an autonomous run parks. After surfacing the exact
current RED reasons verbatim from `pyauto-heart readiness` and passed applicable
tests/smoke/review, a live human may authorize the canonical `AUTONOMY.md`
"Human override for Heart RED (development only)" or the narrower
"Corrective-PR exception for Heart RED" for a causal fix. Follow the selected
canonical section's scope and four record sinks exactly. Neither path permits
release or bypassing CI; merge requires its own current human command and green
required GitHub checks. If `pyauto-brain`/`pyauto-heart` are
unavailable, run the per-repo `pytest <test_dir>/ -x` inside the worktree as the
gate and treat any failure as RED (WORKFLOW.md). Under `--auto`, this step is
the four-leg **autonomous-ship gate** — tests (+ downstream dependents on
public-API changes), smoke, review-faculty CLEAN, Heart — per
`AUTONOMY.md` "The autonomous-ship gate"; do not restate it here.

### 4. Execute the ship (feature-dev)

On GREEN, run the dev workflow's own test → commit → push → feature-PR step per
[`reference.md`](reference.md) → "Execution contract": run tests inside the
worktree, confirm the branch is `feature/<task-name>` (never auto-switch),
commit, push, `gh pr create --label pending-release`, and verify the label
landed. This is feature-development git work, not a Build/release step. In
local-dev Anthropic delegates the mechanical part to its execution tier;
OpenAI runs it inline unless a bounded exception applies. Elsewhere run it
directly. If any step fails, stop and report — do not proceed.

**Under `--auto`:** all four legs of the autonomous-ship gate must pass — **five under a batch launch**, which adds the independent-adversary leg (`AUTONOMY.md` leg 5) — (step
3 note); then ship **without interactive sign-off** — the PR body additionally
carries the `## Validation checklist` section
([`reference.md`](reference.md) → "Validation checklist (--auto)"), the run
**stops at PR-open** (merge stays human, always), a calibration row is
appended to `PyAutoMind/autonomy_log.md` (its **first** table, never the
Shadow window at the end — [`reference.md`](reference.md) → "Which table"),
and `active.md` moves to
`library-shipped, awaiting-merge`. Any failed leg → park per
[`../../AUTONOMY.md`](../../AUTONOMY.md): write state to the issue, never
modify code to make a leg pass, nothing force-shipped.

### 5. Workspace impact + routing

Analyse downstream workspace impact and present data-driven options — see
[`reference.md`](reference.md) → "Workspace-impact analysis":

- **(i)** new demos / **(ii)** API migration → `/start_workspace` next; post a
  "Library PR Created" progress comment, set `active.md` to
  `library-shipped, workspace-pending`, add `library-pr:`, push Mind.
- **(iii)** no workspace impact → run `/smoke_test` (with `activate.sh` sourced).
  On pass, offer to merge the library PR, post a "Shipped" comment, write the
  dated completion record (`lifecycle.py record` — also refreshes the index
  and prunes the `active.md` entry), push Mind. On fail, report and suggest `/start_workspace`
  (likely option ii); do not merge, do not clean up `active.md`.

Comment templates and Mind-state transitions are in [`reference.md`](reference.md)
→ "Issue comments + Mind state".

**Under `--auto`:** run the same analysis but never merge and never offer to —
post the data-driven recommendation (i/ii/iii, affected scripts) to the issue
and end the run at PR-open. Routing into `/start_workspace` happens on the
next human (or queued) launch.

## Notes

- This skill ships **library source only** — workspace scripts/notebooks go
  through `/ship_workspace`.
- Waiting on CI before the merge is [`/prm`](../prm/prm.md) — the close-out door
  that judges every run/leg, merges in library-first order, then runs this
  skill's completion contract itself (Shipped comment, issue closed, Mind record,
  worktree + branches removed).
- Never skip the readiness gate; never `--no-verify`; fix the underlying issue.

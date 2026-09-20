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

A task with a real `worktree:` uses it. A clone+shell surface without a task
worktree may use its working-directory clone with the documented environment
settings. A **GitHub-control-only** task deliberately has no `worktree:`:
resolve each claimed `repos:` branch and exact head commit through GitHub,
inspect its diff against `main`, and never fall back to a canonical local
checkout that this surface does not possess.

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
required GitHub checks. If the organism CLIs are unavailable, use WORKFLOW.md's capability/evidence
rules rather than weakening the gate:

- a runtime-capable surface runs the required per-repo tests/smoke directly;
- a no-runtime GitHub-control surface may consume **existing exact-head GitHub
  Actions evidence** only when the workflow/legs cover the required test scope;
  verify the branch head SHA and each relevant conclusion;
- if the required execution evidence is absent, hand off only that validation
  phase;
- CI is never a Heart verdict. Read fresh authoritative Heart readiness evidence
  from an available Heart surface; if that cannot be obtained here, obtain only
  that bounded evidence before shipping.

Under `--auto`, this step is the four-leg **autonomous-ship gate** — tests
(+ downstream dependents on public-API changes), smoke, review-faculty CLEAN,
Heart — per `AUTONOMY.md` "The autonomous-ship gate"; do not restate it here.
A same-conversation reread is not an independent review.

### 4. Execute the ship (feature-dev)

On a Heart outcome permitted by WORKFLOW.md / AUTONOMY.md, execute the dev
workflow's test/evidence → commit/push → feature-PR step per
[`reference.md`](reference.md) → "Execution contract". A local worktree runs
the commands there. A GitHub-control-only surface verifies the existing remote
feature branch and exact head, uses repository/GitHub write operations for the
remaining commit/PR mechanics, and verifies required exact-head Actions
evidence. It must not claim a local test it did not run. If generation, imports
or another runtime step is still required, perform the bounded execution
handoff before PR-ready status.

This is feature-development git work, not a Build/release step. Provider model
delegation still follows MODEL_DELEGATION.md; capability absence is handled by
its cross-environment handoff rather than by provider-name conditionals. If any
step or evidence leg fails, stop and report — do not proceed.

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

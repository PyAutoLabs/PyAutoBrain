# Ship Workspace: Gate, Validate, PR

Ship workspace / tutorial changes (autofit_workspace, autogalaxy_workspace,
autolens_workspace, autolens_workspace_test, euclid_strong_lens_modeling_pipeline,
HowToLens) for every workspace repo touched by the task. This is
**feature-development** work, gated by Heart — **not** a Build task (Build is
release/packaging only). Same flow as `/ship_library`:

```
ship_workspace → Brain dev-workflow → Brain vitals faculty → Heart (GREEN/YELLOW/RED) → smoke / commit / push / feature-PR / merge
```

Ships **scripts, notebooks and configs only** — never library source. Workflow
entry point, not an agent. Read [`../WORKFLOW.md`](../WORKFLOW.md) for the organ
boundary, readiness gate and execution-environment model; PR format, merge gate
and issue/Mind formats are in [`reference.md`](reference.md).

## Steps

### 1. Identify affected workspace repos (Mind)

Read `PyAutoMind/active.md` for the task's `worktree:` and `repos:` list.

```bash
source PyAutoBrain/bin/worktree.sh
WT_ROOT=~/Code/PyAutoLabs-wt/<task-name>
source "$WT_ROOT/activate.sh"
```

In-scope repos are the workspace/tutorial repos only. If any **library** repo has
uncommitted changes in the worktree, stop and tell the user to ship them with
`/ship_library`. Legacy/no-worktree and other execution environments behave as in
WORKFLOW.md (working-directory clones, manual `PYTHONPATH`).

### 2. Draft commit message + PR body (reasoning model)

Per repo, inspect the diff and draft a concise commit message and the full PR
body — which **must** include `## Scripts Changed`. If a "Library PR Created"
comment exists on the issue, capture the library PR URL for `## Upstream PR`.
Format in [`reference.md`](reference.md) → "PR body format".

### 3. Gate readiness through the vitals faculty → Heart

Consult the Brain vitals faculty (not the Build Agent — shipping a feature is not a
release):

```bash
bin/pyauto-brain vitals              # reason over the readiness surface (vitals faculty → Heart)
pyauto-heart readiness --json        # GREEN / YELLOW / RED
```

Workspace **smoke tests** are part of Heart's verdict. **GREEN** → execute.
**YELLOW** → proceed only on explicit acknowledgement. **RED** → stop. If the
organism CLIs are unavailable, run `/smoke_test` (with `activate.sh` sourced) as
the gate and treat any failure as RED. Under `--auto`, this step is the
four-leg **autonomous-ship gate** (`AUTONOMY.md` "The autonomous-ship gate");
do not restate it here.

### 4. Execute the ship (feature-dev)

On GREEN, run the dev workflow's own commit → push → smoke → feature-PR →
cross-reference step per
[`reference.md`](reference.md) → "Execution contract": verify the branch (never
auto-switch), regenerate notebooks from scripts (never edit `notebooks/`
directly), `gh pr create --label pending-release`, verify the label, and
cross-reference the upstream library PR if linked. In local-dev delegate to a
execution-tier subagent; elsewhere run directly. Any failure → stop and report.

**Under `--auto`:** all four legs of the autonomous-ship gate must pass (step
3 note); ship without interactive sign-off, add the `## Validation checklist`
to the PR body (`../ship_library/reference.md` → "Validation checklist
(--auto)"), **stop at PR-open**, append the calibration row to
`PyAutoMind/autonomy_log.md`, set `active.md` to awaiting-merge. Failed leg →
park per [`../../AUTONOMY.md`](../../AUTONOMY.md). Step 5's merge is skipped
entirely — merge stays human.

### 5. Merge (library-first gate)

Offer to merge (never force). If linked to an upstream library PR, enforce the
**library-first merge gate** — the library PR must be `MERGED` before the
workspace PR may merge; refuse otherwise (no `gh pr merge --auto`-flag
workaround — unrelated to the workflow's `--auto` mode, which never merges).
See [`reference.md`](reference.md) → "Library-first merge gate".

### 6. Complete the issue + Mind state

Detect the issue, generate a session summary, post a "Shipped" comment, move the
task from `active.md` to `complete.md`, and push Mind. Templates in
[`reference.md`](reference.md) → "Issue completion + Mind state".

## Notes

- Workspace scripts/notebooks/configs only — never library source.
- Only edit `scripts/`; notebooks are regenerated.
- Never skip the readiness gate or the library-first merge gate.

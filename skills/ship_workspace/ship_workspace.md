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

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Steps

### 1. Identify affected workspace repos (Mind)

Read `PyAutoMind/active.md` for the task's `worktree:` and `repos:` list.

```bash
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
WT_ROOT=~/Code/PyAutoLabs-wt/<task-name>
source "$WT_ROOT/activate.sh"
```

In-scope repos are the workspace/tutorial repos only. If a local worktree has
uncommitted **library** changes, stop and ship them through `/ship_library`.
A GitHub-control-only task has no local dirty-state claim to make: resolve each
workspace branch and exact head through GitHub and inspect the remote diff.

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
**YELLOW** → proceed only on explicit acknowledgement. **RED** → stop; an
autonomous run parks. After surfacing the exact current RED reasons and passed
applicable tests/smoke/review, including the reason strings verbatim from
`pyauto-heart readiness`, a live human may authorize the canonical
`AUTONOMY.md` "Human override for Heart RED (development only)" or the narrower
"Corrective-PR exception for Heart RED" for a causal fix. Follow the selected
canonical section's scope and four record sinks exactly. Neither path permits
release or bypassing CI; merge requires its own current human command and green
required GitHub checks. If the organism CLIs are unavailable, use WORKFLOW.md's capability/evidence
rules: run smoke locally when a runtime exists; otherwise consume existing
**exact-head** Actions evidence only when its jobs exercise the required smoke
scope, or hand off only that validation phase. Notebook generation or other
required generated artefacts also require a real runtime and cannot be inferred
from source edits. CI never substitutes for Heart: obtain fresh authoritative
Heart readiness evidence separately, or stop at that missing evidence.

Under `--auto`, this step is the four-leg **autonomous-ship gate**
(`AUTONOMY.md` "The autonomous-ship gate"); do not restate it here. A
same-conversation reread is not an independent review.

### 4. Execute the ship (feature-dev)

On a Heart outcome permitted by WORKFLOW.md / AUTONOMY.md, perform the
feature-dev commit/push/validation/PR/cross-reference contract. A local runtime
regenerates notebooks from scripts and runs smoke normally. A
GitHub-control-only surface may perform branch/commit/PR operations but **must
delegate notebook generation and any missing smoke/runtime evidence** before the
branch is PR-ready; it then verifies the returned commit and exact-head checks.
Never edit generated notebooks by hand to avoid the execution requirement.

Provider model delegation still follows MODEL_DELEGATION.md; missing capability
uses its bounded cross-environment handoff. Any failed step or evidence leg →
stop and report.

**Under `--auto`:** all four legs of the autonomous-ship gate must pass — **five under a batch launch**, which adds the independent-adversary leg (`AUTONOMY.md` leg 5) — (step
3 note); ship without interactive sign-off, add the `## Validation checklist`
to the PR body (`../ship_library/reference.md` → "Validation checklist
(--auto)"), **stop at PR-open**, append the calibration row to
`PyAutoMind/autonomy_log.md` (its **first** table, never the Shadow window at
the end — `../ship_library/reference.md` → "Which table"), set `active.md` to
awaiting-merge. Failed leg →
park per [`../../AUTONOMY.md`](../../AUTONOMY.md). Step 5's merge is skipped
entirely — merge stays human.

### 5. Merge (library-first gate)

Offer to merge (never force). If linked to an upstream library PR, enforce the
**library-first merge gate** — the library PR must be `MERGED` before the
workspace PR may merge; refuse otherwise (no `gh pr merge --auto`-flag
workaround — unrelated to the workflow's `--auto` mode, which never merges).
See [`reference.md`](reference.md) → "Library-first merge gate".

**Blocked behind an unreleased library?** Merged is not released, and a
workspace change that needs the new API cannot ship until the library is on
PyPI. Record that on the `active.md` row:

```markdown
- release-gate: <LibraryRepo>
```

one line per library. The Mind dashboard's **Pending release** section lists
the task under that library's pending PRs, so the block is visible without a
GitHub query — `PyAutoMind/REFERENCE.md` → "The pending-release chain".

### 6. Complete the issue + Mind state

Detect the issue, generate a session summary, post a "Shipped" comment, write
the dated completion record (`lifecycle.py record` — also refreshes the index
and prunes the `active.md` entry), and push Mind. Templates in
[`reference.md`](reference.md) → "Issue completion + Mind state".

## Notes

- Workspace scripts/notebooks/configs only — never library source.
- If CI is still running when step 5 arrives, [`/prm`](../prm/prm.md) is the door
  that waits for every run/leg, merges behind the library-first gate, and then
  performs step 6 plus the post-merge cleanup itself.
- Only edit `scripts/`; notebooks are regenerated.
- Never skip the readiness gate or the library-first merge gate.

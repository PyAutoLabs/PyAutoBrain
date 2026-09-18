# PyAuto workflow skills — shared reference

The `start_*` and `ship_*` skills are entry points, not independent reasoning
systems. Mind owns task state, Brain plans and coordinates, Memory supplies
read-only context, Heart gates shipping, and Hands handles releases only.

## Call chains

```text
start_dev      → Brain feature decision → Mind task + plan → start_library/workspace
ship_*         → Brain review/vitals → Heart gate → commit/push/feature PR
release        → Brain release decision → Heart gate → Hands
```

Development worktrees, commits, and feature PRs belong to the dev workflow,
not Hands. Autonomy checkpoints are defined once in `../AUTONOMY.md`; default
runs present and wait, while explicit `--auto` runs follow that contract.

## Brain entry points

```bash
bin/pyauto-brain feature <prompt>
bin/pyauto-brain review --task <name>
bin/pyauto-brain vitals
bin/pyauto-brain build --dry-run
```

If Brain is unavailable, emulate the requested decision from `PyAutoBrain/AGENTS.md`
and this file, and say that it was emulated.

## Model delegation

Provider policies are intentionally asymmetric. Anthropic retains mandatory
execution delegation: Fable → Opus and Opus → Opus, with Sonnet only for the
documented mechanical floor. OpenAI performs routine sequential edits, tests,
and git steps inline; use Sol workers selectively for independent parallel
work, substantial noisy execution or independent progress, and independent
review. Wall-clock duration alone does not force a worker. A Brain role or faculty
consultation does not itself require a new LLM worker.

Read [`MODEL_DELEGATION.md`](MODEL_DELEGATION.md) before assigning a worker. It
contains the preserved Anthropic heartbeat, mechanical, tutorial, bundle, and
Cortex rules plus the bounded worker contract.

## Memory and planning

For substantial architectural or scientific planning, consult
`bin/pyauto-brain memory "<topic>"`, read only the cited pages, and proceed
honestly when it has no matches. PyAutoMemory citations never enter public
user-facing output.

`start_dev` produces both a short human plan and a detailed issue plan, surveys
only affected repos, then uses Mind's `create_issue` primitive. Do not duplicate
issue or lifecycle mechanics in Brain.

## Heart gate

Before `ship_*`, use the vitals faculty for the authoritative verdict:

- GREEN: continue.
- YELLOW: show exact reasons and require the acknowledgement defined by the
  autonomy contract.
- STALE: may pass for development only as defined by the canonical Heart
  contract; it remains a release blocker.
- RED: stop. After the exact reason strings are quoted verbatim from the
  current Heart verdict and validation is shown, a live human may use
  `AUTONOMY.md` "Human override for Heart RED (development only)" or the
  narrower "Corrective-PR exception for Heart RED". Neither permits a release,
  CI bypass, or merge.

Applicable tests, downstream smoke checks for public API changes, independent
review, and Heart form the ship gate. Merge is always a current human action.

## Cross-harness behavior

- `/name` means use that skill; skill-aware harnesses follow its `SKILL.md`.
- Plan Mode means present-and-wait unless explicit `--auto` changes that gate.
- With no prompt, first create a concise Mind draft containing the original
  request verbatim.
- If a requested worker is unavailable, execute directly without weakening
  permissions, review, or health gates.
- `gh` commands name GitHub operations; remote sessions translate them through
  `GITHUB_ACCESS.md`.

## Task state and worktrees

Mind paths are workspace-root-relative: `PyAutoMind/active.md`, `planned.md`,
and prompt lifecycle `draft/ → active/ → complete/YYYY/MM/`. Use Mind's
lifecycle and prompt-sync scripts; do not hand-roll state transitions.

Local tasks use `PyAutoBrain/bin/worktree.sh` and
`feature/<task-name>` branches. `worktree_check_conflict` fails closed when it
cannot read the registry. A repo bullet beneath an active task's `repos:` is a
claim; tasks touching the same repo serialize unless a human explicitly
authorizes coordination. Source the generated `activate.sh` before Python or
tests.

In web/CI sessions, use available clones and explicit cache/PYTHONPATH settings.
The same Mind registry provides continuity across environments.

## Repository routing

<!-- repos_sync:begin -->
All repos live at `PyAutoLabs/<local dir name>` on GitHub, except: `Jammy2211/euclid_assistant`, `Jammy2211/admin_jammy`.

**Library repos:** PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens, PyAutoReduce, PyAutoCTI.
**Workspace repos:** autofit_workspace, autogalaxy_workspace, autolens_workspace, autocti_workspace, autoreduce_workspace, autofit_workspace_test, autogalaxy_workspace_test, autolens_workspace_test, autocti_workspace_test, HowToFit, HowToGalaxy, HowToLens, euclid_strong_lens_modeling_pipeline.

Generated from `PyAutoMind/repos.yaml`; edit there, then run `python3 PyAutoMind/scripts/repos_sync.py --write`.
<!-- repos_sync:end -->

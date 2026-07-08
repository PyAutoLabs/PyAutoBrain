# PyAuto workflow skills — shared reference

The `start_*` / `ship_*` / `register_and_iterate` skills are the
**development-workflow entry points** of the PyAuto organism. They are *not*
independent reasoning systems: each one is a thin entry point that delegates to
the organs. This file is the shared context every workflow skill points at, so
the individual skill files can stay short.

## Organ boundary (who owns what)

The organs and boundaries are defined once in
[`../ORGANISM.md`](../ORGANISM.md). What the workflow skills need to know on
top of that: Mind owns the workflow **state** (`active.md` / `planned.md` /
`complete.md`, the prompt taxonomy), and Build owns **no dev-workflow skills**
— it is the release/packaging executor only.

A workflow skill reasons through **Brain**, gates ship through **Heart**, records
state in **Mind**, and pulls context from **Memory**. The **dev-workflow's own
git mechanics** (worktrees, branches, commits, feature PRs) are part of feature
development — they are **not** Build's job. **Build is release work only**
(PyPI/tags/notebooks); `ship_*` *calls* Build only at actual release time. A
skill never re-implements another organ's job.

## The call chains

```
start_dev      →  Brain Feature Agent  →  Mind task  +  Memory context  →  plan  →  start_library/start_workspace
ship_library   →  Brain dev-workflow   →  Brain vitals faculty  →  Heart (GREEN/YELLOW/RED)  →  commit / push / feature-PR
ship_workspace →  Brain dev-workflow   →  Brain vitals faculty  →  Heart  →  commit / push / feature-PR
release (later)→  Brain Build/Release Agent  →  Brain vitals faculty  →  Heart  →  PyAutoBuild (tag / notebooks / PyPI)
```

`ship_*` is **feature-development** work: the commit/push/feature-PR is the dev
workflow's own execution, gated by Heart. It is **not** a Build task. Build is
release/packaging only; `ship_*` reaches Build solely to trigger the release step
once changes are ready to publish.

Brain agents consult one another — e.g. the Build Agent never queries Heart
directly; it asks the vitals faculty, and only the vitals faculty talks to the Heart
organ. The same applies when the dev workflow consults the vitals faculty for its
ship gate.

## Autonomy (how much human checkpointing)

The human checkpoints across these skills — plan approval, ship PR sign-off,
Heart YELLOW acknowledgement, merge/close, the `pre_build` version ask,
post-merge cleanup — are governed by **the autonomy contract**,
[`../AUTONOMY.md`](../AUTONOMY.md): what each Mind-prompt `Autonomy:` level
(`safe`/`supervised`/`human-required`) does at each checkpoint, the
per-work-type caps, and the hard invariants (merge is always human; autonomous
runs end at PR-open). Levels bind **only** under an explicit `--auto` launch;
default runs present-and-wait at every checkpoint, exactly as the steps below
describe. Do not restate checkpoint rules in a skill body — link the contract.

## Brain agent entry points

Reasoning is delegated to PyAutoBrain agents (`PyAutoBrain/AGENTS.md` is authoritative):

```bash
bin/pyauto-brain feature [<work-type>/<target>/<task>.md]  # classify + plan a task (Feature/Bug/Refactor/… routing)
bin/pyauto-brain build   [--dry-run]                       # consult vitals, then delegate execution to Build
bin/pyauto-brain release                                   # release door → Build Agent release mode (gate + pre_build)
bin/pyauto-brain vitals                                    # one health tick + the unified dashboard card
```

If a dedicated agent for a work type does not exist yet (e.g. Bug/Refactor/Docs),
the Feature Agent's routing applies the closest available reasoning and the
missing agent is recorded as a follow-up — the skill still runs end-to-end.

When `pyauto-brain` is not on `PATH` and no PyAutoBrain checkout is present
(e.g. a GitHub-only session), perform the same reasoning inline following this
file and `PyAutoBrain/AGENTS.md`, and note that the agent was emulated.

## Model delegation (judgment tier plans, execution tier ships)

The workflow skills split work across **model tiers**, not named models — the
doctrine survives model access changing:

- **Judgment tier** — the strongest model available to the session (currently
  **Fable 5**; previously, and as fallback, **Opus**). Planning, orchestration,
  risk judgment, anything user-facing.
- **Execution tier** — a fast, cheap model (currently **Sonnet**) for
  mechanical shell/git phases, delegated as subagents (`Agent` tool,
  `model: "sonnet"`).

The main session stays on the judgment tier; bulk execution moves to the
execution tier — no manual model toggling.

**Delegated (mechanical phase only):**

- `ship_library` — step 3 (test, commit, push, open PR).
- `ship_workspace` — step 3 (commit, push, smoke test, open PR, cross-reference).
- `pre_build` — step 2 (format, generate, version bump, stage, commit, push,
  dispatch workflow).

**Stays in the judgment tier:** planning (`start_dev`), environment setup
(`start_library`/`start_workspace`), release triage (`review_release`);
identifying affected repos, drafting the commit message and full PR body
(`## API Changes` / `## Scripts Changed`), workspace-impact analysis, the
library-first merge gate, the merge decision, `active.md` / `complete.md`
updates, and final issue comments. In `pre_build`: validating clean `main`,
asking for the minor version, printing the summary.

**Subagent prompt contract (all delegated calls):**

- **Inputs the judgment tier passes:** worktree path / `$WT_ROOT`, repo list,
  pre-drafted commit message, pre-drafted PR body (paste verbatim via HEREDOC —
  never rewrite), relevant URLs (library PR, issue), target branch, labels.
- **Subagent's job:** run the named shell steps exactly. `source activate.sh`
  before `pytest` / `smoke_test`. Verify the branch is `feature/<task-name>`
  before committing — never auto-switch branches. **Never modify code to make
  tests or smoke tests pass.** On failure, stop and return the failure verbatim
  (failing test names + traceback tail, or the shell error).
- **Subagent returns:** one line per repo — test/smoke pass-fail counts, commit
  SHA, PR URL, cross-reference/dispatch confirmations.
- **Judgment tier after return:** interpret failures, decide routing, update
  registries, talk to the user.

**Tutorial-prose split** (separate from skill delegation — depends on what the
reader is there to learn):

- **Judgment tier** for narrative science-teaching scripts where the
  docstrings/comments are the product: tutorials in `autofit_workspace`,
  `autogalaxy_workspace`, `autolens_workspace` (`overview_*`, `start_here.py`,
  `howto*`). Execution-tier models drift to generic textbook phrasing and miss
  domain framing here.
- **Execution tier** for code-heavy, doc-light scripts where comments are short
  API-usage notes: `*_workspace_test`, `euclid_strong_lens_modeling_pipeline`
  glue, and developer/regression/smoke/parity scripts.
- Heuristic: *"is the reader here to learn science, or to exercise code?"*
  Science → judgment tier. Code → execution tier.

## Consult Memory before substantial planning

Before committing to a plan, consult **PyAutoMemory** whenever historical,
scientific or architectural context would improve the decision — prior
architectural decisions, literature summaries, previous implementations,
previously failed approaches, coding conventions, design rationale. Memory is
read-only context; do not couple to its internal layout (read its wikis /
`reading-queue.md` / bibliography on demand). The Feature Agent does this for
feature work; do it directly when running a skill without the agent.

## Heart readiness gate (for ship_*)

```bash
pyauto-heart readiness --json    # authoritative GREEN / YELLOW / RED verdict
```

- **GREEN** → proceed to execution.
- **YELLOW** → surface the warnings; proceed only with explicit user
  acknowledgement (a human checkpoint at **every** autonomy level —
  [`../AUTONOMY.md`](../AUTONOMY.md)).
- **RED** → stop; report what failed. Do not ship.

Tests/smoke runs that feed the verdict are Heart's domain — invoke them through
the vitals faculty rather than re-deriving pass/fail criteria in the skill.

## Cross-harness notes (apply to every workflow skill)

- `/name` references mean "use that skill"; a harness without slash commands
  follows the same body file directly.
- "Plan Mode" means: present the plan and wait for explicit user approval
  before any file edit (checkpoint 1 of [`../AUTONOMY.md`](../AUTONOMY.md);
  under an explicit `--auto` launch the contract's level table applies).
- If the user gives a development task with **no** PyAutoMind prompt path,
  first write a concise prompt under the right `<work-type>/<target>/` folder
  (original request verbatim), then continue with that path.
- Where a body delegates mechanical execution to an execution-tier subagent, a harness
  without subagents performs the same steps directly, preserving the
  judgment/mechanical split above.

## Execution environments

There is **no special "mobile" or "phone" mode** — PyAutoBrain runs the same
workflow in any environment. A skill runs the same logic in any of:

| Environment | What it means | Repo access |
|-------------|---------------|-------------|
| `local-dev` | Local Claude Code / Codex with the `~/Code/PyAutoLabs/` checkouts | task worktrees under `~/Code/PyAutoLabs-wt/<task>/` + `activate.sh` |
| `web-github` | Claude or Codex web, GitHub-only (no local tree) | the session's checked-out clones; set `PYTHONPATH` + cache dirs manually |
| `ci-only` | Runs inside CI | the workflow's checkout |
| `analysis-only` | Read/inspect, no code execution | read via GitHub API or the checkout |

Detect environment, don't branch the whole skill on it: if a task worktree root
exists under `~/Code/PyAutoLabs-wt/<task>/`, use it and `source` its
`activate.sh`; otherwise operate on the clones present in the working directory
and export `PYTHONPATH`/`NUMBA_CACHE_DIR`/`MPLCONFIGDIR` yourself. Continuity
across environments needs no special ceremony: PyAutoMind's `active.md` is the
shared task state, so any environment reads it and continues an in-flight task.

## Mind registry coupling (paths are workspace-root-anchored)

Workflow skills read and write Mind state via **workspace-root-relative** paths
that resolve from any sibling repo:

- `PyAutoMind/active.md`, `PyAutoMind/planned.md`, `PyAutoMind/complete.md`
- `source PyAutoMind/scripts/prompt_sync.sh` → `prompt_sync_push "<msg>"` (commit+push registry)

`active.md` task schema, `complete.md` schema, and the prompt taxonomy
(`feature/<target>/`, `bug/<target>/`, …) are documented in `PyAutoMind/README.md`.
**The first folder is the work type, the second is the target repo/domain.**

## Worktree / branch model (local-dev)

Task worktrees keep parallel work isolated (`admin_jammy/software/worktree.sh`):
`worktree_create`, `worktree_add_repo`, `worktree_check_conflict`,
`worktree_list_claimed`, `worktree_remove`. Branch convention: `feature/<task-name>`
(lowercase kebab-case). Worktrees, branches, commits and feature PRs are the
**dev workflow's own git mechanics** — feature-development work, **not** Build.
Build is reached only for the release/packaging step (PyPI/tags/notebooks).

## Repo → GitHub owner mapping

<!-- repos_sync:begin -->
All repos live at `PyAutoLabs/<local dir name>` on GitHub, except: `Jammy2211/autofit_workspace_developer`, `Jammy2211/euclid_assistant`, `Jammy2211/admin_jammy`.

**Library repos:** PyAutoConf, PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens.
**Workspace repos:** autofit_workspace, autogalaxy_workspace, autolens_workspace, autofit_workspace_test, autogalaxy_workspace_test, autolens_workspace_test, HowToFit, HowToGalaxy, HowToLens, euclid_strong_lens_modeling_pipeline.

Generated from `PyAutoMind/repos.yaml`; edit there, then run `python3 PyAutoMind/scripts/repos_sync.py --write`.
<!-- repos_sync:end -->

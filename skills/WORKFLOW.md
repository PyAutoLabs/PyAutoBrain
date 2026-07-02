# PyAuto workflow skills — shared reference

The `start_*` / `ship_*` / `plan_branches` / `register_and_iterate` skills are the
**development-workflow entry points** of the PyAuto organism. They are *not*
independent reasoning systems: each one is a thin entry point that delegates to
the organs. This file is the shared context every workflow skill points at, so
the individual skill files can stay short.

## Organ boundary (who owns what)

| Organ | Repo | Owns |
|-------|------|------|
| **Mind** | PyAutoMind | Intent + workflow **state**: the prompt registry, `active.md` / `planned.md` / `complete.md`, the work-type taxonomy. *What the organism wants.* |
| **Memory** | PyAutoMemory | Accumulated **knowledge**: literature, wikis, scientific/architectural context, prior decisions. *What the organism has learned.* |
| **Brain** | PyAutoBrain | **Reasoning**: task classification, planning, agent selection, phasing, risk judgement. Hosts the specialist agents these skills call. *What to do.* |
| **Heart** | PyAutoHeart | **Health / readiness**: tests, validation, the GREEN/YELLOW/RED `pyauto-heart readiness` gate. *Is it safe?* |
| **Hands** | PyAutoBuild | **Release/packaging executor ONLY**: tagging, notebook generation, PyPI publication via `release.yml`. Owns **no** dev-workflow skills. *Do the release.* |

A workflow skill reasons through **Brain**, gates ship through **Heart**, records
state in **Mind**, and pulls context from **Memory**. The **dev-workflow's own
git mechanics** (worktrees, branches, commits, feature PRs) are part of feature
development — they are **not** Build's job. **Build is release work only**
(PyPI/tags/notebooks); `ship_*` *calls* Build only at actual release time. A
skill never re-implements another organ's job.

## The call chains

```
start_dev      →  Brain Feature Agent  →  Mind task  +  Memory context  →  plan  →  start_library/start_workspace
ship_library   →  Brain dev-workflow   →  Brain Health Agent  →  Heart (GREEN/YELLOW/RED)  →  commit / push / feature-PR
ship_workspace →  Brain dev-workflow   →  Brain Health Agent  →  Heart  →  commit / push / feature-PR
release (later)→  Brain Build/Release Agent  →  Brain Health Agent  →  Heart  →  PyAutoBuild (tag / notebooks / PyPI)
```

`ship_*` is **feature-development** work: the commit/push/feature-PR is the dev
workflow's own execution, gated by Heart. It is **not** a Build task. Build is
release/packaging only; `ship_*` reaches Build solely to trigger the release step
once changes are ready to publish.

Brain agents consult one another — e.g. the Build Agent never queries Heart
directly; it asks the Health Agent, and only the Health Agent talks to the Heart
organ. The same applies when the dev workflow consults the Health Agent for its
ship gate.

## Brain agent entry points

Reasoning is delegated to PyAutoBrain agents (`PyAutoBrain/AGENTS.md` is authoritative):

```bash
bin/pyauto-brain feature [<work-type>/<target>/<task>.md]  # classify + plan a task (Feature/Bug/Refactor/… routing)
bin/pyauto-brain build   [--dry-run]                       # consult Health, then delegate execution to Build
bin/pyauto-brain release                                   # reason over readiness, release on green
bin/pyauto-brain health                                    # one health tick + the unified dashboard card
```

If a dedicated agent for a work type does not exist yet (e.g. Bug/Refactor/Docs),
the Feature Agent's routing applies the closest available reasoning and the
missing agent is recorded as a follow-up — the skill still runs end-to-end.

When `pyauto-brain` is not on `PATH` and no PyAutoBrain checkout is present
(e.g. a GitHub-only session), perform the same reasoning inline following this
file and `PyAutoBrain/AGENTS.md`, and note that the agent was emulated.

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
- **YELLOW** → surface the warnings; proceed only with explicit user acknowledgement.
- **RED** → stop; report what failed. Do not ship.

Tests/smoke runs that feed the verdict are Heart's domain — invoke them through
the Health Agent rather than re-deriving pass/fail criteria in the skill.

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

| Local dir | GitHub repo |
|-----------|-------------|
| PyAutoConf, PyAutoFit | `rhayes777/<name>` |
| PyAutoArray, PyAutoGalaxy, PyAutoLens | `Jammy2211/<name>` |
| autofit_workspace, autogalaxy_workspace, autolens_workspace, autolens_workspace_test, HowToLens, euclid_strong_lens_modeling_pipeline | `Jammy2211/<name>` |

**Library repos:** PyAutoConf, PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens.
**Workspace repos:** the `*_workspace*` repos, HowToLens, euclid pipeline.

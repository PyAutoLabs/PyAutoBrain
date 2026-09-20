# PyAuto workflow skills — shared reference

The `start_*` and `ship_*` skills are entry points, not independent reasoning
systems. Mind owns task state, Brain plans and coordinates, Memory supplies
read-only context, Heart gates shipping, and Hands handles releases only.

Read [CONTEXT.md](CONTEXT.md) once for bounded reads/output, phase handoffs and
grouped/flat path resolution. Reuse unchanged instructions already loaded.

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

If Brain is unavailable, emulate the requested decision from its `AGENTS.md`
and this file, and say that it was emulated.

## Orchestration capabilities and execution evidence

The **orchestration environment** is the scientist-facing session currently
driving the task. The **execution environment** is wherever a particular phase
obtains the evidence it needs. They may be the same place, but they need not be.
Neither is an organ and neither owns task state: Mind remains the sole lifecycle
record.

Reason about capabilities, not product names. Probe the current surface once and
use only capabilities it actually exposes:

- `repository-read` / `repository-write` — inspect or change repository files;
- `github-control` — branches, commits, issues, PRs, reviews and Actions state;
- `local-filesystem` / `shell-runtime` — checkout-local files, commands and imports;
- `test-execution` — unit/integration/smoke commands in a real runtime;
- `worktrees` — isolated local task checkouts;
- `independent-review` — a reviewer genuinely independent of the authoring context;
- `remote-compute` — SSH/HPC/GPU or other environment-specific execution.

A model/provider/app name does not imply any item in that list. In particular, a
connected Chat surface may expose read-only GitHub access, read/write GitHub
actions, or no GitHub action at all. Detect what is present; fail closed on what
is absent.

For each phase, identify the **required evidence** first. Stay in the current
orchestration environment when its capabilities can honestly produce it. An
existing repository CI workflow on the exact branch head may provide applicable
test/smoke evidence when it runs the required scope; verify the head SHA and
individual legs rather than treating "CI green" as a generic proof. Do not add a
throwaway workflow merely to obtain a shell.

When a capability is missing, delegate the **smallest coherent phase** that
needs it and return its diff/commit plus decision-relevant evidence to the same
Mind task. If substantial implementation itself is runtime-dependent
(scientific/numerical debugging, profiling, HPC, environment inspection,
generated artefacts), route that coherent phase to an execution environment
from the outset; Chat or another orchestration surface can still retain the
Brain decisions and user conversation.

Independent review is evidence, not a second look by the author: the same
conversation that wrote a branch cannot self-certify the review faculty's
independence. Delegate only the review phase when that is the sole missing
capability.

**Heart remains separate from CI.** Exact-head CI can satisfy applicable test or
smoke evidence; it never substitutes for the authoritative Heart verdict. If the
current surface cannot read fresh authoritative Heart evidence, obtaining that
evidence is itself a bounded missing-capability step.

`Lane:` remains an intrinsic scheduling requirement (`any` or `local-dev`)
for a task that genuinely needs local data/output/SSH resources. It is not the
name of the orchestrating product and must not grow a `chatgpt`, `codex` or
`claude` value.

### No OpenAI API fallback

The ordinary-Chat route has **no API billing path**. Never use an OpenAI SDK,
Responses API, API Platform key, `OPENAI_API_KEY`, browser/session credential
reuse, or a local Brain process that programmatically starts a ChatGPT
conversation as a fallback. If the current Chat lacks a capability, use only an
explicitly selected supported execution surface (for example existing GitHub
Actions, Codex/Work, local shell or HPC) or stop at that phase. This invariant
does not depend on the user's API billing settings.

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
- If a requested worker is unavailable, execute directly only when the current
  surface has the required capability; otherwise use the bounded cross-environment
  handoff in `MODEL_DELEGATION.md` or stop without weakening any gate.
- `gh` commands name GitHub operations; map those operations onto the authenticated
  GitHub-control surface actually available via `GITHUB_ACCESS.md`.

## Task state and worktrees

Mind paths are relative to its resolved checkout: `active.md`, `planned.md`,
and prompt lifecycle `draft/ → active/ → complete/YYYY/MM/`. Use Mind's
lifecycle and prompt-sync scripts; do not hand-roll state transitions.

Local tasks use the Brain checkout's `bin/worktree.sh` and
`feature/<task-name>` branches. `worktree_check_conflict` fails closed when it
cannot read the registry. A repo bullet beneath an active task's `repos:` is a
claim; tasks touching the same repo serialize unless a human explicitly
authorizes coordination. Source the generated `activate.sh` before Python or
tests.

In web/CI sessions with clones, use those clones and explicit cache/PYTHONPATH
settings. A GitHub-control-only session may have no clone at all: it operates on
remote branches/files and records no fake `worktree:` path. The same Mind
registry and branch/commit provide continuity across environments.

## Repository routing

<!-- repos_sync:begin -->
All repos live at `PyAutoLabs/<local dir name>` on GitHub, except: `Jammy2211/euclid_assistant`.

**Library repos:** PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens, PyAutoReduce, PyAutoCTI.
**Workspace repos:** autofit_workspace, autogalaxy_workspace, autolens_workspace, autocti_workspace, autoreduce_workspace, autofit_workspace_test, autogalaxy_workspace_test, autolens_workspace_test, autocti_workspace_test, HowToFit, HowToGalaxy, HowToLens, euclid_strong_lens_modeling_pipeline.

Generated from `PyAutoMind/repos.yaml`; from the resolved Mind checkout, edit `repos.yaml`, then run `python3 scripts/repos_sync.py --write`.
<!-- repos_sync:end -->

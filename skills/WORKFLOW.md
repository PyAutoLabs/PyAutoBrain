# PyAuto workflow skills — shared reference

The `start_*` and `ship_*` skills are entry points, not independent reasoning
systems: Mind owns task state, Brain plans and coordinates, Memory supplies
read-only context, Heart gates shipping, Hands handles releases only. Read
[CONTEXT.md](CONTEXT.md) once; reuse unchanged instructions already loaded.

```text
start_dev  → Brain feature decision → Mind task + plan → start_library/workspace
ship_*     → Brain review/vitals → Heart gate → commit/push/feature PR
release    → Brain release decision → Heart gate → Hands
```

Worktrees, commits and feature PRs belong to the dev workflow, not Hands.
Autonomy checkpoints live once in `../AUTONOMY.md`: default runs present and
wait; explicit `--auto` runs follow that contract. Brain entry points:
`bin/pyauto-brain feature <prompt>`, `review --task <name>`, `vitals`,
`build --dry-run`; if Brain is unavailable, emulate the decision from its
`AGENTS.md` and this file and say it was emulated.

## Orchestration capabilities and execution evidence

The **orchestration environment** drives the task with the scientist; the
**execution environment** is wherever a phase obtains its evidence. They may
differ; neither is an organ or owns task state (Mind does). Probe the current
surface once for capabilities, never product names — `repository-read` /
`repository-write`, `github-control`, `local-filesystem` / `shell-runtime`,
`test-execution`, `worktrees`, `independent-review`, `remote-compute` — and
fail closed on what is absent (a connected Chat surface may have read-only,
read/write or no GitHub action).

Per phase, name the **required evidence** first and stay where the current
capabilities can honestly produce it. Exact-head CI on the branch can supply
applicable test/smoke evidence (verify the head SHA and each leg); never add a
throwaway workflow to get a shell. When a capability is missing, delegate the
**smallest coherent phase** that needs it and return its diff plus evidence to
the same Mind task; route runtime-dependent implementation (numerical
debugging, profiling, HPC, generated artefacts) to an execution environment
from the outset.

Independent review, where the path requires it (the review-faculty leg of the
`--auto` ship gate; the independent-adversary cases in `AUTONOMY.md`), is
evidence: the conversation that wrote a branch cannot self-certify it. Delegate
only that phase, or require human review. It is not a prerequisite for an
ordinary human-approved merge. **Heart remains separate from CI:** exact-head
CI never substitutes for the authoritative Heart verdict; reading fresh Heart
evidence is itself a bounded missing-capability step.

`Lane:` stays an intrinsic scheduling requirement (`any` or `local-dev`); it
must not grow a `chatgpt`, `codex` or `claude` value. **No OpenAI API
fallback** — and worker assignment — see
[`MODEL_DELEGATION.md`](MODEL_DELEGATION.md); read it before assigning a worker.

## Memory and planning

For substantial architectural or scientific planning, consult
`bin/pyauto-brain memory "<topic>"`, read only the cited pages, and proceed
honestly when it has no matches; PyAutoMemory citations never enter public
user-facing output. Issue and lifecycle mechanics stay with Mind's
`create_issue` primitive and scripts, never duplicated in Brain.

## Heart gate

**Heart at the door:** development entry (`start_dev` step 0a, mirrored by
`route`) reads the Heart's published feed with the read-only
`bin/heart_feed.py` — RED stops before planning, YELLOW/STALE warn and
continue. A light early read, never a tick; the ship-time gate stays
authoritative.

Before `ship_*`, the vitals faculty gives the **scoped** dev-ship verdict,
`pyauto-heart readiness --dev --repos A,B` with the task's `repos:` from
`active.md` (PyAutoHeart#340): only CI on `main` of those repos and their
dependants blocks, other reasons are shown; GREEN continues; STALE (evidence
over 6 h, missing or unfinished) never passes — re-check or park; RED stops.
`heart_feed.py --repos A,B` gives the door the same scope. Releases keep the
unscoped verdict. After the exact
reason strings are quoted verbatim from the current Heart verdict and
validation is shown, a live human may use
`AUTONOMY.md` "Human override for Heart RED (development only)" or the narrower
"Corrective-PR exception for Heart RED" — neither permits a release, CI bypass
or merge.

Ordinary development evidence is applicable tests, downstream smoke checks for
public API changes, and Heart. For review, under `--auto` the autonomous-ship
gate requires review-faculty `CLEAN` (`AUTONOMY.md`); for an ordinary human-approved
ship/merge it is **not a universal prerequisite** unless a repository,
branch-protection or task rule says so. Merge is always a current human action
and still requires the applicable GitHub checks.

## Cross-harness behavior

`/name` means use that skill (`SKILL.md`); Plan Mode means present-and-wait
unless explicit `--auto`; with no prompt, first write a Mind draft holding the
request verbatim. An unavailable worker → execute directly only where the
surface has the capability, else the bounded handoff in `MODEL_DELEGATION.md`
or stop, never weakening a gate. `gh` commands name GitHub operations; map them
onto the surface actually available via `GITHUB_ACCESS.md`.

## Task state and worktrees

Mind paths are relative to its resolved checkout (`active.md`, `planned.md`,
`draft/ → active/ → complete/YYYY/MM/`); use Mind's lifecycle and prompt-sync
scripts, never hand-rolled transitions. Local tasks use `bin/worktree.sh` and
`feature/<task-name>` branches: `worktree_check_conflict` fails closed when it
cannot read the registry and warns on unclaimed on-disk worktrees;
`worktree_audit_orphans` is the report-only sweep. A repo bullet under an
active task's `repos:` is a claim; tasks on the same repo serialize unless a
human authorizes coordination. Source the generated `activate.sh` before
Python or tests. Web/CI sessions use their clones; a GitHub-control-only
session operates on remote branches and records no fake `worktree:` path.

## Repository routing

<!-- repos_sync:begin -->
All repos live at `PyAutoLabs/<local dir name>` on GitHub, except: `Jammy2211/euclid_assistant`.

**Library repos:** PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens, PyAutoReduce, PyAutoCTI.
**Workspace repos:** autofit_workspace, autogalaxy_workspace, autolens_workspace, autocti_workspace, autoreduce_workspace, autofit_workspace_test, autogalaxy_workspace_test, autolens_workspace_test, autocti_workspace_test, HowToFit, HowToGalaxy, HowToLens, euclid_strong_lens_modeling_pipeline.

Generated from `PyAutoMind/repos.yaml`; from the resolved Mind checkout, edit `repos.yaml`, then run `python3 scripts/repos_sync.py --write`.
<!-- repos_sync:end -->

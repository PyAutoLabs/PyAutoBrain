# Feature agent

> **Tier: conductor** — a front-door agent you *drive*. It decides how the
> organism grows and drives that plan into the dev workflow; it *consults* the
> read-only vitals faculty (`--check-health`) but never queries Heart directly.

The **growth function** of PyAutoBrain. It reasons over the feature *intent*
stored in PyAutoMind and decides **how the organism should grow** — which feature
task to work on, how hard it is, whether it must be phased, what scientific
context applies, and which development path to take. It does **not** implement
code: it produces a structured `FeatureDecision` that the existing development
workflow consumes.

```
Mind (PyAutoMind feature/*)  →  Feature Agent  →  start_dev
                                              →  start_library / ship_library
                                              →  start_workspace / ship_workspace
       consults ↘                    ↙ consults
        vitals faculty            PyAutoMemory (scientific / architectural context)
```

> Long term this is the organism-facing **Growth Agent**; *Feature Agent* is the
> engineering-facing name and the safe first implementation.

## Fundamental principle

**The Feature Agent reasons; it does not build.** It never edits source. It reads
intent, consults memory, estimates difficulty, decides phasing, and emits a plan
that `start_dev` / `ship_*` execute. Implementation only happens when the plan is
handed to the existing workflow.

## Brain agents consult one another

Like the Build Agent, the Feature Agent is a citizen of the society of agents.
For risky / multi-repo / release-bound work it **consults the sibling vitals faculty** (`--check-health`) rather than querying the Heart organ directly — only
the vitals faculty talks to Heart. It also consults **PyAutoMemory** for scientific
and architectural context, and **never invents science** when memory has
material. See [`MIND_TAXONOMY.md`](./MIND_TAXONOMY.md) for the PyAutoMind taxonomy
it reasons over and the PyAutoMemory routing it uses.

## Three modes

| Mode | Trigger | What it does |
|------|---------|--------------|
| **specific** | a task path is given | Read the named prompt, classify repos, consult memory, size it, decide phasing, and produce a `start_dev`-ready plan. |
| **selection** | no task given | Scan `feature/**`, rank candidates, and recommend the best next task — **not** merely the first in a list; down-ranks in-flight work (from `active.md` / `planned.md`). |
| **difficulty-constrained** | `--difficulty` / `--model` / `--budget` / `--ambitious` / `--impact` | Estimate difficulty per task and select to match the constraint (easy/weak-model/limited-token → small; ambitious/strong-model → large; impact → high-leverage). |

## Difficulty & sizing

Difficulty is a transparent heuristic (`small | medium | large | too-large`) over
repos affected, prompt size, scientific complexity, architectural risk, test
burden, and whether memory context / human judgement is required. The factor
breakdown is in every decision so the reasoning layer can adjust.

Sizing then drives the **phase decision**:

- **direct** — small/medium; one PR.
- **split-into-phases** — large/too-large; prefer several small shippable PRs over
  one fragile PR. For *too-large* it emits phase stubs, e.g.
  `feature/<target>/<name>_phase_1_design.md … _phase_4_docs.md`.
- **research-first** — ambiguous, no repo resolved; open a `research/` task first.
- **defer / re-home** — if the prompt is mis-filed (a bug, refactor, research or
  experiment), it says so and suggests the correct PyAutoMind category.

## Run

```bash
bin/pyauto-brain feature                                   # selection mode
bin/pyauto-brain feature feature/autofit/sbi.md            # specific mode
bin/pyauto-brain feature select --difficulty easy          # easy task
bin/pyauto-brain feature select --model strong --limit 5   # ambitious shortlist
bin/pyauto-brain feature select --impact                   # highest-leverage
bin/pyauto-brain feature --check-health feature/autolens/x.md   # also consult Health
bin/pyauto-brain feature --json select                     # machine-readable
```

A bare path is treated as `specific`; nothing given is `selection`. `--json`
emits the full `FeatureDecision` (with a `shortlist` in selection modes).

Exit codes: `0` produced a decision · `4` no prompts / could-not-resolve mind ·
`5` bad usage (unknown task / flag).

## FeatureDecision (the structured return)

Mirrors the spec's required fields:

```
Selected task · Mode · Work-type/target · Repos affected · Difficulty (+score)
Recommended workflow (library|workspace|combined|research|experiment|refactor|bug)
Relevant context (PyAutoMemory sub-wikis to consult) · Phase decision (+stubs)
Execution plan (start_dev / start_library / ship_library / start_workspace / …)
Health considerations · Risks · Next action (one concrete step)
```

`--json` returns the same shape for programmatic use (a future Python
`FeatureAgent().decide(...)` can return it verbatim).

## Workflow mapping

- **library** → `start_dev` → `start_library` → `ship_library`
- **workspace** → `start_dev` → `start_workspace` → `ship_workspace`
- **combined** → library PR first (so the workspace consumes its `## API Changes`
  summary), then the workspace PR; ship both in order.

Library vs. workspace is decided from the `@RepoName` references in the prompt
body, not the folder (per PyAutoMind `ROUTING.md`).

## What this agent must never do

- Edit source, open PRs, or run builds itself — that is the Build Agent /
  PyAutoBuild via `start_dev` / `ship_*`.
- Query PyAutoHeart directly — consult the vitals faculty (`--check-health`).
- Invent scientific or architectural context when PyAutoMemory has material —
  cite the sub-wiki instead.
- Just pick the first prompt in selection mode — rank, and explain the choice.

See [`MIND_TAXONOMY.md`](./MIND_TAXONOMY.md) for the PyAutoMind work-type taxonomy,
the PyAutoMemory sub-wiki routing, and the difficulty heuristic in detail.

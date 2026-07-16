# Workspace agent

> **Tier: conductor** — a front-door agent you *drive*. The *Voice* — the
> organism's expressive function: how it speaks to its users. Workspace
> examples are how it addresses practitioners; the `howto` register is how it
> teaches first-time learners (undergrads, new PhD students). It reasons over
> example-authorship intent and emits a `WorkspaceDecision` the
> `start_dev → start_workspace → ship_workspace` flow consumes — it never
> edits source and, in v0, never writes anything at all.

Grown from demonstrated need, not symmetry: workspace-example authorship is a
recurring follow-up to every library extension, and `autoreduce_workspace` /
`autoreduce_workspace_test` are being born and must mirror the established
workspaces. Founding prompt and one-agent-vs-two assessment: PyAutoMind
`active/workspace_examples_agent.md` (issue PyAutoBrain#116).

## One agent, two registers

The examples surface has one format and two audiences:

- **`workspace`** — reference examples for practitioners (`*_workspace`
  repos): standalone, task-oriented, reachable from a search with no prior
  reading assumed.
- **`howto`** — narrative teaching for first-time learners (`HowTo*` repos):
  cumulative chapters, terms defined at first use, physical intuition before
  API.

Everything else — the contents+docstring script format, markdown/notebook
generation, the `start_workspace → ship_workspace` pipeline, API grounding
against the installed stack, the assistant-training role — is shared, which is
why this is one agent and not two.

**Split trigger** (recorded so the future decision is cheap): promote the
`howto` register to its own agent only when it develops a decision surface the
workspace register cannot share — curriculum/chapter-continuity planning,
exercise design, or learner-feedback state. Until then it is a register, not
an organism function.

## Modes

Both modes are read-only; the agent writes nothing (the Clone Agent's v0
boundary).

- **plan** (default) — `pyauto-brain workspace "<raw text>"` or
  `pyauto-brain workspace <PyAutoMind prompt path>`: classifies the intent and
  emits the `WorkspaceDecision` — library family, target repo, register,
  placement (ranked against the target's *real* `scripts/` tree; the repo's
  own folders always win), the sibling example to mirror, the prose tier
  (WORKFLOW.md tutorial-prose split), the format checklist, and the routing
  (`start_dev` → `start_workspace`). A newborn target with no `scripts/` tree
  anchors its structure on `autolens_workspace` — the bootstrap case.
- **survey** — `pyauto-brain workspace survey <repo> [--against <sibling>]`:
  inventories a workspace repo's example catalogue (packages + script counts);
  `--against` diffs the structure against a sibling — missing/extra packages
  and per-package counts. This is the `autoreduce_workspace` bootstrap tool:
  `survey autoreduce_workspace --against autolens_workspace` is its birth
  checklist.

`--json` gives the machine-readable decision/survey for both.

## Format grounding (pointers, never a restated spec)

The canonical format lives where it is executed, and the decision points at it
rather than duplicating it:

- the **sibling example script** the decision names — structure is copied from
  a living example, never invented;
- **PyAutoBuild's notebook generation** — every top-level docstring becomes a
  markdown cell, which is what makes the docstring format load-bearing;
- **`skills/WORKFLOW.md` tutorial-prose split** — example/howto prose is
  judgment-tier (the docstrings are the product); `*_workspace_test` scripts
  are execution-tier;
- the workspace rules that recur in review: docs are minimal not maximal
  (flag/value + one-line note, no ported runnable blocks); new library
  `output.yaml` keys are mirrored into workspace configs; every API symbol is
  grounded against the installed stack (the PyAuto API gate enforces this).

## Consult graph

Like every conductor it consults faculties, never other conductors: the
**memory faculty** when tutorial prose needs scientific or prior-art context
(`pyauto-brain memory "<topic>"`). It has no business with Heart — example
authorship is dev work, gated at ship time like any other change.

## Boundary

- **Decides and routes; never authors.** The writing happens in the dev flow
  the decision points into; prose stays judgment-tier per WORKFLOW.md.
- **Never writes files, never mutates a repo** (v0). If an `--apply` ever
  arrives it will scaffold *placement* (empty package dirs mirroring a
  sibling), not prose.
- **Conductor, not faculty, deliberately:** it is a front door a human drives
  to *start* example work (the Feature Agent's shape), not an opinion another
  conductor consults. If a ship-time "does this script meet the format?"
  opinion is later needed, that is a separate read-only faculty, not this
  agent grown teeth.

## Running

```
bin/pyauto-brain workspace "interferometer example for autoreduce_workspace"
bin/pyauto-brain workspace "new HowToLens chapter on mass profiles"
bin/pyauto-brain workspace draft/docs/workspaces/<prompt>.md
bin/pyauto-brain workspace survey autoreduce_workspace --against autolens_workspace
```

Repos resolve under `PYAUTO_ROOT` (default `~/Code/PyAutoLabs`). Exit codes:
0 decision · 4 inputs unresolvable · 5 bad usage.

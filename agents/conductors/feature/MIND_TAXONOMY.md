# PyAutoMind & PyAutoMemory surface known to the Feature Agent

This audit records the **intent surface** (PyAutoMind) the Feature Agent reasons
over and the **knowledge surface** (PyAutoMemory) it consults. Both are markdown
knowledge bases with no CLI — the Brain reasons over their files directly. The
agent must treat these as inputs to reason about, never as logic to reimplement.
Sources of truth: `PyAutoMind/ROUTING.md`, `PyAutoMind/README.md`,
`PyAutoMemory/index.md`.

## PyAutoMind taxonomy (intent → work-type)

Prompts live at `<work-type>/<target>/<name>.md`. The **work-type** (first
folder) declares the kind of thinking required; the **target** (second folder)
names the affected repo or domain. The Feature Agent owns `feature/` and helps
keep it organised — re-homing mis-filed prompts.

| Work-type | Intent | If a `feature/` prompt is really this → re-home as |
|-----------|--------|-----------------------------------------------------|
| `feature/` | new user-facing / scientific capability | (stays) |
| `bug/` | incorrect behaviour, crash, regression | `bug/` |
| `refactor/` | internal restructuring, no behaviour change | `refactor/` |
| `research/` | unclear science → investigate before building | `research/` |
| `experiment/` | proof-of-concept / spike | `experiment/` |
| `docs/` `test/` `release/` `maintenance/` `triage/` | docs / tests / release / hygiene / unclear | matching folder |

The agent classifies a prompt's intent and, when it does not match `feature/`,
states the better category in `rehome_suggestion` rather than planning code.

## Targets → library vs. workspace

The `/start_library` ↔ `/start_workspace` split is decided from the `@RepoName`
references in the **prompt body**, not the folder (per `ROUTING.md`).

- **Libraries** (source): PyAutoConf, PyAutoFit, PyAutoArray, PyAutoGalaxy,
  PyAutoLens (`autoconf`, `autofit`, `autoarray`, `autogalaxy`, `autolens`;
  aliases `aa`/`af`/`ag`/`al`). API paths like `@aa.decorators.transform`
  resolve by their head token (`aa` → `autoarray`).
- **Workspaces / tutorials / examples**: `autolens_workspace`(`_test`),
  `autogalaxy_workspace`(`_test`), `autofit_workspace`(`_test`), `HowToLens`,
  `HowToGalaxy`, `HowToFit`, `autolens_assistant`, `autolens_profiling`, and the
  `workspaces` bucket.

`@`-mentions that resolve to neither (e.g. `@z_projects`, `@jax`) are dropped so
the repo count reflects real affected repos. Workflow mapping:

- library only → `start_dev → start_library → ship_library`
- workspace only → `start_dev → start_workspace → ship_workspace`
- both → library PR first (workspace consumes its `## API Changes` summary), then
  the workspace PR; ship in order.

## Workflow state the agent reads

- `active.md` — in-flight tasks (sessions, worktrees, claimed repos).
- `planned.md` — filed-but-not-started tasks.
- `queue.md` — ordered processing queues.

In **selection** mode the agent extracts `feature/...md` paths referenced in
`active.md` / `planned.md` and **down-ranks** them, so it surfaces genuinely new
next work rather than resurfacing what is already moving. Priorities and
inter-task dependencies are applied by the reasoning layer on top of the ranking.

## PyAutoMemory routing (scientific / architectural context)

Before planning substantial scientific or architectural work, the agent maps the
task to the relevant PyAutoMemory sub-wiki and **cites it** — it does not invent
context when memory has material. Sub-wikis (source: `PyAutoMemory/index.md`):

| Sub-wiki | Domain | Triggered by (examples) |
|----------|--------|--------------------------|
| `lensing_wiki/` | strong gravitational lensing | lens, deflection, source reconstruction, subhalo, time delay, cosmography, SLACS/TDCOSMO |
| `smbh_wiki/` | supermassive black holes | black hole, SMBH, binary, recoil, NANOGrav |
| `cti_wiki/` | charge-transfer inefficiency | CTI, trap, arctic, VIS calibration |
| `methods_wiki/` | statistical / computational methods | Bayesian, sampler, JAX, NUFFT, SBI, graphical models, deep learning |
| `galaxies_wiki/` | galaxy formation & evolution | bulge/disk, MGE, morphology, IFU, kinematics |

Library targets also pull a default sub-wiki (`autolens`→lensing,
`autogalaxy`→galaxies, `autofit`/`autoarray`/`autoconf`→methods). PyAutoMemory is
**optional**: if the checkout is absent the agent still names the sub-wikis to
read, degrading gracefully rather than failing.

## Difficulty heuristic (transparent by design)

`_feature.py` scores each task and the score appears in every decision:

| Signal | Contribution |
|--------|--------------|
| repos affected | `(count − 1) × 2` — the dominant driver |
| library **and** workspace | `+2` (coordination cost) |
| prompt size | `+min(words/150, 4)` |
| scientific complexity | `+min(#keywords, 3)` |
| architectural / API risk | `+min(#keywords × 2, 4)` |
| test burden (JAX, smoke, parity, …) | `+1` |
| memory context required | `+1` |

Thresholds: `≤2 small · ≤5 medium · ≤9 large · >9 too-large`. These are a
**v1 heuristic**: the factor breakdown is exposed precisely so the reasoning
layer can override the bucket (e.g. a pre-phased prompt that scores "too-large"
is already a single phase). When the keyword lists or thresholds drift, update
them here and in `_feature.py` together; do not encode them anywhere the agent
must re-derive at runtime.

## Boundary audit — reasoning vs. intent vs. knowledge vs. execution

```
intent      → PyAutoMind   (feature/* prompts, active/planned/queue state)
reasoning   → PyAutoBrain  (Feature Agent — this)
knowledge   → PyAutoMemory (via direct file reads; cited, never invented)
health      → PyAutoHeart  (via the Health Agent, never queried directly)
execution   → PyAutoBuild  (via start_dev / ship_* — never run by this agent)
```

No execution, health-checking, or knowledge-authoring logic lives in the Feature
Agent. It reads intent, consults knowledge and (optionally) health, reasons, and
hands a plan to the existing workflow. If intent-shaping logic ever creeps in
here, it belongs back in PyAutoMind; if knowledge authoring creeps in, it belongs
in PyAutoMemory.

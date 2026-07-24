# Eyes agent

> **Tier: conductor** — a front-door agent you *drive*. The *perceptive
> function* — the organism's sense of its own appearance: it owns the
> render → present → critique → delegate loop over a project's visualization
> surface. It consults the read-only memory faculty for style/paper context
> like every conductor; it never renders (the workspace's own
> `gallery/gallery_run.sh` does), never edits plot source, and
> delegates every accepted change via intake → start_dev.

Grown from demonstrated need: the organism produces rich visualizations
(imaging / interferometer / point_source / multi / cluster) but had no formal
loop for a human to look at them, judge them and drive updates (epic
PyAutoBrain#117; Phase 1 — the render harness, gallery + machine-readable
`viz_manifest.yaml` in the reference visualization workspace,
`autolens_workspace_test` — merged as autolens_workspace_test#170).

## The contract (domain-agnostic core, per-project instance)

The deterministic core consumes any **visualization workspace**: a repo with
`scripts/<domain>/images/<script>/**` figure trees written by its
visualization scripts, plus `output/gallery/` from its gallery builder. The
workspace root is always a CLI argument — the `.py`/`.sh` here name no
repositories (tenant firewall); the instance pointer lives in this prose and
in the `/eyes` skill. Reference instance: `autolens_workspace_test`.

## Modes

| Mode | Question | Emits |
|------|----------|-------|
| `survey` | What figures exist, what is stale, what was never rendered, is the gallery current? | `EyesSurvey` — per-script inventory, stale/gap/orphan lists, gallery currency, next action |
| `review` | What do I look at, in what order, and how do critiques become work? | `EyesReviewSurface` — ordered figure batches for the agentic read loop + the critique-note schema and edit-surface routing |
| `review --against <dir>` | Paper-informed pass: how should these figures change to match this paper's conventions? | the same surface + `reference_figures` (the paper's extracted panels); notes then carry a `reference` |

## The loop (driven by the `/eyes` skill)

1. `eyes survey <workspace>` — establish what needs (re)rendering.
2. Render in the workspace: `bash gallery/gallery_run.sh` (`--all`
   adds the slow tier + JAX variants), which ends in the gallery builder's
   own `--check`.
3. Present: the embedded gallery for the human; the agent reads figure PNGs
   directly, batch by batch per `eyes review`.
4. Critique: collect human + agent notes against the note schema; each note
   is tagged with its edit surface — workspace `config/visualize` yaml,
   library plot functions (the functional `aplt.*` API), the producing
   script, or dataset/simulator inputs.
5. Delegate: one intake prompt per coherent accepted change, routed through
   start_dev. **Never edit plot source in-session.**

## Boundaries

- Decision-only, stdlib-only core: reads the filesystem, writes nothing.
- Rendering and figure regeneration belong to the workspace; the conductor
  only tells you they are stale.
- Paper-informed passes (`review --against`): the reference figures are
  gathered by the session (PDF pages read directly, or panels extracted to a
  directory) — the core never fetches anything. The reviewing session reads
  the references FIRST and writes an explicit convention list (colormaps,
  panel composition, critical-curve/caustic annotation, colorbar placement
  and units, fonts, scale bars) before critiquing workspace figures against
  it; the memory faculty is consulted for style precedent, and PyAutoMemory
  citations never reach public output (privacy seam).

## Running

```bash
bin/pyauto-brain eyes survey <workspace-root>
bin/pyauto-brain eyes review <workspace-root> [--batch N] [--against <reference-dir>]
bin/pyauto-brain eyes --json survey <workspace-root>
```

Exit codes: 0 decision emitted · 4 not a visualization workspace.

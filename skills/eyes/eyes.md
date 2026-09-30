# /eyes — look at, judge and update the organism's figures (via the Brain Eyes Agent)

The **render → present → critique → delegate** loop over a project's
visualization surface, via PyAutoBrain's **Eyes Agent** (the *perceptive
function*). You never name the Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`. The default
visualization instance is the lens visualization project repo,
**`lens/autolens_visualization`**; the galaxy project repo
**`galaxy/autogalaxy_visualization`** is the second instance, then
**`fit/autofit_visualization`** and **`cti/autocti_visualization`**. These four
registered instances are the only Eyes targets. `autolens_workspace_test` (the
original reference instance from epic PyAutoBrain#117 Phase 1) is no longer an
instance: its `gallery/` harness was retired in PyAutoEyes phase 5
(PyAutoEyes#6), and its visualization scripts remain ordinary workspace_test
regression scripts. Pass a different instance root to review another project.

Two layers (human decision 2026-09-28): **project repos**
`<lib>_visualization` (four today: `lens/autolens_visualization`,
`galaxy/autogalaxy_visualization`, `fit/autofit_visualization` and
`cti/autocti_visualization`) make, store
and track one library's figures — producers, datasets, tracked PNGs,
`GALLERY.md`, a tracked `gallery/viz_manifest.yaml` and the
`gallery/gallery_run.sh` harness; **the organ PyAutoEyes** is the
cross-project dashboard that reads each project repo's tracked manifest and
links to its PNGs — it renders nothing and copies no figures. The organ's
`registry.yaml` lists every instance. Name one with `--instance <name>` (the
lens instance is `lens`, the galaxy instance `galaxy`, then `fit` and
`cti` — e.g. `--instance galaxy`), or hand the conductor the PyAutoEyes root to cover
them all.

## Do

1. **Survey**: `bin/pyauto-brain eyes survey --instance <name>` (or
   `<workspace-root>`, or the PyAutoEyes root for every instance): per-script
   figure inventory, stale renders (producer script newer than its figures),
   never-rendered gaps, gallery currency.
2. **Render** what the survey flags, in the instance itself:
   `bash gallery/gallery_run.sh [<domain>|--all]` (ends in the
   builder's own `--check`; `--all` adds the slow tier + JAX variants). Then
   `python gallery/gallery_build.py --embed` and copy
   `output/gallery/gallery_embedded.html` out (e.g. `towin`) for the human.
3. **Review**: `bin/pyauto-brain eyes review --instance <name>` (or
   `<workspace-root>`): read each
   figure batch directly (PNG reads in-session), collect the human's
   critiques plus your own suggestions as notes against the emitted
   `note_schema`, tagging each with its edit surface (`config` /
   `plot_api` / `script` / `data`). A note is `accepted` only on explicit
   human agreement.
4. **Delegate** — one `/intake` prompt per coherent accepted change, then
   `/start_dev` as usual (config + script surfaces → workspace PR; `plot_api`
   → library PR). **Never edit plot source inside the review session.**

## From the dashboard

The PyAutoEyes dashboard (<https://pyautolabs.github.io/PyAutoEyes/>) gives
every figure two critique routes, and neither files anything by itself:

- **`/eyes review <instance> <figure>`**: the human pastes it here. Resolve
  the instance with `--instance <instance>`, read that one figure (and its
  siblings from the same producer, for context), and continue at step 3 with
  a single-figure batch.
- **Suggest an improvement**: a pre-filled `eyes-critique` issue on the
  project repo, which the human files. Treat an open one as a critique note
  whose `accepted` field is still false. Discuss it, and on explicit
  agreement file the `/intake` prompt (step 4) and link the issue from it.

The dashboard also lists the open PyAutoMind drafts that mention each instance
(its open critiques), so check there before filing a duplicate.

## Paper-informed pass ("restyle to match this paper")

When the human supplies a paper (PDF, arXiv link, or a directory of figure
panels):

1. Get the reference figures locally — read PDF pages directly in-session,
   or extract panels into a directory.
2. `bin/pyauto-brain eyes review <workspace-root> --against <reference-dir>`
   — the panels ride the review surface as `reference_figures`.
3. Read the references FIRST and write an explicit **convention list**:
   colormap family, panel composition, critical-curve/caustic annotation,
   colorbar placement + units, fonts, scale bars. Show it to the human
   before critiquing — it is the rubric.
4. Critique the workspace figures against the rubric; notes carry
   `reference` (the motivating panel). Consult the memory faculty for style
   precedent; PyAutoMemory citations never reach public output.
5. Delegate exactly as step 4 above.

## Boundary

- The Eyes Agent decides and routes; the PyAutoEyes organ (or a workspace
  instance) renders and holds the figures; intake/start_dev ship. No step edits plots directly from critique.
- The core never fetches papers or figures — the session gathers reference
  material; the conductor only lists what it is given.

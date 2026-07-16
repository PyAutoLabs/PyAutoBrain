# /eyes — look at, judge and update the organism's figures (via the Brain Eyes Agent)

The **render → present → critique → delegate** loop over a project's
visualization surface, via PyAutoBrain's **Eyes Agent** (the *perceptive
function*). You never name the Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`. The default
visualization workspace is **`autolens_workspace_test`** (the reference
instance of the gallery contract from epic PyAutoBrain#117 Phase 1); pass a
different workspace root to review another project.

## Do

1. **Survey** — `bin/pyauto-brain eyes survey <workspace-root>`: per-script
   figure inventory, stale renders (producer script newer than its figures),
   never-rendered gaps, gallery currency.
2. **Render** what the survey flags, in the workspace itself:
   `bash scripts/gallery/gallery_run.sh [<domain>|--all]` (ends in the
   builder's own `--check`; `--all` adds the slow tier + JAX variants). Then
   `python scripts/gallery/gallery_build.py --embed` and copy
   `output/gallery/gallery_embedded.html` out (e.g. `towin`) for the human.
3. **Review** — `bin/pyauto-brain eyes review <workspace-root>`: read each
   figure batch directly (PNG reads in-session), collect the human's
   critiques plus your own suggestions as notes against the emitted
   `note_schema`, tagging each with its edit surface (`config` /
   `plot_api` / `script` / `data`). A note is `accepted` only on explicit
   human agreement.
4. **Delegate** — one `/intake` prompt per coherent accepted change, then
   `/start_dev` as usual (config + script surfaces → workspace PR; `plot_api`
   → library PR). **Never edit plot source inside the review session.**

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

- The Eyes Agent decides and routes; the workspace renders; intake/start_dev
  ship. No step edits plots directly from critique.
- The core never fetches papers or figures — the session gathers reference
  material; the conductor only lists what it is given.

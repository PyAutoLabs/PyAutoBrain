# Eyes — PyAutoEyes

**What it owns:** the *perception lifecycle* as a **cross-project dashboard**
over the `<lib>_visualization` project repos (`autolens_visualization` and
`autogalaxy_visualization`) — the registry of those repos, the read contract of
their tracked `gallery/viz_manifest.yaml` manifests and the board that links to
their PNGs. The project repos render and hold the figures; the organ renders
nothing and copies no figures. The Eyes are the perception mirror of the
Heart: the Heart says whether the software is *healthy*; the Eyes show what it
*shows*.

**Repo:** [PyAutoLabs/PyAutoEyes](https://github.com/PyAutoLabs/PyAutoEyes)

## The defining function: seeing

Every PyAuto library draws, on one shared plotting API — and the figures a
library draws are the part of it a user sees first. Each library's project
repo renders its figures on fixed, realistic datasets (HST-scale imaging, an
SMA-like interferometer, and their equivalents per library) and keeps the PNGs
**in git**, so a figure's history is a `git log` and a visual regression is a
diff. Figures are **re-rendered on library release only**: a release is the
moment the record changes, and the project repo's render workflow then pings
the organ (`repository_dispatch: eyes-refresh`) to refresh the board.

## Instances

Each instance is a project repo `<lib>_visualization` with the same layout —
`scripts/<domain>/visualization.py` producers, `scripts/<domain>/images/`
renders, a tracked `gallery/viz_manifest.yaml` (every figure's producer,
domain, source type, path, size and content hash, plus the stack it was
rendered with), `output/gallery/gallery.html` and a `GALLERY.md` index.
`autolens_visualization` and `autogalaxy_visualization` are registered; fit
and cti follow. The organ's
instance registry (`registry.yaml`, PyAutoEyes phase 1b/2) names every
instance, its library and its domains, and the board shows each one's figure
count, stale renders, gaps and open critiques — the single point of contact
for the visual behaviour of the whole ecosystem.

## The driver split

The project repos *render and hold* figures and the Eyes *show* them; neither
judges anything. The Brain's **Eyes conductor** (`bin/pyauto-brain eyes`,
`/eyes`) surveys an instance, prepares
the review surface and walks the human through the figures — the same split
as **Heart ↔ vitals** and **Gut ↔ hygiene**: the organ keeps the state, the
conductor reasons over it.

## What it never does

- **It never judges a figure.** Critique happens in the conductor's review
  loop, with the human.
- **It never edits library plot code.** An accepted critique becomes a Mind
  prompt through intake and ships through start_dev like any other change.
- **It never re-simulates a shared dataset.** Where an instance borrows a
  profiling dataset, it is kept byte-identical.
- **It issues no verdict.** Readiness is the Heart's.

## For an adopter

Like Mind, Cortex, Memory and Gut, the Eyes are an **instance organ** —
inherently yours. You do not fork this repo's figures; you create your own
Eyes with the same shape, over your own libraries' visualization project
repos.

The birth of this organ is tracked in the `pyautoeyes-birth` epic
([PyAutoMind#437](https://github.com/PyAutoLabs/PyAutoMind/issues/437) is
phase 0). Phase 1a (PyAutoMind#446) moved the lens gallery back into its own
project repo, `autolens_visualization`, with the tracked manifest; phase 1b
strips the organ to the dashboard skeleton and adds the registry.

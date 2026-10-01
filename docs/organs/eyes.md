# Eyes — PyAutoEyes

**What it owns:** the **cross-project visualization view**
over the `<lib>_visualization` project repos (`autolens_visualization`,
`autogalaxy_visualization`, `autofit_visualization` and
`autocti_visualization`) — the registry of those repos, the read contract of
their tracked `gallery/viz_manifest.yaml` manifests and the board that links to
their PNGs. The project repos render and hold the figures; the organ renders
nothing and copies no figures. The Eyes are the perception mirror of the
Heart: the Heart says whether the software is *healthy*; the Eyes show what it
*shows*.

**Repo:** [PyAutoLabs/PyAutoEyes](https://github.com/PyAutoLabs/PyAutoEyes)

**Dashboard:** <https://pyautolabs.github.io/PyAutoEyes/>

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
`autolens_visualization`, `autogalaxy_visualization`, `autofit_visualization`
and `autocti_visualization` are registered. The organ's
instance registry (`registry.yaml`, PyAutoEyes phase 1b/2) names every
instance, its library and its domains, and the board shows each one's figure
count, stale renders, gaps and open critiques — the single point of contact
for the visual behaviour of the whole ecosystem.

Beside the board, the organ publishes two machine surfaces: `badge.json`, a
one-line headline, and `state.json`, the organ-cockpit feed (contract v1 in
`PyAutoBrain/board/state_schema.json`). The feed is what puts the Eyes on the
[organ cockpit](https://pyautolabs.github.io/cockpit/) alongside the other
organs.

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
inherently yours. You create your own Eyes registry and dashboard over your
own libraries' visualization project repos. Those projects produce and retain
the figures; the organ reads their manifests and links to them.

The organ was born through the `pyautoeyes-birth` epic:

- **Phase 0** ([PyAutoMind#437](https://github.com/PyAutoLabs/PyAutoMind/issues/437))
  added the organ row to the body map.
- **Phase 1a** ([PyAutoMind#446](https://github.com/PyAutoLabs/PyAutoMind/issues/446))
  moved the lens gallery back into its own project repo,
  `autolens_visualization`, with the tracked manifest.
- **Phase 1b** ([PyAutoMind#448](https://github.com/PyAutoLabs/PyAutoMind/issues/448))
  stripped the organ to the dashboard skeleton and added the registry.
- **Phase 2** ([PyAutoMind#451](https://github.com/PyAutoLabs/PyAutoMind/issues/451))
  built the dashboard, the conductor's registry reading and the Brain board chip.
- **Phase 3** ([PyAutoMind#452](https://github.com/PyAutoLabs/PyAutoMind/issues/452))
  registered the galaxy instance, `autogalaxy_visualization`.
- **Phase 4** ([PyAutoMind#455](https://github.com/PyAutoLabs/PyAutoMind/issues/455))
  registered the fit and CTI instances, `autofit_visualization` and
  `autocti_visualization`.
- **Phase 5** ([PyAutoEyes#6](https://github.com/PyAutoLabs/PyAutoEyes/issues/6))
  retired the pre-organ `autolens_workspace_test/gallery/` harness, linked the
  dashboard from the public surfaces and lit the Eyes card on the organ
  cockpit with `state.json`.

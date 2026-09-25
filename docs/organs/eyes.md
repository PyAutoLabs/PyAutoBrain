# Eyes — PyAutoEyes

**What it owns:** the *perception lifecycle* — one **rendered gallery per
library** (lens, galaxy, fit, cti) of every visualizer output on realistic
data, the manifests that inventory them, the one harness that renders them,
the instance registry and the board. The Eyes are the perception mirror of the
Heart: the Heart says whether the software is *healthy*; the Eyes show what it
*shows*.

**Repo:** [PyAutoLabs/PyAutoEyes](https://github.com/PyAutoLabs/PyAutoEyes)

## The defining function: seeing

Every PyAuto library draws, on one shared plotting API — and the figures a
library draws are the part of it a user sees first. The Eyes render each
library's figures on fixed, realistic datasets (HST-scale imaging, an SMA-like
interferometer, and their equivalents per library) and keep the PNGs **in
git**, so a figure's history is a `git log` and a visual regression is a diff.
Figures are **re-rendered on library release only**: a release is the moment
the record changes.

## Instances

The organ holds one instance subtree per library, each with the same layout —
`scripts/<domain>/visualization.py` producers, `scripts/<domain>/images/`
renders, `output/gallery/{gallery.html,viz_manifest.yaml}` and a `GALLERY.md`
index. The lens instance (`lens/`) is the first; galaxy, fit and cti follow.
An instance registry (`registry.yaml`) names every instance, its library and
its domains, and the board shows each one's figure count, stale renders, gaps
and open critiques — the single point of contact for the visual behaviour of
the whole ecosystem.

## The driver split

The Eyes *render and hold* figures; they judge nothing. The Brain's **Eyes
conductor** (`bin/pyauto-brain eyes`, `/eyes`) surveys an instance, prepares
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
Eyes with the same shape, rendering your own libraries.

The birth of this organ is tracked in the `pyautoeyes-birth` epic
([PyAutoMind#437](https://github.com/PyAutoLabs/PyAutoMind/issues/437) is
phase 0). The repo was renamed from `autolens_visualization`, so its lens
gallery is already rendered; phase 1 moves it into the `lens/` instance and
adds the harness package, registry and CLI.

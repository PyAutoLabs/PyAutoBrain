# The worked example: the live lensing instance

Everything on this site is running today, developing the
[PyAuto astronomy stack](https://pyautolabs.github.io). This page is that
instance, labelled as the example — when a concept page says "a library" or
"a workspace", this is what it concretely means upstream. Your organism
replaces every name below with your own.

## The body

The live `repos.yaml` declares ~25 repos. The load-bearing categories:

- **Libraries:** PyAutoConf (shared config), PyAutoFit (Bayesian
  inference), PyAutoArray (data structures), PyAutoGalaxy (galaxy
  modelling), PyAutoLens (strong lensing), PyAutoReduce (data reduction) —
  a dependency chain released to PyPI nightly when there is new activity.
- **Workspaces:** `autofit_workspace`, `autogalaxy_workspace`,
  `autolens_workspace` — user-facing examples, notebook-generated,
  version-pinned against their libraries.
- **Test workspaces:** the `*_workspace_test` trio — regression, smoke and
  parity scripts the release pipeline runs.
- **HowTos:** HowToFit / HowToGalaxy / HowToLens — lecture-style courses.
- **Assistant:** `autolens_assistant` — the curated knowledge pack that
  makes any AI assistant a strong-lensing expert.
- **Memory:** sub-wikis on lensing, black holes, detector calibration,
  inference methods and galaxy evolution, with a ~600-paper bibliography
  layer.

## A task, end to end

A representative real task (2026): a prompt file
`feature/autoarray/psf_oversampling.md` written as free prose — "PSF
blurring lives in `@PyAutoArray/.../convolver.py`; modeling should convolve
at higher resolution than the image; here's roughly how" — with typos and
half-decisions left in. `start_dev` classified it (feature, library),
planned it at two levels, opened a tracked issue, and claimed a worktree.
Development touched PyAutoArray and PyAutoGalaxy; the ship gate ran both
test suites, the review faculty, and Heart's verdict; one PR landed per
repo; the workspaces then gained a demonstration script in a follow-up
workspace task. The registry recorded every state transition, and the task
retired to its dated `complete/` record.

That is the whole pitch: the input was a paragraph of intent, and every
step from there — planning, isolation, testing, gating, releasing,
bookkeeping — was the organism's machinery, with a human approving the plan
and the merge.

## Scale, honestly

This system runs tens of active repos with a single human maintainer. In a
typical recent quarter the framework organs themselves took a few hundred
commits — which is exactly why the {ref}`stability disclaimer <stability>`
exists and why adoption is a fork, not a dependency.

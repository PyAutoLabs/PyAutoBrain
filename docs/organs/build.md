# Hands — PyAutoBuild

**What it owns:** execution of the release pipeline. Packaging, tagging,
notebook generation from example scripts, workspace validation runs, and
PyPI publication via `release.yml` — nightly, when there is new activity to
ship.

**Repo:** [PyAutoLabs/PyAutoBuild](https://github.com/PyAutoLabs/PyAutoBuild)

## The boundary that matters

The Hands are a **pure executor**: no readiness checks of their own, no
re-deriving of gate decisions. Readiness is gated upstream — the Brain's
release path consults the vitals faculty, which reads Heart, and only a
GREEN verdict reaches the dispatch. Historically Build owned some checking;
that all migrated to Heart, and thin shims remain so old entry points still
work.

## The pieces

- **`bin/autobuild`** — the single dispatcher; every operation is a
  subcommand with `--help` (`pre_build`, `generate`, `run_all`,
  `tag_and_merge`, …).
- **`pre_build.sh`** — the declarative heart of the pipeline: one
  `run_workspace <repo> <package> <flags> <library>` row per workspace
  describes everything the pipeline needs to know about it.
- **`release.yml`** — package to TestPyPI, verify the install, run the
  workspace scripts, and on success release to PyPI and tag the workspaces.

## For an adopter

Fork it. The pipeline mechanics are the framework; the `run_workspace`
table in `pre_build.sh` and the small maps in `autobuild/*.py` (which
workspaces to run, what to skip) are the declared config surfaces you
rewrite for your own repos — see {doc}`../adoption/config_surfaces`.

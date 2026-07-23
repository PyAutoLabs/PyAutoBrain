# PyAutoHands capabilities known to the Build Agent

This audit records the execution surface the PyAutoBrain Build Agent reasons over
and **calls**. The agent must treat every item here as a PyAutoHands capability,
not as logic to reimplement inside Brain. Source of truth: the `autobuild`
dispatcher (`PyAutoHands/bin/autobuild`) and `PyAutoHands/CLAUDE.md`.

## Execution capabilities (the Build Agent calls these)

From `autobuild help`. **Mode** is the Build Agent allowlist that *may* route
the capability (`build.sh`); **Consumer today** is who actually drives it now.
The two diverge for the workspace-run surface — see the note below.

| Capability | What it does | Mode | Consumer today |
|------------|--------------|------|----------------|
| `pre_build` | Format, regenerate notebooks, push workspaces, then dispatch `release.yml`. | release | Build Agent (release) · `/pre_build` |
| `tag_and_merge` | Commit and tag every library repo for a release. | release | release path (release execution) |
| `generate_release_notes` | Generate release notes from merged PRs and create GitHub Releases. | release | `release.yml` (CI) |
| `create_analysis_issue` | Open a GitHub issue with the release report and assign Copilot. | release | release path — posts the Heart-run aggregate report |
| `generate` | Convert a workspace's `scripts/` to `notebooks/`. | build, deploy | Build Agent (deploy) **and** Heart `workspace-validation.yml` |
| `run` | Execute notebooks in a workspace folder. | build | **Heart** `workspace-validation.yml` |
| `run_python` | Execute Python scripts in a workspace folder. | build | **Heart** `workspace-validation.yml` · `health_release.sh` |
| `run_all` | Run scripts across one or more workspaces, produce summary reports. | build | **Heart** `health_release.sh` + readiness checks |
| `script_matrix` | Output a JSON `{name, directory}` matrix for GitHub Actions. | build | **Heart** `workspace-validation.yml` (CI) |
| `aggregate_results` | Aggregate per-job JSON into a release-readiness report. | build, release | **Heart** `workspace-validation.yml` (CI) |
| `slow_skip_check` | Surface SLOW / NEEDS_FIX entries in workspace `no_run.yaml`. | build | `run_all.py` + Heart `test_run` check |
| `repro_command` | Emit the shell command autobuild uses to run one script. | build | triage (manual handoff) |
| `bump_colab_urls` | Rewrite Colab URLs in cwd from an old to a new date-tag. | build, deploy | `release.yml` (CI) + deploy |

**Reading the Consumer column — the run\* seam is latent, not active.** The
capabilities still *exist* and match the `autobuild` dispatcher and the
`build.sh` allowlists exactly; the *Mode* column remains accurate as the
allowlist of record. What changed is the driver. The workspace full-run →
report → issue flow moved **out of `release.yml` into PyAutoHeart's
`workspace-validation.yml`** (see `PyAutoHands/docs/internals.md` and the
`release.yml` comment recording the removed `run_scripts` / `run_notebooks` /
`analyze_results` jobs). Heart checks these primitives out from Build and reuses
them directly — calling `run.py` / `run_python.py` / `script_matrix.py` /
`aggregate_results.py`, **not** `autobuild run_*` and **not** `pyauto-brain build
run_*`. Nothing invokes `run` / `run_python` / `run_all` through the Build Agent
today, so their build-mode allowlist entries are a **latent seam** — kept so the
Build Agent could re-own execution without churn, but **Heart is the live
consumer**. This is the execution/health boundary the audit below argues for,
now made visible in the table itself.

Underlying implementation assets the agent never re-owns: `autobuild/run_python.py`,
`run.py`, `generate.py`, `script_matrix.py`, `aggregate_results.py`,
`tag_and_merge.sh`, `build_util.py`, the `release.yml` GitHub workflow, and the
per-workspace `config/build/{no_run,env_vars,visualise_notebooks}.yaml`.

## Boundary audit — execution vs. health

PyAutoHands is meant to be a **pure executor**: it runs no readiness checks of
its own. Confirmed against `PyAutoHands/CLAUDE.md` ("PyAutoHands is the executor
… it runs **no** release-readiness checks of its own").

It does, however, still expose **health-shim commands** that delegate to the
health authority (PyAutoHeart):

- `verify_install` — shim → health authority (deep install-path checks).
- `url_check` — shim → health authority (forbidden Binder/Colab URL guard).
- `watch` / `status` / `tick` / `fix` — monitoring-daemon shims.

**Decision:** these are health concerns, not build actions. The Build Agent
**refuses to route them** and points the caller at `pyauto-brain vitals <cmd>`
instead. They belong to PyAutoHeart and are reached through the vitals faculty —
never re-owned by the Build Agent, and never duplicated in Brain. No non-trivial
readiness logic was found living *inside* PyAutoHands itself (the shims only
delegate); if any ever appears, migrate it to PyAutoHeart and leave only
delegation in PyAutoHands.

This keeps the architecture clean:

```
reasoning  → PyAutoBrain (Build Agent, vitals faculty)
health     → PyAutoHeart (via the vitals faculty)
execution  → PyAutoHands (via the Build Agent)
```

## Naming resilience

PyAutoHands has been renamed onto the canonical **PyAutoHeart** / **PyAutoBrain**
names (the earlier **PyAutoPulse** / **PyAutoAgent** usages are gone). Regardless,
the Build Agent reasons about *categories of capability* (execution vs. health),
not fixed names, so any future rename in PyAutoHands does not break it. When
PyAutoHands gains or renames an execution subcommand, update the table above; do
not encode the list anywhere the agent must re-derive at runtime beyond the
per-mode allowlists in
`build.sh`.

## Build Agent decision policy (recap)

- **GREEN** — proceed; invoke the requested PyAutoHands capability.
- **YELLOW** — build mode proceeds with a warning; deploy/release require
  `--force`. An unknown verdict is treated as YELLOW.
- **RED** — abort; surface Heart's blockers (via the vitals faculty) and do not
  execute.

The Build Agent may sequence, plan, and explain execution, but it must never run
a build step itself, query Heart directly, or re-derive the readiness verdict.

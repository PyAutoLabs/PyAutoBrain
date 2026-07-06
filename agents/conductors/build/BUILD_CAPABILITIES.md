# PyAutoBuild capabilities known to the Build Agent

This audit records the execution surface the PyAutoBrain Build Agent reasons over
and **calls**. The agent must treat every item here as a PyAutoBuild capability,
not as logic to reimplement inside Brain. Source of truth: the `autobuild`
dispatcher (`PyAutoBuild/bin/autobuild`) and `PyAutoBuild/CLAUDE.md`.

## Execution capabilities (the Build Agent calls these)

From `autobuild help`:

| Capability | What it does | Build Agent mode |
|------------|--------------|------------------|
| `pre_build` | Format, regenerate notebooks, push workspaces, then dispatch `release.yml`. | release |
| `tag_and_merge` | Commit and tag every library repo for a release. | release |
| `generate_release_notes` | Generate release notes from merged PRs and create GitHub Releases. | release |
| `create_analysis_issue` | Open a GitHub issue with the release report and assign Copilot. | release |
| `generate` | Convert a workspace's `scripts/` to `notebooks/`. | build, deploy |
| `run` | Execute notebooks in a workspace folder. | build |
| `run_python` | Execute Python scripts in a workspace folder. | build |
| `run_all` | Run scripts across one or more workspaces, produce summary reports. | build |
| `script_matrix` | Output a JSON `{name, directory}` matrix for GitHub Actions. | build |
| `aggregate_results` | Aggregate per-job JSON into a release-readiness report. | build, release |
| `slow_skip_check` | Surface SLOW / NEEDS_FIX entries in workspace `no_run.yaml`. | build |
| `repro_command` | Emit the shell command autobuild uses to run one script. | build |
| `bump_colab_urls` | Rewrite Colab URLs in cwd from an old to a new date-tag. | build, deploy |

Underlying implementation assets the agent never re-owns: `autobuild/run_python.py`,
`run.py`, `generate.py`, `script_matrix.py`, `aggregate_results.py`,
`tag_and_merge.sh`, `build_util.py`, the `release.yml` GitHub workflow, and the
per-workspace `config/build/{no_run,env_vars,copy_files,visualise_notebooks}.yaml`.

## Boundary audit — execution vs. health

PyAutoBuild is meant to be a **pure executor**: it runs no readiness checks of
its own. Confirmed against `PyAutoBuild/CLAUDE.md` ("PyAutoBuild is the executor
… it runs **no** release-readiness checks of its own").

It does, however, still expose **health-shim commands** that delegate to the
health authority (named PyAutoPulse in current PyAutoBuild docs; that is
PyAutoHeart, which keeps a `pyauto-pulse` back-compat shim):

- `verify_install` — shim → health authority (deep install-path checks).
- `url_check` — shim → health authority (forbidden Binder/Colab URL guard).
- `watch` / `status` / `tick` / `fix` — monitoring-daemon shims.

**Decision:** these are health concerns, not build actions. The Build Agent
**refuses to route them** and points the caller at `pyauto-brain vitals <cmd>`
instead. They belong to PyAutoHeart and are reached through the vitals faculty —
never re-owned by the Build Agent, and never duplicated in Brain. No non-trivial
readiness logic was found living *inside* PyAutoBuild itself (the shims only
delegate); if any ever appears, migrate it to PyAutoHeart and leave only
delegation in PyAutoBuild.

This keeps the architecture clean:

```
reasoning  → PyAutoBrain (Build Agent, vitals faculty)
health     → PyAutoHeart (via the vitals faculty)
execution  → PyAutoBuild (via the Build Agent)
```

## Drift note

Current PyAutoBuild guidance still uses the older name **PyAutoPulse** for the
health authority and **PyAutoAgent** for the reasoning layer in places. The Build
Agent reasons about *categories of capability* (execution vs. health), not fixed
names, so a rename in PyAutoBuild does not break it. When PyAutoBuild gains or
renames an execution subcommand, update the table above; do not encode the list
anywhere the agent must re-derive at runtime beyond the per-mode allowlists in
`build.sh`.

## Build Agent decision policy (recap)

- **GREEN** — proceed; invoke the requested PyAutoBuild capability.
- **YELLOW** — build mode proceeds with a warning; deploy/release require
  `--force`. An unknown verdict is treated as YELLOW.
- **RED** — abort; surface Heart's blockers (via the vitals faculty) and do not
  execute.

The Build Agent may sequence, plan, and explain execution, but it must never run
a build step itself, query Heart directly, or re-derive the readiness verdict.

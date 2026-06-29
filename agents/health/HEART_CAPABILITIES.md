# PyAutoHeart capabilities known to the Health Agent

This audit records the health surface the PyAutoBrain Health Agent reasons over.
The agent must treat every item here as a PyAutoHeart capability, not as logic to
reimplement inside Brain.

## Authoritative health commands

- `pyauto-heart tick` — refreshes the cached health snapshot.
- `pyauto-heart status` — renders the cached state.
- `pyauto-heart readiness` — emits the authoritative GREEN / YELLOW / RED gate.
- `pyauto-heart readiness --json` — machine-readable gate for agents/scripts.
- `pyauto-heart watch [seconds]` / `live` — continuous monitoring daemon.
- `pyauto-heart stop` / `stop --all` — daemon lifecycle control.
- `pyauto-heart fix <topic>` — emits a context bundle/invocation for remediation;
  it must not mutate other repos directly.

## Continuous checks in Heart

- Repo state: branch, dirty source files, ahead/behind origin.
- CI status: latest workflow conclusion per repo.
- Open PRs: count and staleness classification.
- Worktree drift: `~/Code/PyAutoLabs-wt/` directories versus PyAutoMind
  `active.md` claims.
- Script timing: per-script duration regressions against rolling baselines.
- Test run: latest PyAutoBuild release-run report under
  `test_results/latest/report.json`.
- Version skew: workspace pinned versions versus installed libraries.
- Generated/noise classification: dirty source files versus generated artifacts.

## Deep / scheduled checks in Heart

- Install verification (`verify_install`, including pip/conda install-path checks).
- URL hygiene (`url_sweep` and the central URL-check workflow).
- Cloud-safe health issue maintenance via `.github/workflows/pulse-health.yml`,
  displayed as Heart Health during the Pulse→Heart compatibility period.

## Heart implementation assets

- Bash dispatcher and loop: `bin/pyauto-heart`, `heart/daemon.sh`, `heart/tick.sh`.
- Bash helpers: `heart/_common.sh`, `heart/_color.sh`.
- Python rendering/verdict/state modules: `heart/status.py`, `heart/readiness.py`,
  `heart/state.py`, `heart/fix.py`, `heart/noise.py`, `heart/heart_color.py`.
- Check modules: `heart/checks/repo_state.sh`, `ci_status.sh`, `open_prs.sh`,
  `worktree_drift.sh`, `script_timing.py`, `test_run.py`, `version_skew.py`.
- Config: `config/repos.yaml`, including thresholds and `noise_globs`.
- Tests: `tests/`, expected to run quickly with stdlib + PyYAML only.
- Docs / agent guidance: `README.md`, `AGENTS.md`, `CLAUDE.md`.

## PyAutoBuild drift audit

Current PyAutoBuild guidance still uses the old names PyAutoPulse and
PyAutoAgent in places, and exposes compatibility shims such as
`autobuild verify_install`, `autobuild url_check`, and `autobuild watch|status|tick|fix`.
These are documented as delegating to the health authority rather than owning
readiness logic.

Decision: YELLOW until the docs are fully renamed from Pulse/Agent to
Heart/Brain and the shims are confirmed to delegate only. Do not duplicate those
checks in Brain. If any shim contains non-trivial readiness logic, migrate that
logic to PyAutoHeart and leave only delegation in PyAutoBuild.

## Health Agent decision policy

- GREEN: Heart reports no blocking or cautionary issues. Build may proceed
  automatically if the calling agent requested execution.
- YELLOW: Heart reports warnings or unknowns. Work may proceed, but human review
  is recommended before release/deployment.
- RED: Heart reports blocking issues. Build must not proceed automatically.

The Health Agent may explain, rank, and recommend actions from Heart output, but
it must never independently measure repo health, run tests directly, classify
files, or re-derive release readiness.

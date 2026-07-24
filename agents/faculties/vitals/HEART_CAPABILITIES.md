# PyAutoHeart capabilities known to the vitals faculty

This audit records the health surface the PyAutoBrain vitals faculty reasons over.
The agent must treat every item here as a PyAutoHeart capability, not as logic to
reimplement inside Brain.

## Authoritative health commands

- `pyauto-heart tick` — refreshes the cached health snapshot.
- `pyauto-heart status` — renders the cached state.
- `pyauto-heart readiness` — emits the authoritative GREEN / STALE / YELLOW / RED gate.
- `pyauto-heart readiness --json` — machine-readable gate for agents/scripts.
- `pyauto-heart dashboard [--oneline|--md|--html|--json|--badge]` — the ONE
  unified health board (verdict + every check + release-validation state); reads
  cache only, never ticks. The vitals faculty's mobile card is the `--json`/`--md`
  view of this board.
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
- Test run: latest PyAutoHands release-run report under
  `run_logs/latest/report.json`.
- Version skew: workspace pinned versions versus installed libraries.
- Generated/noise classification: dirty source files versus generated artifacts.

## Deep / scheduled checks in Heart

- Install verification (`verify_install`, including pip/conda install-path checks).
- URL hygiene (`url_sweep` and the central URL-check workflow).
- Cloud-safe health issue maintenance via `.github/workflows/pulse-health.yml`,
  displayed as Heart Health during the Pulse→Heart compatibility period.

## Release validation in Heart (ingest-and-judge)

- `pyauto-heart validate --ingest <artifacts>` folds the release-validation
  artifacts (the M1 TestPyPI rehearsal, a `{repo: sha}` commit_shas.json, and —
  from M3 — the wheel-based integration `report.json`) into a tracked
  `validation_report.json` (`~/.pyauto-heart/validation_report.json`).
- The report is a **hard readiness gate**: GREEN-for-release requires a fresh
  passing report whose `commit_shas` match the current `main` HEADs under the
  `release` profile; absent/stale/SHA-mismatch/wrong-profile → STALE (an evidence gap: re-run
  the rehearsal, don't fix code); a failed
  stage → RED. It is exposed as the `validate` capability + `validation_report`
  signal in Heart's `health_agent/capabilities.yaml`.
- **Heart is ingest-and-judge only** — it never dispatches `release.yml` or
  `workspace-validation.yml`. Dispatching/polling/downloading the artifacts is the
  **Release Agent's** job (`pyauto-brain release rehearse`), via MCP GitHub tools.
  The **vitals faculty stays read-only**: it reports the resulting verdict, it does
  not dispatch.

## Unified health dashboard (M5)

- `heart/dashboard.py` is a **single pure renderer** that projects the same
  cached snapshot (`state.json` + `release_ready.json` + `validation_report.json`)
  into every surface's format (`term`/`oneline`/`md`/`html`/`json` + a shields
  badge). The web page, the CLI line, and the mobile card are all projections of
  one board, so they cannot disagree.
- **Three surfaces:** GitHub Pages (`https://pyautolabs.github.io/PyAutoHeart/`)
  + `$GITHUB_STEP_SUMMARY` + a README badge/block (all published by
  `pulse-health.yml`); the `pyauto-heart dashboard` CLI + a sourceable venv hook
  (`heart/shell/heart_prompt.sh`); and this vitals faculty's mobile card.
- **The vitals faculty renders the card from `pyauto-heart dashboard --json`/`--md`**
  — the same board, not raw verdict JSON. It is exposed as the `dashboard`
  capability + `published_board` URL in Heart's `health_agent/capabilities.yaml`.
- **Observer-only.** The dashboard SHOWS health; the `readiness` verdict stays
  the gate. Everything the dashboard writes stays within PyAutoHeart's own repo
  (gh-pages / README / `[heart-health]` issue), the job step summary, or
  `~/.pyauto-heart/`. The vitals faculty stays read-and-reason.

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

## PyAutoHands delegation audit

PyAutoHands has been fully renamed onto the Heart/Brain names (no PyAutoPulse or
PyAutoAgent references remain) and exposes health-shim commands such as
`autohands verify_install`, `autohands url_check`, and `autohands watch|status|tick|fix`.
These delegate to the health authority rather than owning readiness logic.

Decision: GREEN — the docs are renamed and the shims delegate only. Do not
duplicate those checks in Brain. If any shim ever gains non-trivial readiness
logic, migrate that logic to PyAutoHeart and leave only delegation in PyAutoHands.

## vitals faculty decision policy

- GREEN: Heart reports no blocking or cautionary issues. Build may proceed
  automatically if the calling agent requested execution.
- STALE: the freshness tier — nothing known-bad, but named evidence is missing
  or expired. **Releases still require GREEN**: recommend re-running the named
  checks (never code fixes), then re-read. The dev-ship gate (`AUTONOMY.md`
  leg 4) treats STALE as passing — evidence gaps are organism-scope, not
  branch-scope.
- YELLOW: Heart reports warnings on current evidence. Work may proceed, but
  human review is recommended before release/deployment.
- RED: Heart reports blocking issues. Build must not proceed automatically.

The vitals faculty may explain, rank, and recommend actions from Heart output, but
it must never independently measure repo health, run tests directly, classify
files, or re-derive release readiness.

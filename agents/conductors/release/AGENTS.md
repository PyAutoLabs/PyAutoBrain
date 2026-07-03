# Release agent

> **Tier: conductor** — a front-door agent you *drive*. It decides whether/when to
> release and orchestrates release validation (dispatch/poll/download across the
> MCP boundary), *consulting* the read-only vitals faculty for the verdict.

A specialist **PyAutoBrain** reasoning agent. It decides whether and when a
release should happen, then drives it through the canonical chain:

```
Brain  →  Heart (gate)  →  Build (execute)
```

## Responsibility

1. Refresh and read PyAutoHeart's authoritative readiness verdict
   (`pyauto-heart readiness --json`).
2. **Reason over it** — block unless the verdict is green:
   - **RED** → a real release blocker; refuse (exit 3).
   - **YELLOW** → caution; refuse unless `--force` (exit 2).
   - **GREEN** → proceed.
3. On green, delegate to the PyAutoBuild executor — `autobuild pre_build`, which
   prepares the workspaces and dispatches `release.yml`.

The agent holds **no health logic and no release mechanics of its own**. The
health decision is Heart's; the execution is Build's. The Brain only reasons
about the verdict and decides to proceed.

## Run

```bash
bin/pyauto-brain release           # reason about readiness, release on green
bin/pyauto-brain release --force   # also proceed on yellow (cautions ack'd)
bin/pyauto-brain release -- 2      # forward `2` (minor_version) to pre_build
```

Exit codes: `0` released/delegated · `2` yellow (use --force) · `3` red blocked
· `1/4` could not obtain a verdict / unknown verdict.

## Release-validation rehearsal (M2) — `release rehearse`

Beyond gating a real release, the Release Agent **orchestrates release
validation**: it proves the exact source about to ship was built, published to
TestPyPI, installed from the wheel, and exercised at release fidelity — then
consults the vitals faculty for the verdict. It does this without ever letting
Heart dispatch a build (Heart is ingest-and-judge only).

The full chain (M2 builds the dispatch+ingest half; M3/M4 add release-fidelity
integration + full orchestration):

```
Mind -> Release Agent (orchestrate) -> Heart (measure) -> vitals faculty (judge) -> Hands/Build (promote on GREEN)
```

`rehearse.sh` is a two-phase driver. Cloud/mobile sessions have **no `gh`**, so
GitHub dispatch/poll/download run through Brain's **MCP GitHub tools**; bash
can't call MCP, so the script emits the MCP plan (phase 1) and owns the local
ingest+verdict (phase 2):

```bash
# 1. print the MCP dispatch/poll/download plan (the agent executes it via MCP):
bin/pyauto-brain release rehearse [--ref main] [--minor N] [--json]

# 2. after downloading the artifact + capturing the library main HEADs,
#    ingest into Heart and get the verdict:
bin/pyauto-brain release rehearse --ingest <dir> --commit-shas <dir>/commit_shas.json
bin/pyauto-brain release rehearse --ingest <dir> --force   # accept a YELLOW
```

Phase 1 emits the steps: `mcp__github__actions_run_trigger` on
`PyAutoLabs/PyAutoBuild` `release.yml` with `{rehearsal: true}` (M1 mode) →
poll `mcp__github__actions_get` to completion → download the
`testpypi-rehearsal-version` artifact → `mcp__github__get_commit` each library's
`main` HEAD into `commit_shas.json`. Phase 2 hands the artifacts to
`pyauto-heart validate --ingest` (Heart writes `validation_report.json`), then
calls `consult_vitals_verdict --refresh` so the **read-only vitals faculty**
reports GREEN/YELLOW/RED from the freshly-ingested report.

Exit codes (phase 2): `0` green (release-ready) · `2` yellow (use --force) ·
`3` red · `4` unknown · `1` could not ingest.

## Full release-validation orchestrator (M4) — `release validate`

`release rehearse` drives Stage 2 alone. `release validate` (`validate.sh`) is
the **full Stages 0–3 orchestrator** — the end-to-end
preflight → unit → rehearse → integrate → ingest → verdict flow the
`release_validation.md` spec calls for. It **sequences** what M2/M3 already
built, adding only Stage 0/1 preflight and the Stage 3 dispatch; it does not
re-implement Stage 2 (it calls into `rehearse.sh`).

Because every dispatch stage crosses the same MCP boundary (bash can't call
GitHub), it is a **3-phase driver** — one phase per hand-off to/from the agent's
MCP work:

```bash
# Phase A — preflight (Stage 0/1) + emit the Stage 2 dispatch plan:
bin/pyauto-brain release validate [--ref main] [--minor N] [--json]
#   Stage 0/1 bad -> RED decision, exit 3, NOTHING dispatched.
#   Stage 0/1 ok  -> emits the Stage 2 plan (via rehearse.sh), which continues to:

# Phase B — once Stage 2 artifacts exist, emit the Stage 3 dispatch plan:
bin/pyauto-brain release validate --stage3-plan <dir> [--ref main] [--json]

# Phase C — once Stage 3 artifacts exist, ingest everything + get the verdict:
bin/pyauto-brain release validate --ingest <dir> --commit-shas <dir>/commit_shas.json
bin/pyauto-brain release validate --ingest <dir> --force   # accept a YELLOW
```

- **Stage 0 (preflight)** and **Stage 1 (unit)** are a *pure local read* of
  Heart's cached `repo_state` / `version_skew` / `ci_status` signals for the 5
  libraries (via `pyauto-heart status --json`). Definitely-bad signals (off-main
  / dirty / behind / failing CI / skew AHEAD/MISMATCH/BAD) abort **RED** (exit 3)
  before anything is dispatched — "no point building a dirty tree". Unknowns are
  surfaced as warnings but do not block (never silently green, never a hard
  abort). Stage 1 reuses the cached CI conclusion; dispatching a fresh unit run
  if stale is the spec's optional path, deferred for M4's first cut.
- **Stage 2 (rehearse)** is `rehearse.sh`'s phase-1 plan, reused verbatim via its
  `--next-plan-cmd` hook so its dispatch/poll/download/capture-heads plan stays
  defined in ONE place; only the "continue" step is redirected into phase B.
- **Stage 3 (integrate)** dispatches PyAutoHeart's `workspace-validation.yml` in
  `mode=release` with `testpypi_version` + `commit_shas` (a JSON *string*) read
  from the Stage 2 artifacts, then downloads the `release-stage-report`
  (`stage_report.json`) **into the same dir** as the Stage 2 artifacts.
- **Final ingest + verdict** delegates to `rehearse.sh --ingest` (reused
  verbatim), so `pyauto-heart validate --ingest` folds Stage 2's
  `rehearsal.json`/`commit_shas.json` and Stage 3's `stage_report.json`
  together, then the vitals faculty judges. Exit codes are identical to Stage 2's.

Exit codes: preflight RED `3`; a phase that can't proceed (missing artifacts)
`1`; phase-C ingest `0` green · `2` yellow (`--force`) · `3` red · `4` unknown ·
`1` could-not-ingest. Plan-emission phases exit `0`.

**`commit_shas` authority.** Stage 2's `commit_shas.json` (library `main` HEADs
the Release Agent read straight from GitHub) is the single source of truth.
Stage 3 only echoes it back — the same JSON is the workflow's `commit_shas`
input, which `emit_release_report` writes out and embeds into
`stage_report.json`. So the phase-C `--commit-shas` flag and the stage report's
embedded copy come from the same file and cannot legitimately disagree; passing
`--commit-shas` is a **safety net** (readiness still gets the SHAs even if a
stage report omits them), not redundant. In `heart/validate.py`'s fold a stage
artifact's embedded `commit_shas` is applied after the `--commit-shas` seed
(last-writer-wins), so on the impossible disagreement the embedded copy wins —
but both originate from Stage 2, which stays authoritative by construction.

## What this agent must never do

- Re-derive or second-guess the readiness verdict (that is Heart's / the vitals faculty's job).
- Run any packaging/tagging/publish step itself (that is Build's job).
- Write into PyAutoHeart or PyAutoBuild repos.

## What only this agent does (not the vitals faculty)

- Dispatch/poll/download GitHub workflows and artifacts (via MCP). The vitals faculty is strictly read-and-reason — it never dispatches. Heart never dispatches
  either. All release-validation dispatching is the Release Agent's job.

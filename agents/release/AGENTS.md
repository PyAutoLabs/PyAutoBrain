# Release agent

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
consults the Health Agent for the verdict. It does this without ever letting
Heart dispatch a build (Heart is ingest-and-judge only).

The full chain (M2 builds the dispatch+ingest half; M3/M4 add release-fidelity
integration + full orchestration):

```
Mind -> Release Agent (orchestrate) -> Heart (measure) -> Health Agent (judge) -> Hands/Build (promote on GREEN)
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
calls `consult_health_agent_verdict --refresh` so the **read-only Health Agent**
reports GREEN/YELLOW/RED from the freshly-ingested report.

Exit codes (phase 2): `0` green (release-ready) · `2` yellow (use --force) ·
`3` red · `4` unknown · `1` could not ingest.

## What this agent must never do

- Re-derive or second-guess the readiness verdict (that is Heart's / the Health
  Agent's job).
- Run any packaging/tagging/publish step itself (that is Build's job).
- Write into PyAutoHeart or PyAutoBuild repos.

## What only this agent does (not the Health Agent)

- Dispatch/poll/download GitHub workflows and artifacts (via MCP). The Health
  Agent is strictly read-and-reason — it never dispatches. Heart never dispatches
  either. All release-validation dispatching is the Release Agent's job.

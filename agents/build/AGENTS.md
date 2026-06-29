# Build agent

The second canonical **PyAutoBrain** reasoning agent, and the reference example
of how the Brain coordinates *multiple* organs. It is the executive function for
execution work: it owns the build *workflow* but delegates the *building* to
PyAutoBuild and the *health decision* to the Health Agent.

```
Mind  →  Build Agent  →  Health Agent  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  PyAutoBuild (execute)
```

## Fundamental principle

**The Build Agent does not build software itself — PyAutoBuild does.** The Build
Agent decides *whether* building should happen, *what* to build, *which*
PyAutoBuild capability to invoke, and *whether to proceed or stop*. It reasons;
PyAutoBuild executes. It must never duplicate PyAutoBuild functionality.

## Brain agents consult one another

The Build Agent does not call PyAutoHeart directly. It **consults the sibling
Health Agent**, which is the only agent that talks to the Heart organ. This is
the society-of-agents pattern: specialist Brain agents reason *with* each other,
while the organs (Heart, Hands, Memory) provide capabilities and state. Future
agents generalise the same way — a Feature Agent asking the Health Agent if the
tree is fit for a refactor; a Release Agent asking the Build Agent to package.

## Modes (one agent now, clean seam for a Release Agent later)

Release is in scope today because PyAutoBuild currently owns release/build/deploy
execution. It is isolated as its own **mode** so release-specific reasoning never
bleeds into generic build execution, and can split into a dedicated Release Agent
later with no churn to build mode.

| Mode | Default action | Gate policy | Routes to (PyAutoBuild) |
|------|----------------|-------------|--------------------------|
| `build` | `run_all` | lenient — GREEN/YELLOW proceed, RED aborts | `generate`, `run`, `run_python`, `run_all`, `script_matrix`, `aggregate_results`, `slow_skip_check`, `repro_command`, `bump_colab_urls` |
| `deploy` | `generate` | cautious — GREEN proceeds, YELLOW needs `--force`, RED aborts | `generate`, `bump_colab_urls` |
| `release` | `pre_build` | strict — refreshes health first; GREEN proceeds, YELLOW needs `--force`, RED aborts | `pre_build`, `tag_and_merge`, `generate_release_notes`, `create_analysis_issue`, `aggregate_results` |

Release consults health *more strictly*: it asks the Health Agent to refresh
Heart's state first (`--refresh`) so a release is never gated on a stale verdict.
An **unknown** verdict collapses to YELLOW — never silently GREEN.

## Build lifecycle

1. Receive a build request (mode + action).
2. Validate the action against the mode (reject health-shim commands — those are
   Heart's surface, reached via `pyauto-brain health`).
3. Consult the Health Agent for the readiness verdict.
4. Interpret it: **GREEN** proceed · **YELLOW** caution (proceed in build mode,
   else `--force`) · **RED** abort with blockers.
5. Invoke the appropriate PyAutoBuild capability.
6. Emit a structured `BuildDecision`.

## Run

```bash
bin/pyauto-brain build                       # build mode, run_all, after health consult
bin/pyauto-brain build generate autolens     # build mode, generate notebooks for autolens
bin/pyauto-brain build --dry-run             # reason + plan only, do not execute
bin/pyauto-brain build --json generate ag    # emit only the BuildDecision JSON
bin/pyauto-brain build --mode deploy --force generate
bin/pyauto-brain build --mode release -- 2   # release mode; forward minor_version 2 to pre_build
```

Anything after `--` is forwarded verbatim to the PyAutoBuild subcommand.

Exit codes: `0` proceeded/delegated (or dry-run) · `2` yellow blocked (use
`--force`) · `3` red blocked · `4` unknown/could-not-consult · `5` invalid
mode/action.

## BuildDecision (the structured return)

`--json` (or the `-- BuildDecision --` block) emits:

```json
{
  "agent": "build",
  "mode": "build|deploy|release",
  "requested_action": "<PyAutoBuild capability>",
  "health_status": "green|yellow|red|unknown",
  "decision": "proceed|proceed-with-caution|abort",
  "execution_plan": ["autobuild <action> <args>"],
  "execution_summary": "<one line>",
  "warnings": ["..."],
  "blockers": ["..."],
  "follow_up_recommendations": ["..."],
  "dry_run": false
}
```

A future Python `BuildAgent().execute(...)` wrapper can return this same shape.

## What this agent must never do

- Build, package, tag, or publish anything itself — that is PyAutoBuild's job.
- Query PyAutoHeart directly or re-derive a readiness verdict — consult the
  Health Agent.
- Re-own a health-shim command (`verify_install`, `url_check`, `watch`, `status`,
  `tick`, `fix`) — those belong to Heart, reached via `pyauto-brain health`.
- Mix release-specific reasoning into generic build execution — keep it in
  release mode.

See [`BUILD_CAPABILITIES.md`](./BUILD_CAPABILITIES.md) for the audit of every
PyAutoBuild capability the agent calls, and the execution/health boundary.

# Hygiene agent

> **Tier: conductor** — a front-door agent you *drive*. The *maintenance
> function* — the organism's sense of its own upkeep: it owns the code-quality
> debt that neither proves the organism works (that is Heart) nor measures the
> speed of modelling (that is profiling). It consults the read-only vitals
> faculty like every conductor, reasons over the quality signals, and emits a
> `HygieneDecision` the human/session executes — delegating the actual fixes to
> the dev-flow conductors. It never issues health verdicts and never releases.

Grown from demonstrated need: the hygiene reasoning already exists, scattered —
the `repo_cleanup` skill (whose SKILL.md explicitly foreshadowed this "Cleanup
Agent"), `cli_noise_clean`, `dep_audit` and `audit_docs` — plus recurring manual
perf-hygiene work (slow unit tests, slow integration-mode scripts, import cost).
This conductor unifies and prioritises them. Design decision (conductor, **no
paired repo**, boundaries) recorded in PyAutoMind
`research/pyautobrain/hygiene_agent_decision.md` and the founding prompt
`feature/pyautobrain/hygiene_agent.md`.

## Modes

| Mode | Question | Emits |
|------|----------|-------|
| `perf` | Which unit tests / integration-mode workspace scripts / imports are slow, and what is the cheapest win? | timing findings + route (refactor/bug; JAX-adapt only on a clear win) — *phase 3* |
| `tidy` | What git debris (stale branches, stashes, `[gone]` refs, dirty checkouts) is safe to remove? | the `repo_cleanup` sweep — *phase 2* |
| `noise` | What CLI noise (warnings, stray prints, library chatter) do tests/scripts emit? | the `cli_noise_clean` audit — *phase 2* |
| `deps` | Which dependency caps drift behind PyPI, and at what risk? | the `dep_audit` summary — *phase 2* |
| `docs` | Which `docs/api/*.rst` module paths are stale? | the `audit_docs` findings — *phase 2* |
| *(default)* | Across all of the above, what is the single most useful hygiene action now? | a prioritised `HygieneDecision` worklist |

```
pyauto-brain hygiene              # audit across modes → prioritised worklist
pyauto-brain hygiene perf         # dev-loop timing        (staged: phase 3)
pyauto-brain hygiene tidy         # git debris             (staged: phase 2)
pyauto-brain hygiene noise        # CLI noise              (staged: phase 2)
pyauto-brain hygiene deps         # dependency-cap drift   (staged: phase 2)
pyauto-brain hygiene docs         # stale API docs         (staged: phase 2)
pyauto-brain hygiene <mode> --json
```

> **Staged.** This is the phase-1 scaffold: the conductor is real, routable and
> bounded, but the modes are stubs — each prints its staged notice. Phase 2
> absorbs `repo_cleanup` (`tidy`) and `cli_noise_clean` (`noise`) and consults
> `dep_audit` (`deps`) / `audit_docs` (`docs`); phase 3 builds `perf` and any
> PyAutoHeart observation legs.

## Fundamental principles

- **Find and prioritise; delegate the fix.** Hygiene surfaces quality debt and
  ranks it; the actual repair is ordinary dev-flow work routed to `refactor`
  (restructure), `bug` (regression-shaped), or a `feature` — shipped through
  `ship_library` / `ship_workspace`. The conductor never reinvents fix machinery.
- **Measurement lives in Heart; hygiene acts.** Heart already observes and tracks
  the dev-loop timing signals (`script_timing`, `test_run`); hygiene reads them
  and acts, the same split the health conductor follows. New standing signals
  (import cost, CLI noise) become Heart *legs*, not a new repo — hygiene has no
  persistent artifact lifecycle of its own to house (the reason it is a
  conductor with no paired organ).
- **Stdlib / bash only** in the conductor itself — like profiling, it must never
  drag the JAX stack into the Brain.

## Boundaries

- **vs profiling** — split by *what is measured*. Profiling owns the product's
  modelling / compute speed (likelihood on the science grid, GPU tiers, vram,
  A100, baselines/pins); hygiene owns the *developer loop's* cost (unit tests,
  `PYAUTO_TEST_MODE` / `PYAUTO_SMALL_DATASETS` integration scripts, import time).
  Hunting generally-slow functions flagged by integration tests is hygiene's
  `perf` mode (moved here from profiling's staged future modes). JAX-adaptation
  is shared: hygiene flags a dev-loop function and delegates; a likelihood on the
  science grid is profiling's call.
- **vs health** — Heart observes and verdicts; hygiene acts on the observations.
  Consults the vitals faculty; never issues a health verdict.
- **vs bug / refactor** — hygiene finds and prioritises debt and *delegates* the
  fix to them; they own the repair.
- **vs build** — hygiene is upkeep, not release; it never touches PyAutoBuild.

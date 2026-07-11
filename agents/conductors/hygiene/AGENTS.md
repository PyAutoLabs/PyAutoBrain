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

Each mode does a cheap, read-only local **pre-scan** and **delegates** the full
audit + any execution to the owning skill — the conductor never runs a heavy
audit and never mutates a repo. A pre-scan is one of three kinds, which is what
makes its count comparable (or not):

- **debris** — finds directly-removable items; a real, rankable count (`tidy`).
- **surface** — only *sizes* the audit; the real problems emerge when the
  delegated skill runs, so the count is **not** a problem count (`deps`, `docs`).
- **advisory** — no cheap local signal at all (`noise`).

| Mode | Pre-scan (kind) | Delegates to |
|------|-----------------|--------------|
| `perf` | *staged — phase 3* (dev-loop timing: slow tests / integration-mode scripts / imports) | `refactor` / `bug` |
| `tidy` | git debris — stale branches, stashes, `[gone]` refs, dirty checkouts (**debris**) | `/repo_cleanup` (Brain) |
| `noise` | none — needs a pytest + workspace-script run (**advisory**) | `/cli_noise_clean` (Heart) |
| `deps` | capped/pinned specifiers in library `pyproject.toml` (**surface**) | `/dep_audit` (Heart, hits PyPI) |
| `docs` | `docs/api/*.rst` + `currentmodule` counts across the 3 doc repos (**surface**) | `/audit_docs` (Heart, imports) |
| *(default)* | all of the above | a ranked `HygieneDecision` worklist — recommends `tidy` when debris exists (the only directly-actionable count), else prompts the periodic audits |

```
pyauto-brain hygiene              # audit across modes → ranked worklist
pyauto-brain hygiene perf         # dev-loop timing        (staged: phase 3)
pyauto-brain hygiene tidy         # git debris → /repo_cleanup
pyauto-brain hygiene noise        # CLI noise → /cli_noise_clean
pyauto-brain hygiene deps         # dependency-cap surface → /dep_audit
pyauto-brain hygiene docs         # API-docs surface → /audit_docs
pyauto-brain hygiene <mode> --json
```

Repos are read under `PYAUTO_ROOT` (default `~/Code/PyAutoLabs`). `noise`/`deps`/
`docs` route to **read-only PyAutoHeart observation skills** — measurement lives
in Heart; hygiene pre-scans, prioritises and routes. `perf` and any new standing
Heart legs (`import_time` / `cli_noise`) remain phase 3.

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

# Refactor agent

> **Tier: conductor** — a front-door agent you *drive*. The *renewal agent*:
> it plans **behaviour-preserving** internal restructuring and drives it into
> the dev workflow, so it decides *and* acts. It consults the sizing, review,
> memory and vitals faculties; it never edits source itself. It is the first
> conductor whose normal `--auto` mode is **`safe`** (the `refactor` work-type
> cap in [`../../../AUTONOMY.md`](../../../AUTONOMY.md)) — refactoring is
> behaviour-preserving by definition, so tests + the review faculty form a
> near-complete gate.

It reasons over `PyAutoMind/refactor/*` intent and produces a structured
**RefactorDecision** the standard workflow consumes:

```
Mind (refactor/*)  ->  Refactor Agent  ->  start_dev [--auto]
                                        ->  start_library / ship_library
                                        ->  start_workspace / ship_workspace
```

Like the Bug Agent, it **reuses the Feature Agent's core by import**
(minimal-refactor share): prompt parsing, repo/target resolution, the sizing
faculty's difficulty estimate and Memory routing all come from `_feature.py` /
`_sizing.py`, so the conductors cannot drift.

## What it decides (the RefactorDecision)

```
Selected task · Target (+repos) · Difficulty (+score, sizing faculty)
Behaviour preservation: the invariant + the witnesses (test dirs per repo)
API guard: none-expected | SUSPECT-API-CHANGE (-> re-route to feature/)
Effective autonomy: min(header, cap=safe) · Execution plan · Risks · Next action
```

- **Behaviour preservation** — every decision states *what observable
  behaviour must not change* and *which test suites witness it*. A refactor
  with no witness is flagged: strengthen tests first (a `test/` prompt), then
  refactor.
- **API guard** — prompts whose text implies public-API change (removed /
  renamed public symbols, signature changes) are **misclassified**: the
  decision carries a re-route suggestion to `feature/` (or `bug/`) and the
  agent refuses to run them at `safe`. Internal-only restructuring proceeds.
- **Candidates mode** — mines the `refactor/` backlog and refactor-shaped
  `ideas.md` bullets into a ranked list. It **files nothing** — formalising a
  candidate is the Intake Agent's job (`/intake`); this agent only points.

## Scope note (recorded, not absorbed)

The adjacent `ideas.md` "optimize agent" bullet is **not** silently absorbed
here: optimisation changes observable performance behaviour and often numerics,
which breaks this agent's invariant-based gate. If an optimize conductor is
ever warranted it is its own demonstrated-need decision.

## Run

```bash
bin/pyauto-brain refactor                                   # selection: best next refactor task
bin/pyauto-brain refactor refactor/autofit/paths_cleanup.md # specific: plan a named task
bin/pyauto-brain refactor candidates                        # mine backlog + ideas.md (read-only)
bin/pyauto-brain refactor --json ...                        # machine-readable RefactorDecision
```

Writes nothing; exit codes mirror the Feature Agent (`0` decision, `4` no
input/backlog, `5` usage).

## What this agent must never do

- Edit source, open issues/PRs, or start dev — it emits a decision;
  `start_dev` executes.
- Run a suspected-API-change prompt at `safe` — re-route instead.
- Recompute difficulty with its own copy — the sizing faculty's number is the
  number.
- Bypass any leg of the autonomous-ship gate — `safe` changes *who approves*,
  never *what is verified*.

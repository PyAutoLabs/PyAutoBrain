# Sizing faculty

> **Tier: faculty** — a read-only reasoning capability the conductors *consult*,
> not a front door you drive. It *estimates how hard a task is*: given a
> PyAutoMind prompt it parses the structure and returns a difficulty judgment,
> and never writes, dispatches or mutates anything. It is a *sink* in the
> consult graph — everything reaches into it; it reaches out only to the body
> map (`PyAutoMind/repos.yaml`) and the Brain policy surface
> (`config/policy.yaml`) it reads at runtime.

A PyAutoBrain read-only reasoning faculty. It owns the organism's single
difficulty heuristic so the number is defined **once** and shared, never
recomputed by a divergent copy.

It also owns the **precedence rule** over that heuristic. `estimate_difficulty`
derives; `effective_difficulty` reconciles — a **declared** `Difficulty:` wins,
and the derived level comes back alongside it so a disagreement is reported
rather than silently resolved (the disagreement is evidence about the
heuristic). `declared_header` reads the keys a filed prompt declares
(`Type:`/`Difficulty:`/`Autonomy:`/`Priority:`/`Status:`/`Blocked-by:`);
`declared_inline` reads the same keys out of unheadered conception prose — the
`ideas.md` idiom `Difficulty large, supervised.` included. Neither reads a
fenced block: a prompt quoting a header is documenting it, not declaring it.

The rule lives here rather than in each conductor because it was re-implemented
per conductor three times and forgotten twice — the ranker (#217), the Bug Agent
and Intake (#274) all derived over a declared key. One heuristic, one
reconciliation, every conductor.

## Who consults it

- The **Intake Agent** (`agents/conductors/intake/`) sizes a task at
  *conception* time and persists the estimate into the prompt's `Difficulty:`
  header — the number you see up front.
- The **Feature Agent** (`agents/conductors/feature/`) sizes a task at
  *selection / planning* time and acts on that same estimate.

Keeping the heuristic here — one definition imported by both — is the whole
point: a value Intake persists that the Feature Agent silently recomputed with a
divergent copy would be a drift bug (`INTAKE_TAXONOMY.md`).

## The SizingSurface

Given a prompt path, the faculty emits a **SizingSurface**: the parsed prompt
(work-type, targets, science vocabulary) plus a difficulty judgment
`(level, score, factors)`. Levels run small → medium → large;
**`too-large`** is a *routing* signal, not a grade — such prompts go to a
decomposition pass, never straight to dispatch.

The scoring substrate lives in `_sizing.py` (stdlib-only; it reads the body map
via config, never imports the libraries). It also owns the shared prompt-parsing
primitives and the PyAutoMind taxonomy both consulting conductors key off
(mirrors `PyAutoMind/ROUTING.md`).

## Boundaries

- **Read-only.** Never writes a prompt, never files, never dispatches — it
  returns a judgment and stops.
- **No behaviour re-derivation.** The heuristic is defined here once; consumers
  import it rather than re-implementing it.

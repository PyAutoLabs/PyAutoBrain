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
recomputed by a divergent copy — and, since 2026-08-30, the **review-cost
model** beside it.

## The review-cost model

`Difficulty:` measures blast radius. It cannot answer the only question a batch
can be planned against, which is what a task costs the **human** once it lands.
Three outputs answer that, plus one that asks whether the human is needed at all:

| Output | Header | Values | What it is |
|---|---|---|---|
| `consequence` | `Consequence:` | `notify` / `glance` / `judge` | how much review the work needs |
| `witness` | `Witness:` | free text | the machine-checkable claim that makes it reviewable |
| `review_minutes` | `Review-minutes:` | integer | a **seed**, not a measurement (see below) |
| `unattended` | `Unattended:` | `ready` / `needs-slicing` / `never` | can it finish without a human |

Graded by **rules over repo class and surface**, never by an agent's reading of
its own work: the ledger's base rate for an agent mis-scoping its own change is
20% (68 of 332 records in 2026-08 carry a correction or a retraction), so
self-assessment is not an input. Repo class comes from `PyAutoMind/repos.yaml`,
where repo identity is already declared once.

**The rule that carries the model: no `Witness:` means `judge`.** Without it the
field would be aspirational — a prompt could claim a cheap tier while offering
the reviewer nothing but the diff. With it, choosing a cheap tier means
committing at conception to producing evidence, which is what actually makes
work reviewable in minutes. A prompt carrying no witness grades `judge` however
small it looks, and that is the intended behaviour, not a gap.

Measured over the 153 backlog prompts on the day this shipped: **151 grade
`judge`, because 3 carry a witness.** Given one, the same backlog grades 33
`notify` / 104 `glance` / 16 `judge`. The entire distance between "everything
costs a PI's hour" and "a fifth of it costs nothing" is whether prompts declare
what will make them checkable.

`unattended` is deliberately not difficulty renamed. `needs-slicing` keys off the
**compaction rule** — a task that would need context compaction to finish is too
big to run unattended — which is measured rather than cautious
(`anthropics/claude-code#54393`, a postmortem of five consecutive failed
autonomous overnight runs, names "good plan → compact → garbage drift" as a
primary failure primitive, and nothing downstream of the run catches it).

`review_minutes` is a **seed awaiting calibration**, tier-driven with one nudge
for size. The honest numbers come from the batch records, which carry the minutes
the human actually spent. Never read a value from here as evidence about how long
anything took.

**Known limit, stated rather than hidden.** The judged-surface test is keyword
matching over the prompt's prose. Fenced and inline code are masked — a prompt
*quoting* a surface is documenting it, not touching it, the same rule
`declared_header` applies — but prose that *describes* a judged surface still
trips it. The prompts specifying this very model are the worst offenders. The
error is in the safe direction (a false `judge` costs review time, a false
`notify` costs a bad merge), and the keyword list is kept deliberately narrow
because a loose one does not fail safe in the way it first appears: it grades
everything `judge`, the cheap tiers starve, and the model stops discriminating
at all.

## Precedence

It also owns the **precedence rule** over the heuristic, and over every output
of the review-cost model above. `estimate_difficulty`
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

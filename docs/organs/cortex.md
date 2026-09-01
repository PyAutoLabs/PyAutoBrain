# Cortex — PyAutoCortex

**What it owns:** the *science body map* (`projects.yaml` — each science
project's repo and remote, local path, RAL root, laptop mirror, sync CLI,
ledger and witness file) and the **rulings of record** for every science run.
The Cortex is the science mirror of the Mind: the Mind holds prompts and PRs,
the Cortex holds runs and rulings. *The Mind decides what to build, the Brain
routes the work and executes nothing, the Cortex learns what is true.*

**Repo:** [PyAutoLabs/PyAutoCortex](https://github.com/PyAutoLabs/PyAutoCortex)

## The defining function: learning

A science phase begins as a **pre-registered question with a witness** — the
file or number that will settle it — before anything is submitted. The run
happens on RAL or the laptop; its evidence (`.err`, checkpoints, witness
JSONs, figures) is **pulled** to the laptop; the human inspects it and records
a **ruling**: *accept*, *rerun* or *drop*. That ruling is the organism
learning something.

The **ruling-of-record rule:** a verdict recorded only outside the Cortex
does not exist. Project ledgers (a `DECISIONS.md`, a `RESULTS.md`, a project
wiki's `state.md`) remain as scientific commentary — evidence, reasoning,
consequences — and cite the ruling id. Rulings are append-only: a superseded
ruling is never edited, a new one supersedes it.

## Gates

A science phase declares what it waits on as GitHub issue and PR references,
in the `Blocked-by:` grammar the Mind already uses. A daily grading job flips
a phase from *gated* to *ready* when every reference closes. The Mind learns
nothing about the Cortex beyond a render-time badge — "gates a Cortex phase"
— on the development issue in question. One grammar, one direction.

## The driver split

The Cortex *holds runs and rulings*; it decides nothing. The Brain's cortex
conductor (phase 2) does the reasoning — renders the board, grades the gates,
plans and collects batches — the same split as **Heart ↔ vitals** and
**Gut ↔ hygiene**: the organ keeps the state, the conductor reasons over it.

## Driving it

The Brain's **cortex conductor** (`bin/pyauto-brain cortex`, `/cortex`) is the
door. It reasons over the Cortex and writes only what the Cortex's own script
would write:

| Verb | What it does |
|------|--------------|
| `census` | What the Cortex is holding — phases by state, rulings, projects, batches |
| `dashboard --check` \| `--apply` | The generated board, `dashboard.md` + `dashboard.html`. `--check` exits **1** on drift — the contract the Cortex's `dashboard_refresh.yml` runs on. The two pages are generated: never hand-edit them |
| `gates [--grade] [--apply]` | The refs each gated phase waits on, their verdicts, and (with `--apply`) the `gated → ready` flips — a thin wrapper over the Cortex script's own `gates_report`, so the **daily** `gates_grade.yml` runs the same grading with no Brain checkout |
| `plan [--budget N]` | Which `ready` phases fit a laptop slot — witness registered, budget set, lane the session's — cheapest first, with the exact launch lines |
| `collect [--slot S] [--pull] [--refreshed ISO] [--apply] [--out F]` | What the pull brought back, as packet member blocks: six legs (`err`, `wall`, `version`, `checkpoint`, `resume`, `witness`) each `PASS`/`FAIL`/**`UNOBSERVABLE`**, the witness readout and a blank ruling line. `--pull` runs the project's own sync CLI; `--apply` moves each member `running → pulled → awaiting-ruling` and appends its `refreshed:` line. Exit **1** = a member the human must look at |

**The board** opens with what needs the human: *Awaiting ruling* (failures
first), then *Running / submitted* with wall against budget, *Ready*, *Gated*
with the open refs, then the ruling ledger, the epics (each card linking its
Mind half) and the project map. It is published to GitHub Pages and carries the
one-tap 📋 payload every board in the family carries; the Brain board reads its
counts table for the morning Cortex strip.

**Two of the four `delivered:` legs are not observable on the laptop** — the
checkpoint is excluded from both projects' pulls and one project writes no
version stamp — so `collect` scores them UNOBSERVABLE and the member reaches
the human as SUSPECT rather than as a failure it cannot prove.

**What the conductor never does:** submit a run, write a ruling, read `sacct`
as health, or touch RAL. The submission is the human's act, the verdict is the
human's word, and both are recorded through
`python3 scripts/cortex.py move | rule`.

## Batches

Cortex batches are a **rolling board**, not a review-at-once slot: a member
joins the review when its results are pulled, and nothing mid-flight is
reviewable. They carry their own `review-at:`, separate from the Mind's
development batches — the two kinds of work keep the batch-processing API but
never share one batch.

## For an adopter

Like Mind, Memory and Gut, the Cortex is an **instance organ** — inherently
yours. You do not fork this repo's contents; you create your own Cortex with
the same shape, pointing at your own science projects and holding your own
rulings.

The birth of this organ is tracked in the
[cortex-birth epic ledger](https://github.com/PyAutoLabs/PyAutoMind/blob/main/draft/feature/pyautocortex/cortex_birth_epic.md).
The repo is born empty; phase 1 fills it.

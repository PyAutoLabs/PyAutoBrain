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

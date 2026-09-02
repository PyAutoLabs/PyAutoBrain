# Cortex — PyAutoCortex

**What it owns:** the *science body map* (`projects.yaml` — each science
project's repo and remote, local path, RAL root, laptop mirror, sync CLI,
ledger and witness file) and the **rulings of record** for every science run.
The Cortex is the science mirror of the Mind: the Mind holds prompts and PRs,
the Cortex holds runs and rulings. *The Mind decides what to build, the Brain
routes the work and executes nothing, the Cortex learns what is true.*

**Repo:** [PyAutoLabs/PyAutoCortex](https://github.com/PyAutoLabs/PyAutoCortex)
· schemas and grammars:
[REFERENCE.md](https://github.com/PyAutoLabs/PyAutoCortex/blob/main/REFERENCE.md)

## The defining function: learning

A science phase begins as a **pre-registered question with a witness** — the
file or number that will settle it — before anything is submitted. The run
happens on RAL or the laptop; its evidence (`.err`, checkpoints, witness
JSONs, figures) is **pulled** to the laptop; the human inspects it and records
a **ruling**: *accept*, *rerun* or *drop*. That ruling is the organism
learning something.

The unit is a **phase** of a **project** — one markdown file under
`phases/<project>/` that spawns **runs** (SLURM job ids) and ends in a ruling.
Development work a phase waits on stays in the Mind, named here only as a gate.

## The state model

A phase moves through ten states, and the sentence is the lifecycle:
**planned** until its gates are written, **gated** while they are open,
**ready** once they clear, **submitted** when the human launches the run,
**running** while it is on the cluster, **pulled** when the evidence reaches
the laptop, **awaiting-ruling** while it sits on the review board, and then
**accepted**, **rerun** or **dropped** by the human's word. Two rules make the
model worth having:

- **`scripts/cortex.py move` owns every edge except the last three.**
  `accepted`, `rerun` and `dropped` are reachable **only** through
  `scripts/cortex.py rule`, which writes the ruling file and the phase's
  `Ruling:` in one act — a phase cannot be marked accepted with no ruling of
  record to point at.
- **`accepted` is not terminal; `dropped` is.** A later ruling may supersede an
  acceptance (that is what a rewind is), and a `rerun` returns to `ready`
  keeping its run history. Reviving a dropped phase means a new phase number.

`legacy` and `legacy_wrong` are states of a **run**, never of a phase — the
quarantine for results produced before a rule the project has since adopted.
`scripts/cortex.py check` enforces the table and its invariants: a witness
before `submitted`, a cleared or overridden gate before `ready`, a ruling
before any terminal state.

## The ruling-of-record rule

**A verdict recorded only outside the Cortex does not exist.** Project ledgers
(a `DECISIONS.md`, a `RESULTS.md`, a project wiki's `state.md`) remain as
scientific commentary — evidence, reasoning, consequences — and cite the ruling
id. Rulings are append-only: a wrong ruling is superseded by a new one and
never edited, and the ledger-merge classifier treats any modification or
deletion under `rulings/` as code, which is a human's turn.

## Gates

A science phase declares what it waits on as GitHub issue and PR references in
its `Gates:` header — `Repo#N` under the default owner, or a full issue/PR URL
— the same grammar the Mind's `Blocked-by:` uses, sharing its regular
expression verbatim. A **daily grading job** (`gates_grade.yml`, 06:47 UTC)
polls those refs and flips a phase `gated → ready` when every one has closed,
stamping `Gates-cleared:`; a cleared gate that reopens flips it back. It is the
one scheduled job in the repo that mutates the ledger, it may make no other
move, and an unreadable ref fails closed — the phase is skipped and the run
goes red so a human sees the ref.

The Mind learns nothing about the Cortex beyond a **render-time badge** —
"gates a Cortex phase" on the development issue in question. One grammar, one
direction.

## What it never does

- **It never dispatches.** No verb in the Cortex or in its conductor submits a
  job, cancels one, or touches RAL. The submission is the human's act at the
  laptop, through the project's own sync CLI, and is recorded afterwards.
- **It never holds data.** The science project trees, their outputs, mirrors
  and checkpoints stay where they are; `projects.yaml` points at them. What is
  committed here is the question, the run ids, the verdict.
- **It never runs under an autonomy level.** Every phase is `Lane: local-dev`;
  the review happens at the laptop, on evidence in the human's hands. The
  autonomy cap is not consulted when a science member is admitted to a slot: a
  science run is supervised by definition, and no autonomous ship gate can
  produce a ruling.
- **It never reads `sacct` as health.** SLURM says a process exited, not that
  it produced science: a run is *delivered* only when the `.err` is clean, wall
  is inside `Budget:`, the version stamp is there and the checkpoint is sane.

## Driving it

The Cortex *holds runs and rulings*; it decides nothing. The Brain's **cortex
conductor** (`bin/pyauto-brain cortex`, `/cortex`) does the reasoning — the
same split as **Heart ↔ vitals** and **Gut ↔ hygiene**.

| Verb | What it does |
|------|--------------|
| `census` | What the Cortex is holding — phases by state, rulings, projects, batches |
| `dashboard --check` \| `--apply` | The generated board, `dashboard.md` + `dashboard.html`. `--check` exits **1** on drift — the contract the Cortex's `dashboard_refresh.yml` runs on. The two pages are generated: never hand-edit them |
| `gates [--grade] [--apply]` | The refs each gated phase waits on, their verdicts, and (with `--apply`) the `gated → ready` flips — a thin wrapper over the Cortex script's own grading, so the daily job needs no Brain checkout |
| `plan [--budget N]` | Which `ready` phases fit a laptop slot — witness registered, budget set, lane the session's — cheapest first, with the exact launch lines |
| `collect [--slot S] [--pull] [--apply]` | What the pull brought back, as packet member blocks: six legs (`err`, `wall`, `version`, `checkpoint`, `resume`, `witness`) each `PASS`/`FAIL`/**`UNOBSERVABLE`**, the witness readout and a blank ruling line. `--pull` runs the project's own sync CLI; `--apply` moves each member `running → pulled → awaiting-ruling`. Exit **1** = a member the human must look at |

The **batch conductor** is the slot door over those two verbs. `pyauto-brain
batch plan --kind cortex --apply --review-at <ISO>` opens the slot's record
under `batches/`, refused without the `--review-at` the human states — the
shift is dispatch → review-at, and that horizon is theirs to declare. `batch
collect --kind cortex [--pull] [--apply]` is the **rolling board**: a phase
joins the review on the pull that fills its results in, each pull appends a
`refreshed:` line, and a member still running renders with its job ids and
wall-against-budget but **holds no review control at all** — there is nothing
to say about a run that has not finished. At close it is written out as
`carried:` and the next plan picks it up at its current state, so a long run
never holds a review. A Mind record never lists a science member and a Cortex
record never lists a development one: two genres, two vocabularies, two
`review-at:` times.

## The board

![The Cortex board](../_static/cortex_board.png)

Every phase the Cortex is holding on one page — awaiting ruling first, then
running, ready, gated, the ruling ledger, the epics (each linking its Mind
half) and the project map — published at
<https://pyautolabs.github.io/PyAutoCortex/>. It hands out the next command;
the verdict is never on the page.

## For an adopter

Like Mind, Memory and Gut, the Cortex is an **instance organ** — inherently
yours. You do not fork this repo's contents; you create your own Cortex with
the same shape — a body map of your projects, a phase file per question, a
place to write what you decided — and hold your own rulings in it.

The birth of this organ is tracked in the
[cortex-birth epic ledger](https://github.com/PyAutoLabs/PyAutoMind/blob/main/draft/feature/pyautocortex/cortex_birth_epic.md).

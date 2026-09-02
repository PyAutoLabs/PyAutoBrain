# Cortex agent

> **Tier: conductor** — a front-door agent you *drive*. The *learning
> function* — where the organism finds out what is true: it reasons over
> PyAutoCortex (the science body map, the pre-registered phases, the rulings
> of record), renders the Cortex board, grades the gates and admits ready
> phases into a laptop slot. It **never submits a run and never writes a
> ruling**: the run is the human's act, the verdict is the human's word, and
> the ruling file is the Cortex script's to write.

The same split the organism already uses twice — **Heart ↔ vitals**, **Gut ↔
hygiene**: the organ keeps the state, the conductor reasons over it. The
Cortex holds runs and rulings the way the Mind holds prompts and PRs; this is
the Cortex's intake-and-dashboard conductor.

## Verbs

| Verb | Question | Emits |
|------|----------|-------|
| `census` | What is the Cortex holding? | phase counts by state, the board's section counts, rulings, projects, batches, epics (`--json` for the lot) |
| `dashboard --check` | Are the committed pages current? | exit 0 current · **1 stale** · 2 no checkout · 3 unreadable tree |
| `dashboard --apply` | — | writes `dashboard.md` + `dashboard.html` |
| `gates [--grade] [--apply]` | What is each gated phase waiting on, and has it cleared? | the refs, a verdict per phase, and with `--apply` the `gated → ready` flips |
| `plan [--budget N]` | Which ready phases fit the slot? | `== CortexPlan ==` — members against the review-minute budget, plus the launch lines |
| `collect [--slot S] [--pull] [--refreshed ISO] [--apply] [--out F] [--phase REL]` | What did the pull bring back, and is it worth reviewing? | one packet member block per live member — six scored legs, the readout, a blank ruling line — and exit **1** when any member is not HEALTHY |

```
pyauto-brain cortex                          # census
pyauto-brain cortex dashboard --apply
pyauto-brain cortex gates --grade
pyauto-brain cortex plan --budget 30
pyauto-brain cortex collect --pull --apply       # score the board, then move it on
pyauto-brain cortex <verb> --cortex <dir>    # another checkout
```

## Where the Cortex is

`--cortex <dir>` → `$PYAUTO_CORTEX` → beside this PyAutoBrain checkout →
`$PYAUTO_ROOT/PyAutoCortex`. Its own resolver (`resolve_cortex` in
`agents/_common.sh`, mirrored in `_cortex.py`), never an extension of the
Mind's: a session holding one organ and not the other still works.

## What it reads, and what it refuses to read

- `<cortex_root>/scripts/cortex.py` is imported at runtime and is the schema
  API: `load_phases`, `load_rulings`, `load_projects`, `gates_report`,
  `batch_records`, `move_phase`. The conductor always reasons with the schema
  the checkout it is pointed at implements.
- **Stdlib only, and Mind-free.** The renderer runs bare inside the Cortex's
  own `dashboard_refresh.yml`, which installs nothing and checks out no
  PyAutoMind — so `_cortex.py` imports neither `_sizing` nor `_intake` (both
  hard-fail without a Mind checkout). The Mind's renderer helpers are copied,
  not imported; that duplication is the price of a one-repo render.
- **No path is named in this code.** Science projects live outside the
  workspace; the one place carrying such a path is the Cortex's own
  `projects.yaml`, and every path the board prints is read from a row of it.

## The board

Sections, in the reading order of a slot: **Awaiting ruling** (pulled and
awaiting-ruling phases, ordered failures → a ruling is required → clean) →
**Running / submitted** (job ids, wall against the phase's budget, the last
`refreshed:` line) → **Ready** → **Gated** (the open refs) → **Recent
rulings** → **Epics** (each card links its Mind half) → **Projects** (the
where-to-look table straight from `projects.yaml`). A counts table near the
top is what `board/_board.py` reads for the Brain board's Cortex strip.

`--check` compares the pages with the generation comment **and** the visible
`Last updated` banner stripped, so a re-render on a new date is not drift —
the Mind's normaliser strips only the comment, which is why its refresh
workflow self-heals with an empty commit most nights.

## The admission rule (`plan`)

A phase is plannable when its `State:` is `ready`, its `Witness:` is
registered, its `Budget:` is set and its lane is the session's — detected the
way the batch conductor detects it (`gh` on PATH ⇒ `local-dev`). Cheapest
first against `--budget` (default 45 review-minutes). **No autonomy cap is
consulted**: science members are supervised by definition, and the ruling is
the human's. A cloud session reports the ready count and plans nothing — a
science run is launched from the machine that can reach the queue.

## Gate grading

`gates --grade [--apply]` is a thin wrapper over the Cortex script's own
`gates_report(root, grade=…, write=…)`. The grading rule (a PR clears when it
merged; an issue when it closed as `completed`; anything unreadable fails
closed) and the writes live there, so the Cortex's daily `gates_grade.yml`
runs them with no Brain checkout at all. `--apply` is this surface's spelling
of the script's `--write`, and it may only ever move `gated → ready` (and
demote a `ready` phase whose gate reopened).

## Scoring a pull (`collect`)

The board is rolling: a member joins the review on the pull that fills its
results in. `collect` scores every member whose phase is `submitted` or
`running` (or the phases named by `--phase`) against **six legs**, each
`PASS | FAIL | UNOBSERVABLE`:

| Leg | Read from |
|-----|-----------|
| `err` | every `error.<jobid>*.err` under the roots. Benign = every non-blank line is a `*Warning*` line or its indented continuation — **not** size 0; `Traceback`/`Error`/`Killed`/`OOM` ⇒ FAIL |
| `wall` | the `.out`'s first and last date stamps when it ends `Finished.`, else `Time To Run` in `search.summary` — **from the `<hash>.zip` when there is one**, because an extracted run dir can be a stale partial. Over `Budget:` ⇒ FAIL |
| `version` | a top-level `version` key in a JSON matching the project's `witness_file` |
| `checkpoint` | `<root>/.cortex/pull.json` only (`{"schema": 1, "pulled_at": ISO, "checkpoints": {"<run dir rel to the pull root>": {"bytes": N, "mtime": ISO}}, "runs": {"<jobid>": {"checkpoint_bytes": N, "checkpoint_mtime": ISO}}}`; looked up `runs[<jobid>]` → `runs[<stem>]` → `checkpoints[<run dir rel>]`, and a manifest with no `schema` is the older `runs`-only shape) — `search_internal/checkpoint.hdf5` is never pulled, so without that manifest the leg is UNOBSERVABLE, tagged `RAL only` |
| `resume` | `Fit Already Completed` / `Resuming … previous samples found` in the `.out` ⇒ FAIL: those are the previous fit's numbers |
| `witness` | a file matching `witness_file` newer than the phase's first submission |

HEALTH is **FAILED** if any leg failed, **SUSPECT** if any is unobservable,
**HEALTHY** otherwise; `delivered:` counts the HEALTHY ones. Two of the four
`delivered:` legs of `batches/AGENTS.md` are simply not visible on the laptop
today — inventing PASS for them would be inventing evidence and FAIL would
condemn every healthy run, so they are UNOBSERVABLE and the member goes to the
human as SUSPECT.

Everything is read from the laptop tree the human's own sync CLI filled; the
search roots are the project's `mirror` then `local_path`, from
`projects.yaml`. **The only thing that reaches the cluster is `--pull`**, which
runs that project's own `<sync_cli> pull` and prints the command first.
`--apply` (which needs a refresh stamp, from `--pull` or `--refreshed <ISO>`)
moves each member `running → pulled → awaiting-ruling`, appends one
`- refreshed:` line per member and rewrites the member's `<state>` — rehearsed
on a throwaway copy of the tree first and refused outright if
`cortex.py check` would not pass afterwards. A phase whose run line is still
live, or one still `submitted` (no such edge), is left where it is with a note.

## What it never does

Submits a job · writes or edits a ruling · reads `sacct` as health · touches
RAL · consults an autonomy cap · edits a phase except through the Cortex
script's own `move`.

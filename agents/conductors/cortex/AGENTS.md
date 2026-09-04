# Cortex agent

> **Tier: conductor** — a front-door agent you *drive*. The *learning
> function* — where the organism finds out what is true: it reasons over
> PyAutoCortex (the science body map, the pre-registered phases, the rulings
> of record), renders the Cortex board, lists what the gates are waiting on
> and scores what came back from a pull. It **never submits a run and never
> writes a ruling**: the run is the human's act, the verdict is the human's word, and
> the ruling file is the Cortex script's to write.

The same split the organism already uses twice — **Heart ↔ vitals**, **Gut ↔
hygiene**: the organ keeps the state, the conductor reasons over it. The
Cortex holds runs and rulings the way the Mind holds prompts and PRs; this is
the Cortex's intake-and-dashboard conductor.

## Verbs

| Verb | Question | Emits |
|------|----------|-------|
| `census` | What is the Cortex holding? | phase counts by state, the board's section counts, rulings, projects, epics (`--json` for the lot) |
| `dashboard --check` | Are the committed pages current? | exit 0 current · **1 stale** · 2 no checkout · 3 unreadable tree |
| `dashboard --apply` | — | writes `dashboard.md` + `dashboard.html` |
| `gates` | What is each gated phase waiting on? | every gated phase, its refs and the URL each resolves to — read-only and offline |
| `collect [--pull] [--refreshed ISO] [--apply] [--out F] [--phase REL]` | What came back, and is it worth reviewing? | one block per phase — six scored legs, the readout, a blank ruling line — and exit **1** when any is not HEALTHY. **Default scope: every `submitted \| running` phase**; `--phase REL` narrows |

```
pyauto-brain cortex                          # census
pyauto-brain cortex dashboard --apply
pyauto-brain cortex gates
pyauto-brain cortex collect --pull --apply   # the check-in: pull, score, move on
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
  `move_phase`. The conductor always reasons with the schema
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

Sections, in the reading order of a check-in: **Awaiting ruling** (pulled and
awaiting-ruling phases, ordered failures → a ruling is required → clean) →
**Running / submitted** (job ids, wall against the phase's budget) →
**Ready** → **Gated** (the open refs) → **Recent
rulings** → **Epics** (each card links its Mind half) → **Projects** (the
where-to-look table straight from `projects.yaml`). A counts table near the
top is what `board/_board.py` reads for the Brain board's Cortex strip.

`--check` compares the pages with the generation comment **and** the visible
`Last updated` banner stripped, so a re-render on a new date is not drift —
the Mind's normaliser strips only the comment, which is why its refresh
workflow self-heals with an empty commit most nights.

## Gates

`gates` is a thin wrapper over the Cortex script's own `gates_report(root)`:
every gated phase, its refs and the URL each ref resolves to. Nothing polls
GitHub and nothing flips a state — gate grading was retired on 2026-09-03 (2
gated refs, 0 flips in its lifetime; sequencing is prose `Ready when:` lines
per Cortex schema decision 54). A human opens the refs and, when they have
closed, types `python3 scripts/cortex.py move <phase> ready`.

## The check-in (`collect`)

This is the verb the human actually drives: *what came back?* With no
`--phase` it scopes to **every phase in `submitted | running`** — the runs the
Cortex believes are out there — and needs no record of any kind. `--phase REL`
(repeatable) narrows it to named phases. Each is scored against **six legs**,
each `PASS | FAIL | UNOBSERVABLE`:

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
`delivered:` legs the batch records were scored on are simply not visible on
the laptop today — inventing PASS for them would be inventing evidence and FAIL would
condemn every healthy run, so they are UNOBSERVABLE and the member goes to the
human as SUSPECT.

Everything is read from the laptop tree the human's own sync CLI filled; the
search roots are the project's `mirror` then `local_path`, from
`projects.yaml`. **The only thing that reaches the cluster is `--pull`**, which
runs that project's own `<sync_cli> pull` and prints the command first.
`--apply` (which needs a refresh stamp, from `--pull` or `--refreshed <ISO>`,
so a human cannot move phases on a stale laptop) moves each phase
`running → pulled → awaiting-ruling` — rehearsed on a throwaway copy of the
tree first and refused outright if `cortex.py check` would not pass afterwards.
Nothing else is written. A phase whose run line is still live, or one still
`submitted` (no such edge), is left where it is with a note.

## What it never does

Submits a job · writes or edits a ruling · reads `sacct` as health · touches
RAL · consults an autonomy cap · edits a phase except through the Cortex
script's own `move`.

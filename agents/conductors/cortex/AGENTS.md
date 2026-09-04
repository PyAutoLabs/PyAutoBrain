# Cortex agent

> **Tier: conductor** — a front-door agent you *drive*. The *learning
> function* — where the organism finds out what is true: it reasons over
> PyAutoCortex (the science body map, the pre-registered phases, the rulings
> of record) and answers one question — *where is my science?* — with one
> command, `checkin`: pull every active project, score every live run, move
> what came back, re-render the board, push the ledger, summarise by project.
> It **never submits a run and never writes a ruling**: the run is the human's
> act, the verdict is the human's word, and the ruling file is the Cortex
> script's to write.

The same split the organism already uses twice — **Heart ↔ vitals**, **Gut ↔
hygiene**: the organ keeps the state, the conductor reasons over it. The
Cortex holds runs and rulings the way the Mind holds prompts and PRs; this is
the Cortex's intake-and-dashboard conductor.

## Verbs

| Verb | Question | Emits |
|------|----------|-------|
| `checkin [--dry-run \| --apply] [--push \| --no-push] [--project KEY] [--skip-pull] [--refreshed ISO]` | **Where is my science?** | the door — the sequence below, ending in a summary keyed by project; exit **1** when a pull failed or the tree needs a look |
| `census` | What is the Cortex holding? | phase counts by state, the board's section counts, rulings, projects, the last check-in stamp (`--json` for the lot) |
| `dashboard --check` | Are the committed pages current? | exit 0 current · **1 stale** · 2 no checkout · 3 unreadable tree |
| `dashboard --apply` | — | writes `dashboard.md` + `dashboard.html` |
| `gates` | What is each gated phase waiting on? | every gated phase, its refs and the URL each resolves to — read-only and offline |
| `collect [--pull] [--refreshed ISO] [--apply] [--out F] [--phase REL]` | What came back, and is it worth reviewing? | one block per phase — six scored legs, the readout, a blank ruling line — and exit **1** when any is not HEALTHY. **Default scope: every `submitted \| running` phase**; `--phase REL` narrows |

```
pyauto-brain cortex checkin --dry-run        # what it would pull and score
pyauto-brain cortex checkin --apply          # the check-in
pyauto-brain cortex                          # census
pyauto-brain cortex dashboard --apply
pyauto-brain cortex gates
pyauto-brain cortex collect --pull --apply   # the scorer on its own
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

The page opens on the door, not on the work: a counts table (what
`board/_board.py` reads for the Brain board's Cortex strip), then the
**check-in chip** — the paste for the laptop's science chat — and the **last
check-in** stamp under it. Then **Summary** (one row per active project),
then the sections in the reading order of a check-in: **Projects** (active →
planned → dormant; each card is the folders, the counts and the ONE phase to
act on next, with the rest of its open phases and its issue list behind a
fold) → **Awaiting ruling** (ordered failures → a ruling is required → clean)
→ **Running / submitted** → **Ready** (one visible row per project, the
queue behind it folded) → **Gated** → **Recent rulings**.

No `## Where to look` bullets ride on the page — they stay in the phase file,
in `census --by-project` and in the check-in printout, which keep the full
per-phase tree. The Cortex has no epics of its own (retired 2026-09-04): a
science project *is* the long programme, and `Epic:` on a phase header is
only an optional join key to a **Mind** epic.

**`checkin.yaml`** is the one-key file (`refreshed: <UTC ISO 8601>`) that
`cmd_checkin` and `collect --apply` write from the stamp they scored against,
before rendering. `census()` reads it into `c["checkin"]`; missing means
"never checked in", unparseable is a `problems` line. The stamp means *last
check-in*, never last render, so a doc-only push cannot fake freshness, and
the HTML twin computes its age on the **viewer's** clock (a static page
cannot know when it is read) and reddens it past sixty minutes.

`--check` compares the pages with the generation comment **and** the visible
`Last updated` banner stripped, so a re-render on a new date is not drift —
the Mind's normaliser strips only the comment, which is why its refresh
workflow self-heals with an empty commit most nights. `checkin.yaml` needs no
rule of its own: it is stable between renders.

## Gates

`gates` is a thin wrapper over the Cortex script's own `gates_report(root)`:
every gated phase, its refs and the URL each ref resolves to. Nothing polls
GitHub and nothing flips a state — gate grading was retired on 2026-09-03 (2
gated refs, 0 flips in its lifetime; sequencing is prose `Ready when:` lines
per Cortex schema decision 54). A human opens the refs and, when they have
closed, types `python3 scripts/cortex.py move <phase> ready`.

## The door (`checkin`)

The verb a human types. It composes what is already here and reasons nothing
extra of its own:

1. **Sync.** Every project with `status: active` in `projects.yaml`, plus any
   project that owns a phase in `submitted | running` (a dormant project with a
   job still out there is still out there). Each is pulled with **its own**
   `<local_path>/<sync_cli> pull` — the verb all seven implement — and the
   output is **streamed**, not captured: a pull runs for minutes and the human
   is watching this one command. A non-zero exit is recorded against that
   project and the sweep continues; one unreachable mirror must not hide the
   other six. After a good pull the door writes `<pull root>/.cortex/pull.json`
   (`project`, `pulled_at`, `cmd`, `rc`, `phases_live`) — **merged** into
   whatever is already there, because one project's own CLI writes the richer
   `checkpoints` / `runs` tables the scorer's checkpoint leg reads.
2. **Score + move.** `collect`'s scorer over every live phase, then the same
   rehearsed `_apply_checked` moves.
3. **Render.** `dashboard.md` + `dashboard.html`.
4. **Push** (the rule below).
5. **Summarise, by project** — printed **last**, so a chat sees it above the
   fold: each project's paths, what its pull did, its phase counts, and every
   phase a human could act on today with its health verdict and the fenced,
   copy-ready prompt its state already has (`_ruling_payload`,
   `_live_payload`, `_ready_payload`, `_gate_payload`). `project_digest()`
   builds one project's block and `checkin_summary()` the whole thing.

`--dry-run` (the default) prints the exact pull command per project, the pull
root, and every phase it would score — and reaches nothing at all. `--project
KEY` narrows the sweep; `--skip-pull` re-scores what is already on the laptop,
stamping the refresh from the newest manifest.

### The push rule

`--push` is allowed only when **`gh auth status` succeeds** *and* **the Cortex
checkout is clean on `main`** — read *before* anything is written, because
"clean" stops being true the moment the phases move. That is the whole
cloud/laptop split, and it is also the default: a laptop pushes without asking,
a cloud session cannot and says so. The push cuts
`claude/checkin-<YYYY-MM-DD>` from a fresh `origin/main`, commits the changed
paths **explicitly**, pushes, and names `ledger_merge.yml` as what lands it.
`scripts/ledger_merge.py classify` is asked first and a code-classified diff is
refused before the branch is cut. Never `main`, never `--force`, and a
same-day re-check-in reuses its branch rather than resetting a pushed ref.

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

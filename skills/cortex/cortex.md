# /cortex — the science board (via the Brain Cortex Agent)

Route science-run work — phases, gates, runs, rulings — through PyAutoBrain's
**Cortex Agent**, the learning function. Development work is the Mind's and
goes through `/intake` and `/start_dev`; this door is for what the organism is
finding out, not what it is building.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain cortex [census | dashboard --check|--apply |
   gates [--grade] [--apply] | plan [--budget N] | collect [--pull]
   [--apply]]`. `census`, `plan` and a bare `collect` are read-only;
   `dashboard --apply` writes the two generated pages; `gates --apply` writes
   only the `gated → ready` flips the grading earned; `collect --apply` moves
   the scored members on and writes the batch record.
2. Read the result to the human and hand them the command the row carries.
   **Never** decide a ruling, never submit a job, never edit a phase file by
   hand — every phase edit goes through `python3 scripts/cortex.py move` and
   every verdict through `python3 scripts/cortex.py rule`, both in the
   PyAutoCortex checkout, and the ruling body is the human's words verbatim.
3. Point at another checkout with `--cortex <dir>` (default: `$PYAUTO_CORTEX`,
   then `PyAutoCortex` beside PyAutoBrain).

## The verbs

| Verb | Answers |
|------|---------|
| `census` | What is the Cortex holding? Phase counts by state, rulings, projects, batches (`--json` for all of it) |
| `dashboard --check` | Are the committed pages current? Exit **1** = stale (the refresh workflow's contract) |
| `dashboard --apply` | Regenerate `dashboard.md` + `dashboard.html` — never hand-edit those two files |
| `gates [--grade]` | What is each gated phase waiting on, and has it cleared? `--apply` writes the flips |
| `plan [--budget N]` | Which ready phases fit the slot, cheapest first, and the exact launch lines |
| `collect [--slot S] [--pull] [--refreshed ISO] [--apply] [--out F]` | What did the pull bring back? One packet member block per live member — six legs each `PASS`/`FAIL`/`UNOBSERVABLE`, the readout, a **blank** ruling line. Exit **1** = a member the human must look at |

## The rules that do not bend

- **The conductor never submits.** `plan` proposes; the human runs the
  project's own sync CLI and then records the job id with
  `cortex.py move <phase> submitted --run <jobid>`.
- **A verdict recorded only outside the Cortex does not exist.** A decision
  reached in chat is not a ruling until `cortex.py rule` has written it.
- **A phase is a question with a pre-registered witness.** If `Witness:` is
  empty, the phase cannot be submitted — write the witness first.
- **Gate grading only ever moves `gated → ready`** (and demotes a `ready`
  phase whose gate reopened). It never touches a submitted run.
- **`collect` never touches RAL, and never rules.** It reads only what the
  human's own sync CLI already mirrored; `--pull` runs that CLI's `pull` and
  nothing else; the `Ruling` line it emits is left blank for the human.
- **UNOBSERVABLE is not FAIL.** Two of the four `delivered:` legs are not
  visible on the laptop (the checkpoint is never pulled; one project writes no
  version stamp), so those members come back **SUSPECT** — read them, do not
  treat them as broken runs.
- **A cloud session plans nothing** — every Cortex phase is `local-dev`, so a
  session with no `gh` reports the ready count and stops.

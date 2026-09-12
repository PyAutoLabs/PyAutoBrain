# Cortex agent

> **Tier: conductor** — a front-door agent you *drive*. The *learning
> function* — where the organism keeps track of what is true: it reasons over
> PyAutoCortex (the science body map and **one ledger per project**) and
> answers one question — *where is my science?* — with one command,
> `checkin`: pull every active project through its own sync CLI, show where
> each run stands, re-render the board, push the ledger, read it back by
> project. It **records cluster facts and the human's words, never a verdict
> of its own**: it never scores a result, never drafts a ruling, never writes
> a `result` or `lesson` entry the human did not say. A run is submitted only
> on the human's ask (by the agent in the session, through the project's own
> sync CLI), and every ledger write is a `scripts/cortex.py` verb.

The same split the organism already uses twice — **Heart ↔ vitals**, **Gut ↔
hygiene**: the organ keeps the state, the conductor reasons over it. A ledger
is `projects/<key>.md`: `## Now` (2–3 lines the human rewrites — what is
running, what they meant to do next), `## Runs` (the jobs on the cluster right
now, `open | running`; a finished run leaves the list and becomes a log
entry), `## Log` (dated entries, newest first, kind `run | result | lesson |
note`).

## Verbs

| Verb | Question | Emits |
|------|----------|-------|
| `checkin [--dry-run \| --apply] [--push \| --no-push] [--project KEY] [--skip-pull]` | **Where is my science?** | the door — the sequence below, ending in a summary keyed by project; exit **1** when a pull failed or the tree does not check |
| `census [--json]` | What is the Cortex holding? | per project: status, summary, runs by state, log length, last update; totals (active projects, runs open, runs running); the check-in stamp; the problems `cortex.py check` would report |
| `dashboard --check` | Are the committed pages current? | exit 0 current · **1 stale** · 2 no checkout · 3 unreadable tree |
| `dashboard --apply` | — | writes `dashboard.md` + `dashboard.html` |
| `issue [--project KEY] [--apply]` | What sits at the top of each project's issue? | the fenced ledger block (`cortex.py`'s `issue_block`) per project with an `Issue:`; `--apply` writes it into the issue body through `gh` (replacing the block between the markers, or prepending it); never creates an issue; exit **1** without `gh` |

```
pyauto-brain cortex checkin --dry-run        # what it would pull; reaches nothing
pyauto-brain cortex checkin --apply          # the check-in
pyauto-brain cortex                          # census
pyauto-brain cortex dashboard --apply
pyauto-brain cortex issue --apply
pyauto-brain cortex <verb> --cortex <dir>    # another checkout
```

## Where the Cortex is

`--cortex <dir>` → `$PYAUTO_CORTEX` → beside this PyAutoBrain checkout →
`$PYAUTO_ROOT/PyAutoCortex`. Its own resolver (`resolve_cortex` in
`agents/_common.sh`, mirrored in `_cortex.py`), never an extension of the
Mind's: a session holding one organ and not the other still works.

## What it reads, and what it refuses to read

- `<cortex_root>/scripts/cortex.py` is imported at runtime and is the schema
  API: `load_projects`, `load_ledgers`, `check_problems`, `issue_block`,
  `issue_url`, the `Ledger` / `Run` / `Entry` objects. The conductor always
  reads the schema the checkout it is pointed at implements.
- **Stdlib only (plus PyYAML through the Cortex script), and Mind-free.** The
  renderer runs bare inside the Cortex's own `dashboard_refresh.yml`, which
  checks out no PyAutoMind — so `_cortex.py` imports neither `_sizing` nor
  `_intake` (both hard-fail without a Mind checkout).
- **No path is named in this code.** Science projects live outside the
  workspace; the one place carrying such a path is the Cortex's own
  `projects.yaml`, and every path the board prints is read from a row of it.
- **The assistant is a name, not a page.** `assistant` is a `projects.yaml`
  field rendered by name into the resume prompt; the conductor never resolves
  it on disk and never reads an assistant page.
- **It never infers from a result.** No results file, log or witness is read
  for a verdict. The only cluster output it shows is the project's own
  `jobs` verb, printed verbatim.

## The board

The page opens on the door: a counts table (`Running`, `Open`, `Projects` —
what `board/_board.py` reads for the Brain board's Cortex strip), the
**check-in chip** — the paste for the laptop's science chat — and the **last
check-in** stamp under it. Then **Summary**: one row per active project, four
narrow columns (`Project | Running | Open | Last update`) so it fits a phone.
Then **Projects**: a `### <key> — <summary>` card per project with a ledger —
active first in `projects.yaml` order, then planned/dormant, with the retired
ones folded into one `N retired` list at the end. Each card is a muted facts
line (status · partition · the issue or "no issue yet" · the ledger · local
path · RAL root), **Now** verbatim, **Runs** one line each (`ident — state —
partition — date — what`, clipped at 160 chars; "nothing on the cluster" when
empty), **Last 5** log entries (clipped at 240 chars) with a link to the full
log, and — for an active project — ONE 📋 chip, **resume `<key>`**: read the
ledger, then the project's own `ledger` file from its row, then the
assistant's `AGENTS.md` when the row names one; "tell me where I left off and
what I said I would do next; submit nothing and log nothing until I say."
Dormant rows with no ledger sit in one small `No ledger` table. No retire
chips anywhere — retiring is `scripts/cortex.py retire`, a typed verb.

**`checkin.yaml`** is the one-key file (`refreshed: <UTC ISO 8601>`) the
door writes before rendering. `census()` reads it into `c["checkin"]`;
missing means "never checked in", unparseable is a `problems` line. The
stamp means *last check-in*, never last render, and the HTML twin computes
its age on the **viewer's** clock and reddens it once stale.

`--check` compares the pages with the generation comment **and** the visible
`Last updated` banner stripped, so a re-render on a new date is not drift.

## The door (`checkin`)

The verb a human types. It composes what is already here and reasons nothing
of its own:

1. **Sync.** Every project with `status: active` in `projects.yaml`, plus any
   project whose ledger lists a run (a dormant project with a job still out
   there is still out there). Each is pulled with **its own**
   `<local_path>/<sync_cli> pull`, output **streamed**, not captured. A
   non-zero exit is recorded against that project and the sweep continues.
2. **Jobs.** Where the row has a `jobs` verb and the ledger lists runs, the
   project's own `<sync_cli> jobs` is run and its output printed **verbatim**
   — no parsing, no state flip. The human, or the agent in the session,
   records what it says with `cortex.py running | done`.
3. **Stamp + render.** `checkin.yaml`, then `dashboard.md` + `dashboard.html`.
4. **Push** (the rule below).
5. **Summarise, by project** — printed **last**, so a chat sees it above the
   fold: `key — summary`, what the pull did, the jobs output (or "no jobs
   verb"), Now, the runs, the last five entries, and a fenced block of the
   three `cortex.py` lines most likely typed next (`done`, `log --kind
   result|lesson`, `now`).

`--dry-run` (the default) prints the exact `cd <local_path> && <sync_cli>
pull` per project and reaches nothing at all. `--project KEY` narrows the
sweep; `--skip-pull` skips the pull and still asks `jobs`, stamps and renders.

### The push rule

`--push` is allowed only when **`gh auth status` succeeds** *and* **the Cortex
checkout is clean on `main`** — read *before* anything is written. That is the
whole cloud/laptop split, and it is also the default: a laptop pushes without
asking, a cloud session cannot and says so. The push cuts
`claude/checkin-<YYYY-MM-DD>` from a fresh `origin/main`, commits the changed
paths **explicitly**, pushes, and names `ledger_merge.yml` as what lands it.
`scripts/ledger_merge.py classify` is asked first and a code-classified diff is
refused before the branch is cut. Never `main`, never `--force`, and a
same-day re-check-in reuses its branch rather than resetting a pushed ref.

## What it never does

Submits a job · scores a result · writes a `result` or `lesson` the human did
not say · edits a ledger except through the Cortex script's own verbs ·
creates an issue · touches RAL except through the project's own CLI ·
consults an autonomy cap · arms a timer.

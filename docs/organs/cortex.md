# Cortex — PyAutoCortex

**What it owns:** the *science body map* (`projects.yaml` — each science
project's repo and remote, local path, RAL root, laptop mirror, sync CLI,
ledger and partition) and **one ledger per project** (`projects/<key>.md`) —
a history of how that project unfolds. The Cortex is the science mirror of the
Mind: the Mind holds prompts and PRs, the Cortex holds runs and the human's
notes on them. *The Mind decides what to build, the Brain routes the work and
executes nothing, the Cortex keeps track of what is true.*

**Repo:** [PyAutoLabs/PyAutoCortex](https://github.com/PyAutoLabs/PyAutoCortex)
· schema and grammars:
[REFERENCE.md](https://github.com/PyAutoLabs/PyAutoCortex/blob/main/REFERENCE.md)

## The defining function: keeping track

Science is not a queue of pre-registered questions that get done and retired.
The human does runs, looks at results, thinks, and decides where to go next.
So a ledger holds no state machine, no witness and no verdict — it holds
three things:

- **`## Now`** — two or three lines the human rewrites: what is running, what
  they meant to do next. The "pick up where I left off" line.
- **`## Runs`** — the jobs on the cluster right now, `open` or `running`. A
  finished run leaves the list and becomes a log entry.
- **`## Log`** — dated entries, newest first, of kind `run | result | lesson |
  note`. Nothing here is ever "done"; it only gets older. The board shows the
  last five.

The header is `# <key> — <summary>`, then `Project:` and `Issue:` (`Repo#N`,
an issue URL, or `none`). Every `status: active` row of `projects.yaml` has a
ledger; `scripts/cortex.py check` enforces the shape.

## Nothing is inferred from a result

A run's submission, start and end are **cluster facts**, recorded by
`scripts/cortex.py run | running | done`. A `result` or a `lesson` is **the
human's own words**, written on their ask with `cortex.py log`. An agent that
reads a results file tells the human what it sees; the human says what to
log. Neither the Cortex nor its conductor scores a run, drafts a verdict or
rules — the earlier task/ruling apparatus (states, witnesses, gates, rulings
of record, the review slot) is frozen under `archive/` and nothing writes
there.

## What it never does

- **It never dispatches.** No verb in the Cortex or in its conductor submits
  a job, cancels one, or touches RAL except through the project's own sync
  CLI. A submission happens only on the human's ask and is recorded at once
  with `cortex.py run`.
- **It never holds data.** The science project trees, their outputs, mirrors
  and checkpoints stay where they are; `projects.yaml` points at them. What
  is committed here is the ledger: Now, the run ids, the words.
- **It never runs under an autonomy level.** Every project runs from the
  laptop, and the review happens there, on evidence in the human's hands.
- **It never reads `sacct` as science.** The project's `jobs` output is
  printed verbatim at a check-in; what a finished run meant is the human's to
  say.

## Driving it

The Cortex *holds the ledgers*; it decides nothing. The Brain's **cortex
conductor** (`bin/pyauto-brain cortex`, `/cortex`) does the reasoning — the
same split as **Heart ↔ vitals** and **Gut ↔ hygiene**.

| Verb | What it does |
|------|--------------|
| `checkin [--dry-run \| --apply] [--push \| --no-push] [--project KEY] [--skip-pull]` | **The door.** Pull every active project through its own sync CLI (streamed; one project's failure does not stop the sweep), print each project's `jobs` output verbatim where its ledger lists runs, stamp `checkin.yaml`, re-render the board, push the ledger where the rule allows, and print a summary **by project** — Now, the runs, the last entries, the `cortex.py` lines likely typed next. `--dry-run` (the default) says what it would do and reaches nothing |
| `census [--json]` | What the Cortex is holding — per project: status, runs by state, log length, last update; the totals; the last check-in stamp |
| `dashboard --check` \| `--apply` | The generated board, `dashboard.md` + `dashboard.html`. `--check` exits **1** on drift — the contract the Cortex's `dashboard_refresh.yml` runs on. The two pages are generated: never hand-edit them |
| `issue [--project KEY] [--apply]` | The concise ledger block (Now, Runs, the last five) that sits at the top of each project's GitHub issue, between two markers; `--apply` writes it there through `gh` — never creates an issue |

**Checking in is one command.** `pyauto-brain cortex checkin --apply` pulls,
shows, renders and pushes on `claude/checkin-<date>` when `gh` is logged in
and the checkout is clean on `main`, then ends with the by-project summary the
human reads back — and then records what they say with `scripts/cortex.py`.

## The board

![The Cortex board](../_static/cortex_board.png)

Every project's ledger on one page — the check-in paste and the last-check-in
stamp, a one-row-per-project summary (running, open, last update), then a
card per project: its facts line, **Now** verbatim, the **runs** on the
cluster, the **last five** log entries, and one 📋 — *resume `<key>`* — that
reads the ledger and the project's own notes back and asks where you left
off. Retired projects fold into one line each; dormant rows with no ledger sit
in a small table. Published at <https://pyautolabs.github.io/PyAutoCortex/>.
It hands out the check-in and the resume; what a run meant is never on the
page.

## For an adopter

Like Mind, Memory and Gut, the Cortex is an **instance organ** — inherently
yours. You do not fork this repo's contents; you create your own Cortex with
the same shape — a body map of your projects and one ledger per project — and
keep your own history in it.

The birth of this organ is tracked in the
[cortex-birth epic ledger](https://github.com/PyAutoLabs/PyAutoMind/blob/main/complete/archive/epics/cortex_birth_epic.md).

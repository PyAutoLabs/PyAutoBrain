# /cortex — check in on the science (via the Brain Cortex Agent)

**This is the check-in.** You have runs on a cluster; this door finds out where
they got to — in **two verbs, split by the machine they need**:

- `pull` asks the cluster, through each project's *own* sync CLI, and shows
  that CLI's `jobs` output verbatim. It runs **on the laptop only**: every
  science root is a `local_path` out of `projects.yaml`, and it exists on one
  machine. Asked anywhere else it says so, once, and stops.
- `checkin` stamps, re-renders the board, pushes the ledger when it is allowed
  to, and hands you each project's ledger back — **Now**, the runs, the last
  entries — with the `cortex.py` lines you are most likely to type next. It
  reaches no cluster, so it works **anywhere**: web, mobile, laptop.

It records cluster facts and your words. It never decides what a result meant.

Development work is the Mind's and goes through `/intake` and `/start_dev`;
this door is for what the organism is *finding out*, not what it is building.
Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

The Cortex is one ledger per project, `PyAutoCortex/projects/<key>.md`:
`## Now` (2–3 lines the human rewrites), `## Runs` (on the cluster now,
`open | running`), `## Log` (dated, newest first, `run | result | lesson |
note`). Every write to one is a verb of `PyAutoCortex/scripts/cortex.py`.

## Do

### 1. On the laptop, pull first

```bash
bin/pyauto-brain cortex pull --dry-run   # names every pull; reaches nothing
bin/pyauto-brain cortex pull             # pull, then jobs verbatim
bin/pyauto-brain cortex pull --project subhalo_validation
```

Each project's own `<sync_cli> pull`, streamed as it comes (a pull takes
minutes; do not wrap it in anything that buffers), then — where the row has a
`jobs` verb and the ledger lists runs — its `<sync_cli> jobs`, printed
**verbatim**. Nothing is parsed, no state flips, nothing is written. A pull
that exits non-zero is recorded against *that* project, the sweep carries on,
and the verb exits 1.

**Not on the laptop?** `pull` exits **2** and names each missing root: *"this
is not the laptop — run `checkin` here and `pull` on the laptop."* That is the
expected answer on web and mobile, not a failure to work around. Go to step 2;
the runs you read back are the ledger's word, and say so.

### 2. Check in — on any surface

```bash
bin/pyauto-brain cortex checkin --dry-run          # what it would write
bin/pyauto-brain cortex checkin --apply            # push per the rule below
bin/pyauto-brain cortex checkin --apply --no-push  # never push
bin/pyauto-brain cortex checkin --apply --project subhalo_validation
```

It runs, in order:

1. **Render** — the refresh stamp into `checkin.yaml` (the board's "Last
   check-in", red on the Pages twin once stale), then `dashboard.md` +
   `dashboard.html`.
2. **Push** — see the rule below.
3. **Summarise by project** — printed last, so it is what the chat sees.

It shells out to no sync CLI. `--skip-pull` is accepted and ignored with a
notice, so an old paste still runs.

### 3. Read the summary back, project by project

The last block of the output is the deliverable: one section per project —
`key — summary`, then **Now**, the **runs** and the **last entries** as the
ledger holds them. Read it to the human as *where each project is*, in that
shape: what they said they were doing, what the ledger says is on the cluster,
what they last wrote down. If you could not pull, say that the runs are the
ledger's word and the cluster was not asked. Then stop and let them talk.

### 4. Record what the human says

Every ledger write is a `cortex.py` verb, run in the PyAutoCortex checkout:

```bash
python3 scripts/cortex.py run <key> <jobid> "<what it is>" [--partition P]   # a submission
python3 scripts/cortex.py running <key> <jobid>                              # the cluster says it started
python3 scripts/cortex.py done <key> <jobid> [--failed] [--wall H:MM]        # the cluster says it ended
python3 scripts/cortex.py log <key> "<their words>" --kind result|lesson|note
python3 scripts/cortex.py now <key> "<where they are, what comes next>"
```

- `running` and `done` are **cluster facts**: the agent may run them straight
  from the `jobs` output `pull` printed, and say it did.
- A `result` or a `lesson` is written **only in the human's words, when they
  say it**. If you read a results file, tell the human what you see; they say
  what to log. Never paraphrase a result into the ledger unasked.
- `now` is the human's "pick up where I left off" line. Rewrite it when they
  tell you where they are, in their words.
- After a ledger changes, `bin/pyauto-brain cortex dashboard --apply` (or the
  next check-in) re-renders the board; `bin/pyauto-brain cortex issue --apply`
  refreshes the block at the top of the project's issue.

### 5. Resume a project

The board carries one 📋 per active project — **resume `<key>`**. Its paste:
read `PyAutoCortex/projects/<key>.md` (Now, Runs, Log), then the project's own
`ledger` file from its `projects.yaml` row, then — when the row names an
`assistant:` — that assistant's `AGENTS.md`; then tell the human where they
left off and what they said they would do next. **Submit nothing and log
nothing until they say.** Work on the project itself is delegated the way
[`../WORKFLOW.md`](../WORKFLOW.md) "Cortex project work" says; the resume is
the entry protocol, not the work.

## The push rule

`--push` is allowed when **the Cortex checkout is clean on `main` with a
resolvable `origin`**, and it is the default. It asks git only — no `gh`, on
any surface: the probe that used to open this rule refused every session that
reaches GitHub another way (the map is
[`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md)), which left the ledger to the
merge bot. The push itself is the gate; if it fails, the summary says exactly
how and the commit is still on the branch.

When it pushes it cuts `claude/checkin-<YYYY-MM-DD>` from a fresh
`origin/main`, commits the changed paths **explicitly**, and pushes. If
`scripts/ledger_merge.py classify` calls the diff *code*, it stops before the
branch is cut and says why. `ledger_merge.yml` merges a ledger-only
`claude/**` push into `main` and deletes the branch — there is no PR to open
and nothing for the human to merge. **Never `main` directly, never `--force`.**

## The rules that do not bend

- **Never submit unless asked.** The check-in door never submits. When the
  human asks for a run in the session, the agent submits it with the
  project's own sync CLI (its `submit` / `push-submit` verb) and records the
  job id at once with `cortex.py run <key> <jobid> "<what>"`.
- **Never write a result or lesson the human did not say.** The conductor
  scores nothing, rules nothing, drafts no verdict. A `result` or `lesson`
  entry is the human's words, verbatim, on their ask.
- **Never edit a ledger by hand.** Every write is a `cortex.py` verb; the
  script refuses an edit that would not read back.
- **Only the project's own CLI reaches a cluster.** `pull` adds no SSH of its
  own, `checkin` reaches no cluster at all, and either `--dry-run` reaches
  nothing.
- **The door runs once and ends.** No timer, no subscription, no cron, no
  loop — you check in, you report, you stop.
- **The door names the assistant, never reads it.** No assistant page is
  loaded in the Cortex chat; the assistant is the resume's entry protocol.
- **Retiring ends a project, it does not erase one.** `cortex.py retire`
  changes a `projects.yaml` row's `status:` and `note:` and logs it; the row
  and the ledger stay. It refuses while the ledger still lists a run.

## Appendix — the verbs it composes

`checkin` is a composition; each part is still runnable on its own, and
`--cortex <dir>` (a flag of the *subcommand*) points any of them at another
checkout.

| Verb | Answers |
|------|---------|
| `pull [--project KEY] [--dry-run]` | What does the cluster say? Each project's own pull, then its `jobs` output verbatim. The laptop only. Exit **1** = a pull failed · **2** = no project's `local_path` is on this machine |
| `checkin [--dry-run\|--apply] [--push\|--no-push] [--project KEY]` | Where is my science? Stamp, render, push, read each ledger back. Any surface. Exit **1** = the tree does not check |
| `census [--json]` | What is the Cortex holding? Per project: status, runs by state, log length, last update; the totals; the last check-in stamp |
| `dashboard --check` | Are the committed pages current? Exit **1** = stale (the refresh workflow's contract) |
| `dashboard --apply` | Regenerate `dashboard.md` + `dashboard.html` — never hand-edit those two |
| `issue [--project KEY] [--apply]` | The ledger block at the top of each project's issue (Now, Runs, the last five). `--apply` writes it there through `gh`; never creates an issue; exit **1** without `gh` |
| `retire <project> --why "…"` (`scripts/cortex.py`) | Is this project over? Flips the row to `status: retired`, stamps the note, logs it. Exit **1** = an unknown key, an already-retired row, or a run still listed |

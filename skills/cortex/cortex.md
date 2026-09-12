# /cortex — check in on the science (via the Brain Cortex Agent)

**This is the check-in.** You have runs on a cluster; this door finds out where
they got to. It pulls every active project through that project's *own* sync
CLI, shows that CLI's `jobs` output verbatim, re-renders the board, pushes the
ledger when it is allowed to, and hands you each project's ledger back — **Now**,
the runs on the cluster, the last entries — with the `cortex.py` lines you are
most likely to type next. It records cluster facts and your words. It never
decides what a result meant.

Development work is the Mind's and goes through `/intake` and `/start_dev`;
this door is for what the organism is *finding out*, not what it is building.
Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

The Cortex is one ledger per project, `PyAutoCortex/projects/<key>.md`:
`## Now` (2–3 lines the human rewrites), `## Runs` (on the cluster now,
`open | running`), `## Log` (dated, newest first, `run | result | lesson |
note`). Every write to one is a verb of `PyAutoCortex/scripts/cortex.py`.

## Do

### 1. Look before you pull

```bash
bin/pyauto-brain cortex checkin --dry-run
```

Prints every project it would sweep and the exact `cd <local_path> &&
<sync_cli> pull` it would run for each (and the `jobs` line where the ledger
lists runs). It reaches no cluster and writes nothing. Read it to the human —
especially if a project they expect is missing (it is missing because its
`projects.yaml` row is not `status: active` and its ledger lists no run).

### 2. Check in

```bash
bin/pyauto-brain cortex checkin --apply            # push per the rule below
bin/pyauto-brain cortex checkin --apply --no-push  # never push
bin/pyauto-brain cortex checkin --apply --project subhalo_validation
bin/pyauto-brain cortex checkin --apply --skip-pull   # no pull; jobs, stamp, render
```

It runs, in order:

1. **Sync** — each project's own `<sync_cli> pull`, output streamed as it
   comes (a pull takes minutes; do not wrap this in anything that buffers).
   A pull that exits non-zero is recorded against *that* project and the sweep
   carries on.
2. **Jobs** — where the row has a `jobs` verb and the ledger lists runs, the
   project's own `<sync_cli> jobs`, printed **verbatim**. Nothing is parsed
   and no state flips.
3. **Render** — the refresh stamp into `checkin.yaml` (the board's "Last
   check-in", red on the Pages twin once stale), then `dashboard.md` +
   `dashboard.html`.
4. **Push** — see the rule below.
5. **Summarise by project** — printed last, so it is what the chat sees.

### 3. Read the summary back, project by project

The last block of the output is the deliverable: one section per project —
`key — summary`, what its pull did, the jobs output, then **Now**, the
**runs** and the **last entries** as the ledger holds them. Read it to the
human as *where each project is*, in that shape: what they said they were
doing, what is on the cluster, what they last wrote down. Then stop and let
them talk.

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
  from the `jobs` output the check-in printed, and say it did.
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

`--push` is allowed only when **`gh auth status` succeeds** *and* **the Cortex
checkout is clean on `main`**. That `gh` call is a *probe*, not a GitHub
operation — a session without `gh` (a remote one, which reaches GitHub through
the `mcp__github__*` tools instead; the map is
[`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md)) simply gets `--no-push` and is
told so. Do not install `gh` to change that answer: the push wants a laptop
with a clean checkout, and a remote session has neither.

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
- **Only the project's own CLI reaches a cluster.** The door adds no SSH of
  its own, and `--dry-run` reaches nothing at all.
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
| `checkin [--dry-run\|--apply] [--push\|--no-push] [--project KEY] [--skip-pull]` | Where is my science? The whole sequence above. Exit **1** = a pull failed or the tree does not check |
| `census [--json]` | What is the Cortex holding? Per project: status, runs by state, log length, last update; the totals; the last check-in stamp |
| `dashboard --check` | Are the committed pages current? Exit **1** = stale (the refresh workflow's contract) |
| `dashboard --apply` | Regenerate `dashboard.md` + `dashboard.html` — never hand-edit those two |
| `issue [--project KEY] [--apply]` | The ledger block at the top of each project's issue (Now, Runs, the last five). `--apply` writes it there through `gh`; never creates an issue; exit **1** without `gh` |
| `retire <project> --why "…"` (`scripts/cortex.py`) | Is this project over? Flips the row to `status: retired`, stamps the note, logs it. Exit **1** = an unknown key, an already-retired row, or a run still listed |

# /cortex — check in on the science (via the Brain Cortex Agent)

**This is the check-in.** You have runs on a cluster; this door finds out where
they got to. It pulls every active project through that project's *own* sync
CLI, scores every live phase against the witness it pre-registered, moves what
came back to `awaiting-ruling`, re-renders the board, pushes the ledger when it
is allowed to, and hands you a summary **by project** with the prompt you would
paste to carry each one forward.

Development work is the Mind's and goes through `/intake` and `/start_dev`;
this door is for what the organism is *finding out*, not what it is building.
Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

### 1. Look before you pull

```bash
bin/pyauto-brain cortex checkin --dry-run
```

Prints every project it would sweep, the exact `cd <local_path> && <sync_cli>
pull` it would run for each, the pull root each manifest would land in, and
every `submitted | running` phase it would score. It reaches no cluster and
writes nothing. Read it to the human — especially if a project they expect is
missing (it is missing because its `projects.yaml` row is not `status: active`
and it owns no live phase).

### 2. Check in

```bash
bin/pyauto-brain cortex checkin --apply            # push per the rule below
bin/pyauto-brain cortex checkin --apply --no-push  # never push
bin/pyauto-brain cortex checkin --apply --project subhalo_validation
bin/pyauto-brain cortex checkin --apply --skip-pull   # re-score, offline
```

It runs, in order:

1. **Sync** — each project's own `<sync_cli> pull`, output streamed as it
   comes (a pull takes minutes; do not wrap this in anything that buffers).
   A pull that exits non-zero is recorded against *that* project and the sweep
   carries on. After a good pull it writes `<pull root>/.cortex/pull.json`,
   merging with whatever the project's CLI already wrote there.
2. **Score** — every `submitted | running` phase, six legs each, against the
   phase's own pre-registered witness.
3. **Move** — `running → pulled → awaiting-ruling`, rehearsed on a throwaway
   copy first and refused outright if `cortex.py check` would not pass after.
4. **Render** — `dashboard.md` + `dashboard.html`.
5. **Push** — see the rule below.
6. **Summarise by project** — printed last, so it is what the chat sees.

### 3. Read the summary back, project by project

The last block of the output is the deliverable: one section per project — its
`local_path` / `mirror` / RAL root, what its pull did, its phase counts, and
then every phase a human could act on today, each with the health verdict and
a fenced, copy-ready prompt. Read it to the human as *state of each project*,
then offer the prompts:

- **awaiting a ruling** → the review prompt (read the witness, score it, draft
  the ruling for approval, then `cortex.py rule`).
- **still out there** → the project's own `jobs` line.
- **ready** → the launch lines (the phase, the `submit`, the `move … submitted
  --run <jobid>`).
- **gated** → the refs to open.

Never decide a ruling, never submit a job, never edit a phase file by hand:
every phase edit is `python3 scripts/cortex.py move`, every verdict is
`python3 scripts/cortex.py rule`, both in the PyAutoCortex checkout, and the
ruling body is the human's words verbatim.

## The push rule

`--push` is allowed only when **`gh auth status` succeeds** *and* **the Cortex
checkout is clean on `main`**. That `gh` call is a *probe*, not a GitHub
operation — a session without `gh` (a remote one, which reaches GitHub through
the `mcp__github__*` tools instead; the map is
[`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md)) simply gets `--no-push` and is
told so. Do not install `gh` to change that answer: the push wants a laptop
with a clean checkout, and a remote session has neither. That is the whole cloud/laptop split: on a
laptop it is the default and needs no asking; in a cloud session there is no
logged-in `gh`, so the default is `--no-push` and the check-in says so.

When it pushes it cuts `claude/checkin-<YYYY-MM-DD>` from a fresh
`origin/main`, commits the changed paths **explicitly**, and pushes. If
`scripts/ledger_merge.py classify` calls the diff *code*, it stops before the
branch is cut and says why. `ledger_merge.yml` merges a ledger-only
`claude/**` push into `main` and deletes the branch — there is no PR to open
and nothing for the human to merge. **Never `main` directly, never `--force`.**

## The rules that do not bend

- **The conductor never submits.** The human runs the project's own sync CLI
  and records the job id with `cortex.py move <phase> submitted --run <jobid>`.
- **A verdict recorded only outside the Cortex does not exist.** A decision
  reached in chat is not a ruling until `cortex.py rule` has written it.
- **A phase is a question with a pre-registered witness.** If `Witness:` is
  empty the phase cannot be submitted — write the witness first.
- **The only thing that reaches a cluster is the project's own CLI.** The door
  adds no SSH of its own, and `--dry-run` reaches nothing at all.
- **UNOBSERVABLE is not FAIL.** Some legs are not visible on the laptop (the
  checkpoint is never pulled; one project writes no version stamp), so those
  phases come back **SUSPECT** — read them, do not treat them as broken runs.
  The checkpoint leg becomes scorable where `.cortex/pull.json` carries a
  `checkpoints` table (keyed by run directory) or a `runs` table (by job id).
- **The door runs once and ends.** No timer, no subscription, no cron, no
  loop — you check in, you report, you stop.
- **`rulings/` is append-only.** Never edit or delete one.

## Appendix — the verbs it composes

`checkin` is a composition; each part is still runnable on its own, and
`--cortex <dir>` (a flag of the *subcommand*) points any of them at another
checkout.

| Verb | Answers |
|------|---------|
| `checkin [--dry-run\|--apply] [--push\|--no-push] [--project KEY] [--skip-pull] [--refreshed ISO]` | Where is my science? The whole sequence above. Exit **1** = a pull failed or the tree needs a look |
| `census [--json]` | What is the Cortex holding? Phase counts by state, rulings, projects, epics |
| `dashboard --check` | Are the committed pages current? Exit **1** = stale (the refresh workflow's contract) |
| `dashboard --apply` | Regenerate `dashboard.md` + `dashboard.html` — never hand-edit those two |
| `gates` | What is each gated phase waiting on? Read-only and offline; a human types `move <phase> ready` |
| `collect [--phase REL] [--pull] [--refreshed ISO] [--apply] [--out F]` | The scorer `checkin` composes: one block per phase — six legs each `PASS`/`FAIL`/`UNOBSERVABLE`, the readout, a **blank** ruling line. Exit **1** = a phase the human must look at |

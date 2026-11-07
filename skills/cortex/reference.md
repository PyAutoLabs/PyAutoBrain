# /cortex — reference

Moved word for word from [`cortex.md`](cortex.md) to keep the skill's mandatory
load under its 200-line budget. Read a section when the step that needs it is
reached.

## Start a new project (step 6)

A new Science project is born in two halves, in this order:

1. **Scaffold** — through the domain assistant the project will work with
   (`autolens_assistant` or `autofit_assistant`): run its
   `skills/start-new-project.md` (Create phase) with the target folder
   `<Science root>/<active|development>/<key>/` (`development/` for a project
   whose purpose is developing or validating the software). Take data from the
   Science tree: copy a sample from `dataset/<sample>/`, or run a standard lens
   from `simulators/<type>/<lens>.py --dataset-path dataset` inside the new
   folder. The assistant owns the scaffold — never hand-copy an older project.
2. **Register** — `pyauto-brain cortex birth <key> --category <active|development>
   --assistant <name> --summary "<one line>"`. The dry run prints the row it
   derived from the folder (remote, `ral_root` in the same category, the
   `hpc/sync` verbs, the ledger file); show it to the human, then `--apply`:
   it cuts `claude/birth-<key>`, writes the row and ledger through
   `scripts/cortex.py birth`, and pushes when the Cortex's classifier calls it
   a birth (which lands by itself). It creates no GitHub remote and reaches no
   cluster — it prints those lines for the human.

`pyauto-brain cortex drift` should then be clean for the new project.

## The push rule: what a push does

When it pushes it cuts `claude/checkin-<YYYY-MM-DD>` from a fresh
`origin/main`, commits the changed paths **explicitly**, and pushes. If
`scripts/ledger_merge.py classify` calls the diff *code*, it stops before the
branch is cut and says why. `ledger_merge.yml` merges a ledger-only
`claude/**` push into `main` and deletes the branch — there is no PR to open
and nothing for the human to merge. **Never `main` directly, never `--force`.**

## Appendix — the verbs it composes

`checkin` is a composition; each part is still runnable on its own, and
`--cortex <dir>` (a flag of the *subcommand*) points any of them at another
checkout.

| Verb | Answers |
|------|---------|
| `pull [--project KEY] [--dry-run]` | What does the cluster say? Each project's own pull, then its `jobs` output verbatim — or, for a campaign project, its `status` output and a dry-run `sync-runs` of the digest. The laptop only. Exit **1** = a pull failed · **2** = no project's `local_path` is on this machine |
| `checkin [--dry-run\|--apply] [--push\|--no-push] [--project KEY]` | Where is my science? Stamp, render, push, read each ledger back. Any surface. Exit **1** = the tree does not check |
| `census [--json]` | What is the Cortex holding? Per project: status, runs by state, log length, last update; the totals; the last check-in stamp |
| `dashboard --check` | Are the committed pages current? Exit **1** = stale (the refresh workflow's contract) |
| `dashboard --apply` | Regenerate `dashboard.md` + `dashboard.html` — never hand-edit those two |
| `issue [--project KEY] [--apply]` | The ledger block at the top of each project's issue (Now, Runs, the last five). `--apply` writes it there through `gh`; never creates an issue; exit **1** without `gh` |
| `drift [--science-root PATH] [--json]` | Does the register match the laptop Science tree? Errors: unregistered `active/`/`development/` folders, vanished rows, category vs status. Reads, never writes; exit **1** on an error |
| `birth <key> --category C --assistant A --summary S [--apply] [--no-push]` | Register a scaffolded project: its row and ledger on `claude/birth-<key>`, written by `cortex.py birth`. Dry run by default; exit **2** = refused (no folder, key or path taken, no sync verbs) |
| `retire <project> --why "…"` (`scripts/cortex.py`) | Is this project over? Flips the row to `status: retired`, stamps the note, logs it. Exit **1** = an unknown key, an already-retired row, or a run still listed |

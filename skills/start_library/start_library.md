# Start Library: Set Up Library Development

Set up the development environment for **library source-code** work (PyAutoConf,
PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens). Assumes `/start_dev` already
registered the task in `PyAutoMind/active.md`.

Workflow entry point — the worktree/branch setup is the dev workflow's own
**feature-dev** git mechanics (not Build, which is release-only) and the task
state is **Mind**. Read [`../WORKFLOW.md`](../WORKFLOW.md) for the organ boundary,
the worktree helpers, the execution-environment model, and the registry paths.

## Steps

### 1. Conflict guard

```bash
source admin_jammy/software/worktree.sh
worktree_check_conflict <task-name> <repo1> [repo2 ...]
```

A conflict only fires when another `active.md` entry already claims one of the
target repos via its `worktree:` field (tasks on different repos run in
parallel). On non-zero exit, **block** and show the holding task, its worktree
and branch; the only options are finish that task first, or abort. If the repo
appears under the **same** task (resuming), proceed.

### 2. Read the active issue (Mind)

Read `PyAutoMind/active.md` for the issue URL. If not there, check
`planned.md` — the task may have been queued on a conflict; re-run the conflict
guard against its `affected-repos`, and if now clear, move the entry into
`active.md` (`status: library-dev`) and proceed. If found nowhere, tell the user
to run `/start_dev` first. Fetch the plan:

```bash
gh issue view <number> --repo <owner/repo> --json body,title --jq '.body'
```

### 3. Parse the plan

Extract the **Affected Repositories**, **Suggested branch**, **Implementation
Steps**, and **Key Files**. If the issue has no detailed plan (filed by hand),
read the description and formulate one by exploring the code. Confirm the repos
are libraries (WORKFLOW.md mapping); if workspace repos appear, note that
library work ships first (`/ship_library`), workspace follows.

### 4. Create the task worktree (feature-dev mechanics, local-dev)

```bash
source admin_jammy/software/worktree.sh
worktree_create <task-name> <repo1> [repo2 ...]
```

The helper creates `~/Code/PyAutoLabs-wt/<task-name>/`, runs
`git worktree add -b feature/<task-name>` (from `origin/main`) for each listed
repo, symlinks every other PyAutoLabs entry back to the canonical checkout, and
writes `activate.sh` with the per-task `PYTHONPATH` / `NUMBA_CACHE_DIR` /
`MPLCONFIGDIR`. If the branch already exists (resuming), it is checked out
instead. Print prominently:

```
Before running Python, pytest, or smoke tests in this session, run:
  source ~/Code/PyAutoLabs-wt/<task-name>/activate.sh
```

**Other execution environments** (web-github / ci-only — see WORKFLOW.md): there
is no local worktree. Operate on the clones present in the working directory,
`git checkout -b feature/<task-name>`, and export `PYTHONPATH` (the library
repos), `NUMBA_CACHE_DIR=/tmp/numba_cache`, `MPLCONFIGDIR=/tmp/matplotlib`
manually. Register the repos in `active.md` without a `worktree:` field.

### 5. Register repos in active.md (Mind) + push

Update the task entry to record the worktree path and claimed repos:

```markdown
## <task-name>
- issue: <issue-url>
- session: claude --resume <session-id>
- status: library-dev
- worktree: ~/Code/PyAutoLabs-wt/<task-name>
- repos:
  - PyAutoFit: feature/<task-name>
  - PyAutoArray: feature/<task-name>
```

The `worktree:` field is what `worktree_check_conflict` reads to detect
collisions from other sessions. Then:

```bash
source PyAutoMind/scripts/prompt_sync.sh
prompt_sync_push "prompt: register <task-name> library repos in active.md"
```

### 6. Explore key files + present "ready to develop"

Read the key files and their callers/tests (blast radius across repos), then
show: the issue + title, the worktree root, the activation reminder, each repo's
branch, the key files to edit **inside the worktree** (not the main checkout),
test directories, and the implementation steps. End with: "When done, run
`/ship_library` to test, commit, and create PRs."

## Notes

- If `active.md` has multiple issues, ask which one to work on.
- If a repo is already on the correct feature branch, skip creation and note it.
- If a repo has uncommitted changes, warn before switching branches.

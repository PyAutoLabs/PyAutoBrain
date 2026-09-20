# Start Library: Set Up Library Development

Set up the development environment for **library source-code** work (PyAutoNerves,
PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens). Assumes `/start_dev` already
registered the task in `PyAutoMind/active.md`.

Workflow entry point — the worktree/branch setup is the dev workflow's own
**feature-dev** git mechanics (not Build, which is release-only) and the task
state is **Mind**. Read [`../WORKFLOW.md`](../WORKFLOW.md) for the organ boundary,
the worktree helpers, the execution-environment model, and the registry paths.

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Steps

### 1. Conflict guard

```bash
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
worktree_check_conflict <task-name> <repo1> [repo2 ...]
```

A conflict fires when another `active.md` entry claims one of the target repos
in its `repos:` block (tasks on different repos run in parallel). On a
worktree-capable surface the helper performs this check. On a
GitHub-control-only surface, read current `active.md` through GitHub and apply
the same rule; fail closed if it cannot be read. On conflict, **block** and show
the holding task plus any recorded worktree/branch. Same task = resuming.

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
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
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

**Other capability surfaces** (see WORKFLOW.md):

- **clone + shell, no task worktree:** operate on the provided clone, create or
  resume `feature/<task-name>`, export the documented cache/PYTHONPATH values,
  and register no fake `worktree:`.
- **GitHub-control-only, no clone:** create or resume
  `feature/<task-name>` through the GitHub branch operation from current
  `main`, then edit/commit files through repository-write operations. Register
  `session:`, `location: github-api-only (no local clone or task worktree)`
  and each `repos:` branch claim; omit `worktree:`. This surface may
  implement repository changes but cannot claim local imports/tests.
- **no repository-write capability:** stop before branch creation and use the
  bounded execution handoff. Do not fall back to an OpenAI API call.

### 5. Register repos in active.md (Mind) + push

Update the task entry to record the real execution location and claimed repos.
The local form is:

```markdown
## <task-name>
- issue: <issue-url>
- session: <actual harness; known session ID or URL, otherwise unavailable>
- status: library-dev
- worktree: ~/Code/PyAutoLabs-wt/<task-name>
- repos:
  - PyAutoFit: feature/<task-name>
  - PyAutoArray: feature/<task-name>
```

The `  - <repo>` bullets under `repos:` are the claim — they are what
`worktree_check_conflict` (or its GitHub-only equivalent) compares to detect
collisions from other sessions. `worktree:` is location metadata only and is
omitted when no worktree exists. Both
`  - <repo>: <branch>` and `  - <repo> (<branch>)` parse; the branch is
informational and may be omitted. Then:

```bash
source "${PYAUTO_MIND:-$(test -d organs/PyAutoMind && echo organs/PyAutoMind || echo PyAutoMind)}/scripts/prompt_sync.sh"
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

Resume metadata must describe the active harness. Record `codex resume <id>` or
`claude --resume <id>` only when that harness and its real session ID are known;
otherwise retain the known harness and mark the ID unavailable. Preserve earlier
session records verbatim when resuming work from another harness.

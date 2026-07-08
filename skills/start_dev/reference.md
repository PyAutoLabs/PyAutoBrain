# start_dev — reference detail

Long-form templates and procedures factored out of `start_dev.md` to keep the
primary skill concise. The body skill is authoritative for the flow; this file
holds the verbatim formats it points at.

## Issue body

The issue body is assembled and created by the Mind primitive `/create_issue`
(see `PyAutoMind/skills/create_issue/SKILL.md` → "Assemble + create the issue").
start_dev does **not** call `gh issue create` itself — it supplies the content
and delegates the write.

When delegating, pass these in the plan content so create_issue includes them in
the collapsible detailed block (they are start_dev-specific extras on top of
create_issue's base template):

- **Work Classification** — `Library / Workspace / Both`
- **Worktree root** — `~/Code/PyAutoLabs-wt/<name>/` (created later by `/start_library`)

## Registry entries

### active.md (no conflict — task can start)

```markdown
## <task-name>
- issue: <issue-url>
- session: claude --resume <session-id>
- status: <library-dev | workspace-dev>
- worktree: ~/Code/PyAutoLabs-wt/<task-name>
- repos:
```

`status` follows the classification: library work or both → `library-dev`;
workspace work → `workspace-dev`. The `worktree:` directory does not exist yet
(`/start_library` creates it); `repos:` starts empty and is filled when branches
are created.

### planned.md (conflict — task is queued)

```markdown
## <task-name>
- issue: <issue-url>
- planned: <YYYY-MM-DD>
- classification: <library | workspace | both>
- suggested-branch: feature/<name>
- blocked-by: <conflicting-task-name> (using <repo>)
- affected-repos:
  - <repo1>
  - <repo2>
```

A "conflict" means another `active.md` entry already claims one of the target
repos via its `worktree:` field. Tasks editing different repos run in parallel;
two tasks wanting the same repo must serialise. After a blocking task ships,
`/health status` shows the queued task as ready, then `/start_library` or
`/start_workspace` begins it.

Legacy check: if a target repo's **main checkout** is on a feature branch not
referenced by any `worktree:` claim, warn (unregistered prior-session work) —
ask whether to proceed; don't treat it as an automatic conflict.

## z_features audit (tracker mode)

`z_features/<epic>.md` files are umbrella trackers for multi-task epics; their
sub-prompts are issued individually. In audit-only mode, **do not create an
issue** — instead:

1. **Parse** the tracker for sub-prompt references (markdown links → path in
   parens; bare `<work-type>/<target>/<name>.md` or pre-migration
   `<target>/<name>.md` paths). Dedupe, resolve `../` relative to the tracker,
   skip self-references inside `z_features/`.
2. **Status each sub-prompt:**
   - exists at `PyAutoMind/<path>` → **not yet issued**;
   - exists at `PyAutoMind/issued/<basename>` → **issued**; derive task-name
     candidates from the filename stem (`_`→`-`) and from `## <task-name>`
     headings, grep `PyAutoMind/complete.md` for `^## <candidate>$` → match =
     **shipped** (record heading + PR URL); no match = **in flight**;
   - neither → **unknown** (link rot — warn).
3. **Report** a table (Sub-prompt | Status | Notes) + summary line
   `N shipped / M in flight / K not yet issued / U unknown`.
4. **Decide:**
   - Any non-shipped entries → stop, list outstanding work, do not move the
     tracker, do not push.
   - All shipped → verify PyAutoMind is on `main` and clean, show the archive
     commands, get explicit confirmation, then:
     ```bash
     mkdir -p PyAutoMind/z_features/complete
     mv PyAutoMind/z_features/<filename> PyAutoMind/z_features/complete/<filename>
     source PyAutoMind/scripts/prompt_sync.sh
     prompt_sync_push "prompt: archive completed z_features tracker — <stem>"
     ```
   Print a one-line "archived" confirmation and stop.

## Branch survey (the former /plan_branches)

Run after the plan is approved (start_dev step 4): survey every repository the plan will touch, report branch state, and propose a single working branch name for the task.

A PyAutoBrain planning entry point — branch/worktree setup is the dev workflow's
own feature-dev git mechanics (not Build, which is release-only); task state is
PyAutoMind. Shared organ boundary and the execution-environment model are in
[`../WORKFLOW.md`](../WORKFLOW.md).

## Steps

1. **Identify affected repositories**

   Review the approved plan and list every repository that will be modified. Only include repos that the plan actually touches — do not list all repos from `settings.json` if they are not relevant.

2. **Report current branch state for each affected repo**

   For each affected repository, run:
   ```bash
   git -C <repo_path> branch --show-current
   git -C <repo_path> status --short
   ```

   Display a table like:

   ```
   Repository              | Current Branch | Dirty?
   ------------------------|----------------|-------
   ./PyAutoFit             | main           | clean
   ./PyAutoArray           | feature/xyz    | 2 modified
   ```

   If a repo is on a non-main/non-master branch or has uncommitted changes, flag it with a warning — this may indicate another task or agent is active there.

3. **Check for active Claude agents, recent branches, and worktree claims**

   Source the worktree helper and list anything already claimed by another task:

   ```bash
   source admin_jammy/software/worktree.sh
   worktree_list_claimed
   ```

   This prints one line per `(task, repo, branch, worktree_path)` quadruple currently registered in `active.md`. For each affected repo the new plan wants to touch, check whether a different task already claims it via a `worktree:` field. If so, flag it as a **hard conflict** — the new task cannot start until the other one ships.

   Then, for each affected repo, also run:
   ```bash
   git -C <repo_path> branch --sort=-committerdate | head -5
   ```

   Show the 5 most recent branches per repo so the user can spot ongoing work that pre-dates the worktree flow. A feature branch on the main checkout that is **not** referenced by any `worktree:` claim is unregistered work, not a conflict — surface it as a warning, not a block.

4. **Suggest a unified branch name**

   Propose a single branch name to be used across all affected repos. Use the format:
   ```
   feature/<short-description-of-plan>
   ```

   The name should be:
   - Descriptive of the task from the plan
   - Lowercase, kebab-case
   - Short (under 50 chars)

5. **Present summary for approval**

   Display the full summary:
   - List of affected repos
   - Current branch and dirty state for each
   - Recent branches for each
   - Any warnings about potential overlap
   - The suggested branch name

   Then ask the user:
   - "Does this branch name work, or would you like a different one?"
   - "Are any of the flagged repos a concern? Should we wait or coordinate?"

   **Do not proceed with any work until the user confirms the branch name and acknowledges any overlap warnings.**

6. **On resume: verify branches and worktree match the plan**

   When resuming work on an existing plan (e.g. a new conversation continuing previous work, or returning after a break), run this verification step **before making any edits**:

   a. Read the plan or `active.md` entry to find the agreed branch name, the worktree root path (`worktree:` field), and the list of affected repositories.

   b. **Verify the worktree root exists on disk:**
   ```bash
   test -d "$WT_ROOT" && echo "present" || echo "MISSING"
   test -f "$WT_ROOT/activate.sh" && echo "activate.sh ok" || echo "activate.sh MISSING"
   ```

   If the worktree root has been deleted but `active.md` still lists it, stop and ask the user whether to:
   - Re-create the worktree via `worktree_create <task-name> <repos...>` (resumes the task), or
   - Abandon the task and remove its entry from `active.md`.

   c. For each affected repo listed in the task, run `git -C "$WT_ROOT/<repo>" branch --show-current` and compare against the expected branch. Display the comparison table:

   ```
   Repository              | Expected Branch       | Actual Branch         | Status
   ------------------------|-----------------------|-----------------------|--------
   $WT_ROOT/PyAutoFit      | feature/my-task       | feature/my-task       | OK
   $WT_ROOT/PyAutoArray    | feature/my-task       | main                  | MISMATCH
   ```

   d. If **all repos match**: confirm and continue work. Remind the user to `source "$WT_ROOT/activate.sh"` if they're in a fresh shell.

   e. If **any repo is on an unexpected branch**:
      - Flag each mismatch with a warning
      - Ask the user whether to:
        - Switch the mismatched worktree to the expected branch (`git -C "$WT_ROOT/<repo>" checkout <expected>`)
        - Continue on the current branch (with acknowledgement)
        - Abort and investigate
      - **Do not proceed with any edits until the user responds.**

## Execution environments

The steps above assume a local-dev checkout with task worktrees. In other
execution environments (see [`../WORKFLOW.md`](../WORKFLOW.md)):

- **web-github / analysis-only** (no local tree): skip the worktree checks
  (`worktree_list_claimed`, `worktree_check_conflict`) and read branch state via
  the GitHub API instead of local `git -C`:
  ```bash
  gh api repos/<owner>/<repo>/branches --jq '.[].name' | head -10
  gh api repos/<owner>/<repo>/branches/<branch> --jq '.name' 2>/dev/null
  ```
  Use the repo → owner mapping in WORKFLOW.md. Suggest the branch name and present
  the summary as normal; on resume, verify branches via the API.

This is the same reasoning in every environment — only the source of branch state
differs (local git vs GitHub API). It is not a separate "mobile mode".

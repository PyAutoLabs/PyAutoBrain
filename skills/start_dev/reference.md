# start_dev — reference detail

Long-form templates and procedures factored out of `start_dev.md` to keep the
primary skill concise. The body skill is authoritative for the flow; this file
holds the verbatim formats it points at.

## Issue body template

```markdown
## Overview

<2-4 sentence summary of what this task is and why it matters>

## Plan

<High-level bullet-point plan — human readable, no code>

<details>
<summary>Detailed implementation plan</summary>

### Affected Repositories
- repo1 (primary)
- repo2

### Work Classification
<Library / Workspace / Both>

### Branch Survey

| Repository | Current Branch | Dirty? |
|-----------|---------------|--------|
| ./RepoName | main | clean |

**Suggested branch:** `feature/<name>`
**Worktree root:** `~/Code/PyAutoLabs-wt/<name>/` (created later by `/start_library`)

### Implementation Steps

1. Detailed step with file paths and specifics...
2. ...

### Key Files
- `path/to/file.py` — description of changes

</details>

## Original Prompt

<details>
<summary>Click to expand starting prompt</summary>

<original prompt content copied verbatim>

</details>
```

Pass via HEREDOC:

```bash
gh issue create --repo <owner/repo> --title "<title>" --body "$(cat <<'ISSUE_EOF'
<body content>
ISSUE_EOF
)"
```

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
`/pyauto-status` shows the queued task as ready, then `/start_library` or
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

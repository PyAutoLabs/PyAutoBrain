---
name: update-issue
description: Post a progress update to a GitHub issue from the current CLI session — commits, summary, and remaining work.
---

Post a progress summary from the current session to a GitHub issue.

A **PyAutoBrain dev-workflow** skill — communicating progress on a tracked issue
is part of the development cycle (the `start_*` → `ship_*` lifecycle;
`start_dev_for_user` calls it at milestones). It reads the PyAutoMind registry to
find the active issue. Organ boundary: [`../WORKFLOW.md`](../WORKFLOW.md).

## Usage

```
/update-issue <issue-url-or-number>
```

Examples:
- `/update-issue https://github.com/PyAutoLabs/PyAutoArray/issues/42`
- `/update-issue Jammy2211/PyAutoArray#42`
- `/update-issue` (auto-detect from current plan or branch)

## Steps

### 1. Identify the issue

Determine the target issue from (in order of priority):

1. **Explicit argument** — use the URL or `owner/repo#number` provided
2. **Current plan file** — if a plan file exists in the current session, look for an issue URL in it
3. **Branch name** — check if the current branch name matches a known issue pattern

If none of these work, ask the user for the issue URL.

### 2. Identify affected repositories

Read the issue body (via `gh issue view`) to find the list of affected repositories from the "Affected Repositories" section. If not found, use the repos that have changes on the current branch.

### 3. Gather progress across all affected repos

For each affected repository, collect:

```bash
# Commits on this branch since diverging from main
git -C <repo_path> log main..HEAD --oneline

# Uncommitted changes
git -C <repo_path> diff --stat

# Staged changes
git -C <repo_path> diff --cached --stat
```

### 4. Read the plan from the issue

Fetch the issue body via:

```bash
gh issue view <number> --repo <owner/repo> --json body -q '.body'
```

Extract the plan (both high-level and detailed) to compare against completed work.

### 5. Generate the progress summary

Produce a summary covering:

- **What was accomplished** — summarize from commit messages and diffs
- **What remains** — compare the plan steps against completed commits to identify remaining work
- **Any blockers or decisions** — note if you encountered anything that deviates from the plan

### 6. Post the progress comment

Post via `gh issue comment`:

```bash
gh issue comment <number> --repo <owner/repo> --body "$(cat <<'UPDATE_EOF'
## Progress Update — <YYYY-MM-DD>

### Summary
<2-4 sentences describing what was accomplished this session>

### Commits
- `abc1234` — Description of change
- `def5678` — Description of change

<details>
<summary>Detailed changes</summary>

<diff stats per repo, file-by-file breakdown>

</details>

### Remaining
- [ ] Uncompleted plan step 1
- [ ] Uncompleted plan step 2
- [x] Completed step (for reference)

UPDATE_EOF
)"
```

### 7. Update checkboxes in previous progress comments

Before posting or after posting the new update, check if there are any earlier progress comments on the issue that have unchecked `- [ ]` items in a `### Remaining` section. For each unchecked item, determine whether it has been completed based on the current session's work (commits, PRs created, tests run, etc.).

If items are now complete, edit the previous comment to tick them:

```bash
# Get comment IDs that contain unchecked remaining items
gh api repos/<owner>/<repo>/issues/<number>/comments --jq '.[] | select(.body | contains("- [ ]")) | .id'

# For each comment, fetch its body, update the checkboxes, and PATCH it
gh api repos/<owner>/<repo>/issues/comments/<comment_id> --method PATCH --field body="<updated body with [x] replacing [ ]>"
```

Only tick items that are genuinely completed — do not tick items that are still pending. If all items in a previous comment are now ticked, that's fine — it shows progress over time.

### 8. Optionally update labels

If the work is complete, ask the user if they want to:
- Add a `needs-review` label
- Close the issue

If work is in progress, add an `in-progress` label if one doesn't exist.

Only update labels if the repo uses them — check with `gh label list --repo <owner/repo>` first.

### 9. Report to the user

Display:
- Link to the posted comment
- Summary of remaining work
- Reminder of the branch name and any uncommitted changes

## Notes

- This skill is manual — the user calls it when they want to post progress.
- Keep the posted comment concise. The detailed changes go in the collapsible block.
- If there are no commits and no changes, tell the user there's nothing to report rather than posting an empty update.
- If the issue doesn't have a plan section, just post the commit summary without the "Remaining" comparison.

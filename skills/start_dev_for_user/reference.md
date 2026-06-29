# start_dev_for_user — reference detail

Factored out of `start_dev_for_user.md` (read by repo path
`PyAutoBrain/skills/start_dev_for_user/reference.md`). Holds the tone rules,
comment templates, registry formats, and the forward-compatibility note.

## Tone rules (every comment on a `user-facing: true` task)

- First/second person, contractions allowed — a polite teammate, not a status bot.
- Lead with what the reporter cares about (status, plan, next); file paths and
  class names go inside `<details>`.
- No emojis (unless explicitly requested).
- Length: receipt ≈ 2 lines; plan ≈ 15 visible lines + collapsible detail;
  routing ≈ 3 lines.
- When asking for clarification, group every question into **one** comment, each
  with a one-sentence reason it helps.

## Argument normalisation

Accept a full URL (`https://github.com/<owner>/<repo>/issues/<n>`), a slug
(`<owner>/<repo>#<n>`), or a bare number `<n>` (only when cwd is inside a known
PyAuto checkout — derive `<owner>/<repo>` from its origin + the WORKFLOW.md
mapping). Strip whitespace/backticks/angle-brackets.

```bash
gh issue view <n> --repo <owner>/<repo> \
  --json number,title,body,author,labels,state,url,comments
```

- `.state == "CLOSED"` → abort (won't be picked up).
- A prior comment containing `<!-- start_dev_for_user:claimed -->` → already
  claimed; offer **resume** (jump to the right step from the `active.md` entry) or
  **re-claim** (only if the previous claim was abandoned; confirm first).

## Receipt comment (milestone #1)

```bash
gh issue comment <n> --repo <owner>/<repo> --body "$(cat <<'RECEIPT_EOF'
Hi @<author> — thanks for the report. I'm Jammy's CLI assistant; I'll take a look and post back shortly with a plan, or follow-up questions if I need more detail.

<!-- start_dev_for_user:claimed -->
RECEIPT_EOF
)"
```

## Clarification gate

Decide whether the issue is actionable. Treat as unclear when: a bug report has
no repro; no version/error trace where needed; ambiguous scope ("make it faster"
with no metric); title/body conflict; or the ask contradicts a documented design
choice. If clear, proceed to the plan. If unclear:

1. Use `AskUserQuestion` to surface the gaps **to the developer first** (curate
   before going public).
2. Post **one** consolidated clarifying comment in the tone above; tag the
   reporter, one sentence per question.
3. Apply a `needs-info` label if the repo has one.
4. Add a partial `active.md` entry (no worktree/repos/session):
   ```markdown
   ## <task-name>
   - issue: <issue-url>
   - user-facing: true
   - status: awaiting-info
   ```
5. Tell the developer to re-run once the reporter replies. **Stop** (no plan,
   branch survey, or routing). The push carries the partial registration:
   `prompt_sync_push "prompt: register <task-name> (#<issue>) awaiting reporter info [user-facing]"`.

## Plan comment (milestone #2)

We do **not** create or rename an issue — we comment on the existing one. Reuse
the `/start_dev` issue-body content (Overview/Plan/collapsible detail) reframed as
a teammate update:

```markdown
Here's what I'm planning to do — let me know if anything looks off.

<one-paragraph plain-English summary>

**Plan**
- <high-level bullet 1>
- <…>

<details>
<summary>Detailed implementation plan</summary>

### Affected repositories
- repo1 (primary)

### Work classification
<Library / Workspace / Both>

### Branch survey

| Repository | Current Branch | Dirty? |
|---|---|---|
| ./RepoName | main | clean |

**Suggested branch:** `feature/<name>`
**Worktree root:** `~/Code/PyAutoLabs-wt/<name>/` (created later by `/start_library`)

### Implementation steps
1. <detailed step with file paths>

### Key files
- `path/to/file.py` — description of changes

</details>

I'll post back when the work is in progress and again when there's a PR.
```

**Present the comment for developer review before posting** (same gate as
`/start_dev`).

## Registry entries

`active.md` (no conflict) and `planned.md` (conflict) use the same formats as
`start_dev` (see `../start_dev/reference.md` → "Registry entries"), plus
`- user-facing: true` carried through so downstream skills keep conversational
mode. Push commit message tag: `[user-facing]`.

## Routing note

After routing to `/start_library` or `/start_workspace`, remind: this task is
`user-facing: true`; use `/update-issue` between milestones with a conversational
summary. Optionally ask (via `AskUserQuestion`) whether to post a brief
"starting work now" milestone — default to not posting to avoid a double comment.

## Forward compatibility — `user-facing: true`

Downstream skills should eventually honour the flag: `/update-issue` defaults to
conversational tone; `/ship_library` and `/ship_workspace` post PR-open and merge
milestones. Until then, the developer calls `/update-issue` manually at PR-open
and merge.

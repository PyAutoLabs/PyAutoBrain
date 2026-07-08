# Start Dev For User: Pick Up a User-Filed GitHub Issue

Variant of `/start_dev` whose starting point is a GitHub issue **opened by an
external user** rather than a `PyAutoMind/` prompt. Same downstream routing
(Feature Agent → classify → branch survey → register → `/start_library` or
`/start_workspace`), plus two extra responsibilities:

1. **Conversational, milestone-driven comments** posted back to the issue so the
   reporter can follow progress.
2. **A clarification gate** — user-filed issues are often incomplete, so the
   skill stops and asks for missing info before planning.

Workflow entry point — not an agent. Read [`../WORKFLOW.md`](../WORKFLOW.md) for
the organ boundary, the Feature Agent, Memory consultation and the
execution-environment model. Tone rules, comment templates and registry formats
are in [`reference.md`](reference.md) (`PyAutoBrain/skills/start_dev_for_user/reference.md`).

## Usage

```
/start_dev_for_user <issue-url-or-number>
```

Accepts a full URL, `<owner>/<repo>#<n>`, or a bare `<n>` (only when cwd is inside
the relevant checkout). See [`reference.md`](reference.md) → "Argument
normalisation".

## Flow

### 0. Resume check (Mind)

Like `/start_dev` step 0 — scan `PyAutoMind/active.md`: if an entry already
matches this issue/task, offer to **resume** it (read the entry and continue)
instead of starting fresh. `active.md` is the shared task state across
environments, so no special handoff step is needed.

### 1. Resolve + read the issue

Normalise the argument and fetch the issue (reference.md → "Argument
normalisation"). Abort if closed; if already claimed, offer resume or re-claim.

### 1a. Receipt comment (milestone #1)

Post a short acknowledgment so the reporter sees activity within seconds —
template in [`reference.md`](reference.md) → "Receipt comment". Substitute the
reporter's actual `.author.login`.

### 2. Route through the Feature Agent (Brain + Memory)

```bash
bin/pyauto-brain feature        # classify from the issue + its @RepoName refs; pull Memory context
```

Identify the target repos by scanning the issue title + body + reporter details
(`@RepoName` convention; default the primary to the repo the issue lives on if
none are referenced). Classify library vs workspace (WORKFLOW.md mapping). Consult
Memory for context. Explore the referenced code briefly. If `pyauto-brain` is
unavailable, emulate inline per WORKFLOW.md.

### 3. Clarification gate

Decide whether the issue is actionable. If unclear, run the clarification
subroutine (developer triage via `AskUserQuestion` → one consolidated reporter
comment → `needs-info` label → partial `active.md` entry → **stop**) per
[`reference.md`](reference.md) → "Clarification gate". If clear, continue.

### 4. Plan + branch survey

Produce the two-level plan (high-level + detailed) as in `/start_dev` step 3, and
run the branch survey (`start_dev/reference.md` → "Branch survey") — suggest
`feature/<task-name>` and derive the worktree root. We do **not** create or
rename an issue.

### 5. Plan comment (milestone #2)

Post the plan as an issue comment (reframed as a teammate update), **after
developer review** — template in [`reference.md`](reference.md) → "Plan comment".

### 6. Conflict check + register (Mind)

```bash
source admin_jammy/software/worktree.sh
worktree_check_conflict <task-name> <repo1> [repo2 ...]
```

Conflict → `planned.md` (blocked); no conflict → `active.md`. Both carry
`user-facing: true`. Formats in [`reference.md`](reference.md) → "Registry
entries". (No prompt-file move — there is no prompt file in this flow.)

### 7. Route + push (milestone #3, optional)

Route to `/start_library` / `/start_workspace` and display issue URL, primary
repo, branch, classification, plus the user-facing reminder
([`reference.md`](reference.md) → "Routing note"). Push Mind:

```bash
source PyAutoMind/scripts/prompt_sync.sh
prompt_sync_push "prompt: route <task-name> (#<issue>) → <next-skill> [user-facing]"
```

## Notes

- Present every comment body for developer review before posting.
- If `gh auth status` fails, tell the developer to run `! gh auth login`.
- Forward compatibility for the `user-facing: true` flag is in
  [`reference.md`](reference.md).

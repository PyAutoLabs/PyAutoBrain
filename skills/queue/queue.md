# /queue — keep the human's ranked list, in chat

`PyAutoMind/queue.md` says what the human wants done next, in order. Its only
writer is the human, through this chat (PyAutoBrain#640). The Mind dashboard
shows it read-only: a ★ and rank `#n` on each queued task, and a 📋 on every
task that copies the line to paste here.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## The rule of this chat

After `/queue`, a pasted task is an **add**. That covers a whole prompt, a
prompt path or GitHub link, a task title, or a dashboard 📋 line such as
`Use the start-dev skill. draft/feature/x/y.md`. It is never a start-dev,
`/route`, intake, plan or build request. Do not read the prompt to plan it, and
do not offer to start it. If the human clearly wants to leave queue mode
("start this one now"), confirm that in one line, then route normally.

## Verbs (plain words map onto these)

Run `python3 scripts/queue_edit.py <verb> …` in the Mind worktree (step 1):

| The human says | Run |
|---|---|
| a pasted task, or "add …" (optional note, optional place) | `add - [--note "<note>"] [--at <n>\|top]` with the paste on stdin |
| "remove / drop / retire …" (optional reason) | `remove "<who>" [--why "<reason>"]` |
| "move … up / down / to the top / to the bottom / to 3" | `move "<who>" up\|down\|top\|bottom\|<n>` |
| "show" / "what's queued?" | `show` |

`<who>` is a rank (`2` or `#2`), a path, or the entry's label or title. `add`
refuses a ref that resolves to no `draft/` or `active/` prompt, a title that
matches several prompts, and a prompt that is already queued. Relay the refusal
in one line and ask for the path. Never work around it by editing the file.
`remove` moves the entry to `## Retired` with `shelved-as:` and keeps its
note. The prompt itself stays in `draft/`.

`show` writes nothing: run it in a fresh worktree (steps 1, 2 and 5 below)
and skip the commit, so it reads `origin/main`, not a stale checkout.

## Procedure for a write

1. **Temporary Mind worktree, detached on `origin/main`.** Never edit the
   shared checkout:
   ```bash
   MIND=<resolved PyAutoMind checkout>; T=$(mktemp -d)/mind
   git -C "$MIND" fetch -q origin && git -C "$MIND" worktree add -q --detach "$T" origin/main
   ```
2. **Edit:** `cd "$T" && python3 scripts/queue_edit.py <verb> …`. For a paste,
   use a quoted heredoc on stdin (`add - <<'PASTE'`). One or more verbs may run
   before the commit.
3. **Commit and push only `queue.md`:**
   ```bash
   source scripts/prompt_sync.sh && PROMPT_REPO="$T" PROMPT_SYNC_PUSH_TO=main \
     prompt_sync_push "queue: <what changed, a few words>" queue.md
   ```
   If the push is rejected because main moved, run
   `git -C "$T" fetch origin && git -C "$T" rebase origin/main && git -C "$T" push origin HEAD:main`.
4. **Check:** `python3 scripts/lifecycle.py check`. Report any `queue.md`
   finding. Other drift is not this chat's to fix; mention it in one line.
5. **Clean up:** `git -C "$MIND" worktree remove "$T"`.
6. **Reply with the new order** as one short numbered list (the script prints
   it: `n. label — ref`). Nothing else unless something was refused.

The dashboard re-renders on its own (`dashboard_refresh.yml` watches
`queue.md`), so do not regenerate it here.

## Without a shell (web or mobile)

If the chat cannot run git, say so and give the exact `queue_edit.py` command
for the human to run later. Never hand-edit `queue.md` through the GitHub
contents API.

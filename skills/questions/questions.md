# /questions — clear the inbox of parked questions, in chat

`PyAutoMind/questions.md` holds the questions shift workers parked on, one
`Q<n>` entry each under Open, Deferred, Answered or Dropped. The shift watcher
adds them; no @mention is sent mid-shift, and the digest says how many were
added (PyAutoBrain#645). This chat is the one chat writer, as `/queue` is for
the queue. The dashboard's inbox section is read-only: its 📋 copies
`Use the questions skill. Q<n>` (or `Use the questions skill.`) to paste
here.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## The rule of this chat

After `/questions`, a pasted `Use the questions skill. Q17` line (or
`/questions Q17`), a `Q<n>` id or "go through my questions" opens the inbox.
It is never a start-dev, `/route`, intake, plan or build request, even when
the human's answer names work to do. An answered
task resumes in the **next** shift (a shift already running has counted it),
or in a session if the human says "start it now" in words.
If `/queue` or `/cockpit` also ran in this chat, ask which one a paste is for.

## Verbs

Run `python3 scripts/questions_edit.py <verb> …` in the Mind worktree (step 1
of the write procedure):

| The human says | Run |
|---|---|
| an answer in words | `answer Q<n> --text "<answer>" --comment <url> --by <login> --via chat\|issue` |
| "later" / "not now" (optional date) | `defer Q<n> [--until YYYY-MM-DD] --by <login>` |
| "drop" / "withdraw" (a reason) | `drop Q<n> --why "<reason>" --by <login>` |
| "reopen Q<n>" (a mistake, a revived task) | `reopen Q<n>` |
| "skip" | nothing: go to the next entry |
| "show" / "what's open?" | `show --open` (or `show --all`, `show Q<n>`) |

`<login>` is the human's GitHub login (`gh api user --jq .login`, once).
Relay a refusal in one line; never work around it by editing the file.

## A sitting

1. **List.** `show --open` in a fresh worktree on `origin/main` (steps 1 and 5
   below; no commit). It lists Open entries and Deferred ones that are due,
   oldest first. Say "N open. Go one at a time?"
2. **Each entry.** Show its ask, options, issue link and age (`show Q<n>`).
   First make one read of the issue's comments since `asked:` by the human's
   login:
   `gh api "repos/<owner>/<repo>/issues/<n>/comments?since=<asked>" --jq '.[] | select(.user.login=="<login>") | .body'`.
   If the human already replied there, offer: "You replied on the issue:
   '<first 200 chars>'. Record that as the answer?" A yes records it with
   `--via issue` and that comment's URL, and posts nothing new.
3. **The human's word.**
   - **Answer:** post it on the issue as the human:
     `gh issue comment <issue> --body "Answer (Q<n>, from the questions inbox): <text>"`
     (it prints the comment URL). Then run `answer` with `--comment <url>`.
     In one commit this moves the entry to Answered and appends the answer to
     the task's prompt under `## Answers from the human`; the script prints
     `prompt: <path>`, which the commit must include.
   - **Later:** `defer`. Nothing is posted.
   - **Drop:** `drop --why`, then post
     `gh issue comment <issue> --body "Question withdrawn by the human: <why>"`.
     Dropping shelves the task: no shift picks it until it is reopened, named
     in a brief, or `/add`-ed. If the task is in `queue.md`, ask once whether
     to take it off the queue too, and if so follow the `/queue` procedure
     (`../queue/queue.md`); never edit `queue.md` here.
4. **Commit before the next question** (steps 3–5), so a sitting cut short
   loses nothing.
5. **End with a summary**: answered (and whether each resumes: queued at #n,
   a small single-repo dip, or "not queued and not small — `/queue` it to have
   a shift pick it up"; an answer is not a new priority), deferred, dropped.

## Procedure for a write

1. **Temporary Mind worktree, detached on `origin/main`.** Never edit the
   shared checkout:
   ```bash
   MIND=<resolved PyAutoMind checkout>; T=$(mktemp -d)/mind
   git -C "$MIND" fetch -q origin && git -C "$MIND" worktree add -q --detach "$T" origin/main
   ```
2. **Edit:** `cd "$T" && python3 scripts/questions_edit.py <verb> …`.
3. **Commit and push `questions.md`, plus the `prompt:` path an answer printed:**
   ```bash
   source scripts/prompt_sync.sh && PROMPT_REPO="$T" PROMPT_SYNC_PUSH_TO=main \
     prompt_sync_push "questions: <what changed, a few words>" questions.md [<prompt path>]
   ```
   If the push is rejected because main moved, do not rebase or `git push`
   by hand: remove the worktree (step 5), re-create it on a fresh
   `origin/main` (step 1), re-run the same `questions_edit.py` verb (step 2;
   an issue comment already posted is reused by its URL, never posted twice),
   and push again through `prompt_sync_push`.
4. **Check:** `python3 scripts/lifecycle.py check`. Report any `questions.md`
   finding. Other drift is not this chat's to fix; mention it in one line.
5. **Clean up:** `git -C "$MIND" worktree remove "$T"`.

The dashboard re-renders on its own (`dashboard_refresh.yml` watches
`questions.md`), so do not regenerate it here.

## Without a shell (web or mobile)

If the chat cannot run git, say so, still post the answer on the issue if the
human wants (that alone does not release the task), and give the exact
`questions_edit.py` command for the human to run later. Never hand-edit
`questions.md` through the GitHub contents API.

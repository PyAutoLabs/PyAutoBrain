# /cockpit — watch a shift and steer it from chat

The shift watcher (a timer, not a session) is the engine. It writes one line per
event to the shift's `events.jsonl`, and `pyauto-brain batch watch --stream`
prints them (PyAutoBrain#644). This chat only reads that stream and posts
steering comments on the shift issue, which the watcher reads on its next tick
(about 3 minutes). Closing the chat changes nothing about the shift.

The watch is the one carve-out from "sessions end at their deliverable"
(PyAutoMind `policy/shift_cockpit_watch.md`). The end-at-deliverable hook
enforces it: it lets through only the canonical stream command below, inside
the shift's window. If the hook refuses a Monitor, relay its reason in one line
and stop. Never retry it in another form.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## The rule of this chat

After `/cockpit`, a pasted task is an **add to this shift**. That covers a whole
prompt, a prompt path or GitHub link, a task title, or a dashboard 📋 line such
as `Use the start-dev skill. draft/feature/x/y.md`. It is never a start-dev,
`/route`, intake, plan or build request (see "Steering", `/add`). If the human
clearly wants a task started outside the shift ("start this one now, not in
the shift"), confirm in one line, then route normally.

## 1. Find the shift

- **Record:** the `--record` the human named, else `PYAUTO_SHIFT_BRIEF` in
  `~/.config/pyauto/orchestrator.env`, else the newest
  `<MIND>/batches/<slot>.md` whose window is open.
- **Checkouts:** `<BRAIN>` and `<MIND>` are the resolved PyAutoBrain and
  PyAutoMind checkouts of this workspace (root: `PYAUTO_ROOT`, else the nearest
  ancestor holding `.pyauto-root`):
  `python3 <BRAIN>/agents/_repo_paths.py path PyAutoMind --required --root <root>`.
  The hook pins the stream to exactly these two, so a copy elsewhere is refused.
- **Check, in the foreground:**
  `<BRAIN>/bin/pyauto-brain batch watch --stream --check --record <MIND>/batches/<slot>.md`.
  On a non-zero exit, say why in one line (its stderr) and stop, with nothing
  armed.

## 2. Check the steering identity once

`gh api user --jq .login` must equal the watcher's mention login
(`PYAUTO_SHIFT_MENTION`, else `shift_watcher: mention_login:` in
`<BRAIN>/config/policy.yaml`). If it differs, say once that the watcher ignores
steering from this login, and carry on watch-only. Read the shift issue URL from
the record's `- issue:` line.

## 3. Attach

Call `Monitor` with `timeout_ms: 1800000`, description `shift <slot> events`,
and exactly this command, in this flag order, with nothing before, after or
around it:

```
<BRAIN>/bin/pyauto-brain batch watch --stream --record <MIND>/batches/<slot>.md --from <seq> --for 28
```

- Replace `<BRAIN>`, `<MIND>`, `<slot>` and `<seq>` with literal text: absolute
  paths, digits. No `$VAR`, `~`, quotes, `cd`, pipe or `2>&1`. The hook refuses
  any shell metacharacter, and paths only of `A-Z a-z 0-9 . _ / -`.
- First attach: leave out `--from <seq>` (the last 5 events), or `--from 0` when
  the human wants everything so far.
- Never add `--json` (one plain line per event is the report). Add
  `--home <dir>` after `--for 28` only when the human named one.

Then say, in one line, the `attached <slot>: …` summary and the inbox count
(section 6).

## 4. On each notification

- **Print the lines as they came**, one plain line per event, with no
  commentary unless asked.
- **A line starting `HH:MMZ NEEDS YOU:`** is also sent as a phone push
  (`PushNotification`, where the client has it), with that line as the text.
  Nothing else is pushed.
- **`segment-end next=--from N`** (exit 3): arm the same command again with
  `--from N`. This is the only re-arm.
- **Anything else ends the watch:** `shift-end`, the `stopped` line, the
  `STOP file present` line, the `Watch window over` line, exit 2 (refused), or
  a Monitor expiry without `segment-end`. Do not arm again. Say:
  "Shift over. Digest: <url>. <q> questions in your inbox. Go through them now
  or later?" (the digest URL from the `digest` line, else the shift issue). The
  session ends at that deliverable.

## 5. Steering: plain words become one comment

Post each act as one comment on the shift issue, first line the command (all
the watcher reads), second line an audit note:

```bash
gh issue comment <issue-url> --body-file - <<'STEER'
/drop markdown_regeneration_sigma_min
(said in the cockpit: "drop the sigma one, it's not worth it")
STEER
```

Then say "posted; the watcher acknowledges on its next tick (about 3 min)". The
`steer` event arrives through the stream. If no `steer` event for it arrives
within 2 ticks (about 6 min), or `steer-unread` arrives, say so once.

| The human says (examples) | Comment | Confirm first? |
|---|---|---|
| "pause", "hold off", "stop starting things" | `/pause` | no |
| "carry on", "resume" | `/resume` | no |
| "drop the PyAutoLens one", "forget X" | `/drop <task>` | no |
| "stop the shift", "kill everything" | `/stop` | **yes**: echo the comment, wait for "yes" (the watcher stops for good until `STOP` is removed by hand) |
| "kill that worker and retry", "restart X" | `/kill <task>` | **yes**, one line |
| "kill X and don't retry" | `/drop <task>`, then `/kill <task>` (two comments, in that order) | **yes** |
| "also do <prompt>", a pasted task | `/add <draft path>` after the premise check below | no |
| "only one more merge", "no more merges" | `/cap merges <n>` | no |
| "fewer workers", "one worker only" | `/cap workers <n>` | no |
| "keep it under 400k" | `/cap tokens 400000` | no |
| "merge #347" | not a comment: the `/prm` procedure on that PR, in this chat. If a close-out is `running` on it, say so and ask the human to wait or `/drop` first | /prm's own |
| "put X on the queue", "move X up" | not a shift command: the `/queue` procedure | /queue's own |
| "go through my questions", "answer Q17" | not a shift command: `/questions` (section 6) | n/a |

- **`<task>`** is the task id from the last snapshot
  (`<BRAIN>/bin/pyauto-brain batch watch --once --record <record>`). "The
  PyAutoLens one" is resolved from it. If two match, ask.
- **`/add`**: resolve the paste to a Mind-relative `draft/…/x.md` path. Then run
  `<BRAIN>/bin/pyauto-brain batch premise <path>` once in the foreground, and do
  not post when it says `obsolete` (say why). The watcher's own gates (cutoff
  30 min before `review-at`, lanes, claims, organ rule) answer in the ack.
- **`/cap`** sets `merges`, `workers`, `sessions` or `tokens` for the rest of
  the shift, never above the brief's own value (the watcher refuses that).
- Only the verbs above; the watcher ignores any other first line.

## 6. Questions

Parked workers' questions go to the Mind inbox `questions.md`, answered through
`/questions` (Build B), never in this chat's steering. Count the open ones at
attach and at shift end, from Mind `origin/main` (one foreground fetch, then a
local read):

```bash
git -C <MIND> fetch -q origin && git -C <MIND> show origin/main:questions.md
```

Count the `### Q<n>` entries under `## Open`. It is a reminder, never a demand.
When the human says "go through my questions" (or "now" at shift end), hand
over to the `/questions` skill. If `questions.md` is not on Mind `origin/main`,
or the `/questions` skill is not installed, say "the questions inbox is not
installed yet; parked questions are in the digest and on the shift issue" and
leave the count out.

## 7. Answering questions about the shift

Answer on request only, with reads made in this session: `batch watch --once`
(the snapshot), the status comment (`gh api` read), a PR (`gh pr view`, or
`gh pr checks` once) and `events.jsonl`. Never a polling loop, and never a
second Monitor.

## Never in the cockpit

- A Monitor or background command on anything but the stream. A Monitor or
  background loop on GitHub (CI, a review, a merge) is refused by the hook:
  read CI once and report.
- A merge the human did not command.
- A Mind write outside the `/queue` and `/questions` procedures.
- Arming anything after the shift ends, or re-arming after any exit but
  `segment-end`.

## Without Monitor (web, mobile, Codex)

Run `batch watch --once` in the foreground when asked, and steer by the same
comments. Nothing is armed. Without `gh`, post the steering comment and make
the reads through the GitHub MCP tools that
[`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md) maps each `gh` call to.

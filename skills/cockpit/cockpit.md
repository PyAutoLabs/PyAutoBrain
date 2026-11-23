# /cockpit — watch a shift and steer it from chat

The shift watcher (a timer, not a session) writes each event to the shift's
`events.jsonl`; `pyauto-brain batch watch --stream` prints them (#644). This
chat reads that stream and steers only by comments on the shift issue, which
the watcher reads each tick (about 1 min); closing the chat changes nothing.
The watch is the one carve-out from "sessions end at their deliverable"
(PyAutoMind `policy/shift_cockpit_watch.md`); the hook lets through only the
canonical command below, inside the window. If it refuses a Monitor, relay
its reason in one line and stop. Never retry it in another form.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Attach only when asked

Attach only when explicitly asked in this session, e.g. `/cockpit` or "watch the shift".
For a status question, answer once with `batch watch --once` or the reads in section 7, with no Monitor.

## The rule of this chat

After `/cockpit`, a pasted task is an **add to this shift**. That covers a whole
prompt, a prompt path or GitHub link, a task title, or a dashboard 📋 line such
as `Use the start-dev skill. draft/feature/x/y.md`. It is never a start-dev,
`/route`, intake, plan or build request (see "Steering", `/add`). If `/queue`
or `/questions` also ran in this chat, ask which one the paste is for. To start
a task outside the shift, confirm in one line, then route normally.

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

In Codex, run the command below in a foreground terminal during the **current chat turn**.
Read stdout from the same session handle with short, interruptible waits and relay each event as it arrives.
Resume only on exit 3 with the printed cursor. On cancellation or turn end, interrupt and reap the reader.
If streaming is unavailable, give the human the command for their terminal.

In Claude, call `Monitor` with `timeout_ms: 1800000`, description `shift <slot> events`,
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

Then say "posted; the watcher acknowledges on its next tick (about 1 min)". The
`steer` event arrives through the stream. If no `steer` event for it arrives
within 3 ticks (about 3 min), or `steer-unread` arrives, say so once.

| The human says (examples) | Comment | Confirm first? |
|---|---|---|
| "pause", "hold off", "stop starting things" | `/pause` | no |
| "carry on", "resume" | `/resume` | no |
| "drop the PyAutoLens one", "forget X" | `/drop <task>` | no |
| "stop the shift", "kill everything" | `/stop` | **yes**: "This stops new work; running workers continue — kill each with /kill <task>?" Post `/stop` on "yes" (the watcher stops for good until `STOP` is removed by hand). Then offer each running worker's `/kill <task>` as its own confirmed comment |
| "kill that worker and retry", "restart X" | `/kill <task>` | **yes**, one line |
| "kill X and don't retry" | `/drop <task>`, then `/kill <task>` (two comments, in that order) | **yes** |
| "also do <prompt>", a pasted task | `/add <draft path>` after the premise check below | no |
| "only one more merge", "no more merges" | `/cap merges <n>`, n as below | **yes**, with n shown |
| "one worker only" (a number) | `/cap workers <n>` | **yes**, with n shown |
| "fewer workers" (no number) | nothing yet: ask "how many workers at most?" | ask |
| "keep it under 400k" | `/cap tokens 400000` | **yes**, with n shown |
| "the red sweep is fine", "unblock merges" | `/clear-sweep` (clears the latest red workspace sweep only) | **yes**, naming the run |
| "merge #347" | not a comment: the `/prm` procedure on that PR, in this chat. If a close-out is `running` on it, say so and ask the human to wait or `/drop` first. An adversary pass first, only if they ask: an Opus sub-agent, never this chat's model (`AUTONOMY.md` "Adversary model default — 2026-11-22"); a finding on the PR description alone is a note and does not hold the merge | /prm's own |
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
  `merges` counts the **whole shift**, not merges from now on: read merged
  and running close-outs from `batch watch --once` first, then "one more
  merge" is n = merged + running + 1, and "no more merges" is
  n = merged + running. Confirm every `/cap` in one line with the number,
  e.g. "Post `/cap merges 3` (2 merged, 0 running, so one more)?"
- **Unclear wording: ask.** Never guess a verb, a task or a number. One short
  question, then post on the answer; the watcher ignores any other first line.

## Stop watching

On "stop watching" or "close the cockpit", interrupt and reap the Codex reader or use Claude's `TaskStop`.
Confirm that the shift carries on. Resume watching only on request.

## 6. Questions

Parked workers' questions go to the Mind inbox `questions.md`, answered through
`/questions`, never by steering. At attach and at shift end, after one
foreground `git -C <MIND> fetch -q origin`, count the `### Q<n>` entries under
`## Open` in `git -C <MIND> show origin/main:questions.md`: a reminder, never a
demand. "Go through my questions" (or "now" at shift end) hands over to
`/questions`. If `questions.md` is not on Mind `origin/main`, or the
`/questions` skill is not installed, say "the questions inbox is not installed
yet; parked questions are in the digest and on the shift issue" and leave the
count out.

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

## Without a streaming tool

On web or mobile, use `batch watch --once` on request and steer through the shift issue.
When `gh` is unavailable, use the equivalents in [GitHub access](../GITHUB_ACCESS.md).

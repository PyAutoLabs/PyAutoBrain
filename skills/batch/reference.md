# Batch — reference

Moved word for word from [`batch.md`](batch.md) to keep the skill's mandatory
load under its 200-line budget. Read a section when the step that needs it is
reached; `batch.md` points here from each one.

## The member-session contract

**The member-session contract (2026-08-31, both measured that night):**

- *Spawned from the orchestrator's session template, never bare*
  (2026-11-03). Under a brief, every worker starts from the same template
  the orchestrator uses — sources, bootstrap, the brief's path — so the two
  points below are met by construction rather than remembered.

- *Spawned cloud sessions need sources and a bootstrap preamble.* A session
  created bare (environment inherited, no source repos) has no clones, no
  skills and no GitHub scope — the whole first wave died on
  `Unknown command: /start_dev`. Seed `PyAutoMind@main` as the session
  source and prepend: run `scripts/session_bootstrap.sh`; attach
  PyAutoLabs/PyAutoBrain via `add_repo` (push) + `register_repo_root`; read
  `PyAutoBrain/skills/GITHUB_ACCESS.md`; read the batch record; then follow
  `skills/start_dev/start_dev.md` for the prompt in `--auto` mode.
- *Members END at their deliverable — a green PR, a posted verdict, or a
  park.* The dispatch line must say, and members must obey: **do not watch
  the PR, do not `subscribe_pr_activity`, do not schedule check-ins or
  routines after the last push.** The batch review owns everything that
  follows. This is no longer a batch-only exemption: every session ends at
  its deliverable (`PyAutoMind/policy/end_at_deliverable.md`), `/prm`
  included.
  Five members self-armed 2–4-hourly check-ins on green PRs overnight and
  drained usage with no task active.

## Under a brief, the digest is the review surface

**Under a brief, the digest is the review surface** (2026-11-03). The watcher
appends a `## Digest` to the record — brief work, then backlog picks with a
one-line reason each, one proof packet per task, then the shift counters — and
posts it once as a comment on the shift's `issue:`. The record plus that comment
is what the human reads; the HTML packet is written only when the brief says
`packet: yes`. Formats: `PyAutoMind/batches/AGENTS.md`, "Digest" and "Proof
packet".

## Brief verbs

**Brief verbs.** `bin/pyauto-brain batch brief --check <file>` validates a
brief against the `batches/AGENTS.md` schema (every error names its key;
exit 1 refuses it), and `batch plan --brief <file>` composes inside it: named
tasks first, then only the backlog its policy covers, against its
`review-minutes:`. Run the check before writing a brief's `review-at:` into
`batches/`. The check also runs `batch premise` on each named task and warns
when one is **obsolete on main** (`--no-premise` skips it) — drop that task
before the shift pays a worker to find out. For a live brief (not `shadow: yes`)
the check also refuses a missing `issue:` and a CLI login that has expired or
expires before `review-at:` (`claude auth status --json`, no model call; the
human runs `claude /login`). `batch brief --new <slot> --review-at <ISO> --out
<file>` makes that shift issue on PyAutoMind (one `gh issue create`) and
writes it as `issue:`; `--issue <url>` names one instead, and a file that
already has one keeps it. Dispatch is the watcher's (`batch.md`, "The watcher"), not a verb:
it finds the one open brief on Mind `origin/main` (only a pushed brief opens;
two open briefs tick neither) and ends at `review-at:` + 45 min. `batch digest
--record <file>` prints a shift's digest and writes nothing; the record append
and the one issue comment are the watcher's, at `review-at:`, or earlier on
the tick a shift has nothing left to do (early close, M3.7c).

## Launching a shift brief

Compose it with `batch brief --new <slot> --review-at <ISO> --out <file>`,
which also makes the shift issue on PyAutoMind and writes `issue:`
(2026-11-17). Then run `batch brief --check <file>`: it refuses a live brief
without `issue:`, and an expired CLI login (the human runs `claude /login`).
**Pushing the brief is the launch.** The watcher finds it on Mind
`origin/main` itself, ticks it from `dispatched:` to `review-at:`, and stops
45 min after `review-at:`. Never two open briefs at once. The watcher reads
the `origin/main` ref of the Mind checkout in its env file **without
fetching**, so push the brief from that checkout or `git fetch` it before
launch; otherwise the watcher idles with "no open brief".

## When the batch is complete

**Review closes the batch; follow-ups never block the next one** (2026-08-31).
Every tweak and follow-up is *queued*, enacted in the next batch the human
launches — it is never executed inside the review, and an open follow-up is
never a reason to hold the next dispatch. The batch is complete when: accepted
PRs are merged, science rulings are in their ledgers, follow-ups sit at the top
of `queue.md`, and the batch
record carries `reviewed-at:` (when they actually sat down — the calibration of
their own `review-at:` estimate), `delivered:` (`batch.md`: "`delivered:` is not green"), `review:` (the
review file's path) and **`review-minutes-actual:`**. That last number is the
only calibration the review estimate will ever get, so ask for it if the human
does not volunteer it.

## `/batch watch` and steering a running shift (PyAutoBrain#622)

- **On the laptop** (the slot is local): `bin/pyauto-brain batch watch --record
  PyAutoMind/batches/<slot>.md --once`. It is read-only; relay the snapshot as
  written, then explain what stands out (a parked worker, a refusal that
  repeats, a budget near its cap).
- **Anywhere else**: the watcher keeps the same snapshot as one comment on the
  brief's `issue:`, edited in place. Read it with `gh issue view <issue>
  --comments` (or the GitHub connector) — it is the comment whose first line is
  `<!-- pyauto-shift-status <slot> … -->`. The dashboard's batch box carries a
  one-line copy (`Live: …`) with its link.
- **Steering is the human's comment on that issue**, its first line one of
  `/pause`, `/resume`, `/drop <task>`, `/stop`, from their own login (the
  watcher ignores every other account and its own comments). Each command is
  acknowledged once, in the status comment's `Commands` list, on the next tick.
  `/pause` holds spawns, re-dispatches and new close-outs; reaps and mentions
  continue.
  A dropped worker that is already running is not killed by `/drop`; the
  human may stop it by hand (`claude stop <id>`) or command `/kill <task>`.
  Never post a command for them.
- **More verbs (PyAutoBrain#644):** `/cap merges|workers|sessions|tokens <n>`
  lowers a cap for this shift, or raises it back, never above the brief's own
  value (`tokens` takes `400k`, `1.2M`); `/add <prompt>` makes a draft on Mind
  origin/main a named task (refused within 30 min of `review-at:`; overrides the
  brief's `exclude:`, never the organ rule); `/kill <task>` runs `claude stop` on
  that task's running worker, which is re-dispatched once unless dropped first.
  An ack starting `ignored:` or `refused:` is a needs-you event: at most 5 such
  comments a shift, no `@`.
- **The event stream:** `bin/pyauto-brain batch watch --stream --record
  <brief> [--from N] [--for MIN] [--json]` prints the slot's `events.jsonl`, one
  plain line per event (`NEEDS YOU:` first when it needs the human), and exits 0
  at `shift-end`, a `STOP` or `review-at:` + 45 min; with `--for` it ends the
  segment with `segment-end next=--from N` (exit 3). `--check` only says whether
  it may attach now (exit 2 outside `dispatched:` − 30 min … `review-at:` + 45
  min). `--record`/`--home` default from `~/.config/pyauto/orchestrator.env`.

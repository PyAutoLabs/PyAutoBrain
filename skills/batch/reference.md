# Batch — reference

Moved word for word from [`batch.md`](batch.md) to keep the skill's mandatory
load under its 200-line budget. Read a section when the step that needs it is
reached; `batch.md` points here from each one.

## The member-session contract (dispatch step 3)

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
  drained usage with no task active. At collect, the orchestrator deletes
  any member-armed routine it finds and archives finished member sessions.

## Collect: the integration worktree

- **"I want to run the whole batch."** —
  `bin/pyauto-brain batch collect --slot <date>-<slot> --integration --apply`
  (laptop only). One worktree root per slot under
  `~/Code/PyAutoLabs-wt/integration-<slot>/`, each affected repo on
  `integration/<slot>` cut from `origin/main` with every member's head merged
  in dispatch order. Hand the human the `source <root>/activate.sh` line: once
  it is sourced a **library** member's change is live anywhere (it is on the
  `PYTHONPATH`), while a **workspace** member's script must be run from inside
  `<root>/<workspace>`. A member that conflicts is **left out and named with
  the conflicting files** — report that as the answer to "how would this
  resolve at the end?", not as a failure. Nothing is pushed, no PR is opened,
  no remote ref is touched. If the reviewer needs it on another machine or in
  CI, add `--push`: one real `integration/<slot>` per repo, pushed with the
  laptop's own git auth, never forced, never a PR, and swept after the record's
  `sweep-after:` date. The first push of a slot is the human's call.

## Collect: PENDING entries and science runs

- **The PENDING entries fill themselves in.** `--apply` regenerates each
  member's section in place — same path, same id — and stamps the page
  `refreshed:`, normally while the human is already reading the finished
  members. No other member's markup is touched, so their stored notes and
  chips survive.
- **Science runs are not batch members.** Checking in on the science is its
  own door — `/cortex`, over `bin/pyauto-brain cortex collect --pull --apply`,
  which pulls every active project, scores every `submitted | running` phase
  against its pre-registered witness and moves what came back to
  `awaiting-ruling`. It needs no record, no slot and no packet. The science
  board this conductor once opened (`--kind cortex`) was retired on
  2026-09-03; see `PyAutoBrain/skills/cortex/cortex.md`.

## Under a brief, the digest is the review surface

**Under a brief, the digest is the review surface** (2026-11-03). Collect
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
before the shift pays a worker to find out. Dispatch is the watcher's (`batch.md`, "The watcher"), not a verb. `batch digest
--record <file>` prints a shift's digest and writes nothing; the record append
and the one issue comment are the watcher's, at `review-at:`.

## Collect: gathering the evidence

- **Gather the evidence, then hand it over.** Collect has no GitHub of its
  own. In a web session, read each member's PRs with the GitHub MCP tools
  (`pull_request_read` for state and diff counts, the check rollup or
  `actions_list` for the checks — `PyAutoBrain/skills/GITHUB_ACCESS.md` maps
  each operation) and write them into the evidence JSON that the conductor's
  `AGENTS.md` documents under "The collect recipe". On the laptop lane
  `--fetch` does the same by running one `gh pr view` per PR. Run it once
  without `--apply` to read the report; run it again with `--apply` to write
  the packet and stamp the record.

## When the batch is complete

**Review closes the batch; follow-ups never block the next one** (2026-08-31).
Every tweak and follow-up is *queued*, enacted in the next batch the human
launches — it is never executed inside the review, and an open follow-up is
never a reason to hold the next dispatch. The batch is complete when: accepted
PRs are merged, science rulings are in their ledgers, follow-ups sit at the top
of `queue.md`, the packet page is archived in `batches/packets/`, and the batch
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
  A dropped worker that is already running is not killed: stopping it is the
  human's, `claude stop <id>` on the laptop. Never post a command for them.

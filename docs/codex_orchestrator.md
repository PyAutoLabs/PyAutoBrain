# Codex workers in the existing shift orchestrator

Codex is an opt-in execution backend, not a second scheduler. Existing briefs
continue to launch Claude workers. Queue order, leases, caps, questions, Mind's
single writer, proof packets, Heart, merge ordering and shift expiry keep their
existing contracts. The canonical brief schema is PyAutoMind `batches/AGENTS.md`.

## Local prerequisites

Use the laptop's Linux/WSL workspace and the same installed watcher. This chat's
cloud checkout cannot operate the laptop's watcher or prove its setup works.
No timer is installed or enabled by the backend.

- A recent Codex CLI advertising `exec --json`, `--sandbox`, `--add-dir` and
  `--approve-for-me`, authenticated with `codex login` using the subscription.
  API-key authentication is refused; inherited OpenAI API-key variables are
  removed from the worker. No OpenAI SDK or API fallback is used.
- Claude CLI authenticated for independent Opus reviews and close-outs. This
  remains required even when a shift has `merge-cap: 0`: pre-ship review is
  separate from close-out.
- The existing local `gh` identity, Heart readiness, Python environment,
  trusted workspace and generated skills/hooks. Review the current Codex
  project hook hash with `/hooks`; the backend never bypasses hook trust.
- Linux `/proc` identity checks (WSL supported). Native Windows and macOS
  supervisors are not implemented by this adapter.

Read-only check, with no model call:

```bash
python3 PyAutoBrain/bin/codex_orchestrator_check.py
```

It checks CLI capabilities and both logins. Hook trust, GitHub permissions and
Heart remain separate checks; a green result is not a shift launch grant.

## Opt into Codex in an approved brief

Add these under the existing `brief:` block before approval/dispatch:

```yaml
  - worker-backend: codex
  - codex-model: <your-installed-model-id>
  - codex-effort: medium
  - worker-mode: auto
```

The model is explicit rather than inherited from a laptop preference. Effort
is `low`, `medium`, `high` or `xhigh`, subject to model support. `auto` uses
Codex automatic approval review; `dontAsk` never asks. Both keep the
workspace-write sandbox and allow the workspace, worktree root and shift-state
root. `acceptEdits` has no equivalent and fails validation. Permission refusals
must become the existing question sidecar and `.done` outcome, not a stalled
interactive prompt. No unrestricted or hook-trust-bypass flags are passed.

Run the existing `batch brief --check <brief>` before dispatch. Backend
selection does not change `Lane:` or grant extra tasks, merges or runtime.
Do not switch an active brief's backend to change a running session: lease
identities retain the backend that actually launched them.

## Reviews and accounting

The shared worker prompt still requires independent pre-ship review. A Codex
worker calls `agents/conductors/batch/_codex_review.py --task <task> --repo
<checkout>` (repeat `--repo` for each affected repository). The helper starts a
fresh Opus CLI session with the existing review-faculty instructions and a
structured CLEAN/FINDINGS/BLOCKED verdict. It records every attempt before
calling the model. It cannot substitute a Codex self-review. The later
close-out remains the existing independent Opus session, with unchanged gates.

Codex multi-agent tools are disabled for shift workers; the accounted review
helper is their only model delegation. Reviewer input, output and cache
creation are added to the worker's usage. Codex JSONL input includes cached
input, so cache reads are subtracted for the existing uncached-token budget
and separately reported. Incomplete/missing usage remains unknown and retains
the existing reservation; the budget is a dispatch budget, not a hard
inference-token ceiling. Accounting is updated from completed turns, not a
provider quota/weekly-limit API. The existing `bin/codex_usage.py` remains a
separate rollout-inspection tool.

## Recovery and stopping

Opaque `codex:<id>` lease identities point to private `codex-sessions/<id>/`
directories under the orchestrator home. Each holds the prompt/request,
JSONL events, stderr, reviewer records and atomic supervisor state. It may
contain project data; it is local runtime state and should not be committed.

The identity and attempt accounting are recoverable before process launch.
A watcher restart adopts the lease and reservation once. Linux boot id and
process start ticks protect against PID reuse. Unreadable state and ambiguous
supervisor/child startup are **unknown**: hold the lease and inspect the local
record; never redispatch just because an observation failed. A no-handshake
session likewise needs inspection, not an automatic retry.

`/kill <task>` asks that worker's verified supervisor to stop its child process
group. The existing one-retry rule still applies; `/drop <task>` first if no
restart is wanted. `/stop` retains its existing whole-shift meaning. A normal
CLI exit without the task's `.done` proof remains an incomplete worker, not
proof that development succeeded.

## First local check and pilot

After the read-only check passes, explicitly run one disposable no-op session:

```bash
python3 PyAutoBrain/bin/codex_orchestrator_check.py --smoke --model <your-installed-model-id>
```

This consumes a Codex session. It verifies launch, completion, a written marker
and usage in a temporary workspace. It does not create an issue, PR or shift,
run a reviewer, or prove repository permissions. It times out after five minutes.

For the first real approved shift, use one named low-risk task, `backlog: none`,
`max-workers: 1`, `merge-cap: 0`, an explicit token budget and a human-stated
`review-at:`. Inspect its Opus pre-ship verdict, proof packet, usage, questions
and final PR before increasing concurrency or enabling merges. Use the
existing watcher installation and cockpit; do not create another timer.

CLI contracts checked during implementation:
[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
and [Claude CLI reference](https://code.claude.com/docs/en/cli-reference).

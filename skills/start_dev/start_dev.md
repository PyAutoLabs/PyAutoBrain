# Start Dev: Classify, Plan, Register

Universal entry point for starting development work. It reads intent from a
**PyAutoMind** prompt, routes the reasoning through the **PyAutoBrain Feature
Agent** (which consults **PyAutoMemory** for context), creates a tracked GitHub
issue, registers the task in Mind state, and hands off to `/start_library` or
`/start_workspace`.

This is a **workflow entry point, not an agent** — classification, planning and
risk judgement belong to Brain. Read
[`../WORKFLOW.md`](../WORKFLOW.md) first: it defines the organ boundary, the
Brain-agent entry points, Memory consultation, the execution-environment model,
the provider-aware **model-delegation policy** (Anthropic retains Fable → Opus
and Opus → Opus; OpenAI works inline by default with bounded exceptions), and
the Mind registry paths used below.

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Usage

```
/start_dev <prompt-file-path>          # path relative to PyAutoMind/
/start_dev <prompt-file-path> --auto   # autonomous mode per ../AUTONOMY.md (see "--auto mode")
```

Prompts live under `draft/<work-type>/<target>/` (first folder = work type, second =
target repo/domain). Pre-migration `<target>/<name>.md` paths still resolve.
Examples: `draft/bug/autofit/factor_graph_instance_iteration.md`,
`draft/feature/autoarray/oversampling.md`.

If the user gives a development task with **no** prompt path, first write a
concise prompt file under the resolved Mind checkout’s `draft/<work-type>/<target>/` folder
(include the original request verbatim), then continue with that path. Never
write one under `human_review/` — that folder is shipped work awaiting a human's
sign-off, not work to start, and it is filed only by an explicit `/intake`
declaration.

A `draft/human_review/…` path handed to `/start_dev` is almost certainly a
mistake: the work it names already shipped. Say so and offer the review (read
the prompt, find the merged PR and the `complete/` record, report back) instead
of opening a worktree — unless the user confirms they want new development, in
which case file that as its own ordinary prompt.

## --auto mode

Only when the human launches with an explicit `--auto` (never ambient — the
activation rule in [`../../AUTONOMY.md`](../../AUTONOMY.md)):

1. Compute the **effective level** = min(prompt `Autonomy:` header, work-type
   cap from the contract); missing header → `human-required`.
2. **`safe`** → skip the Plan-Mode hold: write both plan levels into the issue
   (step 5 below) and proceed straight through steps 4–7 and into
   `start_library`/`start_workspace` and implementation. The plan the human
   would have approved is on the issue for post-hoc validation.
3. **`supervised`** → the **ship checkpoint does not park**: it resolves to
   decide-and-flag ([`../../AUTONOMY.md`](../../AUTONOMY.md),
   "Decide-and-flag") — ship through the autonomous-ship gate, flag the
   decision in the PR body, and **end at PR-open** (merge stays human). Every
   *other* judgment gate — a scope/design fork the plan didn't settle, a second
   flagged decision, a hard blocker — still becomes a batched issue question
   with an `awaiting-input` park (the contract's "Checkpoint-and-continue"
   section: question → park → next independent step or task → resume from
   `active.md`); mechanical stretches proceed.
4. **`human-required`** → `--auto` changes nothing; today's flow.
5. If the human acknowledged a Heart YELLOW reason set at launch, record that
   exact list in the task's `active.md` entry (`- heart-ack:` block) — the
   ship gate's leg 4 reads it; it never extends to new reasons.

Everything downstream (`ship_*` under `--auto`) is gated by the four-leg
autonomous-ship gate and **ends at PR-open** — merge stays a human act.
Default runs without the flag are unchanged: present-and-wait.

Resolve paths once using [CONTEXT.md](../CONTEXT.md). Read only the reference
section required by the current step; a prior accepted plan remains approved.

## Flow

### 0. Sync + resume check (Mind)

```bash
source "${PYAUTO_MIND:-$(test -d organs/PyAutoMind && echo organs/PyAutoMind || echo PyAutoMind)}/scripts/prompt_sync.sh"
prompt_sync_new_prompts          # sweep up any new local prompt ideas (no-op if none)
```

Then scan `PyAutoMind/active.md`: if an entry already matches this prompt/task
(work begun in another session or environment), offer to **resume** it — read the
entry and continue from where it is — instead of starting fresh. `active.md` is
the shared task state, so no special handoff step is needed across environments.

### 1. Read the prompt

Normalize the argument (strip whitespace/backticks/angle-brackets; if it's a
markdown link `[label](path)`, take its target). Resolve Mind once. Accept a
Mind-relative path, or strip the resolved Mind root / its workspace-relative
prefix (`organs/PyAutoMind/` or `PyAutoMind/`) exactly once. Never prepend Mind
to an already resolved path. Read the resulting file inside that checkout. If missing, report and list prompts in that folder.

### 2. Route through the Feature Agent (Brain + Memory)

Hand the prompt to the Brain reasoning layer:

```bash
bin/pyauto-brain feature <work-type>/<target>/<task>.md
```

The Feature Agent classifies the work (using the work-type folder and the
prompt's `@RepoName` references), **consults PyAutoMemory** for scientific/
architectural context and prior art, estimates difficulty, decides whether to
phase, and emits a decision the rest of this skill consumes. If `pyauto-brain`
is unavailable (e.g. a GitHub-only session), emulate it inline per WORKFLOW.md:

- **Classify** by work type and target repos (library vs workspace — see
  WORKFLOW.md mapping). Library + workspace → start library, workspace follows.
- **Pull Memory context** for any non-trivial design decision before planning.
- **Explore** the referenced code briefly (classes, callers, existing tests) —
  enough for an informed plan, not an exhaustive audit.

For a non-feature work type with no dedicated agent yet (bug/refactor/docs/…),
apply the closest available reasoning and record the missing agent as a
follow-up; the skill still runs end-to-end.

### 3. Produce the plan

Two levels: a **high-level** plan (3–8 plain-English bullets, no code) and a
**detailed** plan (file paths, function/class names, changes per step, key
trade-offs, testing approach). The detailed plan must be good enough that a
fresh session could start from the issue alone.

### 4. Survey branches

Run the **branch survey** ([`reference.md`](reference.md) → "Branch survey")
for the affected repos: report each repo's branch + dirty state, check worktree
claims, suggest `feature/<task-name>` (kebab-case, <50 chars), and derive the
worktree root `~/Code/PyAutoLabs-wt/<task-name>/` (created later by
`/start_library`).

### 5. Create the issue via the Mind primitive

Generate a concise title (<70 chars, conventional prefix where apt), then
**delegate the issue write to `/create_issue`** (the PyAutoMind issue+registry
primitive) — pass it the classified primary repo, title, two-level plan, and
suggested branch. It assembles the body, creates the issue (after review), moves
the prompt to `active/`, and pushes Mind. Do **not** re-implement issue creation
here. Registration in `active.md` is conflict-dependent (next step), so tell
`/create_issue` to **skip its active.md registration** — start_dev owns that
routing decision.

### 6. Register in Mind + route

First resolve the current surface's capabilities (WORKFLOW.md).

**Local/worktree-capable surface:**

```bash
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
worktree_check_conflict <task-name> <repo1> [repo2 ...]
```

**GitHub-control-only surface (no clone/worktree):** do not skip the conflict
guard. Read the current `PyAutoMind/active.md` through GitHub and inspect every
other task's `repos:` bullets. Any target repo claimed by another active task
is the same hard conflict the local helper would report. If current Mind state
cannot be read, fail closed; never infer "no conflict" from missing local files.

- **No conflict, local:** register `status: library-dev | workspace-dev` and the
  real `worktree:` path.
- **No conflict, GitHub-control-only:** register the same status, real
  `session:` / `location:` metadata and repo branch claims, and record **no fake `worktree:` field**. A later execution environment resumes the same
  branch/commit.
- **Conflict:** register in `PyAutoMind/planned.md` (blocked) and tell the user
  what's holding the repo.

Registry-entry formats are in [`reference.md`](reference.md) → "Registry
entries". Then route: library → `/start_library`; workspace → `/start_workspace`;
both → `/start_library` first. Display the issue URL, primary repo, branch, and
classification.

### 7. Push Mind state

`/create_issue` already pushed the issue + `active/` move; push the routing
registration (active.md / planned.md) added in step 6:

```bash
source "${PYAUTO_MIND:-$(test -d organs/PyAutoMind && echo organs/PyAutoMind || echo PyAutoMind)}/scripts/prompt_sync.sh"
prompt_sync_push "prompt: route <task-name> (#<issue>) → <next-skill>"
```

## Notes

- Always present the issue body for review before creating it.
- Resolve GitHub operations through `GITHUB_ACCESS.md`. Only a shell-`gh`
  surface can meaningfully use `gh auth login`; a connected GitHub action
  surface has its own permissions and must never be repaired with an OpenAI API
  key or browser/session credential.
- Long-form detail (issue-body template, registry formats) is in
  [`reference.md`](reference.md).

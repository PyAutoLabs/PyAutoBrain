# Start Dev: Classify, Plan, Register

Universal entry point for starting development: read a **PyAutoMind** prompt,
route the reasoning through the **PyAutoBrain Feature Agent** (which consults
**PyAutoMemory**), create a tracked issue, register the task in Mind and hand
off to `/start_library` or `/start_workspace`. A workflow entry point, not an
agent — classification, planning and risk judgement belong to Brain. Read
[`../WORKFLOW.md`](../WORKFLOW.md) first (organ boundary, entry points,
execution environments, model delegation, Mind paths).

> No `gh` on a remote session — map each `gh` step via [`../GITHUB_ACCESS.md`](../GITHUB_ACCESS.md).

## Usage

```
/start_dev <prompt-file-path>          # path relative to PyAutoMind/
/start_dev <prompt-file-path> --auto   # autonomous mode per ../AUTONOMY.md
```

Prompts live under `draft/<work-type>/<target>/` (pre-migration
`<target>/<name>.md` still resolves), e.g.
`draft/bug/autofit/factor_graph_instance_iteration.md`. No prompt path → first
write one under `draft/<work-type>/<target>/` with the request verbatim (never
under `human_review/`); a `draft/human_review/…` path names shipped work —
offer the review instead ([`reference.md`](reference.md) → "Prompt-path edge
cases").

**`--auto`** applies only when the human launches with the flag (never
ambient): read [`reference.md`](reference.md) → "--auto mode" for the
effective-level rules (`safe` skips the plan hold; `supervised` decides-and-flags
at ship and parks other judgment gates; `human-required` changes nothing) and
the launch-time `heart-ack:` record. Without the flag: present-and-wait.

Resolve paths once using [CONTEXT.md](../CONTEXT.md). Read only the reference
section required by the current step; a prior accepted plan remains approved.

## Flow

### 0a. Heart at the door

Before anything else — before the resume check, before planning — run the
read-only helper (never a tick) and show its first line to the user:

```bash
python3 "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/heart_feed.py"
```

- **GREEN** (exit 0) → continue.
- **YELLOW / STALE** (exit 1) → print the reasons and continue; the YELLOW
  acknowledgement stays a ship-time act (`ship_*` step 3), unchanged.
- **RED** (exit 2) → **stop before planning**; quote every reason verbatim.
  The human may invoke [`../../AUTONOMY.md`](../../AUTONOMY.md)
  "Human override for Heart RED (development only)" to proceed — record it on
  the issue when invoked.
- **GREY / unreachable** (exit 3) → say so and continue.
- **`--auto` + RED** → park the run before any issue is opened.

### 0. Sync + resume check (Mind)

```bash
source "${PYAUTO_MIND:-$(test -d organs/PyAutoMind && echo organs/PyAutoMind || echo PyAutoMind)}/scripts/prompt_sync.sh"
prompt_sync_new_prompts          # sweep up any new local prompt ideas (no-op if none)
```

Then scan `PyAutoMind/active.md`: an entry matching this prompt (begun in
another session or environment) → offer to **resume** it from where it is;
`active.md` is the shared state, so no handoff step is needed.

### 1. Read the prompt

Normalize the argument (strip whitespace, backticks, angle brackets; a
markdown link → its target). Accept a Mind-relative path, or strip the resolved
Mind root / `organs/PyAutoMind/` / `PyAutoMind/` prefix exactly once — never
prepend Mind to a resolved path. Missing file → report and list that folder.

### 2. Route through the Feature Agent (Brain + Memory)

```bash
bin/pyauto-brain feature <work-type>/<target>/<task>.md
```

The Feature Agent classifies (work-type folder + `@RepoName` references),
**consults PyAutoMemory**, estimates difficulty, decides phasing and emits the
decision this skill consumes. Without `pyauto-brain` (e.g. GitHub-only),
emulate it inline per WORKFLOW.md: classify (library + workspace → library
first), pull Memory context for non-trivial design, explore the referenced code
just enough to plan; a work type with no agent uses the closest reasoning and
records the missing agent as a follow-up.

### 3. Produce the plan

Two levels: **high-level** (3–8 plain-English bullets, no code) and
**detailed** (file paths, functions/classes, changes per step, trade-offs,
testing) — enough for a fresh session to start from the issue alone. The
high-level plan ends with one **tier + merge mode** line from the prompt's
**declared** `Consequence:` (never sizing-inferred), per
[`../../AUTONOMY.md`](../../AUTONOMY.md) "Merge authority follows Consequence —
2026-10-02":

```
Tier: notify — merge mode: auto-merge on green (in-turn wait, then /prm close-out)
Tier: glance — merge mode: auto-merge on green if the Witness passes, post-merge summary
Tier: judge (or undeclared) — merge mode: human /prm
```

**Approving the plan authorizes that merge mode**; a plan without the line
authorizes no merge. An epic's approval chains auto-merged phases without
re-asking, stopping at a `judge` phase, a failure, Heart RED or unnamed scope.

### 4. Survey branches

Run the **branch survey** ([`reference.md`](reference.md) → "Branch survey"):
each repo's branch + dirty state, worktree claims, a suggested
`feature/<task-name>` (kebab-case, <50 chars) and the worktree root
`~/Code/PyAutoLabs-wt/<task-name>/` (created by `/start_library`).

### 5. Create the issue via the Mind primitive

Title <70 chars (conventional prefix where apt), then **delegate the issue
write to `/create_issue`** with the primary repo, title, two-level plan and
branch — it assembles the body, creates the issue after review, moves the
prompt to `active/` and pushes Mind. Never re-implement it; tell it to **skip
its active.md registration** (start_dev owns that routing decision).

### 6. Register in Mind + route

First resolve the current surface's capabilities (WORKFLOW.md).

**Local/worktree-capable surface:**

```bash
source "${PYAUTO_BRAIN:-$(test -d organs/PyAutoBrain && echo organs/PyAutoBrain || echo PyAutoBrain)}/bin/worktree.sh"
worktree_check_conflict <task-name> <repo1> [repo2 ...]
```

**GitHub-control-only surface (no clone/worktree):** never skip the conflict
guard — read the current `PyAutoMind/active.md` through GitHub; a target repo
under another active task's `repos:` is a hard conflict, and unreadable Mind
state fails closed.

- **No conflict:** register `status: library-dev | workspace-dev` with the real
  `worktree:` path (local), or real `session:` / `location:` metadata and repo
  branch claims and **no fake `worktree:` field** (GitHub-control-only; a later
  execution environment resumes the same branch/commit).
- **Conflict:** register in `PyAutoMind/planned.md` (blocked) and say what holds
  the repo.

Formats: [`reference.md`](reference.md) → "Registry entries". Route library →
`/start_library`, workspace → `/start_workspace`, both → library first; show
the issue URL, primary repo, branch and classification.

### 7. Push Mind state

Push the routing registration from step 6 (`/create_issue` pushed the rest):

```bash
source "${PYAUTO_MIND:-$(test -d organs/PyAutoMind && echo organs/PyAutoMind || echo PyAutoMind)}/scripts/prompt_sync.sh"
prompt_sync_push "prompt: route <task-name> (#<issue>) → <next-skill>" active.md
# planned.md instead of active.md when step 6 hit a conflict
```

The helper commits only the paths it is given (relative to the Mind root). It
refuses, committing nothing, when no paths are given, when anything else in the
tree has changed, when a changed file holds conflict markers, or when a changed
`state.json` does not parse. Another session's edits are left to that session.

## Notes

- Always present the issue body for review before creating it.
- A connected GitHub action surface has its own permissions: never repair it
  with an OpenAI API key or browser/session credential (`gh auth login` only on
  a shell-`gh` surface).

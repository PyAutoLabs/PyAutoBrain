# PyAutoBrain command surface — shared reference

The short verb commands (`/intake`, `/community`, `/feature`, `/build`, `/health`, `/bug`,
`/refactor`, `/workspace`, `/eyes`, `/profiling`, `/hygiene`, `/docs`, `/research`, `/route`, `/brain`) are a thin, human-friendly **veneer**
over the PyAutoBrain router (`bin/pyauto-brain`). This file is the shared context
every command file points at, so each command body stays a few lines long.

> **Users speak in short commands; PyAutoBrain performs the routing.**

## The Brain is implicit

You don't tell a brain to "activate the visual cortex" — you *look*, and it
routes. Same here: a user types a short verb (or plain natural language) and the
Brain routes it to the right specialist agent. **Normal usage never says
"PyAutoBrain".** The only explicit-Brain surface is `/brain`, the debug door.

## Never bypass the Brain

Every command routes **through** PyAutoBrain — either its CLI (`bin/pyauto-brain
<agent>`) or the `start_dev` workflow entry point, which itself routes reasoning
through the Brain Feature Agent. A command is a *shortcut into* the Brain, never a
*replacement for* it. No command file re-implements classification, planning, the
readiness gate, or execution — those belong to the organs.

## The three command tiers

**1. Real conductors** — route straight to an existing agent in
`agents/conductors/` (`AGENTS.md` is authoritative):

| Command | Agent | Chain |
|---------|-------|-------|
| `/intake` | Intake Agent | `bin/pyauto-brain intake` → files a PyAutoMind prompt (**before** `start_dev`); `census`/`dashboard` = backlog inventory / `PyAutoMind/dashboard.md` |
| `/community` | Community Agent | `bin/pyauto-brain community` → scan/triage user-filed issues (read-only surfaces) → session drafts replies for human approval → `/start_dev_for_user` |
| `/feature` | Feature Agent | `bin/pyauto-brain feature` → `start_dev` → `ship_*` |
| `/bug` | Bug Agent | `bin/pyauto-brain bug` → `start_dev` → `ship_*` (health mode → vitals + Heart issues) |
| `/refactor` | Refactor Agent | `bin/pyauto-brain refactor` → `start_dev [--auto]` → `ship_*` (behaviour-preserving; default-safe) |
| `/workspace` | Workspace Agent | `bin/pyauto-brain workspace` → WorkspaceDecision (plan/survey example authorship) → `start_dev` → `start_workspace` → `ship_workspace` |
| `/eyes` | Eyes Agent | `bin/pyauto-brain eyes` → survey/review a visualization workspace's figures; render via its `gallery_run.sh`; accepted critiques → `/intake` → `start_dev` |
| `/profiling` | Profiling Agent | `bin/pyauto-brain profiling` → campaign/ingest/triage plans over the autolens_profiling workspace |
| `/hygiene` | Hygiene Agent | `bin/pyauto-brain hygiene` → perf/tidy/noise/deps/docs/docstrings upkeep plans; delegates fixes to refactor/bug/feature |
| `/build` | Build Agent | `bin/pyauto-brain build` → vitals faculty → Heart → PyAutoHands |
| `/health` | Health Agent | `bin/pyauto-brain health` loop → vitals faculty → Heart → GREEN |

**2. Work-type entries** — no dedicated conductor exists **yet**, so these route
through the Brain dev-flow with their PyAutoMind work-type fixed. Still through
the Brain (via `start_dev` → Feature Agent), so nothing is bypassed:

| Command | PyAutoMind work-type |
|---------|----------------------|
| `/docs` | `docs/` |
| `/research` | `research/` |

(`/docs` remains the generic docs work-type entry; workspace/HowTo *example
authorship* specifically now has a real conductor — the Workspace Agent,
tier 1 above.)

(`/refactor` graduated to a real conductor — the Refactor Agent,
`agents/conductors/refactor/` — and now sits in tier 1 above.)

These are honest doors — they do **not** pretend an agent exists that doesn't,
and a dedicated conductor is added only on demonstrated need, never for
symmetry. The taxonomy they tag is `PyAutoMind/ROUTING.md`.

**3. Router + debug door:**

- **`/route <free text>`** — the natural-language door (the "look at this" path):
  infer the work-type from the request and dispatch to the matching command
  above. This is the primary interface; the verbs are typed shortcuts into it.
- **`/brain <agent> [args]`** — explicit, un-veneered passthrough to
  `bin/pyauto-brain` for debugging. Free-text `/brain` defers to `/route`.

**4. Composition doors** — orchestrate existing doors + workspace-ops scripts;
own no agent and re-implement no reasoning (all judgment defers to the doors they
call, so the Brain is not bypassed):

- **`/wake_up`** — **superseded by the Brain board** (the generated morning
  surface `board/_board.py` renders and `brain_board.yml` publishes to Pages:
  overnight sweep, readiness headline, version consistency, community scan,
  resume context, upkeep doors — each row a one-tap 📋 payload). The local leg
  is one terminal command, `bin/morning.sh` (sync via `bin/pull_all_main.sh` +
  clean via `bin/clean_slate.sh`). Invoked anyway, the skill runs that local
  leg and relays `pyauto-brain board`'s digest — the fallback for a stale or
  unreachable board. Auto-runs only the non-destructive steps; surfaces
  destructive cleanup for approval. Interactive/terminal only (the automated
  morning webhooks are separate).

- **`/prm`** — the wrap-up shortcut: *"PR, CI green, then merge"*. Watches a
  feature PR's checks until **every** workflow run and **every** matrix leg for
  the head sha is green, merges in library-first order, then hands back to the
  `ship_*` completion steps (Shipped comment, `lifecycle.py record`, cleanup).
  Three keystrokes for the sentence the human types at the end of nearly every
  task. Owns no gate of its own — it refuses on red/pending/conflicting and on an
  unmerged upstream library PR, and asks before closing the issue. Pure `gh`, so
  it runs on the CLI, mobile Claude Code chat and Codex alike.

**5. Maintenance doors** — periodic sweeps that reason about accumulated debris
and then execute their own cleanup after per-bucket human confirmation. They own
no agent, but unlike the composition doors they *mutate*, so each is
audit-first and confirmation-gated:

- **`/repo_cleanup`** — git debris across the canonical checkouts and worktrees:
  stale feature branches, `[gone]` tracking refs, stashes, dirty checkouts,
  orphan worktrees. Local-dev only (needs the checkouts). The Hygiene Agent's
  `tidy` mode is its front door; this skill is the executor.
- **`/issue_cleanup`** — the GitHub **issue trackers**: audit every open issue
  against the PyAutoMind completion records and merged PRs, bucket them
  (shipped / weak evidence / deliberately open / in flight / external /
  unreconciled), close only what a human confirms. Runs anywhere `gh` is
  authenticated, including mobile/Codex. Closing needs **two independent
  evidence legs**, and the record header *key* decides meaning — `issue:`
  completes, `followup-issue:` / `parent-issue:` / `plan:` mean the record
  *spawned* a still-open issue. The Brain board surfaces the open-issue count
  and points here; the audit itself stays this door's job.

These two are complements, not overlaps: `/repo_cleanup` never touches issues,
`/issue_cleanup` never touches git. Neither handles **external** users' issues —
that is `/community`, whose drafts stay human-approved.

Codex skills also expose the remaining public CLI agents directly: the `clone`
conductor, the `release` conductor, and the read-only `vitals`, `review`,
`memory`, and `samplers` faculties. They do not gain new
slash commands; `brain` remains Claude's low-level passthrough.

## How these are installed

Each command directory keeps `<verb>.md` as its canonical command body and may
add a thin `SKILL.md` discovery wrapper. `bin/install.sh` treats the two files
independently: it installs the command into `~/.claude/commands/` and the skill
into both `~/.claude/skills/` and `~/.codex/skills/` (using the skill's
hyphenated frontmatter name for Codex). This file (`COMMANDS.md`)
sits at the `skills/` root, so the directory scan skips it; it is reference-only.
Keep wrappers and command bodies short and keep shared architecture prose here
(guarded by `bin/check_skill_line_counts.sh`).

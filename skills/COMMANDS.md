# PyAutoBrain command surface — shared reference

The short verb commands (`/intake`, `/feature`, `/build`, `/health`, `/bug`,
`/refactor`, `/profiling`, `/hygiene`, `/docs`, `/research`, `/route`, `/brain`) are a thin, human-friendly **veneer**
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
| `/feature` | Feature Agent | `bin/pyauto-brain feature` → `start_dev` → `ship_*` |
| `/bug` | Bug Agent | `bin/pyauto-brain bug` → `start_dev` → `ship_*` (health mode → vitals + Heart issues) |
| `/refactor` | Refactor Agent | `bin/pyauto-brain refactor` → `start_dev [--auto]` → `ship_*` (behaviour-preserving; default-safe) |
| `/profiling` | Profiling Agent | `bin/pyauto-brain profiling` → campaign/ingest/triage plans over the autolens_profiling workspace |
| `/hygiene` | Hygiene Agent | `bin/pyauto-brain hygiene` → perf/tidy/noise/deps/docs upkeep plans; delegates fixes to refactor/bug/feature (modes staged) |
| `/build` | Build Agent | `bin/pyauto-brain build` → vitals faculty → Heart → PyAutoBuild |
| `/health` | Health Agent | `bin/pyauto-brain health` loop → vitals faculty → Heart → GREEN |

**2. Work-type entries** — no dedicated conductor exists **yet**, so these route
through the Brain dev-flow with their PyAutoMind work-type fixed. Still through
the Brain (via `start_dev` → Feature Agent), so nothing is bypassed:

| Command | PyAutoMind work-type |
|---------|----------------------|
| `/docs` | `docs/` |
| `/research` | `research/` |

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

- **`/morning`** — start-of-day routine. **Local:** sync every repo to main
  (`bin/pull_all_main.sh`) → clean generated cruft, restoring shipped datasets
  (`bin/clean_slate.sh`) → consult **`/health`** + **`/hygiene`**. **Everywhere
  (gh-API, so it runs on mobile Claude Code chat / Codex too):** an overnight
  scheduled-run sweep (`bin/overnight_status.sh`), a version-pin drift check
  (`bin/version_drift.sh`), and resume-context (in-flight work + pending-release
  PRs) → one prioritized digest. Auto-runs only the non-destructive steps;
  surfaces destructive cleanup for approval; on mobile/codex it skips the
  local-only steps. Interactive/terminal only (the automated morning webhooks are
  separate).

Codex skills also expose the remaining public CLI agents directly: the
analysis-only `clone` conductor, the `release` conductor, and the read-only
`vitals`, `review`, `memory`, and `samplers` faculties. They do not gain new
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

# PyAutoBrain command surface — shared reference

The short verb commands (`/feature`, `/build`, `/health`, `/bug`, `/refactor`,
`/docs`, `/research`, `/route`, `/brain`) are a thin, human-friendly **veneer**
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
| `/feature` | Feature Agent | `bin/pyauto-brain feature` → `start_dev` → `ship_*` |
| `/build` | Build Agent | `bin/pyauto-brain build` → vitals faculty → Heart → PyAutoBuild |
| `/health` | Health Agent | `bin/pyauto-brain health` loop → vitals faculty → Heart → GREEN |

**2. Work-type entries** — no dedicated conductor exists **yet**, so these route
through the Brain dev-flow with their PyAutoMind work-type fixed. Still through
the Brain (via `start_dev` → Feature Agent), so nothing is bypassed:

| Command | PyAutoMind work-type | Promotion follow-up |
|---------|----------------------|---------------------|
| `/bug` | `bug/` | dedicated Bug conductor |
| `/refactor` | `refactor/` | dedicated Refactor conductor |
| `/docs` | `docs/` | dedicated Documentation conductor |
| `/research` | `research/` | dedicated Research conductor |

These are honest interim doors — they do **not** pretend an agent exists that
doesn't. The taxonomy they tag is `PyAutoMind/ROUTING.md`.

**3. Router + debug door:**

- **`/route <free text>`** — the natural-language door (the "look at this" path):
  infer the work-type from the request and dispatch to the matching command
  above. This is the primary interface; the verbs are typed shortcuts into it.
- **`/brain <agent> [args]`** — explicit, un-veneered passthrough to
  `bin/pyauto-brain` for debugging. Free-text `/brain` defers to `/route`.

## How these are installed

Each command is a directory `skills/<verb>/` containing only `<verb>.md` (no
`SKILL.md`). `bin/install.sh` turns that into a flat `~/.claude/commands/<verb>.md`
symlink — a typed slash command, not an auto-triggered skill. This file
(`COMMANDS.md`) sits at the `skills/` root, so the installer's directory scan
skips it: it is reference-only. Keep command bodies short and this file the single
place architecture prose lives (guarded by `bin/check_skill_line_counts.sh`).

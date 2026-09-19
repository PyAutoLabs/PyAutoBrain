# Agent architecture and command reference

Read when designing agents or changing command wiring, not at session startup.

## What this repo is

PyAutoBrain is the **reasoning layer** of the PyAuto ecosystem as it grows into a
software organism. It figures out *how* work should be done and coordinates the
organs that do it. It hosts specialist **reasoning agents** — each a documented
role plus a deterministic entrypoint script — that read intent (from PyAutoMind
and the developer), reason about it, and drive the health/execution machinery at
the right points.

PyAutoBrain owns **no state, no health checks, and no execution mechanics**. It
only *reasons* and *delegates*: it asks PyAutoHeart whether the organism is
healthy, decides whether and how to proceed, and tells PyAutoHands to execute
when it should.

## The organism

The organs, their boundaries, and the `Brain → Heart (gate) → Build (execute)`
call chain are defined **once** in [`ORGANISM.md`](../ORGANISM.md) — this repo
hosts that canonical page; every other organ links to it. In one line: the
Mind decides *what*, the Brain (this repo) figures out *how*, the Heart gates,
the Hands build, Memory knows what the science says.

## Brain agents consult one another (a society of agents)

Brain agents are not limited to driving organs — they can **consult each other**.
The canonical example is the **Build Agent**, which does not query Heart directly:
it consults the **vitals faculty**, and only the vitals faculty talks to the Heart
organ. So the Build Agent's full chain is:

```
Mind  →  Build Agent  →  vitals faculty  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

The consult graph is a DAG (see [`ORGANISM.md`](../ORGANISM.md)): conductors
consult faculties; faculties read their sensor organ; a conductor never
consults another conductor — if it wants one's opinion, that opinion should be
a faculty. The Build Agent is the reusable template for this pattern.

How much human checkpointing a workflow run needs is defined once in
[`AUTONOMY.md`](../AUTONOMY.md) — the autonomy contract mapping each Mind-prompt
`Autonomy:` level to behaviour at every checkpoint.

## Specialist reasoning agents

Agents live in **two tiers** under `agents/`, distinguished by one question —
*does it act, or only opine?*

- **Conductors** (`agents/conductors/<name>/`) — front-door agents a human
  **drives**. They *decide **and** act*, delegating execution to the organs.
  They have side effects in the world (a plan driven into dev, a build, a
  release). This is the small, curated set of things you invoke and converse
  with.
- **Faculties** (`agents/faculties/<name>/`) — read-only reasoning capabilities
  the conductors **consult**. They *only opine* — return a judgment and stop;
  they never dispatch or mutate. They are *sinks* in the consult graph
  (everything reaches into them; they reach out only to their sensor organ). Not
  chat-first surfaces, though they stay runnable for a quick read.

The rule of thumb: **keep the conductor set small and human-meaningful; let
faculties multiply behind them.** A side-effecting decider is a conductor; a
side-effect-free opinion is a faculty.

Each agent is a directory with an `AGENTS.md` (what it reasons about + how to run
it) and a deterministic entrypoint script (`*.sh` / `*.py`) — the part CI and
humans invoke identically, so behaviour isn't re-derived from prose each time.

New agents are added on **demonstrated need, never for symmetry**. Place by
tier: a side-effecting decider you drive → `agents/conductors/<name>/`; a
read-only opinion the conductors consult → `agents/faculties/<name>/`. Follow
the Build Agent's shape (a concise `AGENTS.md` opening with its `Tier:` line, a
deterministic entrypoint, and a capability audit of any organ it drives — the
Feature Agent's `MIND_TAXONOMY.md` is that audit for the PyAutoMind/PyAutoMemory
surface). Keep the conductor set small; prefer a faculty when the new thing
only reasons.

**Scaling invariant.** The per-agent roster is not maintained here. Adding an
agent touches only `bin/pyauto-brain` (the registry) and the agent's own
directory (`agents/<tier>/<name>/` with its `AGENTS.md` + entrypoint). The verb
tables below are **generated** from that registry by
`bin/install.sh --write-agents-surface` — never hand-edit this file's roster,
and read each agent's own `AGENTS.md` for its full role.


## The command surface (Brain implicit)

The verb table in [AGENTS.md](../AGENTS.md) is the machinery; humans drive it through short commands
(`/intake`, `/feature`, …) in Claude Code, or discoverable skills in Claude and
Codex. The Brain stays **implicit** — you type a verb, or plain natural language
via `/route`, and it routes to the right agent; normal usage never says
"PyAutoBrain". A few commands are compositions rather than single agents:
`/docs` and `/research` route through the dev-flow with their PyAutoMind
work-type fixed (no dedicated conductor — added only on demonstrated need, never
for symmetry); `/prm` composes the
end-of-task close-out (CI green → merge → issue closed → Mind `active/` →
`complete/` → dashboard reconciled and regenerated → worktree and local branches
removed); `/brain
<agent>` is the raw passthrough. Every command routes **through** the Brain;
none replaces it.

The morning routine is not a command at all: the **Brain board**
(`board/_board.py`, published to the Brain's GitHub Pages URL each morning by
`brain_board.yml`) carries what `/wake_up` used to assemble — overnight runs,
readiness, community, resume, upkeep — as one-tap 📋 payloads, and
`bin/morning.sh` is the local sync/clean leg you run in a terminal.
`/wake_up` remains only as the fallback door when the board is unreachable.

The command bodies live in `skills/<verb>/<verb>.md`; thin `SKILL.md` wrappers
make the same canonical workflows discoverable to skill-aware harnesses.
`bin/install.sh` installs both surfaces without duplicating their bodies. Shared
architecture prose is in [`skills/COMMANDS.md`](../skills/COMMANDS.md); the
work-type taxonomy the router uses is `PyAutoMind/ROUTING.md`.

## Chat register: concise by default

The default register for **chat replies** is concise — every harness and every
session (Claude Code CLI, web, mobile; Codex; Cursor). A reply is the smallest
thing that answers the question and says what changed. It is not a report on the
work.

- **Answer first.** Lead with the answer, the verdict, or what you did. No
  preamble, no restatement of the request, no summary of the summary.
- **A few lines is the default length.** One line is a good answer. Prose
  paragraphs, file-by-file inventories and "what I did / why / next steps"
  scaffolding are opt-in, not the baseline.
- **Don't narrate the work.** Skip the tool-by-tool commentary, the list of
  files read, and any recap of a diff the human can read on the branch or PR.
- **Link, don't paste.** Point at the file, the issue, the PR, the prompt under
  `PyAutoMind/draft/`; quote only the lines being discussed.

Four things are never compressed: a **plan awaiting approval**, a **decision
surface** a human must judge, a **failure or blocker** (say exactly what broke
and where), and anything the human **asked to have explained**. Brevity is not a
licence to drop the detail a decision needs.

The escape hatch is a word — "expand", "in full", "explain" — and it applies to
that reply, not the session; the register comes back on the next turn.

Agent output is not chat and keeps its defined shape: a `*Decision`, a
`ReviewSurface`, a vitals verdict, the board digest are structured artefacts
this register does not trim. It governs the prose around them. On Claude Code
the same default can also be pinned per-tool with an output style, but the
register above is the portable one — it travels with the repo to every harness.

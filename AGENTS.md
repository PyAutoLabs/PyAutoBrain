# PyAutoBrain — Agent Guidance

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.) and humans
discovering this repository. It is the canonical description of PyAutoBrain — the
**reasoning layer** of the PyAuto organism — and of the Brain / Heart / Build
boundary; PyAutoBuild and PyAutoHeart point back here.

## What this repo is

PyAutoBrain is the **reasoning layer** of the PyAuto ecosystem as it grows into a
software organism. It figures out *how* work should be done and coordinates the
organs that do it. It hosts specialist **reasoning agents** — each a documented
role plus a deterministic entrypoint script — that read intent (from PyAutoMind
and the developer), reason about it, and drive the health/execution machinery at
the right points.

PyAutoBrain owns **no state, no health checks, and no execution mechanics**. It
only *reasons* and *delegates*: it asks PyAutoHeart whether the organism is
healthy, decides whether and how to proceed, and tells PyAutoBuild to execute
when it should.

## The organism

The PyAuto ecosystem is structured as a software organism. Each repo is an
organ with one job:

| Organ | Repo | Role |
|-------|------|------|
| **Mind** | PyAutoMind | Decides *what* should be done — intent, goals, priorities, future work. |
| **Brain** | **PyAutoBrain** (this repo) | Figures out *how* — reasoning, planning, decomposition, orchestration, agent coordination, decision-making. |
| **Hands** | PyAutoBuild | Builds and releases the software — packaging, tagging, notebooks, PyPI. (May later be renamed PyAutoHands.) |
| **Heart** | PyAutoHeart | Determines whether the organism is healthy — the authoritative readiness verdict. |
| **Memory** | PyAutoMemory | Long-term scientific, software and project knowledge. |

The clean boundary, in one line each:

- **Mind** → decides what should be done.
- **Brain** → figures out how.
- **Hands** → build and release the software.
- **Heart** → determines whether the organism is healthy.

PyAutoBrain does not build or release software (that belongs to the Hands /
PyAutoBuild) and does not measure health (that belongs to the Heart /
PyAutoHeart). The Brain determines *how* work should be done; the Hands build
and release it; the Heart says whether it is safe to.

## The boundary (one description, mirrored across the organs)

- **PyAutoHeart — the health authority.** All health/readiness logic lives here:
  version drift, install-path, URL hygiene, CI/worktree/timing monitoring.
  `pyauto-heart readiness` is the **authoritative** green/yellow/red verdict —
  the single "is it safe to release?" gate. Heart is an observer: it reads and
  emits verdicts; it never writes into other repos and never triggers Build.
- **PyAutoBuild — the executor (Hands).** Packaging, tagging, notebook
  generation, and PyPI publication via `release.yml`. Build runs **no** readiness
  checks of its own and never re-derives a gate decision; it just executes.
- **PyAutoBrain — the reasoning layer.** Hosts the specialist agents that connect
  the organs. It owns no checks and no execution steps; it reasons over Heart's
  verdict and delegates execution to Build.

## The call chain (always this order)

```
Brain  →  Heart (gate)  →  Build (execute)
```

The Brain asks `pyauto-heart readiness --json`, reasons over the result, and only
on a **green** verdict triggers Build's release. Heart never triggers Build;
Build never re-derives a decision the Brain already made.

## Brain agents consult one another (a society of agents)

Brain agents are not limited to driving organs — they can **consult each other**.
The canonical example is the **Build Agent**, which does not query Heart directly:
it consults the **vitals faculty**, and only the vitals faculty talks to the Heart
organ. So the Build Agent's full chain is:

```
Mind  →  Build Agent  →  vitals faculty  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

This generalises: a future Feature Agent can ask the vitals faculty whether the
tree is fit for a refactor; a future Release Agent can ask the Build Agent to
package a release. Reasoning lives in Brain agents that consult one another; the
organs (Heart, Hands/Build, Memory) provide capabilities and state. The Build
Agent is the reusable template for this pattern.

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

### Conductors

- **`agents/conductors/intake/`** — the **conceptive function**: turns raw input
  (a text-vomit idea, a bug report, an `ideas.md` bullet) into a *formal, grouped,
  headed* PyAutoMind prompt under `<work-type>/<target>/<name>.md`. Classifies the
  work-type, resolves the target (incl. the organism repos), consults the sizing
  faculty for difficulty and **persists** it (plus autonomy/priority) into the
  prompt header, and emits an `IntakeDecision`. It *files* a prompt; it never
  starts dev — the step *before* `create_issue`/`start_dev`. Lifecycle:
  **Conception → Growth**. It reasons + writes a Mind prompt (under `--apply`); it
  never edits source. (Organism-facing name: *Conception Agent*.)
- **`agents/conductors/feature/`** — the **growth function**: reasons over
  PyAutoMind `feature/*` intent and decides *how the organism should grow*.
  Selects the next feature task (or plans a named one), estimates difficulty,
  decides whether to phase, consults PyAutoMemory for scientific/architectural
  context and (for risky work) the vitals faculty, and emits a `FeatureDecision`
  that the existing `start_dev → ship_library/ship_workspace` workflow consumes.
  It reasons; it never edits source. (Organism-facing name: *Growth Agent*.)
- **`agents/conductors/bug/`** — the organism's **immune system**: recognises a
  pathogen (bug, regression, failing test or PyAutoHeart finding), tells it from
  benign self, classifies it (severity/scope/type/confidence), consults PyAutoMemory
  as immune memory, and mounts a *targeted* response — deciding **where the fix
  belongs** (source-first; never degrading a user-facing workspace script, the
  autoimmune failure mode) and emitting a `BugDecision` the `start_dev → ship_*`
  workflow consumes. Health mode reads two inputs: the live vitals verdict **and**
  the filed PyAutoHeart issues. Reuses the Feature Agent's core; consults the vitals
  faculty, never Heart directly. It reasons; it never edits source. (Organism-facing
  name: *Immune Agent*.)
- **`agents/conductors/build/`** — the executive function for execution work.
  Consults the vitals faculty, reasons over the verdict, and on a healthy result
  delegates to the appropriate PyAutoBuild capability. The canonical example of
  the Brain coordinating *multiple* organs. Has `build` / `deploy` / `release`
  modes — release is isolated as a mode now, with a clean seam to the release
  conductor.
- **`agents/conductors/release/`** — reasons over `pyauto-heart readiness`, and on
  green triggers the PyAutoBuild release executor (`autobuild pre_build` →
  `release.yml`); also orchestrates release validation (`release rehearse` /
  `release validate`) across the MCP boundary.
- **`agents/conductors/health/`** — the organism's **clinician**: runs the health
  *loop* with a human — assess → triage → (on your go-ahead) dispatch a
  validation leg → re-judge — until Heart goes GREEN. Consults the vitals faculty
  for every verdict and delegates all dispatch to the release conductor; it drives
  the loop, not the wire. Named for what it manages (the organism's *health*), not
  an external visitor. Current scope is *validation + recommend*, checkpointing
  every dispatch; *edit-in fixes* are an explicit follow-up. (Skeleton.)

### Faculties

- **`agents/faculties/vitals/`** — the read-only **vitals faculty** (it *reads the
  Heart's pulse*): adopts the PyAutoHeart readiness verdict and explains it,
  mapping each reason to its capability. It is the single component that talks to
  Heart; the conductors (build, release, feature, health) all consult it rather
  than querying Heart directly. It never dispatches or mutates — that inertness is
  why it is safe for everyone to call.

> **Build Agent vs. release mode vs. the release agent.** The Build Agent owns
> all execution orchestration and keeps release as one of its modes (broad build
> scope: generate, run, aggregate, package, tag). `agents/conductors/release/` is the older,
> narrower readiness→`pre_build` driver. The mature architecture splits a
> dedicated **Release Agent** out of the Build Agent's release mode — making
> release-specific decisions (versioning, changelogs, PyPI/tags, human approval),
> consulting the vitals faculty *more strictly*, then requesting execution from the
> Build Agent / PyAutoBuild. Until then: one agent now, clean seam for two later.

More specialist agents are expected over time (Refactor / Documentation / Research
agents, a `diagnosis` faculty split from the Bug Agent, cost/risk faculties, …).
When adding one, **place it by tier**:
a side-effecting decider you drive → `agents/conductors/<name>/`; a read-only
opinion the conductors consult → `agents/faculties/<name>/`. Follow the Build
Agent's shape (a concise `AGENTS.md` opening with its `Tier:` line, a
deterministic entrypoint, and a capability audit of any organ it drives — the
Feature Agent's `MIND_TAXONOMY.md` is that audit for the PyAutoMind/PyAutoMemory
surface). Keep the conductor set small; prefer adding a faculty when the new
thing only reasons.

## Running

```bash
bin/pyauto-brain help            # list agents
bin/pyauto-brain intake "add data cube modelling to autolens"  # conceive: raw text -> a formal Mind prompt (dry-run)
bin/pyauto-brain intake --apply ideas             # sweep ideas.md into formal prompts
bin/pyauto-brain feature         # select the best next PyAutoMind feature task
bin/pyauto-brain feature feature/autofit/sbi.md   # plan a specific feature task
bin/pyauto-brain build           # consult vitals, then delegate execution to Build
bin/pyauto-brain build --dry-run # reason + plan only (emit the BuildDecision)
bin/pyauto-brain release         # reason about readiness, then release on green
bin/pyauto-brain health          # (conductor) run the health loop with a human, toward green
bin/pyauto-brain vitals          # (faculty) one tick + the unified dashboard card (raw read)
```

Like the other PyAuto repos, PyAutoBrain runs from its checkout (no pip install);
it resolves the sibling `pyauto-heart` and `autobuild` binaries from PATH or the
`~/Code/PyAutoLabs/` checkouts.

## The command surface (Brain implicit)

The `bin/pyauto-brain <agent>` CLI above is the machinery; humans drive it through
short verb commands installed into `~/.claude/commands/`. The Brain stays
**implicit** — you type a verb (or plain natural language) and the Brain routes it
to the right agent; normal usage never says "PyAutoBrain".

> **Users speak in short commands; PyAutoBrain performs the routing.**

| Command | Routes to | Tier |
|---------|-----------|------|
| `/intake` | Intake Agent → files a PyAutoMind prompt (before `start_dev`) | real conductor |
| `/feature` | Feature Agent → `start_dev` | real conductor |
| `/bug` | Bug Agent → `start_dev` (health mode → vitals + Heart issues) | real conductor |
| `/build` | Build Agent → vitals → Heart → PyAutoBuild | real conductor |
| `/health` | Health Agent loop → vitals → Heart | real conductor |
| `/refactor` `/docs` `/research` | `start_dev` pre-tagged with the work-type | work-type entry* |
| `/route <text>` | infers the work-type and dispatches to one of the above | NL router |
| `/brain <agent>` | raw `bin/pyauto-brain` passthrough | debug door |

\* No dedicated Refactor/Docs/Research conductor exists yet — those verbs route
through the Brain dev-flow with their PyAutoMind work-type fixed (still through the
Brain, nothing bypassed), until each earns promotion to its own conductor (as `/bug`
now has). Every command routes **through** the Brain; none replaces it.

The command bodies live in `skills/<verb>/<verb>.md` (thin; installed as flat
commands by `bin/install.sh`); the shared architecture prose is in
[`skills/COMMANDS.md`](skills/COMMANDS.md). The work-type taxonomy the router and
work-type entries use is `PyAutoMind/ROUTING.md`.

## Never rewrite history

NEVER perform these operations on any repo with a remote:

- `git init` in a directory already tracked by git
- `rm -rf .git && git init`
- Commit with subject "Initial commit", "Fresh start", "Start fresh",
  "Reset for AI workflow", or any equivalent message on a branch with a remote
- `git push --force` to `main`
- `git filter-repo` / `git filter-branch` on shared branches
- `git rebase -i` rewriting commits already pushed to a shared branch

If the working tree needs a clean state, the **only** correct sequence is:

    git fetch origin
    git reset --hard origin/main
    git clean -fd

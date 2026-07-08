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

The organs, their boundaries, and the `Brain → Heart (gate) → Build (execute)`
call chain are defined **once** in [`ORGANISM.md`](ORGANISM.md) — this repo
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

The consult graph is a DAG (see [`ORGANISM.md`](ORGANISM.md)): conductors
consult faculties; faculties read their sensor organ; a conductor never
consults another conductor — if it wants one's opinion, that opinion should be
a faculty. The Build Agent is the reusable template for this pattern.

How much human checkpointing a workflow run needs is defined once in
[`AUTONOMY.md`](AUTONOMY.md) — the autonomy contract mapping each Mind-prompt
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

### Conductors

- **`agents/conductors/intake/`** — the *Conception Agent*: turns raw input
  (an idea, a bug report, an `ideas.md` bullet) into a formal PyAutoMind prompt
  under `<work-type>/<target>/<name>.md` — classifies the work-type, resolves
  the target, consults the sizing faculty and persists Difficulty/Autonomy/
  Priority into the header, and emits an `IntakeDecision`. Files a prompt only;
  never starts dev (the step *before* `create_issue`/`start_dev`).
- **`agents/conductors/feature/`** — the *Growth Agent*: selects the next
  PyAutoMind `feature/*` task (or plans a named one), estimates difficulty,
  decides phasing, consults PyAutoMemory (and vitals for risky work), and emits
  a `FeatureDecision` the `start_dev → ship_*` workflow consumes. Reasons only;
  never edits source.
- **`agents/conductors/bug/`** — the *Immune Agent*: classifies a bug,
  regression, failing test or PyAutoHeart finding (severity/scope/type/
  confidence), consults PyAutoMemory for recurring cases, decides **where the
  fix belongs** (source-first; never degrade a user-facing workspace script),
  and emits a `BugDecision` for `start_dev → ship_*`. Health mode reads the
  live vitals verdict plus the filed Heart issues. Reuses the Feature Agent's
  core; consults vitals, never Heart directly.
- **`agents/conductors/refactor/`** — the *Renewal Agent*: plans
  **behaviour-preserving** restructuring from `refactor/*` intent and emits a
  `RefactorDecision` — invariant + witnessing test suites, a public-API guard
  (suspect prompts re-route to `feature/`, never run at `safe`), and a
  `candidates` miner over the backlog + `ideas.md` (files nothing; intake
  formalises). The first conductor whose normal `--auto` mode is **`safe`**
  (the `refactor` work-type cap in [`AUTONOMY.md`](AUTONOMY.md)). Reuses the
  Feature Agent's core by import.
- **`agents/conductors/build/`** — the executive function for execution work.
  Consults the vitals faculty, reasons over the verdict, and on a healthy result
  delegates to the appropriate PyAutoBuild capability. The canonical example of
  the Brain coordinating *multiple* organs. Has `build` / `deploy` / `release`
  modes — release is isolated as a mode now, with a clean seam to the release
  conductor.
- **`agents/conductors/release/`** — the release door and release-validation
  orchestrator: `release rehearse` / `release validate` drive the TestPyPI
  rehearsal and the full Stages 0–3 validation; plain `release` delegates the
  readiness gate and execution to the Build Agent's release mode (one gate
  implementation, not two).
- **`agents/conductors/health/`** — the *clinician*: runs the health loop with
  a human — assess (vitals) → triage → (on your go-ahead) dispatch a validation
  leg → re-judge — until Heart goes GREEN. Delegates all dispatch to the
  release conductor. Current scope is *validate + recommend*, checkpointing
  every dispatch; edit-in fixes are an explicit follow-up. (Skeleton.)

### Faculties

- **`agents/faculties/vitals/`** — *reads the Heart's pulse*: adopts the
  PyAutoHeart readiness verdict and explains it, mapping each reason to its
  capability. The single component that talks to Heart; every conductor
  consults it rather than querying Heart directly. Never dispatches or mutates.
- **`agents/faculties/review/`** — *reviews the change*: prepares a feature
  branch's ReviewSurface (diff, commits, risk flags) and defines the procedure
  by which the reviewing agent maps it to a **CLEAN / FINDINGS / BLOCKED**
  verdict — the automatic-review leg of the autonomous-ship gate
  ([`AUTONOMY.md`](AUTONOMY.md)). Dev-workflow ship only: it never opines on
  release readiness (Heart's, via vitals) and never fixes what it finds.
- **`agents/faculties/memory/`** — *recalls what the organism knows*: given a
  topic, returns a **cited digest** (ranked pages + snippets) over
  PyAutoMemory's sub-wikis, `autolens_assistant`'s skills/wiki, and Mind's
  `complete.md` history. Grep-ranked at query time — no indexes, no layout
  coupling, never a page dump; an empty digest is the honest answer. Privacy
  seam: PyAutoMemory citations never reach public user-facing output.

> **Build Agent vs. the release conductor — resolved.** The Build Agent's
> release mode owns the **single** readiness-gate + execution path
> (`build.sh --mode release` → `pre_build`). The release conductor owns
> release-*validation* orchestration (`rehearse` / `validate`) and, for plain
> releases, is a door that delegates through that mode. There is deliberately
> no second gate implementation.

New agents are added on **demonstrated need, never for symmetry**. Place by
tier: a side-effecting decider you drive → `agents/conductors/<name>/`; a
read-only opinion the conductors consult → `agents/faculties/<name>/`. Follow
the Build Agent's shape (a concise `AGENTS.md` opening with its `Tier:` line, a
deterministic entrypoint, and a capability audit of any organ it drives — the
Feature Agent's `MIND_TAXONOMY.md` is that audit for the PyAutoMind/PyAutoMemory
surface). Keep the conductor set small; prefer a faculty when the new thing
only reasons.

## Running

```bash
bin/pyauto-brain help            # list agents
bin/pyauto-brain intake "add data cube modelling to autolens"  # conceive: raw text -> a formal Mind prompt (dry-run)
bin/pyauto-brain intake --apply ideas             # sweep ideas.md into formal prompts
bin/pyauto-brain feature         # select the best next PyAutoMind feature task
bin/pyauto-brain feature feature/autofit/sbi.md   # plan a specific feature task
bin/pyauto-brain refactor        # select + plan the best next behaviour-preserving refactor
bin/pyauto-brain refactor candidates              # mine the refactor backlog + ideas.md (read-only)
bin/pyauto-brain build           # consult vitals, then delegate execution to Build
bin/pyauto-brain build --dry-run # reason + plan only (emit the BuildDecision)
bin/pyauto-brain release         # reason about readiness, then release on green
bin/pyauto-brain health          # (conductor) run the health loop with a human, toward green
bin/pyauto-brain vitals          # (faculty) one tick + the unified dashboard card (raw read)
bin/pyauto-brain review --task <name>   # (faculty) a branch's ReviewSurface for the ship gate's review leg
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
| `/refactor` | Refactor Agent → `start_dev [--auto]` (default-safe) | real conductor |
| `/docs` `/research` | `start_dev` pre-tagged with the work-type | work-type entry* |
| `/route <text>` | infers the work-type and dispatches to one of the above | NL router |
| `/brain <agent>` | raw `bin/pyauto-brain` passthrough | debug door |

\* No dedicated Docs/Research conductor exists — those verbs route through the
Brain dev-flow with their PyAutoMind work-type fixed (still through the Brain,
nothing bypassed). A dedicated conductor is added only on demonstrated need,
never for symmetry — the Refactor Agent earned its promotion via the `ideas.md`
backlog bullet, the skill's own recorded follow-up, and the autonomy series.
Every command routes **through** the Brain; none replaces it.

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

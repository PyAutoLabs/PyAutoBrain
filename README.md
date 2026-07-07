# PyAutoBrain

The **reasoning layer** of the PyAuto organism. PyAutoBrain figures out *how*
work should be done: it hosts specialist **reasoning agents** that reason over
the health verdict from [PyAutoHeart](https://github.com/PyAutoLabs/PyAutoHeart)
and delegate execution to [PyAutoBuild](https://github.com/PyAutoLabs/PyAutoBuild).

It owns no state, no health checks, and no release mechanics — it only reasons
and delegates.

## The organism

The PyAuto ecosystem is a software organism; each repo is an organ with one job:

| Organ | Repo | Role |
|-------|------|------|
| **Mind** | PyAutoMind | Decides *what* should be done — intent, goals, priorities. |
| **Brain** | **PyAutoBrain** | Figures out *how* — reasoning, planning, orchestration. |
| **Hands** | PyAutoBuild | Builds and releases the software — packaging, tagging, notebooks, PyPI. |
| **Heart** | PyAutoHeart | Determines whether the organism is healthy. |
| **Memory** | PyAutoMemory | Long-term scientific / software / project knowledge. |

In one line each: **Mind** decides what, **Brain** figures out how, **Hands**
build and release the software, **Heart** says whether it is healthy.

## The split

| Repo | Role |
|------|------|
| **PyAutoHeart** | Health authority. `pyauto-heart readiness` is the authoritative green/yellow/red release gate. Observer-only. |
| **PyAutoBuild** | Executor (Hands). Packaging, tagging, notebooks, PyPI via `release.yml`. No checks. |
| **PyAutoBrain** | Reasoning layer. Reasons over Heart's verdict, delegates execution to Build. |

Call chain, always in this order:

```
Brain  →  Heart (gate)  →  Build (execute)
```

## Specialist reasoning agents

Agents live in **two tiers** under `agents/`, split by one question — *does it
act, or only opine?* **Conductors** (`agents/conductors/`) are front doors you
drive: they decide *and* act, delegating execution to the organs. **Faculties**
(`agents/faculties/`) are read-only reasoning capabilities the conductors
consult: they only return a judgment and stop. Keep the conductor set small; let
faculties multiply behind them.

**Conductors:**

- **`agents/conductors/feature/`** — the growth function: reasons over PyAutoMind
  `feature/*` intent and plans how the organism grows.
- **`agents/conductors/build/`** — the executive function for execution work.
  Consults the vitals faculty, reasons over the verdict, and on a healthy result
  delegates to PyAutoBuild. Has `build` / `deploy` / `release` modes.
- **`agents/conductors/release/`** — reasons over `pyauto-heart readiness` → on
  green, runs the PyAutoBuild release executor; also orchestrates release
  validation (`release rehearse` / `release validate`).
- **`agents/conductors/health/`** — the organism's clinician: runs the health
  loop with a human — assess → triage → (on your go-ahead) dispatch a validation
  leg → re-judge — until Heart goes green. Consults the vitals faculty and
  delegates dispatch to the release conductor. (Skeleton; validation + recommend.)

**Faculties:**

- **`agents/faculties/vitals/`** — read-only: reads the Heart's pulse — adopts the
  PyAutoHeart readiness verdict and explains it. The single component that talks
  to Heart.

Brain agents **consult one another**: a conductor doesn't query Heart directly —
it asks the vitals faculty, which is the only agent that talks to the Heart
organ.

```
Mind  →  Build Agent  →  vitals faculty  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

Release is a **mode** of the Build Agent today (because PyAutoBuild owns
release/build/deploy execution), isolated so it can split into a dedicated
**Release Agent** later — one agent now, clean seam for two later.

## Usage

```bash
bin/pyauto-brain help        # list agents
bin/pyauto-brain build       # consult vitals, then delegate execution to Build
bin/pyauto-brain release     # reason about readiness, then release on green
bin/pyauto-brain health      # (conductor) run the health loop with a human, toward green
bin/pyauto-brain vitals      # (faculty) one tick + the unified dashboard card (raw read)
```

PyAutoBrain runs from its checkout (no pip install), resolving the sibling
`pyauto-heart` and `autobuild` binaries from PATH or `~/Code/PyAutoLabs/`.

`bin/` also hosts the cross-organ Claude skill **installer** (`install.sh`) and
line-count **guard** (`check_skill_line_counts.sh`) — organism-wide infrastructure
that used to live in `admin_jammy/skills/`. Run `bash PyAutoBrain/bin/install.sh`
to (re-)symlink every organ's skills/commands into `~/.claude/`. See
[`bin/README.md`](bin/README.md).

## The command surface (Brain implicit)

Humans drive the CLI above through short verb commands installed into
`~/.claude/commands/`. The Brain stays **implicit**: you type a verb (or plain
natural language) and it routes to the right agent — normal usage never says
"PyAutoBrain".

> **Users speak in short commands; PyAutoBrain performs the routing.**

- **Real conductors:** `/feature` → Feature Agent, `/build` → Build Agent,
  `/health` → Health Agent (each → vitals/Heart/Build as needed).
- **Work-type entries:** `/bug` `/refactor` `/docs` `/research` route through the
  Brain dev-flow (`start_dev`) with their PyAutoMind work-type fixed — honest
  interim doors until each earns its own conductor.
- **Router + debug:** `/route <text>` infers the work-type and dispatches;
  `/brain <agent>` is the raw passthrough. Every command routes **through** the
  Brain; none replaces it.

Bodies live in `skills/<verb>/<verb>.md`; shared prose in
[`skills/COMMANDS.md`](skills/COMMANDS.md).

See [`AGENTS.md`](AGENTS.md) for the full description.

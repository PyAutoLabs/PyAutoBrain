# PyAutoBrain

The **reasoning layer** of the PyAuto organism. PyAutoBrain figures out *how*
work should be done: it hosts specialist **reasoning agents** that reason over
the health verdict from [PyAutoHeart](https://github.com/PyAutoLabs/PyAutoHeart)
and delegate execution to [PyAutoBuild](https://github.com/PyAutoLabs/PyAutoBuild).

It owns no state, no health checks, and no release mechanics — it only reasons
and delegates.

> Renamed from **PyAutoAgent**. The canonical CLI is now `pyauto-brain`;
> `pyauto-agent` remains as a back-compat shim.

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

- **`agents/build/`** — the executive function for execution work. Consults the
  Health Agent, reasons over the verdict, and on a healthy result delegates to
  PyAutoBuild. The canonical example of the Brain coordinating multiple organs;
  has `build` / `deploy` / `release` modes.
- **`agents/release/`** — reasons over `pyauto-heart readiness` → on green, runs
  the PyAutoBuild release executor.
- **`agents/health/`** — reasons over the PyAutoHeart monitoring / readiness surface.

Brain agents can also **consult one another**: the Build Agent doesn't query
Heart directly — it asks the Health Agent, which is the only agent that talks to
the Heart organ.

```
Mind  →  Build Agent  →  Health Agent  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

Release is a **mode** of the Build Agent today (because PyAutoBuild owns
release/build/deploy execution), isolated so it can split into a dedicated
**Release Agent** later — one agent now, clean seam for two later.

## Usage

```bash
bin/pyauto-brain help        # list agents
bin/pyauto-brain build       # consult health, then delegate execution to Build
bin/pyauto-brain release     # reason about readiness, then release on green
bin/pyauto-brain health      # one health tick + the unified dashboard card
```

PyAutoBrain runs from its checkout (no pip install), resolving the sibling
`pyauto-heart` and `autobuild` binaries from PATH or `~/Code/PyAutoLabs/`.

See [`AGENTS.md`](AGENTS.md) for the full description.

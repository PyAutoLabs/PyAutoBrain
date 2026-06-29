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
| **Hands** | PyAutoBuild | Performs the work — packaging, tagging, notebooks, PyPI. |
| **Heart** | PyAutoHeart | Determines whether the organism is healthy. |
| **Memory** | PyAutoMemory | Long-term scientific / software / project knowledge. |

In one line each: **Mind** decides what, **Brain** figures out how, **Hands**
perform the work, **Heart** says whether it is healthy.

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

- **`agents/release/`** — reasons over `pyauto-heart readiness` → on green, runs
  the PyAutoBuild release executor.
- **`agents/health/`** — reasons over the PyAutoHeart monitoring / readiness surface.

## Usage

```bash
bin/pyauto-brain help        # list agents
bin/pyauto-brain release     # reason about readiness, then release on green
bin/pyauto-brain health      # one health tick + readiness verdict
```

PyAutoBrain runs from its checkout (no pip install), resolving the sibling
`pyauto-heart` and `autobuild` binaries from PATH or `~/Code/PyAutoLabs/`.

See [`AGENTS.md`](AGENTS.md) for the full description.

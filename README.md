# PyAutoAgent

The orchestration brain of the PyAuto release ecosystem. PyAutoAgent hosts named
**agents** that gate on [PyAutoPulse](https://github.com/PyAutoLabs/PyAutoPulse)
and delegate execution to [PyAutoBuild](https://github.com/PyAutoLabs/PyAutoBuild).

It owns no state, no checks, and no release mechanics — it only decides and
delegates.

## The split

| Repo | Role |
|------|------|
| **PyAutoPulse** | Health authority. `pyauto-pulse readiness` is the authoritative green/yellow/red release gate. Observer-only. |
| **PyAutoBuild** | Executor. Packaging, tagging, notebooks, PyPI via `release.yml`. No checks. |
| **PyAutoAgent** | Brain. Gates on Pulse, delegates execution to Build. |

Call chain, always in this order:

```
Agent  →  Pulse (gate)  →  Build (execute)
```

## Agents

- **`agents/release/`** — `pyauto-pulse readiness` gate → on green, run the
  PyAutoBuild release executor.
- **`agents/health/`** — drive the PyAutoPulse monitoring / readiness surface.

## Usage

```bash
bin/pyauto-agent help        # list agents
bin/pyauto-agent release     # gate, then release on green
bin/pyauto-agent health      # one health tick + readiness verdict
```

PyAutoAgent runs from its checkout (no pip install), resolving the sibling
`pyauto-pulse` and `autobuild` binaries from PATH or `~/Code/PyAutoLabs/`.

See [`AGENTS.md`](AGENTS.md) for the full description.

# The PyAuto organism

The **one canonical page** for the organs, their boundaries, and the call
chain. Every other repo links here instead of restating this — if you are
editing organism prose anywhere else, stop and edit this file.

The organism is an agentic AI ecosystem for **human-led, natural-language
software development**: you describe what you want in plain English, the
organs plan, build, test and release it, and you make every judgment call.

## The organs

| Organ | Repo | Role and boundary |
|-------|------|-------------------|
| **Mind** | PyAutoMind | Decides *what* — intent, goals, priorities, workflow state, the prompt registry and taxonomy. Also holds the body map (`repos.yaml`, the single source of repo identity). |
| **Brain** | PyAutoBrain | Figures out *how* — reasoning, planning, decomposition, routing; hosts the specialist agents. Owns **no state, no health checks, no execution mechanics**. |
| **Heart** | PyAutoHeart | Determines whether the organism is healthy. `pyauto-heart readiness` is the **authoritative** GREEN/YELLOW/RED "is it safe to release?" gate. An observer: never writes into other repos, never triggers Build. |
| **Hands** | PyAutoBuild | Builds and releases — packaging, tagging, notebook generation, PyPI via `release.yml`. A pure executor: runs no readiness checks and never re-derives a gate decision. |
| **Memory** | PyAutoMemory | Long-term knowledge — *what the science says* (literature wikis, concepts, bibliographies). Operational history — *what the organism did* — lives in Mind (`complete.md`, issues), not here. |
| **Gut** | PyAutoGut | Owns the lifecycle of *condemned self-material* — stale branches, stashes, dead code/tests. Holds each as a durable, recoverable git ref through a transit window and **voids** it on a sweep. The storage mirror of Memory (retention ↔ release); the hygiene conductor drives it, as vitals reads Heart. |

The scientific libraries (PyAutoConf, PyAutoFit, PyAutoArray, PyAutoGalaxy,
PyAutoLens) and the workspaces are **capabilities the organism uses, not
organs**. The full inventory is `PyAutoMind/repos.yaml`.

## The call chain (always this order)

```
Brain  →  Heart (gate)  →  Build (execute)
```

The Brain asks `pyauto-heart readiness --json`, reasons over the verdict, and
only on **GREEN** triggers Build. Heart never triggers Build; Build never
re-derives a decision the Brain already made.

## Agents: conductors and faculties

Brain agents live in two tiers, split by one question — *does it act, or only
opine?*

- **Conductors** (`agents/conductors/<name>/`) — front-door agents a human
  drives; they decide **and** act, delegating execution to the organs.
- **Faculties** (`agents/faculties/<name>/`) — read-only opinions the
  conductors consult; they judge and stop, never dispatch or mutate.

The consult graph is a DAG: **conductors consult faculties; faculties read
their sensor organ; only the vitals faculty talks to Heart.** A conductor never
*consults* another conductor — if it wants one's opinion, that opinion should
be a faculty. (A conductor may *delegate execution* to another conductor's
organ, which is the normal Brain → organ chain, not consultation.)

Keep the conductor set small and human-meaningful (bounded by the verbs a
human types); let faculties multiply behind them.

## Growth rule: no new organs by default

New capability grows as a **faculty** (cheap: one directory, one doc, one
script), not as a repo. A new organ costs an `AGENTS.md`, a `CLAUDE.md` stub,
install wiring, a body-map row and boundary prose — it must earn that by
owning state or effects no existing organ can. Configuration/signalling
belongs to the existing config surfaces; the human interaction layer is the
command surface (`/route` + the verb commands), which is part of Brain.

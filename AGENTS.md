# PyAutoBrain — Agent Guidance

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.) and humans
discovering this repository. It is the canonical description of PyAutoBrain — the
**reasoning layer** of the PyAuto organism — and of the Brain / Heart / Build
boundary; PyAutoBuild and PyAutoHeart point back here.

> Renamed from **PyAutoAgent** to **PyAutoBrain**. The CLI is now `pyauto-brain`;
> `pyauto-agent` remains as a back-compat shim. See "Renamed from PyAutoAgent".

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
it consults the **Health Agent**, and only the Health Agent talks to the Heart
organ. So the Build Agent's full chain is:

```
Mind  →  Build Agent  →  Health Agent  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

This generalises: a future Feature Agent can ask the Health Agent whether the
tree is fit for a refactor; a future Release Agent can ask the Build Agent to
package a release. Reasoning lives in Brain agents that consult one another; the
organs (Heart, Hands/Build, Memory) provide capabilities and state. The Build
Agent is the reusable template for this pattern.

## Specialist reasoning agents

Each agent is a directory under `agents/<name>/` with:

- `AGENTS.md` — what the agent reasons about and how to run it.
- a deterministic entrypoint script (`*.sh` / `*.py`) — the part CI and humans
  invoke identically, so behaviour isn't re-derived from prose each time.

Current agents:

- **`agents/feature/`** — the **growth function**: reasons over PyAutoMind
  `feature/*` intent and decides *how the organism should grow*. Selects the next
  feature task (or plans a named one), estimates difficulty, decides whether to
  phase, consults PyAutoMemory for scientific/architectural context and (for
  risky work) the Health Agent, and emits a `FeatureDecision` that the existing
  `start_dev → ship_library/ship_workspace` workflow consumes. It reasons; it
  never edits source. (Organism-facing name: *Growth Agent*.)
- **`agents/build/`** — the executive function for execution work. Consults the
  Health Agent, reasons over the verdict, and on a healthy result delegates to
  the appropriate PyAutoBuild capability. The canonical example of the Brain
  coordinating *multiple* organs. Has `build` / `deploy` / `release` modes —
  release is isolated as a mode now, with a clean seam to a future Release Agent.
- **`agents/release/`** — reasons over `pyauto-heart readiness`, and on green
  triggers the PyAutoBuild release executor (`autobuild pre_build` → `release.yml`).
- **`agents/health/`** — reasons over the PyAutoHeart monitoring/readiness surface.

> **Build Agent vs. release mode vs. the release agent.** The Build Agent owns
> all execution orchestration and keeps release as one of its modes (broad build
> scope: generate, run, aggregate, package, tag). `agents/release/` is the older,
> narrower readiness→`pre_build` driver. The mature architecture splits a
> dedicated **Release Agent** out of the Build Agent's release mode — making
> release-specific decisions (versioning, changelogs, PyPI/tags, human approval),
> consulting the Health Agent *more strictly*, then requesting execution from the
> Build Agent / PyAutoBuild. Until then: one agent now, clean seam for two later.

More specialist agents are expected over time (Bug / Refactor / Documentation /
Research agents, and a split-out Release agent); the Feature Agent above is the
first of these, the Brain agent that reasons over PyAutoMind `feature/*` intent.
The Build Agent is the reusable template — add new ones as `agents/<name>/`
directories following its shape (a concise `AGENTS.md`, a deterministic
entrypoint, and a capability audit of any organ it drives — the Feature Agent's
`MIND_TAXONOMY.md` is that audit for the PyAutoMind/PyAutoMemory surface).

## Running

```bash
bin/pyauto-brain help            # list agents
bin/pyauto-brain feature         # select the best next PyAutoMind feature task
bin/pyauto-brain feature feature/autofit/sbi.md   # plan a specific feature task
bin/pyauto-brain build           # consult health, then delegate execution to Build
bin/pyauto-brain build --dry-run # reason + plan only (emit the BuildDecision)
bin/pyauto-brain release         # reason about readiness, then release on green
bin/pyauto-brain health          # one health tick + readiness verdict
```

Like the other PyAuto repos, PyAutoBrain runs from its checkout (no pip install);
it resolves the sibling `pyauto-heart` and `autobuild` binaries from PATH or the
`~/Code/PyAutoLabs/` checkouts.

## Renamed from PyAutoAgent

This repository was previously **PyAutoAgent**. The rename to **PyAutoBrain**
reflects the organism model above: it is the reasoning layer, not just a host of
"agents". Backwards compatibility is preserved where practical:

- `bin/pyauto-brain` is the canonical CLI; `bin/pyauto-agent` is a thin shim that
  forwards to it.
- The sibling health authority moved from `pyauto-pulse`/PyAutoPulse to
  `pyauto-heart`/PyAutoHeart (PyAutoHeart keeps a `pyauto-pulse` shim).

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

# PyAutoAgent — Agent Guidance

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.) and humans
discovering this repository. It is the canonical description of the
Build / Pulse / Agent split; PyAutoBuild and PyAutoPulse point back here.

## What this repo is

PyAutoAgent is the **orchestration brain** of the PyAuto release ecosystem. It
hosts named *agents* — each a documented role plus a deterministic entrypoint
script — that read tasks (from PyAutoPrompt and the developer), dispatch work,
and drive the release/health machinery at the right points.

PyAutoAgent owns **no state, no checks, and no release mechanics**. It only
*decides* and *delegates*: it asks PyAutoPulse whether things are healthy, and
tells PyAutoBuild to execute when they are.

## The boundary (one description, mirrored in all three repos)

- **PyAutoPulse — the health authority.** All health/readiness logic lives here:
  version drift, install-path, URL hygiene, CI/worktree/timing monitoring.
  `pyauto-pulse readiness` is the **authoritative** green/yellow/red verdict —
  the single "is it safe to release?" gate. Pulse is an observer: it reads and
  emits verdicts; it never writes into other repos and never triggers Build.
- **PyAutoBuild — the executor.** Packaging, tagging, notebook generation, and
  PyPI publication via `release.yml`. Build runs **no** readiness checks of its
  own and never re-derives a gate decision; it just executes.
- **PyAutoAgent — the brain.** Hosts the agents that connect the two. It owns no
  checks and no release steps; it gates on Pulse and delegates execution to
  Build.

## The call chain (always this order)

```
Agent  →  Pulse (gate)  →  Build (execute)
```

The agent asks `pyauto-pulse readiness --json`; only on a **green** verdict does
it trigger Build's release. Pulse never triggers Build; Build never re-derives a
gate decision the agent already made.

## Agents

Each agent is a directory under `agents/<name>/` with:

- `AGENTS.md` — what the agent is responsible for and how to run it.
- a deterministic entrypoint script (`*.sh` / `*.py`) — the part CI and humans
  invoke identically, so behaviour isn't re-derived from prose each time.

Current agents:

- **`agents/release/`** — gates on `pyauto-pulse readiness`, and on green
  triggers the PyAutoBuild release executor (`autobuild pre_build` → `release.yml`).
- **`agents/health/`** — drives the PyAutoPulse monitoring/readiness surface.

More agents are expected over time (e.g. several health agents each consuming a
different part of Pulse); add them as new `agents/<name>/` directories.

## Running

```bash
bin/pyauto-agent help            # list agents
bin/pyauto-agent release         # readiness gate, then release on green
bin/pyauto-agent health          # one health tick + readiness verdict
```

Like the other PyAuto repos, PyAutoAgent runs from its checkout (no pip install);
it resolves the sibling `pyauto-pulse` and `autobuild` binaries from PATH or the
`~/Code/PyAutoLabs/` checkouts.

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

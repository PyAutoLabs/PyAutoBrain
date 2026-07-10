# Brain — PyAutoBrain

**What it owns:** reasoning. The Brain classifies work, plans it, routes it
through the {doc}`conductors and faculties <../concepts/agents>`, and
delegates everything else: state to Mind, health to Heart, execution to
Hands. It deliberately owns no state, no checks, no release mechanics.

**Repo:** [PyAutoLabs/PyAutoBrain](https://github.com/PyAutoLabs/PyAutoBrain)
· canonical organism page:
[ORGANISM.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md)
· autonomy contract:
[AUTONOMY.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/AUTONOMY.md)

## The pieces

- **`agents/`** — the conductor and faculty directories, each an `AGENTS.md`
  role description plus a deterministic entrypoint (`bin/pyauto-brain
  <agent>` dispatches to them).
- **`skills/`** — the workflow skill bodies (`start_dev`, `ship_library`,
  the verb commands, the shared `WORKFLOW.md`). These are production
  prompts, symlinked into the agent harness by `bin/install.sh`; they are
  the agents' operating procedure, and this documentation never restates
  them.
- **`ORGANISM.md` / `AUTONOMY.md`** — the two canonical doctrine pages the
  whole organism links to.
- **`bin/`** — the CLI dispatcher and the cross-organ skill installer.

Runs from its checkout — no pip install; it resolves the sibling organs'
binaries from `PATH` or the workspace layout.

## For an adopter

Fork it. The reasoning, the agent architecture, the skills and the doctrine
pages are the framework — domain facts appear only in small constant tables
inside `agents/` (repo sets for sizing, keyword maps for routing, the
release library tuple), which are declared config surfaces you replace with
your own. See {doc}`../adoption/config_surfaces` for the exact list.

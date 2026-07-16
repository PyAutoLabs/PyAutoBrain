# Mind — PyAutoMind

**What it owns:** intent and workflow state. Every task starts here as a
plain-English markdown prompt; the registry files track what is in flight
(`active.md`), queued (`planned.md`) and done (the dated `complete/` records); and
`repos.yaml` — the **body map** — is the single source of repo identity for
the whole organism.

**Repo:** [PyAutoLabs/PyAutoMind](https://github.com/PyAutoLabs/PyAutoMind)
· schemas and conventions:
[REFERENCE.md](https://github.com/PyAutoLabs/PyAutoMind/blob/main/REFERENCE.md)

## The pieces

- **Prompts** live at `<work-type>/<target>/<name>.md`. The first folder is
  the kind of thinking required (`feature/`, `bug/`, `refactor/`, `docs/`,
  `research/`, …) — it selects the Brain agent. The second is the target
  repo or domain. Prompts are free-form prose; an optional light header
  (`Type:` / `Difficulty:` / `Autonomy:` / `Priority:`) gives both humans
  and the Brain a glance-level summary.
- **The registry** (`active.md` / `planned.md` / the `complete/` records) is the
  shared task state — worktree claims, issue links, status, resume notes.
  It is what makes the workflow machine-independent.
- **The body map** (`repos.yaml`) declares every repo's GitHub home,
  category and role. `scripts/repos_sync.py --write` regenerates the routing
  tables other repos display; `--check` fails on any drift between the map,
  the organs' config surfaces, and the actual git remotes — including the
  {ref}`tenant firewall <tenant-firewall>`.

## For an adopter

You do not fork this repo — its content *is* the upstream instance's
backlog and history. You create your own Mind with the same shape: the
registry files, the work-type folders, your own `repos.yaml` describing
your repos, and a copy of `scripts/` (the sync/drift tooling is generic).
The shapes are documented in REFERENCE.md.

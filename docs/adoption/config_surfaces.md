# The declared config surfaces

A fork's diff should touch these — and only these. Everything else in the
framework organs is domain-free logic you pull from upstream.

## The primary surfaces

| Surface | Organ | What it declares |
|---------|-------|------------------|
| `repos.yaml` | Mind (yours) | The body map — every repo's GitHub home, category, role. The single source the rest are checked against. |
| `config/repos.yaml` | Heart | What to poll and gate: repo groups, required CI workflows, thresholds, dirty-file noise patterns. |
| `pre_build.sh` — the `run_workspace` table | Hands | One row per workspace: repo, package, flags, parent library. |
| `agents/faculties/sizing/_sizing.py` | Brain | The library/workspace repo sets and aliases used to size and route tasks. |
| `agents/conductors/intake/_intake.py` — `TARGET_SIGNALS` | Brain | Keyword → target-repo routing for raw ideas. |
| `agents/conductors/release/` — the library tuple + `nightly.sh` | Brain | Which libraries the release path drives. |
| `agents/faculties/memory/` — the wiki keyword map | Brain | Topic keywords → your Memory's sub-wikis. |
| `heart/readiness.py` — `DEFAULT_LIBRARIES`; `heart/checks/version_skew.py` — the workspace→(library, package) map | Heart | The release-gate repo sets. |
| `autohands/run_all.py`, `autohands/slow_skip_check.py`, navigator maps | Hands | Which workspaces the validation pipeline runs and skips. |

The honest state: some of these are clean policy files (Heart's
`config/repos.yaml`), others are constant tables inside code files. A
demand-gated later phase teaches `repos_sync --write` to stamp the tables
from the body map; until then, replacing them by hand is a one-time cost at
fork, and the drift checks below make sure they can't disagree afterwards.

(tenant-firewall)=
## The tenant firewall

`PyAutoMind/scripts/repos_sync.py --check` includes a **tenant-firewall
check**: it scans every `*.py` / `*.sh` file in Brain, Heart and Hands for
*instance facts* — satellite repo names from the body map, GitHub owners,
the workspace home path — and fails on any occurrence outside a frozen
per-file allowlist (`FIREWALL_ALLOWLIST`, which *is* the machine-checked
inventory of the surfaces above plus the legacy remainder scheduled for
extraction).

Two firing modes: a **new** instance fact in an allowlisted file, or **any**
instance fact in a new file. Together they guarantee the property adoption
depends on: as upstream churns daily, no new code path can silently
hardcode the live instance — so your fork's `git pull` stays a config-diff
pull.

## What is *not* a config surface

- **`skills/*.md`** — the Brain's skill bodies are production prompts. They
  mention the live instance in worked examples; that is deliberate and
  harmless (they parameterise through the body map at the points that
  matter). Never run a "genericisation pass" over them.
- **`AGENTS.md` / `ORGANISM.md` / `AUTONOMY.md`** — doctrine, shared as-is.
- **Markdown generally** — the firewall scans code, not prose; generated
  doc blocks (`repos_sync:begin/end` markers) restamp from *your* body map
  when you run `--write`.

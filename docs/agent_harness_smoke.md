# Agent harness support and bounded Codex smoke

Recorded 2026-09-19 for PyAutoBrain issues #386 (discovery) and #400
(metadata and documentation). This is a bounded local check, not certification
of every scientific workflow or every agent product.

## Shared instructions and adapters

`AGENTS.md` holds shared policy, including nested folder instructions.
`CLAUDE.md` imports the sibling file. Public assistant skills retain their flat
canonical Markdown; workspace skills live at `skills/<name>/SKILL.md`.
Generated Claude links and Codex adapters refer to these same bodies. Canonical
instructions retain the full skill description when the discovery description
needs shortening to satisfy Codex metadata limits.

The [official skill documentation](https://learn.chatgpt.com/docs/build-skills)
describes `.agents/skills` as the repository discovery location. This workspace
retains its existing `.codex/skills` adapters: the installed CLI version below
actually discovered them. This evidence is specific to that version; do not infer
support for every older/newer CLI, IDE, or cloud deployment from it.

## Real harness check

Environment: local Linux, `codex-cli 0.155.1`. Started `codex app-server --stdio`,
completed `initialize` / `initialized`, then sent this request with the seven
actual repository working directories and waited for its response:

```json
{"id":2,"method":"skills/list","params":{"cwds":["<repository working directories>"],"forceReload":true}}
```

The four assistants used the phase-4 worktrees; the three workspaces used the
phase-3 worktrees. Both contain the phase-3 generated discovery artifacts.
Only entries whose returned path is inside the requested repository were counted;
user-level and system skills were excluded.

| Repository | Expected adapters | Discovered | Discovery errors |
|---|---:|---:|---:|
| autofit_assistant | 20 | 20 | 0 |
| autogalaxy_assistant | 25 | 25 | 0 |
| autolens_assistant | 44 | 44 | 0 |
| autocti_assistant | 12 | 12 | 0 |
| autofit_workspace | 1 | 1 | 0 |
| autogalaxy_workspace | 2 | 2 | 0 |
| autolens_workspace | 1 | 1 | 0 |

The process was terminated after the response. No model turn, fit, deployment,
or hook-trust mutation was requested. Separately, this Codex development session
read the shared workflow instructions and ran `bin/pyauto-brain help` successfully.

## Adapter and guard checks

- All 105 adapters passed the installed skill-creator `quick_validate.py`.
- All eight phase-3 repository discovery checks passed; canonical references
  resolved and existing Claude links remained usable.
- The four workspace skill bodies moved byte-for-byte to their neutral locations.
- Brain `tests/test_skill_install.py`: 22 tests passed, covering body-map categories, collisions,
  metadata bounds, drift, protected files/links, and symlinked discovery roots.
- Brain clone-profile suite: 35 tests passed. Generated adapters are classified
  for both reference assistants; the lensing-assistant tracked boundary passes.
  The inference assistant retains 11 pre-existing unclassified script/notebook
  paths, with no new unclassified discovery paths. Tenant firewall check passed.
- Mind `tests/test_ledger_merge.py`: 26 tests passed, including ledger allow and
  source-code deny for both `claude/**` and `codex/**`, and workflow triggers.
- Mind `tests/test_codex_hook_sync.py`: 8 tests passed for generated hook config,
  opt-in scope, wire names, drift, and absence of an implicit SessionStart copy.

- Mind end-at-deliverable and assistant API-gate fixture suites: 68 tests passed
  for the shared guard implementations. These did not run as live trusted hooks.

- Mind template-contract and privacy suites: 111 tests passed. Spawned Memory
  examples and schema use canonical `AGENTS.md` plus Claude imports.
- Brain Memory corpus suite: 8 tests passed, including canonical-schema recall
  and compatibility with older checkouts.
- Memory board suite: 62 tests passed with `PYAUTO_BRAIN` unset for its isolated
  workspace-resolution fixture; structure and wikilink validation passed.
- Eight nested instruction migrations preserve their original bodies except
  references updated from `CLAUDE.md` to `AGENTS.md`.

The hook fixtures exercise the shared scripts and adapter generation; they do
not prove that a user's installed session has trusted or invoked project hooks.
Review the current project hook hash with `/hooks` before relying on enforcement.
The Claude remote-session Python bootstrap remains a separate harness adapter;
local development uses the workspace `activate.sh`.

## Limits and rerun

This smoke verifies local discovery and adapter wiring. It does not demonstrate
end-to-end fits in Codex, interactive approval handling, actual trusted-hook
execution inside the app server, IDE/cloud parity, or runtime parity with Claude.
Those claims require their own observed runs. Other harnesses can read the shared
instructions; their discovery and hook support has not been measured here.

To rerun after changing skills, use scoped
`bin/install.sh --check-project-discovery <repo> ...`, validate generated
`SKILL.md` folders, then repeat the initialized app-server `skills/list` request
with `forceReload: true` and compare repository-scoped names and errors. Record
the installed CLI version and terminate the smoke process when done.

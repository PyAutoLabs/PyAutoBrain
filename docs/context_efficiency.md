# Context efficiency after grouped workspace migration

The September 19, 2026 follow-up keeps all approval, Heart, review and release
requirements. It reduces repeated reads, not the evidence needed to decide.

- Root, Brain and Mind AGENTS: 43,365 bytes before; 25,731 bytes after
  the root update, a 40.7% reduction in these maintained instruction surfaces.
- Brain AGENTS: 18,471 → 9,654 bytes; Mind: 12,507 → 5,070 bytes.
- PRM body: 349 → 169 lines. Its MCP lane, library freeze details and post-merge
  close-out are conditional reads. They remain required when their trigger applies.
- The new context guide and wrappers are included in procedure accounting:
  approximately 377 mandatory lines for start-dev and 370 for PRM, including
  shared context/workflow pages. Shared pages are reused within a session.

These are static byte/line measurements, not tokenizer results or measured
runtime/billing savings. The usage study had a 98.6% median cached-input rate
across 14 Astra-containing parent sessions; workers and differing scopes prevent
an exact before/after task-cost claim. Use [codex_usage.md](codex_usage.md) for
subsequent matched-task comparisons, including outcomes and correction loops.

## Check maintained budgets

From the resolved Mind checkout (set `PYAUTO_ROOT` to the workspace being measured):

```bash
python3 scripts/token_load.py report --root "$PYAUTO_ROOT"
python3 scripts/token_load.py check --root "$PYAUTO_ROOT"
```

The report lists core and conditional files separately, includes entry wrappers,
counts shared workflow/context pages, and reports their union without duplicates.
Missing required files fail the check. Byte/4 estimates are explicitly approximate.

## Activate root instructions after both PRs merge

Repo instructions and linked skills take effect when the installed main checkouts
advance. The untracked workspace root needs this explicit, reviewable local step.
From the updated Brain checkout:

```bash
source bin/_pyauto_root.sh
source bin/_repo_paths.sh
python3 bin/workspace_instructions.py --root "$PYAUTO_ROOT"        # check
python3 bin/workspace_instructions.py --root "$PYAUTO_ROOT" --write
bash bin/install.sh --write-workspace-policy
```

Machine-specific HPC instructions remain local and untouched.
The section updater changes only recognized old/new sections; unexpected local
edits fail closed. It preserves custom top-level sections, generated routing,
safety rules and symlinks. Do not overwrite local additions to resolve a refusal.
Refresh root routing and the Brain owner map using Mind's `repos_sync.py` after
reviewing its write scope (its `--only` flag scopes checks, not generation).
For a two-surface refresh, use that module's `routing_table`/`owner_map` and
`write_block` APIs rather than writing every other repository's generated files.
The task root preview is the review artifact; installation is not a merge grant.

[CONTEXT.md](../skills/CONTEXT.md) defines bounded results and completed-phase
handoffs. Continue authorized work; fresh sessions are a human choice at natural
boundaries, not a reason for agents to stop early.

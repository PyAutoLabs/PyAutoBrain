# /hygiene — keep the organism's code clean (via the Brain Hygiene Agent)

Route code-quality upkeep — the debt that neither proves the organism works
(that is `/health`) nor measures modelling speed (that is `/profiling`) —
through PyAutoBrain's **Hygiene Agent**. You never name the Brain; this command
is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain hygiene [tidy | noise | deps | docs]` (no arg = pre-scan
   across modes → a ranked worklist). This is a **dry run** — each mode does a
   cheap read-only pre-scan and emits a `HygieneDecision` naming the skill to run
   for the full audit. Nothing is executed or mutated.
2. Execute the emitted plan: run the named delegate — `/repo_cleanup` (git
   debris), `/cli_noise_clean`, `/dep_audit`, `/audit_docs` — for the full audit,
   then route any code fixes to `/refactor` / `/bug` / `/feature`, shipped via
   `ship_library` / `ship_workspace`.

The Hygiene Agent **reasons; it never edits source and never mutates a repo.**
Measurement lives in Heart (`noise`/`deps`/`docs` route to read-only PyAutoHeart
skills, plus the `script_timing` / `test_run` signals); hygiene pre-scans + routes.

> **Staged:** only `perf` (dev-loop timing) remains staged — it lands in phase 3
> with any new PyAutoHeart legs. `tidy` / `noise` / `deps` / `docs` are live.

# /hygiene — keep the organism's code clean (via the Brain Hygiene Agent)

Route code-quality upkeep — the debt that neither proves the organism works
(that is `/health`) nor measures modelling speed (that is `/profiling`) —
through PyAutoBrain's **Hygiene Agent**. You never name the Brain; this command
is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain hygiene [perf | tidy | noise | deps | docs]` (no arg =
   audit across modes → a prioritised worklist). This is a **dry run** — it emits
   a `HygieneDecision`. Nothing is executed.
2. Execute the emitted plan through the normal dev workflow: hygiene *finds and
   prioritises* quality debt and *delegates the fix* — restructuring to
   `/refactor`, regressions to `/bug`, larger changes to `/feature` — shipped via
   `ship_library` / `ship_workspace`.

The Hygiene Agent **reasons; it never edits source.** Measurement lives in Heart
(the `script_timing` / `test_run` signals); hygiene acts on it.

> **Staged (phase 1):** the conductor is real and bounded but its modes are
> stubs. `tidy` / `noise` / `deps` / `docs` land in phase 2 (absorbing
> `repo_cleanup` + `cli_noise_clean`, consulting `dep_audit` + `audit_docs`);
> `perf` in phase 3.

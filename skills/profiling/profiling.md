# /profiling — measure the organism (via the Brain Profiling Agent)

Route performance-measurement work through PyAutoBrain's **Profiling Agent** —
the measurement function. You never name the Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain profiling [campaign [--tier local|a100] | ingest |
   triage]`. This is a **dry run** — it emits a `ProfilingDecision` (dispatch
   plan / ingest steps / drift classifications). Nothing is executed.
2. Execute the emitted plan: campaign dispatch through the profiling
   workspace's own drivers (honouring the CPU-usability policy), ingest edits
   through the normal dev workflow on `autolens_profiling`, triage routes
   library regressions to `bug/` via `/intake`.

The Profiling Agent **reasons; it never runs sweeps or edits source.** The
classification is the result for CPU-unusable cells; full timings for those
belong to the A100 rows.

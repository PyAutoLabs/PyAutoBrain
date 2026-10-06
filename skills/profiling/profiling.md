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

The cross-project view of profiling results lives in the **Pulse** organ
(PyAutoPulse): its registry, `profiling-summary` read contract, ingest receipts
and board show how fast each `<lib>_profiling` project runs, but it never
judges. This command's `triage` is the only judge of what a timing or a drift
means; the projects keep their producers, results, pins and drift policy.

The Pulse board (strip on the Brain board, card on the organ cockpit) is where
cross-project drift candidates and their provenance are read; `autolens_profiling`
owns the producers, pins and drift policy. A `/profiling triage <comparison_key>`
prompt copied from a Pulse drift item names one comparison row on the Pulse
board: open that row, read the pair of records and their evidence paths, then
judge with the `triage` verb (which takes no target — the key is where to look,
not an argument).

The Profiling Agent **reasons; it never runs sweeps or edits source.** The
classification is the result for CPU-unusable cells; full timings for those
belong to the A100 rows.

## Source catalogue and evidence qualification

Read the project's `catalogue/script_routes.json` first, then the published v2
catalogue's `script_routes` extension. The conductor validates this stdlib-only
contract and reports its source/digest. Legacy sweep AST routing remains only for
projects without the new producer; invalid new data is an error, not a fallback.

Model-first source paths do not rename historical cell IDs or result paths.
Archive coverage is unreviewed evidence, never baseline acceptance or a claim of
current performance. Missing metadata stays unknown. An unavailable compile
builder or absent canonical source suppresses dispatch, with the reason visible.
Campaign commands are plans only; baseline measurement and acceptance require a
separate human-authorized campaign. CPU caps and the RAL CPU partition policy
remain unchanged. Pulse owns campaign intent, Cortex scientific records and Mind
bounded implementation tasks; this routing change moves none of that ownership.

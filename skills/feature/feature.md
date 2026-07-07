# /feature — grow the organism (via the Brain Feature Agent)

Route a feature request through PyAutoBrain's **Feature Agent** — the growth
function — then hand its decision to the dev workflow. You never name the Brain;
this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. If a PyAutoMind task path is given, run `bin/pyauto-brain feature <path>`.
   With no path, run `bin/pyauto-brain feature` to select and plan the next
   feature task from PyAutoMind.
2. Take the emitted `FeatureDecision` (classification, sizing, phasing, memory
   context) and continue with **`/start_dev`** on the chosen task — that carries
   the branch survey, issue creation, and registration.

The Feature Agent **reasons; it never edits source.** Implementation happens only
when `start_dev` / `ship_*` execute the plan. Do not bypass the Brain.

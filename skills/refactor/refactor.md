# /refactor — internal restructuring, no behaviour change (via the Brain Refactor Agent)

Plan and route **behaviour-preserving** restructuring via PyAutoBrain's
**Refactor Agent** (the *Renewal Agent*). You never name the Brain; this
command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run the agent:
   - `bin/pyauto-brain refactor` — select + plan the best next `refactor/*`
     task; `bin/pyauto-brain refactor <refactor/target/name.md>` for a named
     one; `bin/pyauto-brain refactor candidates` to mine the backlog +
     `ideas.md` (read-only).
   - If the request has no prompt yet, file one first via `/intake` (the agent
     files nothing itself).
2. Review the `RefactorDecision` — especially the **behaviour-preservation
   invariant + witnesses** and the **API guard**. `SUSPECT-API-CHANGE` →
   re-home to `feature/` (or `bug/`); a refactor must not change public API.
   Unwitnessed repos → strengthen tests first (a `test/` prompt).
3. Run **`/start_dev`** on the prompt. Refactor's work-type cap is **`safe`**
   (`PyAutoBrain/AUTONOMY.md`), so `--auto` runs end-to-end to an open PR
   gated by the four-leg autonomous-ship gate — merge stays yours.

## Boundary

- The agent decides and routes; it never edits source — implementation goes
  through `start_dev → start_library → ship_library` like everything else.
- `safe` changes *who approves*, never *what is verified* — no gate leg is
  skipped.
- Optimisation work is **not** refactoring (it changes observable
  performance/numerics) — route it via `/route` or file it as its own
  work-type.

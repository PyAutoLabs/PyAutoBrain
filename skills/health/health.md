# /health — the single door to the organism's health

The **one** health command. The Brain is the door; the procedures live in Heart.
You type `/health` (or a mode) and it routes — never invoke the sub-tools by name.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Modes

| Invocation | What it does | Leg it drives |
|------------|--------------|---------------|
| `/health` | The Brain **Health conductor** loop with you: assess (vitals → Heart) → triage → dispatch a validation leg → re-judge, until GREEN. | `bin/pyauto-brain health` |
| `/health check` | One-shot **green-light sweep**: sync each repo's `main`, run library pytest + workspace smoke, report a pass/fail matrix. | `PyAutoHeart/skills/health_sweep/reference.md` |
| `/health status` | **Active-work dashboard**: what's in flight across the repos (reads `active.md` / `planned.md` / `complete.md`), conflicts, idle repos. | `PyAutoHeart/skills/pyauto-status/reference.md` |
| `/health full` | **Release-run dashboard**: what the last PyAutoBuild release-prep run produced (per-workspace pass/fail/timing, slowest scripts, failure tracebacks). | `PyAutoHeart/skills/pyauto-status-full/reference.md` |

## Do

- **Bare `/health`** → run `bin/pyauto-brain health` and drive the loop
  conversationally. Adopt Heart's verdict **verbatim** via the vitals faculty;
  never re-derive it.
- **`/health check`** → follow the sweep procedure in
  `PyAutoHeart/skills/health_sweep/reference.md` (read-mostly test/smoke sweep;
  supports `--no-sync`).
- **`/health status`** → follow the dashboard procedure in
  `PyAutoHeart/skills/pyauto-status/reference.md`.
- **`/health full`** → follow the release-run dashboard procedure in
  `PyAutoHeart/skills/pyauto-status-full/reference.md`.

`/health` is the **only** health command. The former `/health_check`,
`/pyauto-status`, and `/pyauto-status-full` are retired as top-level commands and
live on as the `check`, `status`, and `full` legs above — the door is the Brain,
the procedures are Heart's.

On the shell side, the same vocabulary applies: `health` (git-sync dashboard),
`health release`, and `health audit` (see `PyAutoMind/scripts/health.sh`) — a
separate local convenience layer, not this command.

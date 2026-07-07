# /bug — fix a regression, failing test, or wrong behaviour

A **work-type entry** into the Brain dev-flow. No dedicated Bug conductor exists
yet, so this routes through the Feature Agent's classifier with the PyAutoMind
work-type fixed to `bug/`. (Follow-up: promote to a dedicated Bug conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`bug/`**. If no prompt path exists,
first create one under `PyAutoMind/bug/<target>/<name>.md` (original request
verbatim), then run **`/start_dev`** on it. `start_dev` routes reasoning through
the Brain — nothing bypasses it. Taxonomy: `PyAutoMind/ROUTING.md`.

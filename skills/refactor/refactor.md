# /refactor — internal restructuring, no behaviour change

A **work-type entry** into the Brain dev-flow. No dedicated Refactor conductor
exists yet, so this routes through the Feature Agent's classifier with the
PyAutoMind work-type fixed to `refactor/`. (Follow-up: promote to a dedicated
Refactor conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`refactor/`** — architecture cleanup
or internal restructuring with **no intended behaviour change**. If no prompt path
exists, create one under `PyAutoMind/refactor/<target>/<name>.md` (original
request verbatim), then run **`/start_dev`** on it. `start_dev` routes through the
Brain. Taxonomy: `PyAutoMind/ROUTING.md`.

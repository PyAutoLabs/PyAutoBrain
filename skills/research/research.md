# /research — investigation, design notes, scientific background

A **work-type entry** into the Brain dev-flow. No dedicated Research conductor
exists yet, so this routes through the Feature Agent's classifier with the
PyAutoMind work-type fixed to `research/`. (Follow-up: promote to a dedicated
Research conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`research/`** — exploratory
investigation, design notes, or scientific background *before* implementation. If
no prompt path exists, create one under `PyAutoMind/research/<target>/<name>.md`
(original request verbatim). Research typically produces notes/decisions rather
than a PR; consult **PyAutoMemory** for prior art and record findings back to
Mind. Escalate to `/feature` once scoped. Taxonomy: `PyAutoMind/ROUTING.md`.

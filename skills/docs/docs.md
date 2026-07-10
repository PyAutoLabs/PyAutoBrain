# /docs — documentation, examples, notebooks, tutorials

A **work-type entry** into the Brain dev-flow. No dedicated Documentation
conductor exists yet, so this routes through the Feature Agent's classifier with
the PyAutoMind work-type fixed to `docs/`. (Follow-up: promote to a dedicated
Documentation conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`docs/`** — documentation, examples,
notebooks, or tutorial prose. If no prompt path exists, create one under
`PyAutoMind/docs/<target>/<name>.md` (original request verbatim), then run
**`/start_dev`** on it. `start_dev` routes through the Brain, and the tutorial
The judgment/execution tier split in `../WORKFLOW.md` applies. Taxonomy:
`PyAutoMind/ROUTING.md`.

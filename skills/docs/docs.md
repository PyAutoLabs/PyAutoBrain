# /docs — documentation, examples, notebooks, tutorials

A **work-type entry** into the Brain dev-flow. No dedicated Documentation
conductor exists yet, so this routes through the Feature Agent's classifier with
the PyAutoMind work-type fixed to `docs/`. (Follow-up: promote to a dedicated
Documentation conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`docs/`** — documentation, examples,
notebooks, or tutorial prose. If no prompt path exists, create one under
`PyAutoMind/draft/docs/<target>/<name>.md` (original request verbatim), then run
**`/start_dev`** on it. `start_dev` routes through the Brain.

Once the plan is approved and the development worktree is ready, choose the
writing guide before drafting or reviewing prose:

- **READMEs, setup pages and general Read the Docs pages** follow
  [`../WRITING_STYLE.md`](../WRITING_STYLE.md).
- **Scientific Python scripts, notebooks, worked examples and HowTo lessons**
  follow
  [`../TUTORIAL_WRITING_STYLE.md`](../TUTORIAL_WRITING_STYLE.md).
- **Mixed documents** follow both guides in their respective sections.

Read the selected guide completely before editing. For tutorial work, plan
approval establishes the development scope but does not authorise a bulk prose
rewrite: propose, review and apply one coherent block at a time as defined by
`TUTORIAL_WRITING_STYLE.md`.

The judgment/execution tier split in `../WORKFLOW.md` applies. Taxonomy:
`PyAutoMind/ROUTING.md`.

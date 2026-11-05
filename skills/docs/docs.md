# /docs — READMEs, setup pages, Read the Docs pages and tutorials

Plan documentation work through PyAutoBrain's **Documentation Agent**, the
owner of [`../WRITING_STYLE.md`](../WRITING_STYLE.md). You never name the
Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`. The agent's full
docs: `bin/pyauto-brain help docs`.

## Do

1. Run the agent on the request (raw text or a filed PyAutoMind prompt):

   ```bash
   bin/pyauto-brain docs "<raw request text>"
   bin/pyauto-brain docs <PyAutoMind prompt path>
   ```

   This emits a **DocsDecision**: the surface (GitHub README, setup page, Read
   the Docs page, tutorial narrative or agent-facing file), the target repo,
   whether `WRITING_STYLE.md` applies, the page template from the guide, where
   long material should move, and the sibling repos to keep in step (for
   example the four assistant READMEs). It writes nothing.
2. Review the decision with the user and correct the surface or repo in
   conversation.
3. Route the agreed work into the dev flow. If no prompt path exists, create
   one under `PyAutoMind/draft/docs/<target>/<name>.md` (original request
   verbatim), then run **`/start_dev`** on it with work type **`docs/`**.
4. Before review, audit each people-facing page you changed:

   ```bash
   bin/pyauto-brain docs audit <page>
   ```

   It scores the page against the guide's checklist and lists concrete fixes.
   Checks marked `heuristic` are prompts for judgment, not verdicts.

## Choose the writing guide

Read the selected guide completely before drafting or reviewing prose:

- **READMEs, setup pages and general Read the Docs pages** follow
  [`../WRITING_STYLE.md`](../WRITING_STYLE.md).
- **Scientific Python scripts, notebooks, worked examples and HowTo lessons**
  follow
  [`../TUTORIAL_WRITING_STYLE.md`](../TUTORIAL_WRITING_STYLE.md). The decision
  defers these to `/workspace` (the Workspace Agent's `workspace`/`howto`
  registers), which plans repo, placement and sibling.
- **Mixed documents** follow both guides in their respective sections.

For tutorial work, plan approval establishes the development scope but does not
authorise a bulk prose rewrite: propose, review and apply one coherent block at
a time as defined by `TUTORIAL_WRITING_STYLE.md`.

The judgment/execution tier split in `../WORKFLOW.md` applies. Taxonomy:
`PyAutoMind/ROUTING.md`.

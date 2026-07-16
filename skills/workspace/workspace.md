# /workspace — plan example authorship (via the Brain Workspace Agent)

Reason over **workspace + HowTo example authorship** — the organism's *Voice* —
via PyAutoBrain's **Workspace Agent**. You never name the Brain; this command
is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`. The agent's full
docs: `bin/pyauto-brain help workspace`.

## Do

1. Run the agent on the intent (raw text or a filed PyAutoMind prompt):

   ```bash
   bin/pyauto-brain workspace "<raw intent text>"
   bin/pyauto-brain workspace <PyAutoMind prompt path>
   ```

   This emits a **WorkspaceDecision** — library family, target repo, audience
   register (`workspace` for practitioner examples, `howto` for first-time
   learners), placement in the target's real `scripts/` tree, the sibling
   example to mirror, the prose tier, and the format checklist. It is a dry
   run every time: the agent **writes nothing**.
2. Review the decision with the user — correct the target, register or
   placement in conversation.
3. Route the agreed work into the dev flow: `/start_dev` (workflow:
   workspace) → `/start_workspace` → author → `/ship_workspace`. The decision's
   checklist and sibling pointer ride along in the plan; example/howto prose
   stays judgment-tier per `skills/WORKFLOW.md`.

## Survey mode (catalogue inventory)

```bash
bin/pyauto-brain workspace survey <repo> [--against <sibling>]
```

Read-only inventory of a workspace repo's example catalogue (packages +
script counts); `--against` diffs the structure against a sibling — the
newborn-workspace bootstrap tool (e.g.
`survey autoreduce_workspace --against autolens_workspace`).

## Boundary

- **Decides and routes; never authors.** All writing happens in the dev flow;
  this command never bypasses `start_dev`.
- One agent, two registers (`workspace` | `howto`); the split trigger for a
  future dedicated HowTo agent is recorded in the agent's
  `agents/conductors/workspace/AGENTS.md`.
- `--json` gives the machine-readable decision/survey.

---
name: intake
description: Turn raw PyAutoLabs ideas, bug reports, or loose requirements into classified and sized PyAutoMind prompt files through the PyAutoBrain Intake Agent, regenerating the Mind dashboard in the same commit. Also the door for flagging already-shipped work for human review (Type: human review), which is only ever filed when explicitly asked for. Use before start-dev when intent is not yet formalized.
---

# Intake

Follow [`intake.md`](intake.md) exactly. Run the deterministic intake agent as a
dry run first and apply only after reviewing its decision.

`--apply` writes the prompt file and runs no git. Filing is finished only once
the dashboard is regenerated and committed with it (step 4) — that page is how
the task gets picked up, so a prompt filed without it cannot be found yet.

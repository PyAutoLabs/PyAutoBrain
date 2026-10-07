---
name: intake
description: Turn raw PyAutoLabs ideas, bug reports or loose requirements into classified, sized PyAutoMind prompt files via the Intake Agent; also files a human review of shipped work, only when asked. Use before start-dev when intent is not formalized.
---

# Intake

Follow [`intake.md`](intake.md) exactly. Run the deterministic intake agent as a
dry run first and apply only after reviewing its decision.

`--apply` writes the prompt file and runs no git. Filing is finished only once
the dashboard is regenerated and committed with it (step 4) — that page is how
the task gets picked up, so a prompt filed without it cannot be found yet.

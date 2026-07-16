# /route — say what you want; the Brain routes it

The natural-language door — the "look at this" path. The user describes what they
want in plain words and never names an agent; you infer the work-type and dispatch
to the matching command. This is the primary interface; the verb commands are just
typed shortcuts into the same routing.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Classify → dispatch

Infer the work-type from the request using the taxonomy in
`PyAutoMind/ROUTING.md`, then behave as the matching command:

| The request is about… | Route to |
|-----------------------|----------|
| a new capability, or "what should I work on next" | `/feature` |
| building, shipping, releasing, publishing | `/build` |
| failing tests, readiness, "is it safe / green?" | `/health` |
| a regression, crash, or wrong output | `/bug` |
| restructuring with no behaviour change | `/refactor` |
| authoring a workspace or HowTo example/tutorial | `/workspace` |
| other documentation, notebooks, docstrings | `/docs` |
| investigation, design, or scientific background | `/research` |

Examples: *"Fix failing tests"* → `/bug` (or `/health` if it's a readiness sweep);
*"Implement issue #417"* → `/feature`; *"Publish PyAutoLens"* → `/build`.

If genuinely ambiguous, state your inferred route and the runner-up, then proceed
with the most likely one — only ask when it is a true 50/50. Never route around
the Brain.

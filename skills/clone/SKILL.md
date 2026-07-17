---
name: clone
description: Analyze how a mature PyAuto domain assistant should be reproduced as an exact clone, sibling, or seed through the PyAutoBrain Clone Agent, and birth a lightweight seed once a human has answered the clone-mode question. Use for assistant-cell cloning decisions and seed births.
---

# Clone

Read [`../../agents/conductors/clone/AGENTS.md`](../../agents/conductors/clone/AGENTS.md)
completely, then run `bin/pyauto-brain clone` with the documented arguments and
return its `CloneDecision`.

Bare `clone` writes nothing. A birth happens only under
`--apply --mode lightweight-seed`, and only after a human has answered both the
clone-mode question and the repo-creation gate (name / owner / visibility) —
never unprompted. The agent hands the plan to Build; it never writes repos or
files itself, and never modifies the reference.

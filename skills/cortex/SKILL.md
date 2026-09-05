---
name: cortex
description: Check in on the science — run the PyAutoBrain Cortex Agent's one door (pull every active project through its own sync CLI, score every live run against its pre-registered witness, move what came back, re-render the board, push the ledger) and read the by-project summary back to the human with the prompt each phase needs next. Use for science runs, phases, gates and rulings; never for development tasks, which are the Mind's.
---

# Cortex

Follow [`cortex.md`](cortex.md) exactly: it is the check-in sequence, and the
individual verbs are its appendix. The conductor reasons; its check-in door
never submits a run and never writes a ruling. A run is submitted only when the
human asks for it in the session — then the agent runs the project's own sync
CLI and records the job id with `cortex.py move`. The verdict stays the
human's word.

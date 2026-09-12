---
name: cortex
description: Check in on the science — run the PyAutoBrain Cortex Agent's one door (pull every active project through its own sync CLI, show where each run stands, re-render the board, push the ledger) and read each project's ledger back to the human — Now, the runs on the cluster, the last entries — then record what they say with the Cortex's own cortex.py verbs. Use for science runs and project ledgers; never for development tasks, which are the Mind's.
---

# Cortex

Follow [`cortex.md`](cortex.md) exactly: it is the check-in sequence, and the
individual verbs are its appendix. The conductor records cluster facts and the
human's words, never a verdict of its own: it never scores a result, never
drafts a ruling, never writes a `result` or `lesson` entry the human did not
say. A run is submitted only when the human asks for it in the session — then
the agent runs the project's own sync CLI and records the job id with
`cortex.py run`. Every ledger write is a `cortex.py` verb; no ledger is edited
by hand.

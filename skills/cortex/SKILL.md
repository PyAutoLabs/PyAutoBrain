---
name: cortex
description: Check in on the science via the Cortex Agent — 'cortex pull' on the laptop (pull each project's runs) and 'cortex checkin' anywhere (stamp, re-render, push the board) — and read ledgers back. Use for science runs and ledgers; never dev tasks.
---

# Cortex

Follow [`cortex.md`](cortex.md) exactly: it is the check-in sequence — `pull`
on the laptop, `checkin` on any surface — and the individual verbs are its
appendix. The conductor records cluster facts and the
human's words, never a verdict of its own: it never scores a result, never
drafts a ruling, never writes a `result` or `lesson` entry the human did not
say. A run is submitted only when the human asks for it in the session — then
the agent runs the project's own sync CLI and records the job id with
`cortex.py run`. Every ledger write is a `cortex.py` verb; no ledger is edited
by hand.

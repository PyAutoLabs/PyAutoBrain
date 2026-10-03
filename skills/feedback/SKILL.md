---
name: feedback
description: Draft user-reviewed feedback about using PyAutoLabs software and assistants, including goals, successes, friction and evidence. Use when a user asks to share feedback, summarize their experience for maintainers, or prepare an agent-assisted retrospective. Produces a draft for the existing Discussions hub; never posts it.
---

# Feedback

Follow [feedback.md](feedback.md). Use [template.md](template.md) for the
report and [invitation.md](invitation.md) when inviting another user to
contribute. This is the Community Agent's session-side drafting workflow,
not a new conductor. It needs no GitHub access or local checkout in quick mode.

## Assistant distribution (maintainers)

These files are the canonical workflow, template and invitation. Generate the
standalone reference with `python3 bin/sync_feedback.py ../autolens_assistant`;
use `--check` to detect drift without writing. Propagate the resulting generic
reference diff with `pyauto-brain clone sync`, then regenerate each assistant's
own project-discovery adapters. The embedded copy runs without Brain installed.

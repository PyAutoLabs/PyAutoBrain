---
name: queue
description: Maintain PyAutoMind queue.md, the human's ranked task list, from chat. In a chat that ran /queue, a pasted prompt, prompt path, task title or dashboard copy line means add it to the queue, never start dev. Also remove, move up/down/top/to n, and show.
---

# Queue

Follow [`queue.md`](queue.md) exactly. Once `/queue` has run in a chat, that
chat is a **queue chat** until the human says otherwise: anything they paste
that names a task (a whole prompt, a `draft/`/`active/` path, a title, or the
dashboard's 📋 line `Use the start-dev skill. <path>`) means **add it to
`queue.md`**. It never means start dev, plan, intake or build, even though the
📋 line names the start-dev skill. The edit is done by the Mind's
`scripts/queue_edit.py`, never by hand.

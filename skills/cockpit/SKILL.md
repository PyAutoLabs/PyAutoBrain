---
name: cockpit
description: Watch a running shift from chat when the human asks for a watch (/cockpit, "watch the shift", "start the cockpit") — stream its events in the current Codex turn or with Claude Monitor and steer it by comments on the shift issue. A question about the shift gets a one-shot read, never a watch. In a /cockpit chat, a pasted prompt, path or dashboard copy line means /add it to the shift, never start dev.
---

# Cockpit

Follow [`cockpit.md`](cockpit.md) exactly. This is the one skill allowed to hold
a watch past its turn, and only the shift's own event stream inside its window
(PyAutoMind `policy/shift_cockpit_watch.md`, enforced by the end-at-deliverable
hook), and only when the human asks for a watch: a question such as "what's
the shift doing?" gets a one-shot `batch watch --once` answer, never a
Monitor. Once `/cockpit` has run in a chat, that chat is a **cockpit chat** until
the shift ends: anything pasted that names a task (a prompt, a `draft/` path,
a title, or the dashboard's 📋 line `Use the start-dev skill. <path>`) means
**`/add` it to this shift**. It never means start dev, plan, intake or build.
Every steering act is exactly one comment on the shift issue, from the human's
own login; the chat steers the shift in no other way.

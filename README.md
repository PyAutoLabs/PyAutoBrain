# PyAutoBrain

📖 **Full documentation → <https://pyautoscientist.readthedocs.io>** — the whole PyAutoScientist organism, including how to fork and run your own.

The reasoning layer of the PyAuto organism. Brain figures out *how* work
gets done: it classifies incoming tasks, plans them, and routes them to
specialist agents, delegating execution to the other organs. It holds no
state, runs no health checks, and never releases anything itself.

The organism is described once in [ORGANISM.md](ORGANISM.md). The short
version:

| Organ | Repo | Job |
|-------|------|-----|
| Mind | PyAutoMind | what to do — intent, priorities, workflow state |
| Brain | PyAutoBrain (this repo) | how to do it — reasoning, planning, routing |
| Heart | PyAutoHeart | is it healthy — the release-readiness verdict |
| Hands | PyAutoBuild | do it — packaging, tagging, PyPI releases |
| Memory | PyAutoMemory | what we know — long-term scientific knowledge |

Agents live under `agents/` in two tiers: **conductors** (front doors a
human drives; they decide and act) and **faculties** (read-only judgments
the conductors consult). Humans mostly reach them through short slash
commands — `/intake`, `/feature`, `/bug`, `/health`, `/route` — whose
bodies live in `skills/`.

```bash
bin/pyauto-brain help        # list the agents
bin/pyauto-brain vitals      # one health tick + the dashboard card
bash bin/install.sh          # symlink every organ's skills into ~/.claude
```

Runs straight from its checkout — no pip install. Agent contracts and the
organ boundary are in [AGENTS.md](AGENTS.md); how much a run may do without
a human is the autonomy contract, [AUTONOMY.md](AUTONOMY.md). The full
organism documentation — including how to fork and run your own — is at
<https://pyautoscientist.readthedocs.io> (source: `docs/`).

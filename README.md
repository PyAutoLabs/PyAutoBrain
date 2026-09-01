<p align="center">
  <img src="logo.png" alt="PyAutoBrain" width="400">
</p>

# PyAutoBrain

[![PyAutoScientist GitHub](https://img.shields.io/badge/%E2%9A%9B%EF%B8%8F%20PyAutoScientist-GitHub-181717?style=flat-square)](https://github.com/PyAutoLabs/PyAutoScientist) [![PyAutoScientist ReadTheDocs](https://img.shields.io/badge/%F0%9F%93%96%20PyAutoScientist-ReadTheDocs-8CA1AF?style=flat-square)](https://pyautoscientist.readthedocs.io)

**PyAutoBrain is the Brain of the PyAutoScientist** — the reasoning layer that
turns intent into shipped software. It decides *how* work gets done: it
classifies each task, plans it, and routes it to specialist agents — and it
delegates everything else: it holds no state (the Mind's job), runs no health
checks (the Heart's), and never releases anything itself (the Hands').

See the **[PyAutoBrain Dashboard](https://pyautolabs.github.io/PyAutoBrain/)**
for the organism's morning and general starting point: what ran overnight, the
Heart's readiness headline, who in the community is waiting on a reply, what
to resume, and the upkeep doors — each actionable row with a one-tap 📋
copy-for-Claude command. Regenerated each morning; the local sync/clean leg is
one terminal command, `bash bin/morning.sh` — or schedule it overnight on the
dev box with `bash bin/morning_timer.sh install`, so the board is already
fresh when you wake.

## How PyAutoBrain works

You drive it in plain English, through short slash commands in a Claude Code
chat: `/intake` to file an idea, `/start_dev` to begin a task, `/health` for a
check-up — or just `/route <what you want>` and the Brain picks the right
door. The full command surface (13 conductors + 5 faculties) is the generated
table in [AGENTS.md](AGENTS.md).

1. **A task arrives.** Usually from the Mind's backlog — pick a task on the
   [PyAutoMind dashboard](https://pyautolabs.github.io/PyAutoMind/) and paste
   its `/start_dev` command — or free-form, via `/route` or any conductor's
   own door.
2. **A conductor takes it.** Conductors ([`agents/conductors/`](agents/conductors))
   are the front doors a human drives; they decide *and* act: `intake`
   conceives tasks, `feature`/`bug`/`refactor` plan development, `health`
   runs the clinic, `release` drives a release, and so on.
3. **Faculties advise.** Faculties ([`agents/faculties/`](agents/faculties))
   are read-only opinions the conductors consult: `vitals` reads the Heart's
   verdict, `sizing` estimates difficulty, `memory` recalls what the organism
   knows, `review` judges a branch. A conductor never consults another
   conductor — an opinion worth sharing becomes a faculty.
4. **The organs execute.** Always in the same order — **Brain → Heart (gate)
   → Hands (execute)**: work happens on task worktrees, ships as pull
   requests behind the Heart's health verdict, and is packaged and released
   by the Hands.
5. **Autonomy is a contract.** How much a run may do without a human is
   defined per task in [AUTONOMY.md](AUTONOMY.md) — a safe-capped task may
   carry itself to an open pull request; merging and releasing always stay
   human.

## CLI examples

The same agents are runnable directly — every slash command is a verb of one
CLI, which runs straight from this checkout (no pip install):

```bash
bin/pyauto-brain help                      # list every conductor and faculty
bin/pyauto-brain route "fix the failing lens smoke test"   # plain English in
bin/pyauto-brain vitals                    # read the Heart's readiness verdict
bash bin/install.sh                        # symlink every organ's skills into ~/.claude
```

The eight organs the Brain coordinates — Brain (reasoning), Mind (intent),
Cortex (learning what is true), Memory (knowledge), Heart (health), Hands
(release), Nerves (configuration), Gut (shedding) — are defined once in
[ORGANISM.md](ORGANISM.md), which this
repo hosts. Agent contracts and the generated command table are in
[AGENTS.md](AGENTS.md). The full organism documentation — including how to
fork it and lead your own — is at <https://pyautoscientist.readthedocs.io>,
whose source lives here in [`docs/`](docs).

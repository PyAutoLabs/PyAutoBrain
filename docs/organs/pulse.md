# Pulse — PyAutoPulse

**What it owns:** the **cross-project profiling view** over the
`<lib>_profiling` project repos (today `autolens_profiling`) — the instance
registry of those repos, the versioned `profiling-summary` read contract they
publish, the ingest receipts (the resolved commit per project per render) and
the board built from them. The project repos produce and hold the timings; the
organ measures nothing and copies no results. The Pulse is the speed mirror of
the Eyes: the Eyes show what the software *shows*; the Pulse feels how fast it
*runs*.

**Repo:** [PyAutoLabs/PyAutoPulse](https://github.com/PyAutoLabs/PyAutoPulse)

**Status:** organ row registered (phase 0 of the `profiling-organ-birth`
epic); the registry, reader, receipts, board and workflows arrived in phase 2;
phase 3 puts the organ on the Brain board and the organ cockpit.
Design: `docs/research/profiling_inference_organs.md` in the Brain repo.

## The defining function: feeling the pulse

A pulse is a rate read over time — and the question the organ answers is how
fast each library runs now, and how that has changed from release to release.
Each profiling project times its own likelihoods and searches on fixed data,
pins its baselines and applies its own drift policy; since phase 1,
`autolens_profiling` also publishes a versioned summary
(`dashboard/summary.json`, `profiling-summary` v1, grammar in
`autolens_profiling/dashboard/README.md`). The organ reads those summaries
across projects. It validates the **exchange contract** — envelope, version,
freshness, provenance — and leaves **domain semantics** to the project.

## Instances

Each instance is a `<lib>_profiling` project repo that publishes a
`profiling-summary`. `autolens_profiling` is the one real producer today. The
organ's instance registry names every instance, where its summary lives and
which contract version it speaks; each render records an ingest receipt so a
board row can always be traced to the commit it was built from. A second
project is registered only when a real producer exists — a fixture tests the
reader, an empty sibling repo is never manufactured to fill the row.

The board shows one row per registered project with scope, evidence time, last
fetch, coverage and links, and keeps missing or refused evidence visible beside
valid data. A valid empty feed says "no measurements", never "all passed".

Beside the board, the organ publishes two machine surfaces: `badge.json`, a
one-line headline, and `state.json`, the organ-cockpit feed (contract v1 in
`PyAutoBrain/board/state_schema.json`). The feed is what puts the Pulse on the
[organ cockpit](https://pyautolabs.github.io/cockpit/) alongside the other
organs; the Brain board's Resume section carries a Pulse strip composed from
the head counts of the organ's own `dashboard.md`.

## The driver split

The project repos *produce and hold* timings and the Pulse *shows* them;
neither judges a cross-project trend. The Brain's **profiling conductor**
(`bin/pyauto-brain profiling`, `/profiling`) plans campaigns, ingests fresh
results and triages drift with the human — `triage` is the only judge. The
same split as **Heart ↔ vitals** and **Eyes ↔ Eyes conductor**: the organ
keeps the state, the conductor reasons over it.

## What it never does

- **It never judges a timing.** Drift triage is the conductor's, with the human.
- **It never moves pins** or re-baselines a project's measurements.
- **It never combines unmatched timings** across projects, hardware or
  configurations.
- **It never applies the compile threshold to runtime.** The runtime rule
  (2x ratio, 1 ms floor) and the compile conductor's 1 s floor stay distinct,
  as each source declares them.
- **It computes no ecosystem-wide speed score** and builds no league table
  across unrelated tasks.
- **It issues no verdict.** Readiness is the Heart's.

## For an adopter

Like Mind, Cortex, Memory, Eyes and Gut, the Pulse is an **instance organ** —
inherently yours. You create your own Pulse registry and dashboard over your
own libraries' profiling project repos. Those projects produce and retain the
measurements; the organ reads their summaries and links to them.

The organ is being born through the `profiling-organ-birth` epic:

- **Phase 1** (autolens_profiling#360) published `profiling-summary` v1 from
  the lens profiling project.
- **Phase 0** ([PyAutoMind#463](https://github.com/PyAutoLabs/PyAutoMind/issues/463))
  added the organ row to the body map.
- **Phase 3** ([PyAutoBrain#450](https://github.com/PyAutoLabs/PyAutoBrain/issues/450))
  added the Pulse strip to the Brain board and the Pulse card to the organ
  cockpit, and named the Pulse board in the profiling conductor's prose as
  where drift candidates are read.

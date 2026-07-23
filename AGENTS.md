# PyAutoBrain — Agent Guidance

This file is for AI coding agents (Claude Code, Codex, Cursor, etc.) and humans
discovering this repository. It is the canonical description of PyAutoBrain — the
**reasoning layer** of the PyAuto organism — and of the Brain / Heart / Build
boundary; PyAutoHands and PyAutoHeart point back here.

## The organism map

<!-- repos_sync:map:begin -->
**You are one organ of the PyAuto organism** — an agentic ecosystem for
human-led, natural-language software development. The organs below are
peer repositories; this repo is one of them, not a part of another.
Canonical boundaries live in `PyAutoBrain/ORGANISM.md`; the full body map
(every repo, not just organs) is `PyAutoMind/repos.yaml`.

| Organ | Repo | Role |
|-------|------|------|
| **Mind** | PyAutoMind | Intent, goals, priorities, workflow state; every task starts as a markdown prompt here. |
| **Brain** | PyAutoBrain | Reasoning/orchestration layer; how work is decomposed and routed; the specialist agents. |
| **Hands** | PyAutoHands | Packaging, tagging, notebook generation, PyPI release execution. |
| **Heart** | PyAutoHeart | Health/readiness — the authoritative "is it safe to release?" verdict. |
| **Memory** | PyAutoMemory | Long-term scientific/software/project knowledge (see science pointer below). |
| **Gut** | PyAutoGut | Owns the lifecycle of condemned self-material (stale branches, stashes, dead code/tests): holds it as durable, recoverable git refs through a transit window and voids it on a sweep. The storage mirror of Memory (retention vs release). |
| **Nerves** | PyAutoNerves | The Nerves — the configuration/serialization layer connecting workspace conventions to libraries (layered config, version handshake, test_mode), delivered as the `autonerves` package. |

Call chain (always this order): **Brain → Heart (gate) → Build (execute)**. Brain agents are **conductors** (front-door; a human drives them; they decide *and* act) or **faculties** (read-only opinions the conductors consult; they judge and stop). New capability grows as a faculty, not a new organ, unless it owns state or effects no existing organ can.

Generated from `PyAutoMind/repos.yaml` + `PyAutoBrain/ORGANISM.md`; edit there, then run `python3 PyAutoMind/scripts/repos_sync.py --write`.
<!-- repos_sync:map:end -->

## What this repo is

PyAutoBrain is the **reasoning layer** of the PyAuto ecosystem as it grows into a
software organism. It figures out *how* work should be done and coordinates the
organs that do it. It hosts specialist **reasoning agents** — each a documented
role plus a deterministic entrypoint script — that read intent (from PyAutoMind
and the developer), reason about it, and drive the health/execution machinery at
the right points.

PyAutoBrain owns **no state, no health checks, and no execution mechanics**. It
only *reasons* and *delegates*: it asks PyAutoHeart whether the organism is
healthy, decides whether and how to proceed, and tells PyAutoHands to execute
when it should.

## The organism

The organs, their boundaries, and the `Brain → Heart (gate) → Build (execute)`
call chain are defined **once** in [`ORGANISM.md`](ORGANISM.md) — this repo
hosts that canonical page; every other organ links to it. In one line: the
Mind decides *what*, the Brain (this repo) figures out *how*, the Heart gates,
the Hands build, Memory knows what the science says.

## Brain agents consult one another (a society of agents)

Brain agents are not limited to driving organs — they can **consult each other**.
The canonical example is the **Build Agent**, which does not query Heart directly:
it consults the **vitals faculty**, and only the vitals faculty talks to the Heart
organ. So the Build Agent's full chain is:

```
Mind  →  Build Agent  →  vitals faculty  →  Heart  →  GREEN/YELLOW/RED
                      →  Build Agent  →  Build (execute)
```

The consult graph is a DAG (see [`ORGANISM.md`](ORGANISM.md)): conductors
consult faculties; faculties read their sensor organ; a conductor never
consults another conductor — if it wants one's opinion, that opinion should be
a faculty. The Build Agent is the reusable template for this pattern.

How much human checkpointing a workflow run needs is defined once in
[`AUTONOMY.md`](AUTONOMY.md) — the autonomy contract mapping each Mind-prompt
`Autonomy:` level to behaviour at every checkpoint.

## Specialist reasoning agents

Agents live in **two tiers** under `agents/`, distinguished by one question —
*does it act, or only opine?*

- **Conductors** (`agents/conductors/<name>/`) — front-door agents a human
  **drives**. They *decide **and** act*, delegating execution to the organs.
  They have side effects in the world (a plan driven into dev, a build, a
  release). This is the small, curated set of things you invoke and converse
  with.
- **Faculties** (`agents/faculties/<name>/`) — read-only reasoning capabilities
  the conductors **consult**. They *only opine* — return a judgment and stop;
  they never dispatch or mutate. They are *sinks* in the consult graph
  (everything reaches into them; they reach out only to their sensor organ). Not
  chat-first surfaces, though they stay runnable for a quick read.

The rule of thumb: **keep the conductor set small and human-meaningful; let
faculties multiply behind them.** A side-effecting decider is a conductor; a
side-effect-free opinion is a faculty.

Each agent is a directory with an `AGENTS.md` (what it reasons about + how to run
it) and a deterministic entrypoint script (`*.sh` / `*.py`) — the part CI and
humans invoke identically, so behaviour isn't re-derived from prose each time.

New agents are added on **demonstrated need, never for symmetry**. Place by
tier: a side-effecting decider you drive → `agents/conductors/<name>/`; a
read-only opinion the conductors consult → `agents/faculties/<name>/`. Follow
the Build Agent's shape (a concise `AGENTS.md` opening with its `Tier:` line, a
deterministic entrypoint, and a capability audit of any organ it drives — the
Feature Agent's `MIND_TAXONOMY.md` is that audit for the PyAutoMind/PyAutoMemory
surface). Keep the conductor set small; prefer a faculty when the new thing
only reasons.

**Scaling invariant.** The per-agent roster is not maintained here. Adding an
agent touches only `bin/pyauto-brain` (the registry) and the agent's own
directory (`agents/<tier>/<name>/` with its `AGENTS.md` + entrypoint). The verb
tables below are **generated** from that registry by
`bin/install.sh --write-agents-surface` — never hand-edit this file's roster,
and read each agent's own `AGENTS.md` for its full role.

## Running

<!-- pyauto:commands:begin -->
<!-- Generated by `PyAutoBrain/bin/install.sh --write-agents-surface` from the
     agent registry in `PyAutoBrain/bin/pyauto-brain`. Do not edit between these
     markers — edit the registry there and re-run. Checked by
     `PyAutoBrain/bin/install.sh --check-agents-surface`. -->

The PyAuto **command surface** — every agent verb, runnable on any tool (Claude,
Codex, Cursor; CLI or web) as `bin/pyauto-brain <verb>`. This block lives once in
**PyAutoBrain**'s auto-loaded AGENTS.md, which is present in every session, so the
full verb set is always in context — no per-organ copy needed. Invoking a verb
runs its entrypoint here in PyAutoBrain. On Claude Code the same verbs are also
the `/<verb>` slash commands.

**Conductors** — front doors you drive (decide *and* act):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
| `intake` | Conceive a task: turn raw input into a formal, headed PyAutoMind prompt (files it; never starts dev) | `bin/pyauto-brain intake` |
| `community` | The ears — the organism's receptive function: scan/triage user-filed GitHub issues + PRs and review requests across the repos; drafts stay human-gated, dev work routes via start_dev_for_user (never posts) | `bin/pyauto-brain community` |
| `feature` | Reason over PyAutoMind feature tasks: select, size, phase, plan for start_dev | `bin/pyauto-brain feature` |
| `bug` | The immune system: classify a bug/regression/Heart finding, locate the fix, plan the repair | `bin/pyauto-brain bug` |
| `refactor` | The renewal function: plan behaviour-preserving restructuring — RefactorDecision; default-safe under --auto | `bin/pyauto-brain refactor` |
| `workspace` | The voice — the organism's expressive function: plan/survey workspace + HowTo example authorship (workspace\|howto registers) — WorkspaceDecision (never writes) | `bin/pyauto-brain workspace` |
| `eyes` | The perceptive function — the organism's sense of its own appearance: survey/review a visualization workspace's figure surface, critiques route to intake/start_dev — EyesSurvey/EyesReviewSurface (never renders, never edits) | `bin/pyauto-brain eyes` |
| `profiling` | The proprioceptive function — the organism's sense of its own effort: campaign/ingest/triage plans over the autolens_profiling workspace — ProfilingDecision | `bin/pyauto-brain profiling` |
| `hygiene` | The maintenance function — the organism's sense of its own upkeep: code-quality debt (dev-loop cost + tidiness), delegating fixes — HygieneDecision | `bin/pyauto-brain hygiene` |
| `clone` | The Mitosis Agent: partition the reference assistant, analyze the domain, emit the CloneDecision; --apply --mode lightweight-seed delegates the seed birth to Build | `bin/pyauto-brain clone` |
| `build` | Coordinate execution: consult the vitals faculty, then delegate to PyAutoHands | `bin/pyauto-brain build` |
| `release` | Release door → the Build Agent release mode (single gate); 'release rehearse'/'release validate' drive release validation; 'release nightly' is the scheduled-nightly driver | `bin/pyauto-brain release` |
| `health` | The organism's clinician: run the health loop with a human, dispatch by dispatch, toward green | `bin/pyauto-brain health` |

**Faculties** — read-only opinions the conductors consult (also runnable):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
| `vitals` | Read-only: read the Heart's pulse — the PyAutoHeart readiness verdict (consulted by the conductors) | `bin/pyauto-brain vitals` |
| `review` | Read-only: prepare the branch ReviewSurface — the reviewing agent maps it to CLEAN/FINDINGS/BLOCKED (the ship gate's review leg) | `bin/pyauto-brain review` |
| `memory` | Read-only: recall what the organism knows — a cited digest over PyAutoMemory, autolens_assistant and Mind history | `bin/pyauto-brain memory` |
| `samplers` | Read-only: the motor faculty — SamplerSurface digest over the sampler script tiers, the PyAutoFit search catalogue and the benchmark record | `bin/pyauto-brain samplers` |
| `sizing` | Read-only: the SizingSurface — a difficulty estimate for a PyAutoMind prompt; the single heuristic the intake and feature conductors both consult | `bin/pyauto-brain sizing` |
<!-- pyauto:commands:end -->

Like the other PyAuto repos, PyAutoBrain runs from its checkout (no pip install);
it resolves the sibling `pyauto-heart` and `autohands` binaries from PATH or the
`~/Code/PyAutoLabs/` checkouts.

## The command surface (Brain implicit)

The verb table above is the machinery; humans drive it through short commands
(`/intake`, `/feature`, …) in Claude Code, or discoverable skills in Claude and
Codex. The Brain stays **implicit** — you type a verb, or plain natural language
via `/route`, and it routes to the right agent; normal usage never says
"PyAutoBrain". A few commands are compositions rather than single agents:
`/docs` and `/research` route through the dev-flow with their PyAutoMind
work-type fixed (no dedicated conductor — added only on demonstrated need, never
for symmetry); `/wake_up` composes sync + `/health` + `/hygiene`; `/brain
<agent>` is the raw passthrough. Every command routes **through** the Brain;
none replaces it.

The command bodies live in `skills/<verb>/<verb>.md`; thin `SKILL.md` wrappers
make the same canonical workflows discoverable to skill-aware harnesses.
`bin/install.sh` installs both surfaces without duplicating their bodies. Shared
architecture prose is in [`skills/COMMANDS.md`](skills/COMMANDS.md); the
work-type taxonomy the router uses is `PyAutoMind/ROUTING.md`.

<!-- repos_sync:history:begin -->
## Never rewrite history

Never rewrite pushed history on any repo with a remote — no `git init` over a
tracked repo, no force-push to `main`, no fresh-start "Initial commit", no
`filter-repo` / `filter-branch` / `rebase -i` on pushed branches. To get a
clean tree: `git fetch origin && git reset --hard origin/main && git clean -fd`.
<!-- repos_sync:history:end -->

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
| **Brain** | PyAutoBrain | Reasoning/orchestration layer; how work is decomposed and routed; the specialist agents. |
| **Broca** | PyAutoBroca | Assistant evaluation history, upkeep evidence, collection receipts and a private dashboard. Brain interprets; Mind tracks fixes; public assistants remain independent. |
| **Mind** | PyAutoMind | Intent, goals, priorities, workflow state; every task starts as a markdown prompt here. |
| **Cortex** | PyAutoCortex | The Cortex — what is true in the science: the body map (`projects.yaml`) and one ledger per science project (runs, results, learnings, where to pick up); the science mirror of the Mind. |
| **Memory** | PyAutoMemory | Long-term scientific/software/project knowledge (see science pointer below). |
| **Eyes** | PyAutoEyes | The Eyes — cross-project visualization dashboard over the `<lib>_visualization` repos: their registry, the `gallery/viz_manifest.yaml` read contract and the Pages board linking their PNGs. Renders and copies nothing, never judges figures (the Brain's Eyes conductor does) and never edits plot code. |
| **Ears** | PyAutoEars | The Ears — community listening: read-only public conversation collection, the versioned community snapshot contract, coverage receipts and the dashboard. GitHub stays authoritative; Brain's Community conductor judges and drafts replies; never posts, labels, files issues or exports transcripts. |
| **Heart** | PyAutoHeart | Health/readiness — the authoritative "is it safe to release?" verdict. |
| **Hands** | PyAutoHands | Packaging, tagging, notebook generation, PyPI release execution. |
| **Pulse** | PyAutoPulse | The Pulse — cross-project profiling dashboard over the `<lib>_profiling` repos: campaign intent, instance registry, the versioned `profiling-summary` read contract, ingest receipts and the Pages board. Validates the contract only; never judges, scores or issues verdicts (the Brain's profiling conductor judges). |
| **Insight** | PyAutoInsight | Inference campaign intent, the cross-project inference instance registry, the versioned `inference-summary` read contract, ingest receipts and the evidence dashboard. Projects execute, Cortex records the science, Mind owns task state; never infers scientific acceptance or submits compute. |
| **DNA** | PyAutoDNA | Software-stack specifications, environment inventory receipts, support rationale, upgrade campaigns and adoption history. Brain coordinates, Heart validates readiness, Hands releases, Nerves enforces runtime compatibility; collection never upgrades environments. |
| **Nerves** | PyAutoNerves | The Nerves — the configuration/serialization layer connecting workspace conventions to libraries (layered config, version handshake, test_mode), delivered as the `autonerves` package. |
| **Gut** | PyAutoGut | Lifecycle of condemned self-material (stale branches, stashes, dead code/tests): held as recoverable git refs through a transit window, voided on a sweep. The storage mirror of Memory. |

Call chain (always this order): **Brain → Heart (gate) → Build (execute)**. Brain agents are **conductors** (front-door; a human drives them; they decide *and* act) or **faculties** (read-only opinions the conductors consult; they judge and stop). New capability grows as a faculty, not a new organ, unless it owns state or effects no existing organ can.

Generated from `PyAutoMind/repos.yaml` + `PyAutoBrain/ORGANISM.md`; edit there, then run `python3 PyAutoMind/scripts/repos_sync.py --write`.
<!-- repos_sync:map:end -->

## Working here

Brain plans and coordinates; it owns no task state, health checks or release
mechanics. Mind owns intent/state, Heart gates readiness, Hands executes releases.
Use conductors for decisions and actions; faculties return read-only judgments.
The consultation graph is a DAG: conductors consult faculties, not conductors.
See [ORGANISM.md](ORGANISM.md) for boundaries and [AUTONOMY.md](AUTONOMY.md)
for checkpoint rules. Add a role only on demonstrated need.

Before changing shared board presentation, read the applicable contract in
[shared organism standards](docs/standards.md). Reuse the shared component,
identify its affected consumers and validate adoption; keep domain meanings and
work destinations in their owning renderers.

For development use [skills/WORKFLOW.md](skills/WORKFLOW.md), then the invoked
skill. Read only its current step and applicable environment. Reuse unchanged
instructions already loaded; use [context discipline](skills/CONTEXT.md).
For new agents or command wiring, read [agent reference](docs/agent_reference.md).
Add registry entries in `bin/pyauto-brain` and the agent directory; regenerate
this command table with `bin/install.sh --write-agents-surface`, never by hand.

## Running

<!-- pyauto:commands:begin -->
<!-- Generated by `PyAutoBrain/bin/install.sh --write-agents-surface` from the
     agent registry in `PyAutoBrain/bin/pyauto-brain`. Do not edit between these
     markers — edit the registry there and re-run. Checked by
     `PyAutoBrain/bin/install.sh --check-agents-surface`. -->

Run from the Brain checkout. Read the selected agent's `AGENTS.md` only when
invoking it; `bin/pyauto-brain help <verb>` exposes its full contract.

**Conductors** — front doors you drive (decide *and* act):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
| `intake` | File classified prompts; never start development | `bin/pyauto-brain intake` |
| `batch` | Propose a review-budgeted batch; collect its results | `bin/pyauto-brain batch` |
| `community` | Triage community threads; human-approved replies and development handoffs | `bin/pyauto-brain community` |
| `feature` | Select, size and plan features | `bin/pyauto-brain feature` |
| `bug` | Classify regressions and plan repairs | `bin/pyauto-brain bug` |
| `refactor` | Plan behavior-preserving restructuring | `bin/pyauto-brain refactor` |
| `workspace` | Plan or survey examples and tutorials | `bin/pyauto-brain workspace` |
| `eyes` | Survey figures and route accepted critiques | `bin/pyauto-brain eyes` |
| `profiling` | Plan campaigns; ingest results; triage profiling drift | `bin/pyauto-brain profiling` |
| `cortex` | Pull science runs and record human checkins | `bin/pyauto-brain cortex` |
| `hygiene` | Prioritize upkeep and delegate fixes | `bin/pyauto-brain hygiene` |
| `clone` | Plan assistant births or synchronize generic files | `bin/pyauto-brain clone` |
| `build` | Consult vitals and coordinate Hands execution | `bin/pyauto-brain build` |
| `release` | Coordinate release rehearsal, validation and nightly execution | `bin/pyauto-brain release` |
| `health` | Assess health and route repairs | `bin/pyauto-brain health` |

**Faculties** — read-only opinions the conductors consult (also runnable):

| Verb | Purpose | Entrypoint |
|------|---------|------------|
| `vitals` | Read authoritative Heart readiness | `bin/pyauto-brain vitals` |
| `review` | Prepare independent CLEAN/FINDINGS/BLOCKED branch review | `bin/pyauto-brain review` |
| `memory` | Recall cited scientific and task history | `bin/pyauto-brain memory` |
| `samplers` | Inspect sampler coverage, tiers and benchmarks | `bin/pyauto-brain samplers` |
| `sizing` | Estimate task difficulty | `bin/pyauto-brain sizing` |
<!-- pyauto:commands:end -->

Like the other PyAuto repos, PyAutoBrain runs from its checkout (no pip install);
it resolves the sibling `pyauto-heart` and `autohands` binaries from PATH or the
`~/Code/PyAutoLabs/` checkouts.

<!-- repos_sync:remote:begin -->
## Remote sessions (Claude Code on web and mobile)

Three facts, measured in a web/mobile container. A session holding several
organs is cwd'd at the repos' *parent*, where no project hook fires, so
nothing has set it up — this block is what does.

- **Bootstrap in the first turn, unconditionally** — before the first test
  command, not as a remedy: `bash PyAutoMind/scripts/session_bootstrap.sh`
  (`--check` reports only). It supplies pytest/PyYAML/xdist and **unshallows
  the clones**, without which `git merge-base --is-ancestor` calls a merged
  branch "not an ancestor" and the close-out acts on it.
- **Run the suite in parallel**: `python3 -m pytest -q -n auto` (4 cores,
  ~3.5x).
- **There is no `gh`, and installing one does not help** — it authenticates,
  then 403s every repo-scoped call through the egress proxy. GitHub is the
  `mcp__github__*` tools; `PyAutoBrain/skills/GITHUB_ACCESS.md` maps each
  `gh` operation onto its tool and is the one full page on the subject.
<!-- repos_sync:remote:end -->

## Commands and communication

Users invoke verbs or natural language; Brain stays implicit. `/docs` and
`/research` fix a dev work type; `/prm` merges and closes out a task; `/brain`
is a raw passthrough. Canonical bodies are `skills/<verb>/<verb>.md`, discovered
through thin `SKILL.md` wrappers. The agents/workflows directory is `board/`; it routes unspecified tasks and
retains compact overnight and maintenance surfaces.

Answer first, briefly; link instead of pasting. Expand plans awaiting approval,
decision surfaces, failures/blockers and requested explanations enough to judge.
Keep structured decisions, review surfaces and verdicts complete. These rules
apply to surrounding chat, not to the defined artifact schema.

<!-- repos_sync:history:begin -->
## Never rewrite history

Never rewrite pushed history on any repo with a remote — no `git init` over a
tracked repo, no force-push to `main`, no fresh-start "Initial commit", no
`filter-repo` / `filter-branch` / `rebase -i` on pushed branches. To get a
clean tree: `git fetch origin && git reset --hard origin/main && git clean -fd`.
<!-- repos_sync:history:end -->

<!-- repos_sync:deliverable:begin -->
## Sessions end at their deliverable

A session ends when it reports its deliverable — never arm anything that
outlives the turn to wait for CI, a review or a merge: no `send_later`, no
`subscribe_pr_activity`, no `CronCreate`, no `ScheduleWakeup`, no `/loop`, no
`RemoteTrigger` create/update/run. Judge once, report, stop; the human re-runs
`/prm` (or the batch review) when it is green. Measured: five batch members
armed hourly check-ins on 2026-08-31, and a mobile `/prm` re-armed a 60-minute
`send_later` hourly all night on 2026-09-03 with no task active, draining usage.
<!-- repos_sync:deliverable:end -->

<!-- repos_sync:filing:begin -->
## Where to file

Questions, help with code or an analysis, ideas, bug reports and results from a
user or collaborator — or an agent acting for one — go to
<https://github.com/orgs/PyAutoLabs/discussions> in the matching category
(Help & Questions, Ideas & Proposals, Bugs & Errors, Show and tell;
Announcements is maintainers-only), never to this repo's Issues. An agent never
runs `gh issue create` for such a report: it drafts the title, category and
body and hands them to the human (sessions cannot create Discussions). Only the
development flow — Mind prompt → `/start_dev` → `/create_issue` → one issue per
task → PR — opens issues here. Why: `PyAutoMind/policy/community_surface.md`.
<!-- repos_sync:filing:end -->

Codex loads this repo's generated safety registrations from `.codex/hooks.json`
only after the project layer and exact current hook hash are reviewed and trusted
with `/hooks`; changed or untrusted hooks are skipped. The adapter registers the
shared-Mind commit guard and end-at-deliverable guard. It intentionally does not
copy the Claude remote-session Python `SessionStart` bootstrap; local Codex work
continues to source the workspace `activate.sh` normally.

<!-- repos_sync:standards:begin -->
## Shared standards

Before changing a shared interface, consult the applicable
[organism standard](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/docs/standards.md)
on demand, identify affected consumers, and validate their adoption. Change
generated guidance at its canonical source and regenerate.

For board changes, follow the applicable sizing, navigation and orchestration
standards and reuse Brain’s shared components. Keep domain data, prompt meaning
and approval boundaries with the board’s owner.
<!-- repos_sync:standards:end -->

# The PyAuto organism

The **one canonical page** for the organs, their boundaries, and the call
chain. Every other repo links here instead of restating this — if you are
editing organism prose anywhere else, stop and edit this file.

The organism is an agentic AI ecosystem for **human-led, natural-language
software development**: you describe what you want in plain English, the
organs plan, build, test and release it, and you make every judgment call.

## The organs

| Organ | Repo | Role and boundary |
|-------|------|-------------------|
| **Brain** | PyAutoBrain | Figures out *how* — reasoning, planning, decomposition, routing; hosts the specialist agents. Owns **no state, no health checks, no execution mechanics**. |
| **Mind** | PyAutoMind | Decides *what* — intent, goals, priorities, workflow state, the prompt registry and taxonomy. Also holds the body map (`repos.yaml`, the single source of repo identity). |
| **Cortex** | PyAutoCortex | Keeps track of *what is true* — the science body map (`projects.yaml`) and **one ledger per science project** (`## Now`, the `## Runs` on the cluster, a `## Log` that only gets longer); the science mirror of the Mind (runs and a dated log ↔ prompts and PRs). Not a task tracker: it records cluster facts and the human's words, never a verdict of its own. |
| **Memory** | PyAutoMemory | Long-term knowledge — *what the science says* (literature wikis, concepts, bibliographies). Operational history — *what the organism did* — lives in Mind (the `complete/` records, issues), not here. |
| **Eyes** | PyAutoEyes | Sees *what the figures look like* across the `<lib>_visualization` project repos. Owns the instance registry, the manifest read contract and the dashboard that links to project-owned PNGs. Project repos own producers, render harnesses, figures and manifests; Eyes renders no figures and copies none. The Brain's Eyes conductor drives review and judgment; accepted critiques route through intake, never directly into library plot code. |
| **Ears** | PyAutoEars | The Ears — the community listening organ: owns read-only public conversation collection, the versioned community snapshot contract, coverage receipts and the dashboard. GitHub conversations remain authoritative; Brain’s Community conductor owns judgement, reply drafts and development routing, and Mind owns task state. Never posts replies, labels or issues, exports raw transcripts or private sources, or treats unknown coverage as no work. |
| **Heart** | PyAutoHeart | Determines whether the organism is healthy. `pyauto-heart readiness` is the **authoritative** GREEN/YELLOW/RED "is it safe to release?" gate. An observer: never writes into other repos, never triggers Build. |
| **Hands** | PyAutoHands | Builds and releases — packaging, tagging, notebook generation, PyPI via `release.yml`. A pure executor: runs no readiness checks and never re-derives a gate decision. |
| **Pulse** | PyAutoPulse | Feels *how fast the organism runs* across the `<lib>_profiling` project repos. Owns profiling campaign intent and pending domain tasks, the profiling instance registry, the versioned `profiling-summary` read contract, the ingest receipts (resolved commit per project per render) and the cross-project board. Validates the exchange contract only; project repos own producers, results, pins, drift policy and their own Pages page. Never moves pins, combines unmatched timings, applies the compile threshold to runtime, computes an ecosystem-wide speed score or issues a readiness verdict; the Brain's profiling conductor (`triage`) is the only judge. |
| **Insight** | PyAutoInsight | Owns inference campaign intent and pending domain tasks, the cross-project inference instance registry, versioned `inference-summary` read contract, ingest receipts and evidence dashboard. Projects own execution, producers and raw samples; Cortex owns scientific run records, observations and human conclusions; Mind owns bounded implementation lifecycle and repository claims. Never infers scientific acceptance from execution, ranks incompatible runs or submits compute on refresh. |
| **DNA** | PyAutoDNA | Owns software-stack specifications, environment inventory receipts, compatibility decisions, upgrade campaigns and adoption history across local, RAL and CI. Brain coordinates updates; Heart owns validation/readiness; Hands owns release execution/provenance; Nerves owns runtime compatibility. Package repositories remain authoritative for requirements. Collection never upgrades an environment or treats missing observations as passing evidence. |
| **Nerves** | PyAutoNerves | The configuration/serialization layer (`autonerves`) — layered config with overrides, the workspace↔library version handshake, `test_mode`, FITS/JSON I/O. Connects the organism's conventions to every library; the base layer the scientific libraries all import. |
| **Gut** | PyAutoGut | Owns the lifecycle of *condemned self-material* — stale branches, stashes, dead code/tests. Holds each as a durable, recoverable git ref through a transit window and **voids** it on a sweep. The storage mirror of Memory (retention ↔ release); the hygiene conductor drives it, as vitals reads Heart. |

*Hands* and *Build* name the **same organ** (PyAutoHands) throughout this
document: the organ is the **Hands**, and *Build* is the call-chain step it
performs. (The Hands repo was renamed PyAutoBuild → PyAutoHands; the *Build*
call-chain shorthand and the `autohands` package/CLI keep their names. The
Nerves repo was likewise renamed PyAutoConf → PyAutoNerves, its package
`autoconf` → `autonerves`.)

The scientific libraries (PyAutoFit, PyAutoArray, PyAutoGalaxy, PyAutoLens) and
the workspaces are **capabilities the organism uses, not organs**. The full
inventory is `PyAutoMind/repos.yaml`.

## Responsibility roles

**Library, project and organ** name responsibilities, not levels in a strict
containment tree. A **repository** is the versioned container for those
responsibilities; it is not a separate middle level.

| Role | Responsibility | Examples |
|------|----------------|----------|
| **Library** | Reusable capabilities, their APIs and behavioral contracts. | The scientific libraries and the `autonerves` package. |
| **Project** | Concrete applications, examples or measurement environments; their producers, execution details and local artifacts. | User workspaces, tutorials, profiling, inference and visualization repos. |
| **Organ** | An organism-wide responsibility with explicitly owned state or effects and interfaces to other roles. | Mind's development intent, Cortex's science records, Eyes' cross-project view. |

Relationships can cross these roles: several projects can use one library,
and several organs can read evidence from one project. Nerves is an organ
that also supplies a library package. Eyes demonstrates a project-to-organ
read contract; it does not make evidence aggregation the definition of every
organ or move project producers into the organ. Cortex retains science
records and the human's observations; project artifacts do not replace them.

**Workspace** retains its established meaning for example/tutorial projects
and, when qualified, a local checkout environment. The broader project role
can include workspace-family, `howto` and `project` categories without renaming
them.
The category in `PyAutoMind/repos.yaml` still selects the repository's existing
workflow and validation/release contract, as described in the
[category contract](docs/satellites.md). In particular, the `project` category's
"no release mechanics" expectation does not transfer to every repo serving a
project role. A responsibility role is not a `category: project` filter or a new registry
field. The body map's existing `role` and `public_role` strings remain descriptive
text, not a responsibility-role classification.

## The call chain (always this order)

```
Brain  →  Heart (gate)  →  Build (execute)
```

The Brain asks `pyauto-heart readiness --json`, reasons over the verdict, and
only on **GREEN** triggers Build. Heart never triggers Build; Build never
re-derives a decision the Brain already made.

## Agents: conductors and faculties

Brain agents live in two tiers, split by one question — *does it act, or only
opine?*

- **Conductors** (`agents/conductors/<name>/`) — front-door agents a human
  drives; they decide **and** act, delegating execution to the organs.
- **Faculties** (`agents/faculties/<name>/`) — read-only opinions the
  conductors consult; they judge and stop, never dispatch or mutate.

The consult graph is a DAG: **conductors consult faculties; faculties read
their sensor organ; only the vitals faculty talks to Heart.** A conductor never
*consults* another conductor — if it wants one's opinion, that opinion should
be a faculty. (A conductor may *delegate execution* to another conductor's
organ, which is the normal Brain → organ chain, not consultation.)

Keep the conductor set small and human-meaningful (bounded by the verbs a
human types); let faculties multiply behind them.

## Growth rule: no new organs by default

New capability grows as a **faculty** (cheap: one directory, one doc, one
script), not as a repo. A new organ costs an `AGENTS.md`, install wiring, a body-map row and boundary prose — it must earn that by
owning state or effects no existing organ can. Five capabilities have earned
organ status that way. Configuration/signalling is the **Nerves**
(PyAutoNerves), the base config/serialization layer every library imports — new
config surfaces belong there, not in a new organ. Keeping track of what is
true is the **Cortex** (PyAutoCortex), the second organ to earn it: it owns
state no organ owned before — the science body map and the per-project
ledgers — so science runs and the human's notes on them belong there, not in
the Mind. Seeing what the software shows is the **Eyes** (PyAutoEyes): it owns
the cross-project instance registry, manifest read contract and dashboard.
Each visualization project retains its render harness, figures and generated
manifest; the organ reads those manifests and links to the figures. The
Brain's Eyes conductor owns review and judgment. Feeling how fast the software
runs is the **Pulse** (PyAutoPulse), the fourth: the same layering over the
`<lib>_profiling` project repos — it owns the profiling instance registry, the
versioned `profiling-summary` read contract, the ingest receipts and the
cross-project board, while each profiling project keeps its producers, results
and drift policy and the Brain's profiling conductor stays the only judge. Community listening is the **Ears** (PyAutoEars), the fifth: it owns the
versioned public conversation snapshot, collection coverage receipts and board.
GitHub owns conversations; Brain owns judgement and approved response routing;
Mind owns tasks. Unknown or stale coverage never becomes a no-work claim.

**Insight** (PyAutoInsight) owns inference campaign coordination and pending
domain tasks, plus its inference exchange contract, instance registry, receipts
and evidence board. It uses project drivers and existing Brain routes, with no
new conductor. Cortex remains authoritative for scientific records and
conclusions; Mind retains implementation lifecycle and claims. A dashboard alone does not
waive the state-or-effects requirement for a new organ. The human interaction
layer is the command surface (`/route` + the verb commands), which is part of
Brain.

## Software-stack identity and adoption

DNA owns the persistent environment registry and immutable stack specifications,
plus support rationale, inventory receipts and upgrade/adoption history. This is
state distinct from runtime configuration in Nerves and readiness in Heart.
Source checkouts are identified by commit and dirty state; published wheels by
version and source provenance; workspace declarations are compatibility floors.
Frozen source version stamps are not compared to wheel versions as an equality
check. Upstream availability, declared compatibility, tested combinations,
recommended stacks and observed installations remain separate facts.

Brain coordinates proposals using DNA records and existing development/release
workflows. Heart retains the authoritative validation and readiness verdict;
DNA links evidence without re-deriving it. Hands retains release execution and
provenance. Mind tracks implementation tasks. Project campaigns retain their
original stack identity; adoption changes the default for new work only through
an explicit operation. Dashboard refreshes collect and render, never install,
submit compute or mutate live environments.

## Broca — assistant evidence

PyAutoBroca owns assistant evaluation history, collection receipts and the private
assistant upkeep board. Public assistants retain definitions and reproducible
runners, remain independently usable, and never depend on Broca. Brain interprets
evidence and routes accepted changes through Mind; Cortex retains science
records, Heart retains readiness. Benchmarks and maintenance inventory are
separate evidence kinds. Missing or incomparable results never establish a pass.
Broca's board consumes the shared presentation contract; its private registration
must not create a public Pages link. Public export requires separately reviewed
sanitization. Broca does not automatically launch model or HPC campaigns.

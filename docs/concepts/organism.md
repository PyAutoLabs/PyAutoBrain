# The organism

The system is organised around **organs**, each with an explicit responsibility,
working with libraries and projects. Their boundaries are load-bearing. The canonical
definition lives in the Brain repo as
[ORGANISM.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md)
— one page every organ links to instead of restating. This page summarises
it and adds the framework/instance distinction an adopter needs.

| Organ | Repo | Job |
|-------|------|-----|
| **Brain** | PyAutoBrain | Figures out *how* — reasoning, planning, routing; hosts the specialist agents. Owns no state, no health checks, no execution mechanics. |
| **Mind** | PyAutoMind | Decides *what* — intent, goals, priorities, workflow state, the prompt registry, and the body map (`repos.yaml`). |
| **Cortex** | PyAutoCortex | *Keeps track of what is true* — the science body map (`projects.yaml`) and one ledger per science project (`## Now`, the `## Runs` on the cluster, a `## Log` that only gets longer); the science mirror of the Mind (runs and a dated log ↔ prompts and PRs). Not a task tracker: it records cluster facts and the human's words, never a verdict of its own. |
| **Memory** | PyAutoMemory | *Knows* — long-term domain knowledge: literature wikis, concepts, bibliographies. Pull-only; consulted, never load-bearing at runtime. |
| **Eyes** | PyAutoEyes | *Sees* — the cross-project visualization registry, manifest read contract and dashboard. Project repos render and hold figures; Eyes links to them. The Brain's Eyes conductor handles judgment. |
| **Heart** | PyAutoHeart | Decides whether the organism is *healthy*. `pyauto-heart readiness` is the authoritative GREEN/YELLOW/RED release gate. An observer: never writes into other repos, never triggers a build. |
| **Hands** | PyAutoHands | *Does* — packaging, tagging, notebook generation, PyPI releases. A pure executor: never re-derives a gate decision. |
| **Pulse** | PyAutoPulse | *Feels* — the cross-project profiling registry, the versioned `profiling-summary` read contract, ingest receipts and dashboard. Project repos produce and hold timings; Pulse validates the exchange and links to them. The Brain's profiling conductor handles judgment. |
| **Nerves** | PyAutoNerves | *Connects* — the configuration/serialization layer (`autonerves`): layered config, the workspace↔library version handshake, `test_mode`, FITS/JSON I/O. The base layer every library imports. |
| **Gut** | PyAutoGut | *Sheds* — the lifecycle of condemned self-material (stale branches, stashes, dead code/tests): holds each as a durable, recoverable git ref through a transit window, then **voids** it on a sweep. The storage mirror of Memory (retention ↔ release); the hygiene conductor drives it, as vitals reads Heart. |

Everything else — the libraries being developed, their example workspaces,
test suites, tutorials — is a **satellite**: a capability the organism works
*on*, not part of the organism itself. The satellite kinds and what the
organism expects of each are the {doc}`category contract <../satellites>`.

## Responsibility roles and repository categories

The canonical [responsibility roles](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md#responsibility-roles)
distinguish reusable library capabilities, concrete projects and organism-wide
responsibilities. They describe relationships rather than a containment tree:
Nerves, for example, is an organ that supplies a library package. A repository
is the container, and a workspace is one familiar kind of project.

These roles do not replace the {doc}`repository categories <../satellites>` or
change their workflow and release gates. Profiling, inference and visualization
repos illustrate the project role; Eyes and Pulse provide cross-project organ
views over the visualization and profiling projects. The project-to-organ
boundary is described in {doc}`../organs/eyes` and {doc}`../organs/pulse`.

## The call chain

```
Brain  →  Heart (gate)  →  Build (execute)
```

Always in that order — *Build* is the call-chain step, the Hands are the
organ that performs it (ORGANISM.md). The Brain asks Heart for the readiness
verdict, reasons over it, and only on GREEN triggers Build. Heart never
triggers a build; the Hands never re-check readiness. Each boundary exists so
that no organ has to be trusted to police itself.

## Framework vs instance

The organs split on one line that matters for adoption:

- **Framework organs — Brain, Heart, Hands.** Code, agents, checks,
  pipelines. Domain facts appear only in declared config surfaces (tables
  and policy files, not logic), and a drift check — the
  {ref}`tenant firewall <tenant-firewall>` — keeps it that way.
- **Instance organs — Mind, Cortex, Memory, Eyes, Pulse, Gut.** Committed
  state, ledgers, knowledge, visualization and profiling registries and shed
  material. These are *inherently yours*: an adopter never forks the upstream
  Mind, Cortex, Memory, Eyes, Pulse or Gut content, they create their own repos with the same documented
  shape.

One more principle worth knowing before you read anything else:
**one canonical page per fact.** Organ boundaries live in ORGANISM.md;
autonomy rules live in
[AUTONOMY.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/AUTONOMY.md);
repo identity lives in the Mind's `repos.yaml`. Everything else links. When
prose is duplicated it rots, and an agent acting on rotten prose does real
damage — so the system treats duplication as a bug, and backs the important
cases with machine drift-checks.

---
orphan: true
---

# Library, project and organ roles in the agentic ecosystem

**Research proposal — 2026-10-01.** This note informs an architecture decision;
it does not change the organism's policy, registries or agent instructions.
Prepared for [Brain #440](https://github.com/PyAutoLabs/PyAutoBrain/issues/440).
Sources below are pinned to the inspected commits. No scientific campaigns were
run, and no performance or inference result is being endorsed.

## Recommendation

The proposal is to adopt **library, project and organ** as a vocabulary for responsibility and
context selection. Use the three roles as a useful view of the ecosystem, with
explicit relationships between them, rather than a compulsory containment tree.
A **repository** is the versioned container for a role; it is not the middle
level. A **workspace** remains a familiar kind of project, especially an example
or tutorial collection, and can also mean the local development checkout.

The practical change would be to make an agent answer three questions before
acting: *where is the evidence produced, who owns the relevant decision or
record, and where should a change be made?* These answers can name different
repos. This improves routing without creating one new AI agent per level.

The visualization design already supplies a concrete pattern: library plot
code is exercised by project producers; projects retain the figures and
manifests; Eyes supplies the cross-project view; the Brain Eyes conductor
handles review and routes accepted critiques. [Eyes contract][eyes_contract]

Profiling and inference could use the same project-to-organ relationship.
The Eyes contract itself describes the same project/organ layering for profiling
and inference under the Brain board, establishing a precedent for aggregation
without first creating dedicated organs. [Existing layering][eyes_contract]
Their proposed organs should own cross-project membership, read contracts,
coverage and freshness views, and dashboard projections. Measurement code and
run artifacts stay in projects, scientific progress stays with Cortex, and
software-change intent stays with Mind. Organ birth remains conditional on a
human-approved responsibility that existing organs cannot adequately own,
consistent with the [current growth rule][organism]. A dashboard is a useful
interface, but its existence alone does not establish that responsibility.

## What exists, and where the descriptions disagree

| Inspected evidence | Architectural implication |
|---|---|
| [Mind's body map][body_map] already categorizes profiling, inference and visualization repos as `project`, separately from organs, libraries and workspaces. | Reuse existing identities and categories; do not introduce another repo inventory. The proposed roles are broader than these categories. |
| [Eyes' registry][eyes_registry] contains lens, galaxy, fit and CTI instances. Its [contract][eyes_contract] leaves producers, render harnesses, PNGs and manifests in the project repos. | Promotion produced a cross-project organ while preserving per-library producers; it did not eliminate the project role. |
| [Profiling's instructions][profiling_project] assign likelihood timing, breakdowns and resource measurements to standalone scripts and versioned results. [Inference's instructions][inference_project] assign sampler/pipeline reliability and the cost of an answer to a separate project. | Timing one likelihood and evaluating an inference procedure are related but different measurement domains. |
| [Cortex's current instructions][cortex] define a science body map and per-project Now / Runs / Log ledgers; scientific results and lessons are recorded at the human's request. | An inference dashboard must not become a second science ledger or turn metrics into accepted scientific conclusions. |
| The [cockpit feed][feed] already separates status, evidence links, actions and human decisions; descriptive action metadata is not execution authorization. | Reuse this attention interface, while keeping detailed domain evidence in project-owned formats. |

Two documentation discrepancies matter to this design. In the inspected
[ORGANISM.md][organism], the Eyes row and growth example still say the organ
renders/holds figures and that figures do not belong in per-library galleries.
That conflicts with the explicit project/organ split in the newer operational
[Eyes contract][eyes_contract] and body-map role. This note describes that split
as the implemented design; it does not silently amend canonical policy. The same
stale rendering ownership also appears in [the organism concepts page][organism_concepts],
so reconciliation must cover that copy too.

Similarly, inference's [CORTEX.md][inference_cortex] and
[agent instructions][inference_project] still point to task/ruling surfaces, whereas [Cortex's current contract][cortex] explicitly describes the
ledger model and freezes the former task/ruling archives. Correcting these
references is a separate follow-up. The architectural lesson is to name an
interface owner and record which contract was inspected; proximity of a README
to the code does not guarantee that its cross-repo instructions are current.

## Vocabulary and alternatives

| Term | Recommended meaning | Limitation or alternative |
|---|---|---|
| **Library role** | Reusable computational APIs and shared implementations, with behavioral tests and release contracts. | Prefer this to “source-code level”: projects and organs also contain source code. A reusable capability need not be scientific. |
| **Project role** | A concrete application, tutorial, benchmark or campaign environment that exercises capabilities and owns its producers and local evidence. | Includes `*_workspace`, `*_profiling`, `*_inference` and `*_visualization` cases without requiring repo renames. The role is a superset of the existing [satellite categories][satellites], not a category rename: the `project` category's “no release mechanics” expectation does not transfer to the role, and workspace release gates remain unchanged. Not every `category: project` entry is a measurement project. |
| **Organ role** | An organism-wide responsibility with an explicit owner, durable state or effects, and interfaces to other roles. | Cross-project evidence aggregation describes Eyes and the proposed measurement organs; it does not define every organ. |
| **Repository** | Versioning, contribution and deployment boundary. | All three roles can inhabit repos. “Repo level” cannot distinguish projects from organs. |
| **Workspace** | Existing example/tutorial project terminology, or the local execution/checkout environment, qualified by context. | Familiar, but overloaded. Retain established names; use “project” in general architecture prose. |

A strict three-level tree is attractive for navigation but fails for Nerves,
which is both an organ and a reusable library package, and for projects consumed
by several organs. [Nerves and other boundaries][organism] A terminology-only
change is the cheapest alternative and may be sufficient if agents already
route correctly. A generic graph framework or a mandatory new `level` field
would add machinery before demonstrating a need. Prefer a vocabulary plus a
small, tested routing convention first.

## Relationships and ownership

The following is a responsibility diagram, not a process that automatically
executes actions. “Future” nodes are proposals, not installed organs.

```text
Library APIs ── exercised by ──> Project producers
                                ├─ visualization figures/manifests ──> Eyes
                                ├─ timing results ──> future profiling organ
                                └─ inference results ──> future inference organ
                                                        │
                         domain dashboards / attention feeds
                                                        │
                                                        v
                                                   Brain board
                                                        │
                                                Human + conductor
                                              /                   \
                           software change: Mind             science: Cortex
                                    │                       Now / Runs / Log
                              start_dev workflow
                                    │
                          owning library/project/organ
```

Cortex can track science in a project whose measurements are also read by an
organ. Heart can consume relevant validation evidence without owning the
measurement campaign. The Brain board can link directly to a project dashboard
before any dedicated organ exists. Neither a project-to-organ edge nor a board
link confers parent-child ownership of the entire repository.

| Responsibility | Authoritative owner | Consumers and constraints |
|---|---|---|
| Reusable behavior, API fixes and numerical correctness | Relevant library; shared configuration/serialization in Nerves | Projects exercise it; a dashboard cannot change its release contract. |
| Dataset/config choice, simulation, benchmark/render scripts and execution details | Project repo and its run tooling | A conductor routes authorized work to that tooling. No migration into an organ is implied. |
| Figures, measurements, samples and run provenance | Producing project | Commit small summaries where appropriate; retain bulk inference output under project storage rules. Organ views link to evidence rather than copy it. |
| Domain membership, versioned read contract and cross-project projection | Eyes today; proposed profiling/inference organs if approved | Each organ reads project evidence and reports missing, incompatible or stale inputs. |
| Review, triage, campaign planning and action routing | Brain conductors, with faculties supplying bounded opinions | Domain aggregation is not a separate decision-making authority. Human judgments remain explicit. |
| Development intent and issue/PR lifecycle | Mind | A finding becomes development work through intake/start_dev; retain a link to its evidence. |
| Scientific progress, runs, human observations and lessons | Cortex's science map and ledger contract | Projects/organ views may link to the ledger; they must not invent or duplicate its conclusions. |
| Readiness and release execution | Heart and Hands respectively | Profiling health signals do not make the profiling organ the release gate. |

This assignment follows the [development workflow][workflow], [Cortex
contract][cortex] and [Eyes contract][eyes_contract]. Inference output illustrates
why physical storage differs from logical ownership: its instructions retain
bulk output on disk and commit small result rows, so “project owns evidence”
does not mean “put every artifact in Git”. [Inference storage][inference_project]

## How agents would use the distinction

Proposed routing convention, expressed as behavior before adding any schema:

1. Resolve repository identity through Mind's body map and existing path
   resolver. Preserve its registered category and workflow; the proposed role is
   not a `category: project` filter or a replacement for release rules. If
   starting from an organ, use its registry to select the project.
2. Read the producer's manifest/result and the relevant read contract. Preserve
   the evidence URL or path, revision, run identity and measurement conditions
   that are actually available; mark missing provenance rather than infer it.
3. Classify the intended action: inspection, scientific run/check-in, producer
   repair, reusable-library repair, or organ view/contract repair. Select the
   owner of that action, not necessarily the repo containing the dashboard.
4. Load that owner's instructions and only the dependent APIs/contracts needed
   for the task. Use existing conductors and faculties; do not load every linked
   repo or spawn an agent just because another role appears.
5. Return the decision and evidence to the appropriate existing record. Apply
   existing approval, worktree and shipping gates to any implementation.

This extends the existing [context discipline][context]. A compact reasoning
record can carry `evidence`, `producer`, `proposed change owner`, `action door`
and `reason` in ordinary prose. Do not introduce another durable task registry.

### Example 1: a visualization defect

A human notices a bad axis label on the Eyes dashboard. Start with the lens
registry entry, the figure's manifest `producer` and library versions, then the
project producer and the specific plotting call. If the producer supplied a
bad label, its project owns the fix. If a valid call exposes a shared plotting
bug, the owning library owns the fix. If a project manifest names the wrong
file, or its own `GALLERY.md` links incorrectly, the project owns the fix. If
the manifest entry is correct but the Eyes dashboard joins its URL incorrectly
or emits the wrong link, Eyes owns the fix. Missing/stale renders first
require restoring evidence, not an assumed plot-code defect.

Use the existing Eyes survey/review path; route an accepted critique through
intake/start_dev. Attach the figure and producer provenance to that task, then
regenerate the project artifact and refresh the organ view after the fix.
This is the [existing Eyes conductor boundary][eyes_agent], made explicit as
an ownership decision.

### Example 2: profiling drift

A project timing row slows down. Today it can be inspected through the project
surface and profiling conductor; a future organ would make cross-project
coverage/drift visible. Read the comparable baseline and run conditions before
calling it a regression: dataset/model, hardware/device, numerical precision,
software versions and measurement axis matter. Compilation cost and steady-state
runtime must not be compared as the same quantity.

The existing profiling `triage` path distinguishes stale pins and environmental
causes from library regressions. Repair a measurement script in the project,
route a verified library regression through bug/intake, and treat a justified
baseline update as a measurement-lifecycle action. A missing or incompatible
row is unknown evidence, not a zero-time measurement or a pass. Heart still
owns the readiness consequence. Slow CI tests belong to hygiene/ci-speedup,
not this modelling-performance domain. [Profiling conductor][profiling_agent]

### Example 3: an inference benchmark finding

A sampler appears faster. Read the project's result row and linked samples,
convergence evidence, seeds and model/configuration before recommending it.
A fast unsuccessful run does not establish improved inference; a faster
likelihood does not by itself establish a cheaper reliable answer. Start with
project evidence, then use the read-only [samplers faculty][samplers] for
relevant search context when useful.

A decision to run more experiments or record an interpretation uses the Cortex
science path; the human decides what becomes a result or lesson. A faulty
benchmark/pipeline goes through Mind into the project; a demonstrated reusable
sampler defect goes through Mind to its library owner. A new sampler trial can
use the existing sampler-pipeline door. This proposal does not invent an
`/inference` conductor or let an inference dashboard autonomously promote a
sampler. [Inference remit][inference_project], [Cortex policy][cortex]

## Minimal metadata and read contracts

Keep **repository identity** in Mind `repos.yaml`, **science project identity
and synchronization** in Cortex `projects.yaml`, and **domain membership and
read endpoints** in the domain organ's registry. These answer different
questions. Eyes already follows the identity convention: its registry `repo`
field names the project in Mind's body map. Future registries should retain that
convention and reference Cortex project keys where applicable; they should not become a second catalogue
of clone paths, remotes or science state.

Eyes already repeats some path/GitHub information in its registry. Preserve
compatibility now; a separately approved follow-up could validate those copies
against Mind or derive them. Do not silently change that established schema as
part of naming the levels. [Existing Eyes fields][eyes_contract]

For new measurement organs, first inventory actual project outputs. The
[profiling result conventions][profiling_results] and [inference storage
contract][inference_project] differ; neither is established here as a universal
manifest. Prototype readers against existing formats before imposing changes.
A narrow, versioned summary contract should eventually address:

| Concern | Proposed behavior |
|---|---|
| Identity and provenance | Identify project, producer/run, evidence location and available source/package revisions. Preserve links to detailed artifacts. |
| Comparability | Domain-specific configuration, dataset/model, device/hardware, precision and measurement method. For inference, preserve seed/repetition and validity/convergence context. Keep incomparable rows separate. |
| Freshness | Distinguish measurement time, source revision and dashboard render time. Rebuilding HTML cannot make an old measurement fresh. Use producer-declared policies, not a guessed global expiry. |
| Coverage and failure | Separate absent, unreadable, incompatible, stale, failed and successfully observed results. A partial dashboard cannot silently claim complete coverage. |
| Evolution | Explicit schema/reader support; additive fields remain compatible where specified, breaking changes require coordinated version support. |
| Actions | Link evidence to an existing command or manual handoff. Metadata describes an action; it neither approves nor executes it. |

The Eyes schema already demonstrates versioning, producer links and artifact
integrity. The cockpit [state feed][feed] already provides attention status,
optional deadlines, evidence links and action descriptions. Reuse that feed for
an organ's summary, but do not force timing samples or posterior diagnostics
into it. In particular, its `updated` is render time, not measurement time.

## Staged adoption and decisions

These are proposed follow-ups, not prompts filed or changes performed by this
research task. Organ names remain undecided.

| Stage | Scope and owner | Dependency and completion criterion |
|---|---|---|
| 1. Decide vocabulary and reconcile descriptions | Brain canonical organism prose; stale project-to-Cortex references in their owning repos | Human accepts the responsibility model. Eyes descriptions agree with its live contract; Cortex references agree with the ledger model. Generated copies follow their existing generators. |
| 2. Trial the routing convention | Brain instructions plus three bounded example reviews | Depends on stage 1. Compare current and proposed routing: correct change owner, evidence trail, necessary context only, no extra approval/record system. Retain terminology-only adoption if routing does not improve. |
| 3. Specify profiling/inference aggregation independently | Relevant Brain planning plus each proposed organ's responsibility statement | Depends on accepted boundaries, not on creating every future project. Inventory existing dashboards/results and define consumers, missing-data behavior, comparability and overlap with Cortex/Heart. |
| 4. Pilot one organ at a time | Project adapters if needed; approved new organ registry/reader/dashboard | Depends on a human organ-birth decision and stage 3's contract. Integrate the live lens project first; exercise a fixture for a second library and unavailable/incompatible data. Add real sibling projects only when needed. |
| 5. Generalize only demonstrated common behavior | Existing contract/tool owners | After both domains provide evidence of reuse. Factor proven shared reading/identity logic; avoid a generic framework built solely from Eyes. |

The existing Mind task
`draft/feature/pyautobrain/register_profiling_dashboard_on_brain_board.md`
registers the project profiling dashboard and explicitly excludes organ birth.
It can proceed independently; do not make that useful board link wait for this
architecture, and do not treat completing it as creating a profiling organ.

For each proposed organ, the human decision should name its distinct state or
effects, producer/consumer boundary, value across libraries, and maintenance
cost. A second live producer demonstrates aggregation value, but is not an
invented mandatory birth gate: a planned family plus a tested second-producer
contract can justify building ahead of demand. A cross-project registry alone
is not enough if an existing owner already provides the same responsibility.

Three choices remain: whether “project” is the preferred general term; whether
profiling and inference warrant separate organs now, given their different
comparison semantics; and whether the initial routing trial merits executable
metadata. My recommendation is **project terminology, separate domain contracts,
and a routing trial before new metadata**. Proceed with organ design if its
cross-project responsibility is accepted. The no-new-organ option keeps project
dashboards linked from Brain and science continuity in Cortex, with explicit
ownership and no extra repository cost.

## Validation of the proposal

The Memory faculty was consulted before drafting. It returned relevant Mind
completion records for the Eyes/project split and inference birth, which were
read alongside the current contracts; no relevant scientific-memory page was
identified by that consultation. Private source contents are not reproduced here.

The design is useful if the three examples route to the responsible owner,
load only relevant context, preserve evidence provenance, and leave scientific
judgment and release authority with their existing owners. A successful pilot
must also report missing/incompatible inputs honestly and add a second library
without moving its producers into the organ. These are future adoption checks,
not claims that this research has executed the pilot.

The research deliverable covers the five requested outcomes: vocabulary and
alternatives; relationships and responsibilities; three routing examples;
minimal metadata/contracts; and staged follow-ups with a no-change option.
Its citations describe the inspected commits, not a guarantee that every linked
repo remains unchanged after 2026-10-01.

[organism]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/ORGANISM.md
[body_map]: https://github.com/PyAutoLabs/PyAutoMind/blob/c79217c7a72c851fab9718e9865e2eb715770282/repos.yaml
[eyes_contract]: https://github.com/PyAutoLabs/PyAutoEyes/blob/33cde97da61bdbb03a85d020c284404dc399828c/REFERENCE.md
[eyes_registry]: https://github.com/PyAutoLabs/PyAutoEyes/blob/33cde97da61bdbb03a85d020c284404dc399828c/registry.yaml
[profiling_project]: https://github.com/PyAutoLabs/autolens_profiling/blob/227b5c919b1c205962427a6f48fe233770220a69/AGENTS.md
[inference_project]: https://github.com/PyAutoLabs/autolens_inference/blob/656c348fe39e0acca7e6e92fe1f0fb3f55060dc6/AGENTS.md
[profiling_agent]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/agents/conductors/profiling/AGENTS.md
[cortex]: https://github.com/PyAutoLabs/PyAutoCortex/blob/b66d7fd0a20197d0283da8b802059654e891a3ec/AGENTS.md
[context]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/skills/CONTEXT.md
[feed]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/board/state_schema.json
[workflow]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/skills/WORKFLOW.md
[inference_cortex]: https://github.com/PyAutoLabs/autolens_inference/blob/656c348fe39e0acca7e6e92fe1f0fb3f55060dc6/CORTEX.md
[eyes_agent]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/agents/conductors/eyes/AGENTS.md
[samplers]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/agents/faculties/samplers/AGENTS.md
[profiling_results]: https://github.com/PyAutoLabs/autolens_profiling/blob/227b5c919b1c205962427a6f48fe233770220a69/results/README.md

[organism_concepts]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/docs/concepts/organism.md

[satellites]: https://github.com/PyAutoLabs/PyAutoBrain/blob/c7bfd68ed798b67f082d19116d1571d3330f0121/docs/satellites.md

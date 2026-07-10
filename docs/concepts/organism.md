# The organism

The system is organised as a body: each repository is an **organ** with one
job, and the boundaries between them are load-bearing. The canonical
definition lives in the Brain repo as
[ORGANISM.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md)
— one page every organ links to instead of restating. This page summarises
it and adds the framework/instance distinction an adopter needs.

| Organ | Repo | Job |
|-------|------|-----|
| **Mind** | PyAutoMind | Decides *what* — intent, goals, priorities, workflow state, the prompt registry, and the body map (`repos.yaml`). |
| **Brain** | PyAutoBrain | Figures out *how* — reasoning, planning, routing; hosts the specialist agents. Owns no state, no health checks, no execution mechanics. |
| **Heart** | PyAutoHeart | Decides whether the organism is *healthy*. `pyauto-heart readiness` is the authoritative GREEN/YELLOW/RED release gate. An observer: never writes into other repos, never triggers a build. |
| **Hands** | PyAutoBuild | *Does* — packaging, tagging, notebook generation, PyPI releases. A pure executor: never re-derives a gate decision. |
| **Memory** | PyAutoMemory | *Knows* — long-term domain knowledge: literature wikis, concepts, bibliographies. Pull-only; consulted, never load-bearing at runtime. |

Everything else — the libraries being developed, their example workspaces,
test suites, tutorials — is a **satellite**: a capability the organism works
*on*, not part of the organism itself. The satellite kinds and what the
organism expects of each are the {doc}`category contract <../satellites>`.

## The call chain

```
Brain  →  Heart (gate)  →  Hands (execute)
```

Always in that order. The Brain asks Heart for the readiness verdict,
reasons over it, and only on GREEN triggers the Hands. Heart never triggers
a build; the Hands never re-check readiness. Each boundary exists so that no
organ has to be trusted to police itself.

## Framework vs instance

The five organs split on one line that matters for adoption:

- **Framework organs — Brain, Heart, Hands.** Code, agents, checks,
  pipelines. Domain facts appear only in declared config surfaces (tables
  and policy files, not logic), and a drift check — the
  {ref}`tenant firewall <tenant-firewall>` — keeps it that way.
- **Instance organs — Mind, Memory.** Committed state and knowledge. These
  are *inherently yours*: an adopter never forks the upstream Mind or Memory
  content, they create their own repos with the same documented shape.

One more principle worth knowing before you read anything else:
**one canonical page per fact.** Organ boundaries live in ORGANISM.md;
autonomy rules live in
[AUTONOMY.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/AUTONOMY.md);
repo identity lives in the Mind's `repos.yaml`. Everything else links. When
prose is duplicated it rots, and an agent acting on rotten prose does real
damage — so the system treats duplication as a bug, and backs the important
cases with machine drift-checks.

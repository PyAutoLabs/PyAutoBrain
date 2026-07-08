# Clone agent — design (not yet implemented)

> **Status: DESIGN.** This conductor does not exist yet — no `clone.sh`, no
> `_clone.py`, no `bin/pyauto-brain clone` wiring. This document is the agreed
> design it will be implemented against; `AGENTS.md` arrives with the
> implementation. Filed from `PyAutoMind/issued/clone_mitosis_agent.md`
> (PyAutoBrain #57).

> **Tier: conductor** — a front-door agent you *drive*. Engineering name:
> **Clone Agent** (CLI: `pyauto-brain clone`). Organism-facing name: **Mitosis
> Agent** — the agent that lets the PyAuto organism reproduce a mature
> assistant cell, copying its core machinery and differentiating it for a new
> organ/domain. Use `clone` in code and commands; use *Mitosis* in
> organism-level docs.

It takes a **source library** (e.g. PyAutoFit), its **workspace** (e.g.
`autofit_workspace`), an optional **HowTo** repo (e.g. HowToFit), and the
**reference assistant** (initially `autolens_assistant`), and produces a new
domain assistant (`autofit_assistant`, `autogalaxy_assistant`, …) modelled on
the reference.

```
library + workspace [+ HowTo] + reference assistant
        →  Clone Agent  →  CloneDecision (dry run, always first)
        →  --apply      →  PyAutoBuild executes repo creation + file generation
        →  PyAutoHeart validates the newborn assistant
```

## Fundamental principle

**The Clone Agent reasons about reproduction; it never gives birth itself.**
It inspects, partitions, and plans — emitting a `CloneDecision` — and on
`--apply` hands the generation plan to PyAutoBuild. It writes no repo, no
file, no GitHub state of its own. A clone is never an unreviewed act: the
human answers the clone-mode question before anything is generated.

## The organ boundary (memorise this)

| Organ | Role in a clone |
|-------|-----------------|
| **PyAutoMind** | stores the *intent* — the prompt that asks for the new assistant |
| **PyAutoBrain** (this agent) | inspects the domain, partitions template vs domain content, plans — the `CloneDecision` |
| **PyAutoBuild** (the Hands) | executes: repo creation, file generation, initial commit/push |
| **PyAutoHeart** | validates the result — the newborn's own symbol audit, link sweep, wiki-currency, chat-surface smoke |
| **PyAutoMemory** | supplies reusable architectural knowledge (assistant anatomy, prior CloneDecisions) — cited in the Decision, **never** copied into the public assistant (the privacy seam) |

## What it decides (the CloneDecision)

Mirrors `IntakeDecision`/`FeatureDecision`: a structured record printed on
every run, written to the tracking issue on `--apply`.

```
Sources        · library repo, workspace repo, optional HowTo (+ commits read)
Reference      · assistant repo + commit the clone derives from
Clone mode     · exact-clone | differentiated-sibling | lightweight-seed  ← the question
Domain analysis· concepts, public API surface, canonical workflows, user audiences
                 (from the library's docs/__init__, workspace start_here/examples, HowTo chapters)
Partition      · generic infrastructure / domain-specific / mixed — seeded from the
                 reference's modes/maintainer.md "Assistant-as-template" section
Generation plan· file-by-file: copy verbatim | adapt (named substitutions) | regenerate
                 from domain corpus | scaffold as pending stub
Validation plan· the Heart legs the newborn must pass before its repo goes public
Risks          · e.g. domain has no HowTo; workspace examples stale; name collisions
Next action    · confirm clone mode → --apply hands the plan to Build
```

**The clone-mode question is mandatory** (asked, never defaulted):

- **exact-clone** — domain nearly isomorphic to lensing; rename + substitute,
  keep the full skill/wiki shape. Cheapest; highest risk of lens residue.
- **differentiated-sibling** — full regeneration of skills and `wiki/core/`
  from the domain corpus inside the reference's *structure*. The expected
  normal mode.
- **lightweight-seed** — constitution + setup skill + empty wiki scaffolds +
  a pending-stub queue; the domain assistant grows in use. Right when the
  domain corpus is thin.

## The template seam

The generic-vs-domain partition is **owned by the reference assistant**, not
hardcoded here: `autolens_assistant/modes/maintainer.md` "Assistant-as-template"
already names the three sets (generic infrastructure / PyAutoLens-specific /
mixed). The Clone Agent reads that section as its seed partition and reports
any file the section does not cover as `unclassified` in the CloneDecision —
pressure that keeps the reference's boundary notes complete. If a machine-
readable manifest is ever needed, it is *derived from* that section
(`template_manifest.yaml`, generated in the reference repo), never a second
hand-maintained copy. Do not generalise the reference codebase pre-emptively;
the seam contract is documentation-first.

What the partition means per set, for every clone mode:

- **generic** (AGENTS.md skeleton, modes machinery, skills framework
  `_style.md`/`_bootstrap_skill.md`, wiki three-way split + update rules,
  project lifecycle skills, `sources.yaml` pattern, API gate + wiki-currency
  workflow, profile template) — copied, with only name substitutions.
- **domain** (every `al_*` skill body, `wiki/core/` reference pages,
  `wiki/literature/`, bundled datasets, README science framing + example
  prompts, standard-imports convention, `hpc/` tuning) — regenerated or
  stubbed per the clone mode; **never copied blind**.
- **mixed** (`llms.txt` read-order, `config/`, maintainer smoke tests) —
  copied then adapted with named substitutions listed in the plan.

## Modes (CLI sketch)

| Mode | Command | What it does |
|------|---------|--------------|
| **analyze** (default) | `clone <library> --workspace <repo> [--howto <repo>] [--reference <repo>]` | full dry run: domain analysis + partition + plan → CloneDecision; writes nothing |
| **apply** | `clone --apply …` | after the human confirms the clone mode: hand the generation plan to PyAutoBuild, post the CloneDecision to the tracking issue |
| **audit** | `clone audit <assistant>` | re-partition an *existing* assistant against the current reference — drift report for already-born siblings |

Writes only under `--apply`, and even then only via Build. Exit codes follow
the intake convention (`0` decision produced · `4` inputs unresolvable · `5`
bad usage).

## Phased implementation (each phase = one future Mind prompt, filed when its predecessor nears shipping — never bulk-issued)

1. **v0 — decision only.** `analyze` mode end-to-end: domain analysis,
   partition, generation plan, CloneDecision. No writer at all. Proves the
   reasoning on `PyAutoFit → autofit_assistant` as the dry-run case study.
2. **v1 — seed births.** `--apply` for **lightweight-seed** via a PyAutoBuild
   primitive (repo creation + generic-set copy + scaffolds). Heart gains the
   newborn-validation checklist. First real birth: `autofit_assistant` seed.
3. **v2 — differentiated siblings.** Skill/wiki regeneration from the domain
   corpus (model-assisted, curated per the reference's `al_update_wiki`
   philosophy: generated drafts, human-reviewed PRs). `audit` mode lands here.

## What this agent must never do

- Write a repo, file, or any GitHub state itself — execution is Build's,
  always behind `--apply` and a human-confirmed clone mode.
- Copy domain-specific content (lens science, `al_*` bodies, literature wiki,
  datasets) into a new domain — the partition exists to make this impossible.
- Modify the reference assistant. Gaps it finds there (unclassified files,
  stale boundary notes) are *reported*, and fixed in the reference by its own
  dev workflow.
- Embed PyAutoMemory content in a generated (public) assistant — cite it in
  the CloneDecision only.
- Bypass Heart: a newborn assistant is not announced until its validation
  legs pass.
- Invent a second template-boundary source of truth.

## Open questions (to settle in v0)

- Repo creation ownership: `gh repo create` inside Build vs a pre-created
  empty repo handed in (leaning: Build creates, `--private` first, public at
  the newborn's own Publish gate).
- Whether `clone audit` belongs here or in Heart (leaning: here — it is a
  partition judgement, not a health check; Heart runs the checks it emits).
- How the domain's "three example prompts" (the README front door) are
  chosen — likely the one genuinely creative step that stays human-drafted.

# Intake agent

> **Tier: conductor** — a front-door agent you *drive*. The *Conception
> Agent*: it turns raw input into a formal PyAutoMind prompt and writes it (a
> side effect in the world), so it is a conductor, not a read-only faculty. It
> *consults* the read-only sizing faculty for difficulty; it never starts
> development. ("Intake" because its front door takes in *any* raw input —
> bug, refactor, docs — not just feature ideas.)

It turns raw input — a text-vomit idea, a bug report, an `ideas.md` bullet — into
a **formal, grouped, headed PyAutoMind prompt** under `<work-type>/<target>/<name>.md`.

```
raw input  →  Intake Agent  →  PyAutoMind <work-type>/<target>/<name>.md
                               (Type / Target / Difficulty / Autonomy / Priority
                                header — no YAML)  →  create_issue → start_dev
      consults ↘
        sizing faculty (difficulty — the same estimate the Feature Agent trusts)
```

## Fundamental principle

**Intake formalises intent; it does not act on it.** It classifies, sizes, and
writes a prompt file — nothing downstream. It never opens an issue, never starts
dev, never edits a source repo. `create_issue` / `start_dev` / `ship_*` remain
the separate, later steps.

## The boundary (memorise this)

**Intake = route-to-a-filed-prompt-without-executing.** Three adjacent things it
must not duplicate:

| Thing | Does | Intake differs by |
|-------|------|-------------------|
| `/route` | infer work-type, **dispatch** (starts dev now) | intake **files a prompt**, defers |
| `triage/` | the unclassified-prompt bucket | intake **writes into** it on low confidence — reuse, don't reinvent |
| `create_issue` | prompt → GitHub issue + registry | intake runs strictly **before** it |

## What it decides (the IntakeDecision)

Mirrors the Feature Agent's `FeatureDecision` shape, one stage earlier:

```
Source · Title · Work-type (+confidence) · Target (+resolved repos)
Difficulty (+score, from the sizing faculty) · Autonomy · Priority · Workflow
Proposed path · Header (the block written verbatim) · Risks · Next action
```

- **Work-type** — scored by keyword signal into `feature/bug/refactor/docs/test/
  release/maintenance/research/experiment`; a tie across dissimilar types or zero
  signal → `triage`.
- **Target** — resolved from `@RepoName` mentions *and* bare repo names, incl. the
  **organism repos** (`pyautomind/pyautobrain/pyautoheart/pyautobuild/pyautomemory`)
  — the gap that made the Feature Agent mis-route a `pyautobrain` target.
- **Difficulty** — from the shared `agents/faculties/sizing/` faculty, **persisted
  into the header**, because scope is decided during the intake back-and-forth.
  The Feature Agent later *trusts* this number rather than recomputing a divergent
  one.
- **Autonomy** (`safe|supervised|human-required`) and **Priority**
  (`low|normal|high`) — the "can an agent safely handle this?" and "how urgent?"
  inputs, written into the header.

## The header — extend the blessed convention, never YAML

Writes the light header PyAutoMind blesses (`README.md` "Prompt file format"),
extended with `Difficulty:/Autonomy:/Priority:`. No YAML frontmatter, no required
schema — light structure over free-form prose.

## Modes

| Mode | Command | What it does |
|------|---------|--------------|
| **classify** | `intake "<text>"` / `intake classify --file P` | classify one raw input; `--apply` writes the prompt |
| **ideas** | `intake ideas` | scan `ideas.md`, propose one prompt per bullet; `--apply` writes them |
| **census** | `intake census` | inventory every filed prompt (work-type/target/difficulty/status + hygiene flags); always read-only |
| **dashboard** | `intake dashboard` | render the census as the Mind **backlog** page; `--apply` writes `PyAutoMind/dashboard.md` |

Census/dashboard are the Mind *backlog* view — deliberately distinct from
Heart's `/health status` health view (see "must never do"). The prompt-taxonomy
folder is authoritative for a prompt's work-type/target; header fields are
display metadata, and headerless legacy prompts surface as hygiene flags rather
than errors. `repair` (fixing those flags in place) is the **planned follow-up**
— not in this cut.

## Run

```bash
bin/pyauto-brain intake "add data cube modelling to autolens"     # dry-run classify
bin/pyauto-brain intake --json "<text>"                            # machine-readable IntakeDecision
bin/pyauto-brain intake --apply classify --file tmp/raw.md         # write the prompt
bin/pyauto-brain intake ideas                                      # scan ideas.md (dry-run)
bin/pyauto-brain intake --apply ideas                              # write them + mark bullets
bin/pyauto-brain intake census                                     # backlog inventory (read-only)
bin/pyauto-brain intake dashboard                                  # backlog page to stdout (dry-run)
bin/pyauto-brain intake --apply dashboard                          # write PyAutoMind/dashboard.md
```

**Writes only under `--apply`; dry-run is the default.** Exit codes: `0` produced
a decision · `4` no input / could-not-resolve Mind · `5` bad usage. The analysis
core is `_intake.py` (stdlib-only, writes only under `--apply`); `intake.sh`
resolves the Mind checkout.

## What this agent must never do

- Open an issue, start dev, edit a source repo, or run a build — all strictly
  downstream (`create_issue` / `start_dev` / `ship_*`).
- Query PyAutoHeart, or emit a *health* dashboard (that is Heart's).
- Introduce YAML frontmatter or a required schema — light header only.
- Silently delete raw ideas — mark them, leave deletion to a trusted later pass.
- Recompute difficulty with its own copy — consult the shared sizing faculty.

See [`INTAKE_TAXONOMY.md`](./INTAKE_TAXONOMY.md) for the classification signals,
target resolution, and the header schema in detail.

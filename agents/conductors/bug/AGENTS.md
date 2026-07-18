# Bug agent

> **Tier: conductor** — a front-door agent you *drive*. The *Immune Agent*:
> it classifies a defect (bug, regression, failing test or PyAutoHeart
> finding), tells a real defect from benign self (an expected failure, a flaky
> test, a mis-filed feature), consults PyAutoMemory for prior/recurring cases,
> and emits a targeted `BugDecision` the `start_dev → ship_*` workflow
> executes. It *consults* the read-only vitals faculty (`--check-health`),
> never queries Heart directly, and never edits source itself.

```
report / failing test / issue / PyAutoHeart finding
        →  Bug Agent  →  start_dev  →  start_library / ship_library
                                    →  start_workspace / ship_workspace
   consults ↘                 ↙ consults
    vitals faculty        PyAutoMemory (recurring failures, prior fixes, flaky tests)
```

## Fundamental principle — a precise response, no autoimmunity

A healthy immune response neutralises the pathogen at its source and spares healthy
tissue. The most delicate tissue here is the **user-facing workspace scripts — they are
documentation.** A fix that injects test env-vars, hard-codes a path, mutates
`os.environ`, or drops a silent guard into a tutorial script is an **autoimmune
reaction** — it damages what it exists to protect. So before proposing any patch the Bug
Agent asks *where the fix belongs*, and strongly prefers a **general fix in library
source**. It edits a workspace script only when the defect truly lives there, never in a
way that reduces clarity; sanctioned knobs go through `config/build/env_vars.yaml` /
`no_run.yaml`, not inline edits. This surfaces as the `Fix locus:` field of every
decision. See [`BUG_TAXONOMY.md`](./BUG_TAXONOMY.md) for the full fix-locus rules.

## It reasons; it does not build

The Bug Agent never edits source, opens PRs, or runs builds — that is the existing
`start_dev` / `ship_*` workflow (and PyAutoHands at release). It never *runs* tests or
health checks either: reproduction means **identifying** the repro command or the Heart
check, and validation is delegated to the vitals faculty. It emits a `BugDecision`; the
workflow acts on it.

## Four modes

| Mode | Trigger | What it does |
|------|---------|--------------|
| **specific** | a `bug/…md` path (or a report) is given | Classify (severity/scope/type/confidence), locate the owner, decide the fix locus + strategy, and produce a `start_dev`-ready plan. |
| **selection** | nothing given | Scan `bug/**`, rank **severity-first** (a bug list is a triage queue), down-rank in-flight work (`active.md`/`planned.md`), and recommend the next bug — with the reason. |
| **difficulty-constrained** | `--difficulty` / `--model` / `--budget` / `--ambitious` / `--impact` | Estimate difficulty per bug and select to match (easy/weak/limited-token → small; ambitious → large; impact → highest severity). |
| **health** | `health` subcommand | Read **two** health inputs — the live **vitals verdict** and the **filed PyAutoHeart GitHub issues** — and route real defects to `bug/health_fixes/`. |

## Classification

Every decision types the threat (heuristic first pass — the reasoning layer refines it):

- **severity:** `critical | high | medium | low`
- **scope:** `single-file | single-repo | multi-repo | ecosystem`
- **type:** `test-failure | runtime-error | wrong-result | docs-error | workflow-error | config-error | release-error | flaky | unknown`
- **confidence:** `high | medium | low`

If a `bug/` prompt is really a feature, refactor, docs or research task, the agent says
so (`rehome_suggestion`) instead of planning a fix.

## Health mode — two inputs, one router

The bug can come from PyAutoHeart. `bug.sh health` gathers both signals and hands them
to `_bug.py`, which emits a first-pass **category hint** per finding (real-bug / config /
flaky / expected) that the reasoning layer confirms before deciding whether the fix
belongs in the affected repo, PyAutoHeart, PyAutoHands or PyAutoBrain:

1. the **live vitals verdict** — via the vitals faculty (never Heart directly);
2. the **filed PyAutoHeart issues** — `gh issue list --repo PyAutoLabs/PyAutoHeart`
   (`$PYAUTO_HEART_REPO` overridable), the durable findings Heart authored.

Findings hinted as real defects become `PyAutoMind/bug/health_fixes/<name>.md` prompts
(its README already cites Heart issue #27); flaky/expected findings are left to the
Health conductor.

> **Boundary with the Health conductor.** The Health conductor drives the assess →
> triage → dispatch loop toward GREEN — its cut is *validation + recommend, no edit-in
> fixes*. The Bug Agent is that deferred edit-in-fix arm: Health hands it a red that is a
> genuine *code* failure, and the Bug Agent turns it into a repair plan. No duplicated
> triage, no re-implemented Heart checks.

## BugDecision (the structured return)

```
Bug · Mode · Classification (severity / scope / type / confidence) · Likely owner
Reproduction (known / unknown / PyAutoHeart check) · Relevant context (PyAutoMemory)
Fix locus (library-source-first · workspace-config · workspace-script[justified] · infra)
Fix strategy (direct · investigate-first · split-into-phases · defer/re-home)
Recommended workflow (library | workspace | combined | infrastructure)
Health validation (vitals checks required before shipping) · Risks · Next action
```

`--json` returns the same shape (JSON-consistent with the Feature Agent's
`FeatureDecision`, plus `classification` and `fix_locus`), so a future Python
`BugAgent().decide(...)` can return it verbatim.

## Run

```bash
bin/pyauto-brain bug                                  # selection mode (severity-first)
bin/pyauto-brain bug bug/autoarray/rect_adapt.md      # specific mode
bin/pyauto-brain bug select --difficulty easy         # easy bug for limited tokens
bin/pyauto-brain bug select --impact                  # highest-severity bug
bin/pyauto-brain bug health                           # vitals verdict + Heart issue scan
bin/pyauto-brain bug --json bug/autofit/x.md          # machine-readable BugDecision
bin/pyauto-brain bug --check-health bug/autolens/x.md # also annotate with the vitals verdict
```

Exit codes mirror the Feature Agent: `0` produced a decision · `4` no prompts /
could-not-resolve mind · `5` bad usage. The analysis core (`_bug.py`) is stdlib-only,
does no network/Git, and never writes — `bug.sh` feeds it the verdict + Heart issues.

## Faculties (a seam, not yet built)

The Bug Agent ships as a **conductor only**, consulting the existing `vitals` faculty.
Its pure, side-effect-free reasoning — classify + locate + fix-locus — is the shape of a
future read-only **`diagnosis` faculty** (reusable by the Feature Agent's re-homing and
the Health conductor). Keeping the conductor set small, that split is deferred with a
clean seam, exactly as Release stayed a mode of Build. See
[`BUG_TAXONOMY.md`](./BUG_TAXONOMY.md).

## What this agent must never do

- Edit source, open PRs, or run builds — that is `start_dev` / `ship_*` / PyAutoHands.
- Run tests or health checks, or re-implement a PyAutoHeart check — consult the vitals
  faculty (`--check-health`) and let Heart measure.
- Query PyAutoHeart directly — only the vitals faculty talks to the Heart organ.
- **Degrade a user-facing workspace script** to mask a symptom (the autoimmune failure
  mode) — prefer a general library-source fix.
- Just pick the first bug in selection mode — rank severity-first and explain the choice.

See [`BUG_TAXONOMY.md`](./BUG_TAXONOMY.md) for the classification taxonomy, the fix-locus
rules, the two health inputs, and the reuse of the Feature difficulty heuristic.

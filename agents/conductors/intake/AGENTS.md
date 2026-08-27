# Intake agent

> **Tier: conductor** — a front-door agent you *drive*. The *Conception
> Agent*: it turns raw input into a formal PyAutoMind prompt and writes it (a
> side effect in the world), so it is a conductor, not a read-only faculty. It
> *consults* the read-only sizing faculty for difficulty; it never starts
> development. ("Intake" because its front door takes in *any* raw input —
> bug, refactor, docs — not just feature ideas.)

It turns raw input — a text-vomit idea, a bug report, an `ideas.md` bullet — into
a **formal, grouped, headed PyAutoMind prompt** under `draft/<work-type>/<target>/<name>.md`.

```
raw input  →  Intake Agent  →  PyAutoMind draft/<work-type>/<target>/<name>.md
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
  one. A difficulty **declared in the raw input** — a pasted header block, or the
  `ideas.md` house style `Difficulty large, supervised.` — **wins** over the
  estimate, via the faculty's shared `effective_difficulty`: the author knows the
  scope, and the heuristic's biggest input is length, which is a bad size proxy
  (a prompt is long when it carries a design, not when the work is large). The
  IntakeDecision reports which one it used (`difficulty_source`) and the level
  the heuristic derived, and the declaration is kept out of the derived
  title/slug. A `Difficulty:` quoted inside a code fence or backticks is
  documentation, not a declaration.
- **Autonomy** (`safe|supervised|human-required`) and **Priority**
  (`low|normal|high`) — the "can an agent safely handle this?" and "how urgent?" questions; a declared value wins here too, as does a declared `Type:` over the prose classifier.
  inputs, written into the header.

**`too-large` means decompose, never dispatch.** A prompt sized `too-large` is
not an executable unit of work — no conductor takes it to `start_dev` directly.
The route is a decomposition pass first: rewrite it as a sequenced series of
`small`/`medium` prompts, each with concrete acceptance criteria and stated
dependencies on its predecessors (the psf-oversampling series is the model:
one too-large idea → 8 phased prompts, all shipped). The original prompt
becomes the series' tracker or is retired. Decomposition is planning judgment —
it stays with the strongest available model; the resulting phases are what the
cheaper execution models run.

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
| **dashboard** | `intake dashboard` | render the census as the Mind **task** page — picks, in flight, parked, planned, backlog, recent, epics; `--apply` writes `PyAutoMind/dashboard.md`, `--check` exits 1 on drift |
| **formalise** | `intake formalise [prefix]` | retroactively header the prompts census flags — derive the missing fields, insert in place, prose untouched; `--apply` writes |
| **reconcile** | `intake reconcile [prefix]` | rank backlog prompts that look already-shipped (vs the `complete/` records / `active/`), and pair live prompts that look like the same work filed twice; always read-only — retiring stays human |
| **reconcile --repo** | `intake reconcile --repo <target> [prefix]` | **also** read the target repo's source: identifiers the prompts name that exist upstream, and lines they quote that are **gone** — the two signals that see a prompt with no Mind-side trace. Opt-in; the default path is offline |

**Recent** is the one section laid out by *date* rather than by state: the 50
newest events on the **work in hand** — issued, parked, filed — merged across
every live bucket (the `draft/` backlog included, which is most of them:
150 prompts against a handful of registry rows) and sitting between the Backlog
and the Epics. Epic members stay out, as they do in every pick list on the
page — they are worked in order through their epic, and a Recent row hands out
a standalone `/start_dev`. It *holds* 50
and *shows* 10 (`RECENT_MAX` / `RECENT_PAGE`): the table is a glance, not a
log, so the rest is one tap away — a `…` button on the Pages twin, and nested
`<details>` on the markdown page, which GitHub renders where it strips the
script. Every other
section answers "what should I do now?"; recency is orthogonal to state, so
none of them can answer "what has been happening?". Dates come from the
registry key that names the event (`issued:` / `parked:` / `filed:`, PyAutoMind
REFERENCE.md "Task dates") or a prompt's own `Issued:` header.

Shipped work is deliberately **not** in the feed and `complete/` is never
opened to render it: the ledger is a thousand records deep and takes ~200 a
month, so including it made the table a list of receipts — twenty things nobody
can act on, on the page whose whole job is work in hand. `complete/index.md` is
where shipped work is read.

Census/dashboard are the Mind *backlog* view — deliberately distinct from
Heart's `/health status` health view (see "must never do"). The prompt-taxonomy
folder is authoritative for a prompt's work-type/target; header fields are
display metadata, and headerless legacy prompts surface as hygiene flags rather
than errors. Formalise closes those flags (once codenamed `repair`, renamed
because raw prompts are intended word-vomit awaiting conception, not defects):
it derives Difficulty/Autonomy/Priority via the sizing faculty, writes
Type/Target from the folder, keeps every existing field value and every line of
prose, and turns work-type disagreements into **re-home suggestions** — it never
moves or deletes a file.

Reconcile exists because a prompt's `Status:` header is **not** a completeness
signal — formalise preserves an existing Status verbatim, so shipped work can
still read `Status: planned`. It cross-references each backlog prompt against
the `complete/` records (path references + `## header` topic overlap), `active/`
basenames, and hand-set Status values, then ranks suspects (high/medium/low)
with the evidence shown. The final verification — the target repo's git log /
merged PRs — and the retirement itself stay human.

`--repo <target>` adds the **upstream leg**: identifiers a prompt names that
already exist in the target repo's source, cited as `file:line`, in their own
weaker `needs-review` band. It is the only signal that reaches a prompt with no
Mind-side trace at all — the 2026-08-09 sweep confirmed two such findings, one
whose evidence sat in a sibling *prompt* and one whose fix shipped with no
completion record ever written.

It never produces a shipped verdict, and upstream hits are scored on their own
key so they cannot inflate a Mind-local band. The reason is a measured trap:
`test_mode_bypass_ordered_assertion_ties.md` names five identifiers, all five
are on PyAutoFit `main`, and the prompt is **not** shipped — the upstream catch
wraps only the likelihood call while the raising line sits before the `try`.
Presence of a name is not presence of the fix.

`--repo` also carries the **absence signal**, the inversion of the above: a
literal line a prompt *quotes* that is **gone** from a file it names. Presence
tests "the prompt names things that exist upstream" and is blind to a task that
shipped leaving no Mind-side trace while its files still exist —
`smoke_install_stale_jax_pin.md` shipped 2026-08-23 and both guards passed it
(`lifecycle.py check` has no invariant for a prompt that was never `active/`;
`reconcile --repo autolens_workspace_test` found 0 suspects of 132). It named
`smoke_install.sh`, which still exists. What it quoted —
`pip install "jax<0.7" "jaxlib<0.7"` — did not.

Five filters keep it off every prompt that quotes its own evidence, and all
five must hold:

| Filter | The false positive it kills |
|---|---|
| the fence carries an explicit **source language** | a traceback or pytest summary goes in a bare fence, and those lines are absent from every repo by construction |
| the prompt **names a file that exists upstream** with that extension | without an anchor, *"absent from what?"* has no answer |
| the line is absent from the **whole checkout**, not just that file | a refactor that moved a line is not the prompt shipping |
| the prompt **mentions the repo being read** | a prompt read against a repo it is not about quotes lines absent by construction — its `Repos:` header had the answer all along, while `--repo` had to be told the target by hand |
| **the anchor is corroborated** — at least one quoted line of that kind is still *present* in the named file | **proposed code.** `einstein_radius_jit_native_seed_finder.md` quotes 23 lines of a seed finder it wants *written*; all 23 are absent because none ever existed, and it outscored every true positive. One line still present proves the prompt is talking about this file, in this checkout |

Measured against the live backlog (134 prompts) read at `autolens_workspace_test`:
the last two filters took **6 hits → 0**, every one of the six a proposal or a
wrong-repo read, while the retired `smoke_install_stale_jax_pin.md` — restored
into `draft/` to reproduce — still fires. That prompt quoted *two* lines from
`smoke_install.sh`: the PyAuto install line, still there, and the jax pin, gone.

Like presence, it feeds only the upstream key and never retires anything.

**This is the only network access in PyAutoBrain.** Every other conductor and
faculty is stdlib-only and offline, and the default `reconcile` path stays that
way — a test detonates on any socket or subprocess use when `--repo` is absent.
A target that is not one repo (`workspaces`, `health_fixes`, `priors`,
`graphical_ep` — topic clusters, and among the largest buckets in `draft/`) is
**refused** with exit `5` naming the real candidates, never silently guessed.
Clones are cached shallow (`--depth 1`) under `$PYAUTO_BRAIN_CACHE`
(default `~/.pyauto-brain/upstream`), and the resolved sha is printed so a
verdict is re-checkable.

### Duplicate candidates (offline)

Every signal above scores a prompt against the completion **archive**. Nothing
scored the live prompts against **each other**, and near-duplicate filings are a
standing hazard of a backlog several independent sessions file into.
`bug/workspaces/jax_likelihood_pins_stale_by_1e4.md` (filed 08-14) and
`bug/autolens/jax_likelihood_smoke_pins_stale.md` (filed 08-19) named the same
three scripts from the same failing smoke gate; the 08-19 copy was verified and
retired on 08-26, and the 08-14 copy kept rendering as pickable backlog.

`reconcile` therefore also emits a `duplicate-candidate` bucket, pair-wise, over
shared upstream **source paths**, rare **identifiers** and **tracking
references**. It runs on the default (offline) path — it reads only `draft/`.

Three filters carry the precision, measured on the 2026-08-27 backlog (134
prompts): **36 pairs → 2**.

| Filter | Why |
|---|---|
| A path named by more than `_DUP_PATH_COMMON` prompts is dropped, and a **bare basename never counts** | `start_here.py`, `modeling.py`, `no_run.yaml` are workspace-wide conventions; sharing one is a convention, not a task. This filter alone removed 31 of the 36 |
| **Mutual reference disqualifies** | a phased parent and its child name each other — a series, not a duplicate |
| **A folder index naming both disqualifies** | the four `draft/bug/health_fixes/` prompts were split by *cause*, so they share their failing scripts and none names another; the folder's `README.md` names all four, and that is the declaration |

A pair is something to **read together**, never a verdict: two prompts can share
files and still be different work.

## Machine sources (one staging surface)

Conception input increasingly arrives from the organism itself — research
runs (`/research` scholar mode), Heart-filed findings, profiling results,
review-faculty leftovers. The design is deliberately **one staging surface,
many writers**: every such source appends a bullet to `ideas.md` with a
provenance tag, and the *existing* ideas sweep formalises it —

```markdown
- [from: <source> · <wiki page | issue | result>] <the idea>
```

Intake is **not** taught per-source formats: the sweep, the human review of
each IntakeDecision, and `--apply` are the same whether a human or a machine
staged the bullet. Provenance tags survive into the formal prompt's prose
(private Mind), but PyAutoMemory citations never reach public user-facing
output (the memory faculty's privacy seam). Writers propose their batch to
the human before appending; intake never sweeps silently into prompts —
dry-run first, always.

## Run

```bash
bin/pyauto-brain intake "add data cube modelling to autolens"     # dry-run classify
bin/pyauto-brain intake --json "<text>"                            # machine-readable IntakeDecision
bin/pyauto-brain intake --apply classify --file tmp/raw.md         # write the prompt
bin/pyauto-brain intake ideas                                      # scan ideas.md (dry-run)
bin/pyauto-brain intake --apply ideas                              # write them + mark bullets
bin/pyauto-brain intake census                                     # backlog inventory (read-only)
bin/pyauto-brain intake dashboard                                  # task page to stdout (dry-run)
bin/pyauto-brain intake --apply dashboard                          # write PyAutoMind/dashboard.md
bin/pyauto-brain intake dashboard --check                          # exit 1 if the committed page has drifted
bin/pyauto-brain intake formalise                                  # propose retroactive headers (dry-run)
bin/pyauto-brain intake --apply formalise bug/                     # write them, only under bug/
bin/pyauto-brain intake reconcile                                  # rank shipped-but-stale suspects + duplicate pairs (read-only)
bin/pyauto-brain intake reconcile --repo autolens_workspace_test   # + upstream presence and quote-absence legs
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

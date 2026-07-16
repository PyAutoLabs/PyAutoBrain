# Intake taxonomy — how raw input becomes a formal prompt

The Intake Agent's audit of the surface it drives: the PyAutoMind taxonomy it
writes into, the signals it classifies by, and the header it produces. The
work-type taxonomy itself is owned by `PyAutoMind/ROUTING.md`; the shared
prompt-parsing, repo resolution and difficulty heuristic are owned by
`agents/faculties/sizing/_sizing.py`. This file documents only the *intake-
specific* reasoning layered on top.

## 1. Work-type classification

Each work-type has a keyword signal set (`WORK_TYPE_SIGNALS` in `_intake.py`).
The classifier scores each type by how many of its signals appear (word-boundary
prefix match) and picks the strongest:

| Work-type | Fires on (examples) |
|-----------|---------------------|
| `bug` | crash, regression, fails, traceback, NaN, incorrect, raises |
| `test` | test, coverage, parity, pytest, unit test |
| `docs` | tutorial, notebook, guide, docstring, walkthrough |
| `refactor` | refactor, restructure, rename, decouple, "no behaviour change" |
| `release` | release, PyPI, changelog, version bump, wheel |
| `maintenance` | dependency, bump, upgrade, pin, tech debt |
| `research` | investigate, explore, open question, design note, scoping |
| `experiment` | spike, proof of concept, prototype, sandbox |
| `feature` | add, implement, support, introduce, enable, extend (the default verb set) |

**Confidence & triage.** `high` when the winner has ≥2 signals, `medium` at 1.
A tie across *dissimilar* non-feature types, or zero signal, is genuinely
ambiguous → `triage` (low confidence), written to `triage/<slug>.md` for a human
to re-home. This reuses the existing unclassified bucket rather than inventing a
parallel one.

## 2. Target resolution

The second folder — the affected repo/domain — resolves in this order:

1. **`@RepoName` mentions and bare repo names** in the text, via the shared
   `_sizing` repo sets. Bare names are matched too (a raw dump writes "autolens",
   not "@PyAutoLens"); the auto/pyauto stem + word boundaries keep this safe.
2. **Organism repos** are first-class: `pyautomind`, `pyautobrain`, `pyautoheart`,
   `pyautobuild`, `pyautomemory`. Resolving these is the specific gap that made
   the Feature Agent mis-route a `pyautobrain` target as "(none resolved) →
   research-first".
3. **Keyword domain guess** (`TARGET_SIGNALS`) when nothing resolves — e.g.
   "deflection" → `autolens`, "sampler" → `autofit`, "grid/mask" → `autoarray`.
4. **Unresolved** → the prompt is filed to `triage/` with a note to add an
   `@RepoName` or `Target:` before `start_dev`.

Primary-folder preference when several resolve: library repo → organism repo →
`workspaces` bucket.

## 3. Workflow inference

| Repos resolved | Workflow | Ships via |
|----------------|----------|-----------|
| library + workspace | `combined` | library PR first, then workspace |
| library only | `library` | start_library → ship_library |
| organism only | `infrastructure` | edited like a library (worktree + PR) |
| workspace only | `workspace` | start_workspace → ship_workspace |
| none | `unknown` | scope before start_dev |

## 4. Difficulty, autonomy, priority (the header inputs)

- **Difficulty** (`small|medium|large|too-large`) — the shared sizing faculty's
  `estimate_difficulty`, the *same* function the Feature Agent uses. Persisted so
  the number is decided once, at conception, when scope is freshest.
- **Autonomy** (`safe|supervised|human-required`) — `human-required` when the
  work needs a design decision and no repo resolved; `supervised` for
  architectural risk / large / multi-repo; `safe` otherwise.
- **Priority** (`low|normal|high`) — `high` on urgent/blocker/critical language,
  `low` on someday/nice-to-have, else `normal`.

## 5. The header written (extends PyAutoMind's blessed convention)

```markdown
# <Title derived from the first heading / line>

Type: <work-type>
Target: <RepoDisplayName>
Repos:
- <RepoDisplayName>
Difficulty: <level>
Autonomy: <autonomy>
Priority: <priority>
Status: formalised

<original raw text, verbatim>

<!-- formalised by the Intake (Conception) Agent on <date> from <source> -->
```

No YAML, no required fields — this is the light header PyAutoMind blesses in
`README.md` "Prompt file format", extended with the three intake keys
(`Difficulty:/Autonomy:/Priority:`). `Type:` always matches the work-type folder.

## 6. Census + dashboard (reading the taxonomy back)

The write path above has a read path: **census** walks every work-type folder
(incl. `triage/`) and parses the same light header back out of each prompt
(`parse_header`), producing per-prompt records plus aggregates by work-type,
target, difficulty and priority. The **folder position is authoritative** for
work-type/target — a header `Target:` is free prose and never overrides the
taxonomy. Prompts that pre-date the header surface as *hygiene flags* (shown as
`-`), never errors. `issued/` prompts are already dispatched: counted, not
itemised.

**dashboard** renders that census as `PyAutoMind/dashboard.md` — the Mind
*backlog* page (never health; that is Heart's). Census is always read-only;
dashboard writes only under `--apply`.

**formalise** closes the hygiene flags retroactively (once codenamed `repair`;
renamed — raw prompts are intended word-vomit awaiting conception, not defects).
Per flagged prompt it derives the missing fields (Type/Target from the folder,
Difficulty/Autonomy/Priority via the same sizing-faculty path conception uses)
and inserts only those lines: after the last field of a partial header block,
below an existing `# heading`, or under a derived `# <title>` when there is
neither — every existing line survives verbatim, plus a retroactive-provenance
comment. Where the body classifier disagrees with the folder at medium/high
confidence it emits a *re-home suggestion*; it never moves or deletes a file.
Optional path-prefix argument scopes the run (`intake formalise bug/`); writes
only under `--apply` and re-runs are no-ops (nothing left missing).

**reconcile** audits the opposite failure: prompts whose work shipped but whose
status went stale (a header `Status:` is display metadata — formalise preserves
an existing value verbatim, so `Status: planned` can outlive the work by
months). Per backlog prompt it collects four Mind-local signals — a
completion-record line referencing its path (follow-up/restore/parked wording
downgrades it to likely-open), a duplicate basename in `issued/`, token overlap
with a completed task's `## header`, and a hand-set Status — then ranks
suspects high/medium/low with the evidence shown. Always read-only: the final
verification (target repo git log / merged PRs) and the retirement to
`issued/` stay human.

## 7. What intake does NOT own

- The difficulty heuristic, prompt parsing, repo sets → the **sizing faculty**.
- The work-type → agent routing → `PyAutoMind/ROUTING.md` + the conductors.
- Issue creation, dev-environment setup, shipping → `create_issue` / `start_dev`
  / `ship_*`, strictly downstream.

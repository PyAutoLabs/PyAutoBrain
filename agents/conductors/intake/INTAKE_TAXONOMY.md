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

## 6. What intake does NOT own

- The difficulty heuristic, prompt parsing, repo sets → the **sizing faculty**.
- The work-type → agent routing → `PyAutoMind/ROUTING.md` + the conductors.
- Issue creation, dev-environment setup, shipping → `create_issue` / `start_dev`
  / `ship_*`, strictly downstream.

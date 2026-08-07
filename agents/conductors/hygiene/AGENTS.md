# Hygiene agent

> **Tier: conductor** — a front-door agent you *drive*. The *maintenance
> function* — the organism's sense of its own upkeep: it owns the code-quality
> debt that neither proves the organism works (that is Heart) nor measures the
> speed of modelling (that is profiling). It consults the read-only vitals
> faculty like every conductor, reasons over the quality signals, and emits a
> `HygieneDecision` the human/session executes — delegating the actual fixes to
> the dev-flow conductors. It never issues health verdicts and never releases.

Grown from demonstrated need: the hygiene reasoning already exists, scattered —
the `repo_cleanup` skill (whose SKILL.md explicitly foreshadowed this "Cleanup
Agent"), `cli_noise_clean`, `dep_audit` and `audit_docs` — plus recurring manual
perf-hygiene work (slow unit tests, slow integration-mode scripts, import cost).
This conductor unifies and prioritises them. Design decision (conductor, **no
paired repo**, boundaries) recorded in PyAutoMind
`complete/2026/07/hygiene-agent-decision.md`; the founding prompt is folded
into `complete/2026/07/hygiene-agent.md`.

## Modes

All modes are live. Each does a cheap, read-only local **pre-scan** and
**delegates** the full audit + any execution to the owning skill — the conductor
never runs a heavy audit and never mutates a repo. A pre-scan is one of a few
kinds, which is what makes its count comparable (or not):

- **debris** — finds directly-removable items; a real, rankable count (`tidy`).
- **finding** — confirms a source-quality defect; a real, rankable count
  (`docstrings`, `refs`, `optdeps`, `extras`).
- **timing** — measures import cost; a real, rankable count of *slow* imports (`perf`).
- **surface** — only *sizes* the audit; the real problems emerge when the
  delegated skill runs, so the count is **not** a problem count (`deps`, `docs`).
- **advisory** — no cheap local signal at all (`noise`).

A mode also carries a **status**, and one of them is not a count at all:
**`unscanned`** means the mode read *no repository* — the scan root holds no
managed checkout, or the body map could not be reached. It is reported instead
of `clean` because a zero from "nothing was examined" and a zero from "nothing
was wrong" are indistinguishable to a reader, and the first is not good news.

## Which repositories it scans

**Derived from the body map (`repos.yaml`), never listed here or in the script.**
The conductor takes `library`, `organ` and `workspace` from the map via
`_hygiene_repos.py`; adding a repo to the map adds it to the scan.

This was a bash array once, and it drifted: five libraries where the map
declared six, four organs of seven, and a CRLF count of **5** against a true
**127**. The drift was invisible precisely because an unscanned repo yields no
findings — the conductor reported clean and was believed. `repos_sync.py`'s
`check_hygiene_coverage` now fails if the derived sets stop matching the map, or
if a repo name is written back into a `*_REPOS=(…)` array.

Two modes need a narrower set, and both read what a checkout **contains** rather
than its category — because category alone gets it wrong. The config layer is an
*organ* in the map yet ships a real distribution, so keying `deps` off
`category: library` would silently drop it:

| Set | Rule | Modes |
|-----|------|-------|
| code repos | `library` + `organ` | `tidy`, `deps`, `docs`, `packaging` |
| scanned repos | code repos + `workspace` | `crlf`, `artifacts` |
| ships a distribution | has a `pyproject.toml` | `deps` |
| ships api docs | has a `docs/api/` tree | `docs` |

The helper-backed modes (`docstrings`, `refs`, `optdeps`, `extras`, `config`)
are **not** on this list: they discover their own targets by walking the scan
root for workspace-shaped directories, so they can find material the map never
names — and they keep reporting even when the repo-array modes are `unscanned`.

| Mode | Pre-scan (kind) | Delegates to |
|------|-----------------|--------------|
| `perf` | dev-loop timing — prefers Heart's tracked timing legs when present (`import_time`, `unit_test_timing`, `workspace_testmode_timing`), else times `import <pkg>` per library in a **subprocess** (**timing**) | `/refactor` / `/bug` (+ Heart timing legs) |
| `tidy` | git debris — stale branches, stashes, `[gone]` refs, dirty checkouts (**debris**) | **condemn** → files candidates into `condemned.md` async (PyAutoGut archives the fragile forms); no synchronous per-item gate |
| `sweep` | reads `condemned.md`, classifies entries by their transit clock (**due** / pending / undated) | `pyauto-gut void` for past-due entries, behind the existing `repo_cleanup` safety gates |
| `noise` | none — needs a pytest + workspace-script run (**advisory**) | `/cli_noise_clean` (Heart) |
| `deps` | capped/pinned specifiers in every managed repo that ships a `pyproject.toml` (**surface**) | `/dep_audit` (Heart, hits PyPI) |
| `docs` | `docs/api/*.rst` + `currentmodule` counts across every managed repo shipping a `docs/api/` tree (**surface**) | `/audit_docs` (Heart, imports) |
| `crlf` | executable scripts (`.sh` + shebang-`755` `.py`) with CRLF — the shebang breaks on Linux/HPC (**debris**, the ranked count); plain `.py` CRLF is reported separately as *cosmetic* (Python reads it fine — don't mass-normalise) | `/refactor` + `.gitattributes eol=lf` |
| `docstrings` | consecutive module-level triple-quoted expressions separated only by whitespace in user-facing `*_workspace` and `HowTo*` root `*.py` entry scripts and `scripts/**/*.py` files (**finding**) | `/refactor` (mechanically merge each confirmed boundary) |
| `refs` | file/folder references in user-facing `*_workspace` and `HowTo*` prose (`scripts/**/*.py` docstrings + comments, every `scripts/**/README.md` and `config/**/README.md`, and the top-level README) whose target no longer exists — restructure debt no health sweep can see, since the scripts still run (**finding**). Covers the README idioms a `scripts/`-anchored matcher cannot see: structure-list bullets (``- `slam_pipeline`: ``), slash-less relative folder paths (`data_preparation/imaging`), and config YAML names. Scans the **inverse direction** too: a folder that exists but whose own parent README never names it — a package can ship fully working, with every reference resolving, and still be invisible to a reader browsing the folder list (`interferometer/features/datacube` sat unlisted for three months) | `/refactor` (re-point each dead reference; add an entry for each undocumented folder, sourced from that folder's own README or a script docstring) |
| `optdeps` | smoke-listed workspace scripts that construct an optional-dependency-gated API (`TransformerNUFFT` → `nufftax`) without the house `find_spec` skip guard, so they hard-fail the CI matrices that omit the extras (**finding**). AST-confirmed — prose mentions don't count; scripts outside `smoke_tests.txt` are never flagged | `/refactor` (add the skip guard) |
| `extras` | the complement of `optdeps`: an optional dependency a library **declares** (in the `[optional]` extra `mode=release` installs) that the `workspace-validation.yml` **`mode=smoke`** leg never installs (**finding**). The extras chain only reaches each library's own `[jax]`, never a sibling's `[optional]`, so those need hand-adding and silently drift — the symptom is a script red in smoke and **green in release** | `/bug` (add the install; fix the install set, **never** the script) |
| `config` | library `config/*.yaml` keys missing from the matching workspace config — recursive diff (**surface**) | `/refactor` (mirror keys) |
| `artifacts` | tracked files that look like leaked run outputs / stray data (under `output/`, or data-ext outside fixtures) (**debris**) | `/repo_cleanup` (gitignore + `git rm --cached`) |
| `packaging` | ignored, fully-untracked top-level `*.egg-info/` and `build/` directories in the managed code repos (**debris**) | preview then run `PyAutoBrain/bin/clean_slate.sh --packaging`; repo-set, exact-name, root-depth and tracked-file guards apply |
| *(default)* | all of the above (**perf timing deferred** — it spawns real imports) | a ranked `HygieneDecision` worklist — recommends the highest-count direct mode (`tidy`/`crlf`/`docstrings`/`refs`/`artifacts`/`packaging`), then `hygiene perf`, then the periodic surface audits |

```
pyauto-brain hygiene              # pre-scan across modes → ranked worklist
pyauto-brain hygiene perf         # import cost (subprocess) → /refactor + Heart legs
pyauto-brain hygiene perf --profile <script>   # cProfile a normal-mode run → rank NON-likelihood hotspots → /refactor
pyauto-brain hygiene tidy         # git debris → condemn into condemned.md (async, no per-item gate)
pyauto-brain hygiene sweep        # void condemned.md entries past sweep-after → pyauto-gut void (repo_cleanup gates)
pyauto-brain hygiene noise        # CLI noise → /cli_noise_clean
pyauto-brain hygiene deps         # dependency-cap surface → /dep_audit
pyauto-brain hygiene docs         # API-docs surface → /audit_docs
pyauto-brain hygiene crlf         # CRLF .py files → /refactor
pyauto-brain hygiene docstrings   # adjacent top-level documentation → /refactor
pyauto-brain hygiene refs         # folder-list drift in workspace prose → /refactor
pyauto-brain hygiene optdeps      # smoke-listed scripts missing an optional-dep skip guard → /refactor
pyauto-brain hygiene extras       # optional deps the smoke CI leg never installs → /bug
pyauto-brain hygiene config       # library→workspace config drift → /refactor
pyauto-brain hygiene artifacts    # tracked leaked outputs/data → /repo_cleanup
pyauto-brain hygiene packaging    # ignored root packaging dirs → clean_slate.sh
pyauto-brain hygiene <mode> --json
```

Repos are read under `PYAUTO_ROOT` (default `~/Code/PyAutoLabs`). `noise`/`deps`/
`docs` route to **read-only PyAutoHeart observation skills** — measurement lives
in Heart; hygiene pre-scans, prioritises and routes. `perf` times imports in a
**subprocess** (`HYGIENE_PYTHON`, default `python3` — point it at the PyAuto venv
to time the science libs), so the conductor itself never imports the JAX stack;
the slow-test / slow-script signal is read from Heart, not re-run. A *standing*
Heart `import_time` (or `cli_noise`) leg — promoting the import pre-scan to a
tracked Heart signal — is a deferred optional follow-up (a PyAutoHeart change).

**`perf --profile <script>` (function profiling).** An on-demand action: run a
**normal-mode** script under `cProfile` in a subprocess (`HYGIENE_PYTHON`), then
rank the slowest dev-loop functions by *self* time as `/refactor` candidates (a
clear win may be flagged a JAX-adaptation candidate — a judgement, never
automatic). **Scope is broad by default** — simulation, data prep, model
composition, plotting, the aggregator, config, and general utilities (including
ones called *during* a fit). The **one hard boundary** is the **likelihood
function itself** (`log_likelihood_function` / `figure_of_merit` / `Fitness` +
its JAX/XLA compile) — that compute is `/profiling`'s domain. `_hygiene_profile.py`
draws it in two tiers: the likelihood boundary (self-ranking already drops the
entry points, which wrap the fit at ~0 self time) and non-refactorable noise
(no-source built-ins — not a scope choice). It is a **transparent heuristic, not
a perfect separator**: a hotspot inside the likelihood compute is `/profiling`'s,
a human/refactor judgement surfaced not enforced. `HYGIENE_PROFILE_EXCLUDE`
overrides the boundary tier to profile even more broadly. Heavy + per-target →
on-demand only (never the default scan, never a Heart tick).

## Fundamental principles

- **Find and prioritise; delegate the fix.** Hygiene surfaces quality debt and
  ranks it; the actual repair is ordinary dev-flow work routed to `refactor`
  (restructure), `bug` (regression-shaped), or a `feature` — shipped through
  `ship_library` / `ship_workspace`. The conductor never reinvents fix machinery.
- **Measurement lives in Heart; hygiene acts.** Heart already observes and tracks
  the dev-loop timing signals (`script_timing`, `test_run`); hygiene reads them
  and acts, the same split the health conductor follows. New standing signals
  (import cost, CLI noise) become Heart *legs*, not a new repo — hygiene has no
  persistent artifact lifecycle of its own to house (the reason it is a
  conductor with no paired organ).
- **Stdlib / bash only** in the conductor itself — like profiling, it must never
  drag the JAX stack into the Brain.

## Boundaries

- **vs profiling** — split by *what is measured*. Profiling owns the product's
  modelling / compute speed (likelihood on the science grid, GPU tiers, vram,
  A100, baselines/pins); hygiene owns the *developer loop's* cost (unit tests,
  `PYAUTO_TEST_MODE` / `PYAUTO_SMALL_DATASETS` integration scripts, import time).
  Hunting generally-slow functions flagged by integration tests is hygiene's
  `perf` mode (moved here from profiling's staged future modes). JAX-adaptation
  is shared: hygiene flags a dev-loop function and delegates; a likelihood on the
  science grid is profiling's call.
- **vs health** — Heart observes and verdicts; hygiene acts on the observations.
  Consults the vitals faculty; never issues a health verdict.
- **vs bug / refactor** — hygiene finds and prioritises debt and *delegates* the
  fix to them; they own the repair.
- **vs build** — hygiene is upkeep, not release; it never touches PyAutoHands.
- **vs Gut (PyAutoGut)** — the `tidy`/`sweep` modes are the **hygiene → PyAutoGut
  drive seam**, mirroring the **Heart ↔ vitals** template: the organ *holds and
  voids*, this conductor *decides what to condemn and when to sweep* and owns none
  of the storage. `tidy` enumerates 95%-sure debris and emits an async
  condemnation plan (proposed `condemned.md` entries + the exact `pyauto-gut
  archive` calls) — no synchronous per-item interrogation; `sweep` reads the
  manifest and emits the batch void plan for entries past their `sweep-after`
  transit date. The conductor stays a **planner** (never mutates a repo): it emits
  the plan, `pyauto-gut` archives/voids, and the existing `repo_cleanup` safety
  gates guard the sweep — there is no second gate. Design:
  PyAutoMind `complete/2026/07/pyautogut-organ-decision.md`.

## Capability audit — what `tidy`/`sweep` drive

- **PyAutoGut** (`bin/pyauto-gut`): `archive <local-ref> <slug>` (materialise a
  fragile form under `refs/heads/archive/condemned/<slug>` before deletion),
  `recover <slug>` (reabsorb during transit), `void <slug>` (eliminate on sweep),
  `list`. Resolved via `PYAUTO_GUT` or PATH; the conductor names the commands in
  its plan, it does not run them.
- **PyAutoMind `condemned.md`**: the catalog (symmetric to `parked.md`). `tidy`
  proposes entries; `sweep` reads them. Located via `resolve_mind` (`PYAUTO_MIND`
  → `$PYAUTO_ROOT/PyAutoMind`). `HYGIENE_CONDEMN_TRANSIT_DAYS` (default 30) sets
  the default transit window `tidy` writes into `sweep-after`.

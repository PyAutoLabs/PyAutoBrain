# /hygiene — keep the organism's code clean (via the Brain Hygiene Agent)

Route code-quality upkeep — including adjacent workspace documentation blocks
and other debt that neither proves the organism works (that is `/health`) nor
measures modelling speed (that is `/profiling`) — through PyAutoBrain's
**Hygiene Agent**. You never name the Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain hygiene [perf | tidy | noise | deps | docs | crlf |
   docstrings | refs | optdeps | extras | config | artifacts | packaging]` (no arg = pre-scan across modes → a ranked worklist;
   perf's import timing is deferred there). This is a **dry run** — each mode
   does a cheap read-only pre-scan and emits a `HygieneDecision` naming the
   skill to run for the full audit. Nothing is executed or mutated. (`crlf` =
   executable scripts w/ CRLF that break on HPC — library `.py` CRLF reported as
   cosmetic; `config` = library→workspace config-key drift; `artifacts` =
   tracked leaked outputs/data; `packaging` = ignored, fully-untracked top-level
   `*.egg-info/` and `build/` directories in managed library repositories;
   `docstrings` = exact adjacent module-level triple-quoted documentation
   boundaries in user-facing workspace and HowTo root entry scripts and
   `scripts/**/*.py` files; `refs` = dead internal references — file/folder
   paths quoted in workspace and HowTo prose whose target no longer exists
   after a restructure, across `scripts/**/*.py`, every nested
   `scripts/**/README.md` and `config/**/README.md`, and the top-level README,
   including folder-structure bullet lists and slash-less relative paths;
   `optdeps` = smoke-listed scripts that build an optional-dependency-gated API
   with no `find_spec` skip guard; `extras` = its complement, an optional
   dependency a library declares in the `[optional]` extra that the
   workspace-validation **smoke** leg never installs.)
2. Execute the emitted plan: run the named delegate — `/repo_cleanup` (git
   debris), `/cli_noise_clean`, `/dep_audit`, `/audit_docs` — for the full audit,
   or for `perf` route slow imports/functions to `/refactor` / `/bug` (JAX-adapt
   is a judgement call, never automatic). For `packaging`, preview with
   `DRY_RUN=1 PyAutoBrain/bin/clean_slate.sh --packaging`, then run it without `DRY_RUN` to
   remove only the reported generated directories. For `docstrings` and `refs`, route the
   exact reported findings to `/refactor`; the Hygiene scan remains read-only.
   A `refs` finding is the reference **as written** — judge the intended target
   (a moved file, a file that became a directory, a reference meant for a
   sibling repo) before re-pointing it. Route `optdeps` findings to `/refactor`
   too (add the skip guard), but route `extras` findings to `/bug`: a script
   that fails only in `mode=smoke` and **passes `mode=release`** is correct, so
   the defect is the CI install set — add the missing install (prefer the
   declaring library's whole `[optional]` extra). Never "fix" such a script by
   skip-guarding or parking it; both silently delete coverage that release
   validation still depends on.
   Source changes ship via `ship_library` / `ship_workspace`.

The Hygiene Agent **reasons; it never edits source and never mutates a repo.**
Measurement lives in Heart (`noise`/`deps`/`docs` route to read-only PyAutoHeart
skills; `perf`'s slow-test/script signal is read from Heart's `script_timing` /
`test_run`, and its import timing runs in a subprocess); hygiene pre-scans + routes.

All modes are live. Point `HYGIENE_PYTHON` at the PyAuto venv for `perf` to
time the science libraries (otherwise it reports advisory).

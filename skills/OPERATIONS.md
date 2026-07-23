# Operational gotchas (canonical)

Hard-won operational fixes that every agent — Claude, Codex, or otherwise —
needs and none can derive from the code. One entry per gotcha: the failure,
then the working move. Skills link here instead of restating; if you are
writing one of these workarounds into a skill body, stop and add it here.

These were distilled 2026-07-09 from session-memory lessons that had never
been written into the repos. Add new entries the same way: when a workaround
gets rediscovered twice, it belongs here.

## GitHub CLI fallbacks

- **`gh pr create` fails on SSH remotes.** When `origin` is an SSH URL it can
  refuse to resolve the repo. Fallback:
  `gh api repos/<owner>/<repo>/pulls -f title=… -f head=<branch> -f base=main -f body=…`
  then add labels with `gh api repos/<owner>/<repo>/issues/<n>/labels -f "labels[]=pending-release"`.
- **`gh issue close` is broken** (prints usage and fails). Comment first, then
  `gh api -X PATCH repos/<owner>/<repo>/issues/<n> -f state=closed`.
- **`gh pr edit` fails on repos with classic Projects** (GraphQL `projectCards`
  error aborts the whole edit). Use
  `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -f body=…` instead.

## Diff hygiene

- **CRLF files exist in PyAutoArray.** A scripted `open()`/`write()` edit
  normalises CRLF→LF and 10×'s the diff. Before scripted edits, check
  `grep -c $'\r$' <file>`; preserve the file's existing line endings.
- **Workspace ships can leak binary outputs.** New `images/`/output dirs are
  not always gitignored. Pre-flight every workspace ship with
  `git diff --stat` + `git status --short` and extend `.gitignore` before
  committing, never after.

## Config and environment

- **Smoke/env overrides live in `config/build/profile_smoke.yaml`**, not in
  `os.environ` mutations inside scripts. Fix the override file.
- **`PYAUTO_TEST_MODE` namespaces output under `output/test_mode/`.** Any
  manually composed output path must include that segment or asserts read the
  wrong tree.
- **autoconf lowercases YAML dict keys** (`muJy` → `mujy`). Keep config keys
  and the registries that read them snake-case-lowercase from the start.
- **New library `output.yaml` keys need mirroring** into each workspace's
  config copy — workspace configs override library defaults, so a key added
  only in the library silently stays off for workspace users.
- **Tools under `admin_jammy` resolve through their symlink**:
  `Path(__file__).resolve()` lands at the canonical checkout, not the
  worktree you invoked from. Pass `--root` or use the cwd.

## JAX measurement traps

- **`pure_callback` constant-folds under a single JIT trace** — the callback
  result gets baked in as an XLA constant and the op looks 20–30× faster than
  it is. Benchmark through `vmap` (e.g. `fitness._vmap(jnp.array(params))`),
  which is honest; never trust a single-JIT timing of callback-bearing code.
- **A closure created fresh per call cache-busts the JIT.** A new function
  object is a new cache key, so every call recompiles. Cache the
  (closure, solver) pair on the instance.

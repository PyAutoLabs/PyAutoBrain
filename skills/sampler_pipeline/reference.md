# Sampler pipeline — the development playbook

Long-form implementation reference for `SKILL.md`. The pipeline is a
**development task**: at every stage the session doing the work writes and
runs the code itself (through the normal `start_dev` worktree/plan/ship
workflow) — the faculty supplies judgment, this file supplies the how.

The canonical entry is a pointer at a sampler's **GitHub repo** ("get
<url> running on my likelihood"): Stage 0 ingests the repo, Stage 1 gets it
running on the standard problem, Stage 1b on the owned likelihood, and the
rest is evidence-gathering toward promote-or-archive.

## Stage 0 — ingest the sampler repo

Given a GitHub URL, before writing any adapter code:

1. **Run the repo's own quickstart first, verbatim.** Read README → docs →
   `examples/`; if the README alone doesn't show a runnable likelihood+prior
   example (e.g. nessai routes users to a `nessai-bilby` plugin), go to the
   docs site and examples dir — never guess an API from the package name.
2. **Dependency-compatibility check** against the installed stack *before*
   `pip install`: Python floor, JAX pin overlap with PyAutoConf's `[jax]`
   floor/ceiling, and heavyweight extras (a PyTorch-core sampler like nessai
   brings CUDA-pinning risk beside the JAX stack). Under-declared floors are
   real (the nufftax lesson) — check what the code imports, not just
   `pyproject`. Install with `pip install <pkg>` or `pip install git+<url>`
   into the dev env; note the exact ref/SHA in the prototype docstring.
3. **Classify the sampler on six API dimensions** — these pick the template
   and predict the adapter cost:

| Dimension | Common shapes | Adapter |
|---|---|---|
| Prior interface | unit-cube `prior_transform` (nautilus/dynesty/ultranest) · log-density on physical params (NSS/BlackJAX) · **distribution objects** (jaxns/numpyro: TFP dists via generator `prior_model`) | cube → `model.vector_from_unit_vector`; log-density → JAX-native `Prior.value_for`/`log_prior_from_value`; distribution objects → per-prior mapping to the library's dist classes — **costly, scope before promising** |
| Likelihood signature | single physical vector · batched array · pytree/dict params | `model.instance_from_vector` + `analysis.log_likelihood_function`; batched → `Fitness`/`_vmap` |
| Batching/parallelism | Python pool · `vmap`/devices on-chip | pool → callback template; on-chip → pure-JAX template |
| Gradients | none · required (`jax.grad`) | required → likelihood must be end-to-end traceable |
| Boundary escape hatches | e.g. jaxns `@jaxify_likelihood` (a `pure_callback` wrapper) | usable for a first run, but it reintroduces the host boundary — never benchmark through it and call the sampler "JAX-native" |
| Checkpoint/resume | files · in-memory state | matters at promotion (the `NonLinearSearch` resume contract), not at prototype |

## Stage 1 — writing the prototype (searches_minimal)

Copy the nearest existing script as the template:

| Candidate is a… | Template |
|---|---|
| Python-callback nested sampler | `nautilus_simple.py` (or `dynesty_simple.py`) |
| Pure-JAX / on-device sampler | `nss_jit.py` |
| Gradient-based MCMC | `nuts_jax.py` (BlackJAX NUTS + `window_adaptation`) |
| Optimiser / MLE | `lbfgs_simple.py` |

Rules that make the row comparable (enforced by convention, not tooling):

- Identical problem setup: 1D Gaussian (centre=50, normalization=25,
  sigma=10), 100 points, noise 0.01, `np.random.seed(1)`.
- **MLTracker wiring** (`from searches_minimal._metrics import MLTracker`):
  callback samplers wrap the likelihood (`tracker.wrap(fn)`); fully-jitted
  samplers reconstruct per-eval history afterwards
  (`MLTracker.from_log_l_history(...)` from dead/live-point state).
- Standard summary block → `output/<name>_summary.txt`: wall/sampling time,
  evals, time/eval, evals-to-ML, time-to-ML, ESS, log Z, max log L,
  posterior size, n_live.
- Gradient candidates: likelihood in pure `jax.numpy` (no callbacks, no
  numpy branches) so `jax.grad` traces; handle the prior box by transform or
  penalty; state explicitly what initialization the sampler needs.

**Run it** from the repo root so the package import resolves:

```bash
cd autofit_workspace_developer && python searches_minimal/<name>.py
```

## Stage 1b — running on a likelihood you own

The Gaussian row is the *comparability* baseline; the decision evidence is
the candidate on the likelihood you actually care about. The adapter is the
same two functions and is **model-agnostic** — nothing in the bridge is
Gaussian-specific:

```python
def prior_transform(cube):                     # unit-cube samplers
    return np.array(model.vector_from_unit_vector(cube))

def log_likelihood(params):                    # any af.Model + Analysis
    instance = model.instance_from_vector(vector=params)
    return float(analysis.log_likelihood_function(instance))
```

Swap in the owned `model` + `analysis` (an `autolens`/`autogalaxy`
`AnalysisImaging`, a workspace script's setup — whatever owns the
likelihood) and keep the MLTracker wiring. For JAX/batched samplers the
owned surface is `Fitness` — the `_vmap` path the
`autolens_workspace_test/scripts/jax_likelihood_functions/` scripts
exercise on real lensing likelihoods — and cube → physical stays inside
`jit` because `Prior.value_for` / `log_prior_from_value` are JAX-traceable
(the priors-jax-native work; without it a `pure_callback` hop costs ~18
ms/eval and erases the on-device advantage, per the HPC profiling
findings). Owned-likelihood scripts live beside the Gaussian ones (or in
`autolens_profiling` for HPC-scale runs) — their numbers go in the
promotion argument, not in `comparison.txt`, which stays a same-problem
table.

## Stage 2 — profiling

- Re-run the incumbent baselines in the same session (same machine, same
  environment) rather than trusting stale rows; add the candidate's row to
  `searches_minimal/output/comparison.txt` plus a Notes bullet interpreting
  it — convergence first (log Z within ~1 nat of reference, parameters
  recovered), speed second (time-to-ML, time/eval).
- Honest-benchmarking rules: no `pure_callback` under single-JIT
  (constant-folding fakes 20–30×); time through `vmap` with traced inputs;
  cache compiled closures. Full list: the faculty's AGENTS.md.
- Real-likelihood evidence (required before any promotion argument): run
  the candidate on lensing use cases via `autolens_profiling` — the
  `/profile_likelihood` skill drives the sweep machinery; A100/HPC runs go
  through that repo's conventions.
- Record durable findings in `PyAutoMemory/methods_wiki/concepts/
  sampler-benchmarks.md` (internal; never cited in public output).

## Stage 3 — promotion: the PyAutoFit implementation

**Reference implementations** (read before writing a line):
`nest/nss/` — JAX nested sampler, chunked-vmap internals, ~600-line
`search.py`; `mcmc/blackjax/nuts/` — gradient consumer wired through
`use_jax`; `nest/nautilus/` — the canonical Python-callback shape.

A new search package `autofit/non_linear/search/<group>/<name>/` needs:

1. **`search.py`** — subclass of the group abstract (`AbstractNest` /
   `AbstractMCMC` / `AbstractMLE`): config kwargs on `__init__`, a `_fit()`
   that drives the external sampler API through autofit's `Fitness`,
   checkpoint/resume through `paths` (see NSS's pickle + `NullPaths`
   handling), an `is_test_mode` short-circuit, and an internal-state holder
   if the sampler carries one (cf. `_NSSInternal`).
2. **`samples.py`** — a `Samples` subclass converting sampler output into
   autofit samples (cf. `NSSamples(SamplesNest)` — ~25 lines when the group
   abstract does the heavy lifting).
3. **Public export** — `autofit/__init__.py` (`af.<Name>` is the API).
4. **Dependency** — optional extra in `pyproject.toml`. Gotcha: PyPI
   rejects git-URL dependencies in uploaded wheels ("400 Can't have direct
   dependency") — fork-only deps get a manual-install comment in
   `pyproject.toml` and a post-extras install step in the CI jobs (the
   `[nss]` extra is the worked example).
5. **Unit tests** — `test_autofit/non_linear/search/<group>/test_<name>.py`,
   **numpy-only** (library unit tests never import JAX; cross-backend checks
   live in workspace_test).
6. **Config surfaces** — if the search introduces new output/config keys,
   mirror them into each workspace's config (workspace configs override
   library defaults; a default-on key without the mirror fires warnings in
   every consumer).

This is a normal library task: Mind prompt via `/intake`, `start_dev`,
worktree, plan, `ship_library`.

## Stage 4 — integration scripts (and running them)

- Add `autofit_workspace_test/scripts/searches/<Name>.py` by copying an
  existing script (`Nautilus.py` for callback, `BlackJAXNUTS.py` for
  gradient/JAX): same 1D Gaussian dataset, the auto-simulate snippet, and
  **reduced settings** — the goal is "the path executes end-to-end and
  parameters land near truth", not a science-quality posterior.
- JAX searches construct the analysis with `use_jax=True`; jitted-likelihood
  variants of CPU searches follow the `<Name>_jax.py` convention.
- **Run on demand** from the workspace root:

```bash
cd autofit_workspace_test && python scripts/searches/<Name>.py
```

  (`PYAUTO_TEST_MODE` namespaces output under `output/test_mode/`.) These
  scripts are deliberately **not** in the curated smoke lists — never grow
  `smoke_tests.txt` to exercise a sampler.

## Running the pipeline under `--auto`

"Point at a repo and go" maps onto the autonomy contract
([`../../AUTONOMY.md`](../../AUTONOMY.md)) as **two Mind tasks**:

1. **Trial task** (Stages 0–2; work-type `research`/`feature`, cap
   `supervised`): ingest, prototype, Stage 1b on the owned likelihood,
   benchmark rows — mechanical stretches proceed hands-off; the
   **promote-or-archive call is the one judgment gate**, posted as a batched
   question on the issue (checkpoint-and-continue), or pre-answered at
   launch ("if it converges and beats X on my likelihood, proceed").
2. **Promotion task** (Stages 3–4; a normal `feature/autofit` library task):
   runs `start_dev → ship_library` under the same contract — implementation
   proceeds, ship sign-off checkpoints, PR-open ends the run.

A dependency-compatibility failure at Stage 0 (pin conflict, missing fork)
is a hard blocker, not a question: write it up on the issue and park.

# Samplers faculty

> **Tier: faculty** — a read-only reasoning capability the conductors
> *consult*, not a front door you drive. It is the organism's **motor
> faculty**: expertise in how the organism *moves through parameter space*.
> Given a task that touches non-linear search work — a new sampler candidate,
> a profiling question, "which search for this likelihood" — it returns the
> **SamplerSurface** digest plus this page's judgment tables, and stops. It
> never dispatches, never edits source, never runs a fit.

Samplers are the organism's gaits: gradient-free nested sampling is the
robust walk that works on any terrain; HMC/NUTS is the run — far faster per
unit distance but needing working tendons (gradients) and a good starting
stance (initialization). This faculty holds the judgment for matching gait to
terrain, and the `sampler_pipeline` skill (`skills/sampler_pipeline/`) drives
the learning of a new gait: prototype → profile → promote.

## The SamplerSurface

The entrypoint inventories the sampler machinery deterministically:

```
samplers.sh [--json]
  -> tiers: minimal (autofit_workspace_developer/searches_minimal)
            archive (autofit_workspace_developer/searches)
            integration (autofit_workspace_test/scripts/searches)
            promoted (PyAutoFit autofit/non_linear/search/<group>/<module>)
  -> the latest minimal-tier benchmark table (output/comparison.txt)
  -> tier gaps: prototyped-never-promoted, promoted-never-integration-tested
```

Surfaces are resolved as sibling checkouts (`PYAUTO_FIT`,
`PYAUTO_FIT_DEVELOPER`, `PYAUTO_FIT_TEST` override); absent ones are
reported, never fatal. Exit codes: `0` digest · `4` no surface · `5` usage.

## Judgment: matching sampler to likelihood

| Situation | Reach for | Why |
|---|---|---|
| Cold start, multi-modal risk, evidence needed | Nautilus / dynesty (CPU), NSS (JAX likelihood) | global, evidence-bearing, no gradient needed |
| JAX-native likelihood, GPU available | NSS (vmap-batched) | sampler+likelihood in one XLA program; ~50× per-eval win in the minimal benchmarks, ~7.5×/eval on MGE lens models (A100) |
| Smooth likelihood with `jax.grad` available, mode known | BlackJAX NUTS / `nss_grad` | gradient moves; fastest time-to-posterior, but posterior-only (no log Z) and needs a warm start |
| Posterior refinement around a known mode, no gradients | Emcee / Zeus | ensemble MCMC; tolerant of an imperfect start |
| Quick mode-finding / sanity | LBFGS, Drawer | MLE / prior-draw debugging only |
| Inversion-heavy likelihood (pixelization/Delaunay, big NUFFT) on GPU | NSS **with chunked vmap** | plain vmap fan-out OOMs even an A100 |

## Judgment: gradients and JAX constraints

- A sampler variant is only as JAX-native as its likelihood: `jit` on a
  Python-callback sampler buys nothing (nautilus_simple ≈ nautilus_jax in
  the benchmarks); the win requires the *sampler* to batch on-device.
- `jax.grad` needs end-to-end traceability — `pure_callback` hops or numpy
  branches kill it (or silently zero it). If the likelihood isn't pure JAX,
  gradient-based samplers are off the menu.
- Benchmark honestly: `pure_callback` under single-JIT constant-folds (looks
  20–30× faster than reality); validate via `vmap` with traced inputs, and
  cache compiled closures on the instance (a fresh closure per call re-pays
  compile every time).

## Judgment: initialization (providers vs consumers)

- **Providers** (start cold, map the space): Nautilus, dynesty, NSS,
  UltraNest; cheap mode-finders (LBFGS, PySwarms) provide a point only.
- **Consumers** (need a warm start): HMC/NUTS — a start in the tails wastes
  the whole warmup window or diverges; ensemble MCMC — merely slow to burn
  in. The natural chain is nested sampling → NUTS (seed chains from
  posterior draws; posterior covariance as initial mass matrix).
- Any promoted search that *requires* initialization must declare its
  provider (PyAutoFit chained searches / `autofit/non_linear/initializer.py`
  — `InitializerPrior`, `InitializerBall`, `InitializerParamBounds`), never
  assume one.

## Judgment: promotion criteria (minimal → PyAutoFit)

Promote a prototyped sampler only when **all** hold:

1. Its minimal-tier row is comparable — the script honours the
   `_metrics.MLTracker` contract (evals-to-ML, time-to-ML, ESS, log Z).
2. It converges: log Z within ~1 nat of the reference samplers, parameters
   recovered (wall-time wins with a broken evidence integral don't count —
   see nss_simple's 15-nat error in the benchmark record).
3. It wins somewhere concrete: a use case (likelihood class × hardware)
   where it beats the incumbents on time-to-ML or time/eval at equal
   quality — ideally confirmed on a real likelihood (autolens_profiling),
   not just the 1D Gaussian.
4. The implementation cost is justified: a full `NonLinearSearch` subclass
   must support the Analysis wrap, results/samples API, visualization and
   resumption — that is the expensive step the minimal tier exists to gate.

## Where the knowledge lives (pointers, not copies)

- **PyAutoFit search API** — `PyAutoFit:autofit/non_linear/search/`
  (`nest/`, `mcmc/`, `mle/`; base class `abstract_search.py`; start-point
  machinery `autofit/non_linear/initializer.py`).
- **Script tiers** — `autofit_workspace_developer/searches_minimal/`
  (prototypes + `_metrics.py` + `output/comparison.txt`),
  `autofit_workspace_developer/searches/` (removed-sampler archive),
  `autofit_workspace_test/scripts/searches/` (integration scripts).
- **The science** — `PyAutoMemory/methods_wiki`:
  `concepts/hamiltonian-monte-carlo.md`, `concepts/gpu-nested-sampling.md`,
  `concepts/initialization-chaining.md`, `concepts/sampler-benchmarks.md`
  (the campaign record), `concepts/nested-sampling.md`. **Privacy seam:**
  PyAutoMemory is personal — its citations flow into Mind prompts, issues
  and Brain plans, but never into public user-facing output (the memory
  faculty's AGENTS.md is the rule's home).
- **Profiling campaigns** — `autolens_profiling` (A100/HPC runs on real
  lensing likelihoods).

## Run

```bash
bin/pyauto-brain samplers            # human-readable SamplerSurface
bin/pyauto-brain samplers --json     # machine-readable
```

## What this faculty must never do

- Run a sampler, fit, or benchmark — it reads recorded outputs only.
- Write, dispatch, or file anything — promotion happens through the
  `sampler_pipeline` skill and the normal `start_dev` workflow.
- Invent benchmark numbers — an absent `comparison.txt` means "no benchmark
  record", and the consulting agent says so.
- Leak PyAutoMemory citations toward public user-facing output.

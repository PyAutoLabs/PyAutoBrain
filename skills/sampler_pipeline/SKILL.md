---
name: sampler_pipeline
description: Trial a new non-linear sampler through the prototype → profile → promote pipeline — minimal searches_minimal script with MLTracker diagnostics, benchmark comparison, then (if warranted) a Mind prompt for the full PyAutoFit implementation. Use when the user wants to try, benchmark, or promote a sampler / search / MCMC / nested-sampling / HMC method.
---

# Sampler Pipeline: Prototype → Profile → Promote

The organism learning a new gait: try the movement cheaply, practice it with a
stopwatch, and only then commit it to muscle memory (a full PyAutoFit
`NonLinearSearch`). This is a **PyAutoBrain dev-workflow** skill: it reasons
with the **samplers faculty** and routes every edit through the normal
`start_dev` workflow — shared context in [`WORKFLOW.md`](../WORKFLOW.md).

## 0. Consult the faculty first

```bash
bin/pyauto-brain samplers        # the SamplerSurface: tiers, catalogue, benchmarks, gaps
```

Read `agents/faculties/samplers/AGENTS.md` for the judgment tables (sampler ↔
likelihood match, gradient/JAX constraints, initialization chaining, promotion
criteria). If the candidate is already prototyped or promoted, resume at the
right stage instead of starting over. The deeper science is in
`PyAutoMemory/methods_wiki` (`hamiltonian-monte-carlo`, `gpu-nested-sampling`,
`initialization-chaining`, `sampler-benchmarks`) — internal use only; its
citations never reach public user-facing output.

## 1. Prototype (minimal tier)

A new sampler lands first as **one script** in
`autofit_workspace_developer/searches_minimal/` — external sampler API plugged
directly into `af.Model`/`Analysis`, **no** `NonLinearSearch` subclass. This is
a workspace edit: file/annotate the Mind prompt and go through `start_dev`.

The prototype contract (what makes its row comparable):

- Same problem as the existing scripts: 1D Gaussian (centre=50,
  normalization=25, sigma=10), 100 points, noise 0.01, `np.random.seed(1)`.
- Honour `_metrics.MLTracker` — wrap the likelihood (callback samplers) or
  reconstruct per-eval history (fully-jitted samplers) so evals-to-ML and
  time-to-ML are reported.
- Emit the standard summary block (wall/sampling time, evals, time/eval, ESS,
  log Z, max log L, posterior size, n_live) to `output/<name>_summary.txt`.
- Gradient-based candidates: pure-`jax.numpy` likelihood so `jax.grad` works;
  state the initialization the sampler needs (see the faculty's
  provider/consumer table).

## 2. Profile (benchmark tier)

- Run the prototype plus the incumbent baselines; add the candidate's row to
  `searches_minimal/output/comparison.txt` with a Notes bullet interpreting
  it (convergence first, speed second — log Z agreement within ~1 nat, then
  wall time / time-to-ML).
- Benchmark honestly: no `pure_callback` under single-JIT (constant-folding),
  `vmap` for traced-input timings, compiled closures cached.
- If the candidate targets real likelihoods (lensing MGE / pixelization /
  interferometer), extend to `autolens_profiling` use-case runs before any
  promotion argument — the 1D Gaussian alone never justifies promotion.
- Record durable findings in `PyAutoMemory/methods_wiki` (update
  `concepts/sampler-benchmarks.md`).

## 3. Promote (or archive)

Score the candidate against the faculty's **promotion criteria** (all four:
comparable row · converged · concrete win · implementation cost justified).

- **Promote** → file a Mind prompt via `/intake` for the PyAutoFit
  implementation: `NonLinearSearch` subclass under
  `autofit/non_linear/search/<group>/<name>/`, plus an integration script in
  `autofit_workspace_test/scripts/searches/` (and a `*_jax` variant when the
  likelihood is jittable). That prompt runs `start_dev → ship_library` as a
  normal library task — this skill never edits library source itself.
- **Archive** → the prototype stays in `searches_minimal/` as the record;
  note the negative result in the comparison Notes (a measured "no" is a
  result — nautilus_jax vs nautilus_simple is the canonical example).
- Removed-from-PyAutoFit samplers move to
  `autofit_workspace_developer/searches/<name>/` (the archive tier), like
  UltraNest and PySwarms.

## Boundary

- The faculty **opines**, this skill **drives**, `start_dev` **executes** —
  no edit bypasses the dev workflow, and promotion PRs go through the normal
  ship gates.
- Do not grow the smoke-test lists to exercise a new sampler; integration
  scripts live in `scripts/searches/` and are run on demand.

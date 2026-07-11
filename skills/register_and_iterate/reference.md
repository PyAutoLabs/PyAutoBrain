# register_and_iterate — reference detail

Factored out of `register_and_iterate.md` (read it by repo path from the
PyAutoBrain checkout). Holds the classification heuristic, the scaffold pattern,
the delegation block, the recommended queue, and failure/reporting detail.

## Scaffold `<variant>_pytree.py`

Copy `autolens_workspace_test/scripts/jax_likelihood_functions/imaging/mge_pytree.py`
as the template. From the prompt's `__Reference script__`, splice the reference's
dataset + mask + model construction into the template. Replace the assertion body
with the three-step round-trip:

```python
ref = analysis.fit_from(instance).log_likelihood                              # NumPy reference
jit_ll = jax.jit(lambda i: analysis.fit_from(i).log_likelihood)(instance)     # jit round-trip
assert jnp.allclose(ref, jit_ll, rtol=1e-4), f"divergence: {ref} vs {jit_ll}"
print("PASS: jit(fit_from) round-trip matches NumPy scalar.")
```

Target path:
`autolens_workspace_test/scripts/jax_likelihood_functions/<path>/<variant>_pytree.py`.

## Registration loop (max_iters = 8)

Each iteration: run the script inside the worktree (`activate.sh` sourced); on
`PASS` break; on error parse the traceback, identify the offending type (frame
above the JAX tracer error, or a `jax.tree_util` `TypeError: unhashable type` /
`NotImplementedError`), classify it, register via
`register_instance_pytree(<Cls>, no_flatten=<aux_fields>)` at the right site
(e.g. `_register_fit_imaging_pytrees` in PyAutoLens) with a one-line comment
naming the variant task, then re-run. If `max_iters` is exhausted with no PASS,
dump the full log to `~/Code/PyAutoLabs-wt/<task>/register_iterate.log` and ask
the user to take over.

## Classification heuristic

Read the offending class's `__init__` / `__dict__`:

- **All attrs are `jax.Array` / `np.ndarray` / `AbstractNDArray` / primitives** →
  auto-register `no_flatten=()` (all dynamic).
- **Known-aux patterns** (`cosmology`, `settings`, `config`, `dataset`, `psf`,
  `mask`, `_cache`, `_compiled`, any `scipy.spatial.*`, `Transformer*`,
  `PointSolver*`) → auto-register with those fields in `no_flatten`.
- **Has a callable attribute** → **pause** and ask the user (aux / dyn / split /
  skip / blocker), showing file, attrs+types, and a suggested `no_flatten`.
- **On the prompt's `__What's likely to surface__` hit-list** → follow the
  prompt's guidance (e.g. `TransformerNUFFT` → aux; NNLS solver state → blocker).

## After PASS

Run the affected library repo's suite under the worktree (`pytest test_<repo>/
-x`); if red, stop and show failures. Re-run the new `_pytree.py` as a smoke
check. Stage changes (do **not** commit). Then hit the ship-approval gate.

## Delegation (local-dev)

Delegate the mechanical run-and-register cycle to an execution-tier subagent; the outer
skill keeps cross-task context and handles judgement gates.

```
Agent(model="sonnet", subagent_type="general-purpose", prompt="""
  Inside ~/Code/PyAutoLabs-wt/<task>/, source activate.sh and run
  <task>/autolens_workspace_test/scripts/jax_likelihood_functions/<path>/<variant>_pytree.py.
  On error: identify the offending type, read its class, classify (paste the
  heuristic above). If unambiguous, register via register_instance_pytree at the
  right site and re-run. Max 8 iterations. Stop on: PASS / ambiguous
  classification (report class+attrs) / blocker (report why) / iters exhausted
  (report full log). Report a table of (Class, Registration Site, no_flatten, iter).
""")
```

## Recommended queue (write to PyAutoMind/queue.md if absent)

```
1. autolens/linear_light_profile_intensity_dict_pytree.md
2. autolens/fit_imaging_pytree_lp.md
3. autolens/fit_imaging_pytree_rectangular.md
4. autolens/fit_imaging_pytree_mge_group.md
5. autolens/fit_imaging_pytree_delaunay.md
6. autolens/fit_interferometer_pytree_mge.md
7. autolens/fit_point_pytree.md
8. autolens/fit_imaging_pytree_rectangular_mge.md
9. autolens/fit_imaging_pytree_rectangular_dspl.md
10. autolens/fit_imaging_pytree_delaunay_mge.md
11. autolens/fit_interferometer_pytree_mge_group.md
12. autolens/fit_interferometer_pytree_rectangular.md
```

Skip blank/`#` lines; process in order; on a successful ship prepend
`# DONE <date> ` to the line (don't delete — preserves ordering history).

## Failure modes

- **Iteration limit** → dump `register_iterate.log`, pause queue.
- **Dependency not shipped** → pause, name the prompt to run first.
- **Test regression after PASS** → stop, show failing tests; do not ship.
- **Worktree dirty on resume** → warn, ask discard or continue.
- **Classification ambiguity** → pause with the structured prompt.
- **Subagent blocker** → stop queue, write the blocker per the prompt's fallback
  clause; advance only on explicit user confirmation.

## Reporting (end of queue / on pause)

Print `Shipped (N)` / `Paused (M)` / `Pending (K)` lists, one line per task with
its PR links or pause reason.

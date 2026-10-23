# Likelihood lifecycle — phase-prompt template

The sequence every PyAutoLens likelihood follows from first registration to a
designated, validated, sampler-tested setup (report §3.9 of the
`likelihood-lifecycle` epic). This page is a **template**: each step below ends
in one fenced `prompt` block that renders, by plain placeholder substitution,
into one PyAutoMind phase prompt. Phase 8's `pyauto-brain profiling lifecycle`
verb renders it mechanically; until then a session renders it by hand and files
the prompts through `/intake`.

## Placeholders

One set, nothing else is substituted:

| Placeholder | Value |
|---|---|
| `<dataset_type>` | one of the ten dataset types (`imaging`, `interferometer`, `datacube`, `point_source_image`, `point_source_source`, `multi_galaxy`, `group`, `cluster`, `multi_dataset`, `weak`) |
| `<variant>` | the likelihood variant (`delaunay`, `mge`, `source_plane`, …) |
| `<instrument>` | the reference instrument the cells are measured on (`hst`, `sma`, `simple`, …) |
| `<regime>` | the named size bin (`standard` where the type has one bin) |
| `<trigger>` | `new` (a likelihood not yet registered) or `reoptimised` (an existing likelihood whose optimum may have changed) |

## Rendering rules

1. `<trigger>` = `new` renders L0–L7. `<trigger>` = `reoptimised` renders L2–L7
   and drops L2's `Blocked-by:` line; L2's new `current` records supersede the
   prior ones.
2. L6 is rendered only when the human answers yes at the L3 gate to "could this
   designation change which sampler is chosen?". When L6 is not rendered, L7's
   `Blocked-by:` names Phase 5.
3. Each block is written to the path on its fence line, substituted the same
   way. The folder after the work type is the census target, so it matches
   `Target:`.
4. File prompts lazily, one phase at a time, after the previous phase ships
   (ledger rule of the `likelihood-lifecycle` epic). When the previous phase's
   issue exists at filing, `Blocked-by:` may carry its `Repo#N` ref instead.
5. The epic slug is `lifecycle-<dataset_type>-<variant>`; add it to Mind
   `epics.md` when L0 (or L2 for `reoptimised`) is filed.

Every rendered header passes the `pyauto-brain intake census` header check
(`tests/test_profiling_lifecycle_template.py` renders `imaging/delaunay`).

## Reading Pulse and Insight

- Lookups read `class: optimal` and `status: current` unless the request asks
  for secondary, experimental or superseded rows.
- `optimal` is always a PyAutoPulse `designation` decision. The producer
  declares `class` from that decision; no conductor infers or assigns it.
- Full-fit wall-time validation is a PyAutoPulse evidence axis
  (`walltime-validation@1`, instance `lens-walltime`, producer
  autolens_inference), never a PyAutoInsight artefact.
- PyAutoInsight sampler campaigns record `setup_mode: auto`, with
  `setup_resolved` as provenance.
- Pulse selector order: Class → Likelihood → Instrument → Hardware class →
  Measurement.

## Steps

| Step | Owning repos | Brain door | Human gate | Witness (short) |
|---|---|---|---|---|
| L0 register | autolens_profiling, PyAutoPulse | `/profiling`, `/intake` | approve regime bins and planned classes | planned cells listed as `missing` |
| L1 figures | autolens_visualization, PyAutoEyes | `/eyes` | sign off `fit.png` | `fit.png` signed off |
| L2 profile | autolens_profiling, PyAutoPulse | `/profiling` | RAL compute per batch | no missing/stale optimal or secondary runtime/breakdown cell |
| L3 designate | PyAutoPulse, autolens_profiling, PyAutoArray, PyAutoLens, autolens_workspace, autolens_assistant | `/profiling`, `/intake` | approve the designation | Pulse `designation` decision resolved by every optimal record |
| L4 validate | autolens_inference, PyAutoPulse | `/profiling` | RAL compute per batch | `walltime-validation@1` row per optimal setup |
| L5 gradient | autolens_profiling, PyAutoPulse | `/profiling` | RAL compute per batch | current `gradient` record with passing FD check |
| L6 samplers | autolens_inference, PyAutoInsight | `/sampler_pipeline` | protocol freeze; compute | ≥3-seed rows per sampler under `setup_mode: auto` |
| L7 close | PyAutoPulse, PyAutoMind, PyAutoCortex | `/cortex` | human closes the epic | Pulse task complete; Mind record; Cortex note |

### L0 register

Register the likelihood: the taxonomy row and source route in autolens_profiling
(`catalogue/script_routes.json`), the declared regime, and the Pulse
`planned_cells` with a class per setup.

```prompt draft/feature/autolens_profiling/lifecycle_<dataset_type>_<variant>_l0_register.md
# Lifecycle <dataset_type>/<variant> L0 register: taxonomy row, regime and Pulse planned cells

Type: feature
Target: autolens_profiling
Repos:
- autolens_profiling
- PyAutoPulse
Themes:
- profiling
- dashboard
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: `pyauto-brain profiling campaign` lists the `<dataset_type>/<variant>` planned cells on `<instrument>` (regime `<regime>`) as `missing` under their declared class, and `pyauto-pulse check` accepts the `profiling-summary@3` catalogue that declares them
Review-minutes: 10
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 0

Lifecycle step L0 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_profiling: add the source route and runtime cell for `scripts/<dataset_type>/<variant>/` to `catalogue/script_routes.json`; declare regime `<regime>` for `<instrument>`.
- autolens_profiling catalogue: emit `planned_cells` for `<dataset_type>/<variant>` on `<instrument>`, one per setup and measurement (`runtime`, `breakdown`), each with the class the producer declares (`optimal`, `secondary` or `experimental`).
- Human gate: approve the regime bins and the planned classes before L2 measures anything.
- Door: `/profiling` (`campaign` shows the new cells); this prompt is filed through `/intake`.
```

### L1 figures

Render `fit.png` for the likelihood through the visualization plotter and sign
it off (the Eyes loop when the figure is new).

```prompt draft/feature/autolens_visualization/lifecycle_<dataset_type>_<variant>_l1_figures.md
# Lifecycle <dataset_type>/<variant> L1 figures: fit.png through the viz plotter, signed off

Type: feature
Target: autolens_visualization
Repos:
- autolens_visualization
- PyAutoEyes
Themes:
- visualization
- profiling
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: `fit.png` for `<dataset_type>/<variant>` on `<instrument>` is rendered by the visualization harness, listed in `gallery/viz_manifest.yaml`, and signed off by the human in the `/eyes` loop
Review-minutes: 10
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 1
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 0

Lifecycle step L1 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_visualization: add or refresh the producer that renders `fit.png` for `<dataset_type>/<variant>` on `<instrument>`.
- PyAutoEyes: the figure appears on the Eyes board through the manifest; nothing is copied.
- Human gate: the human signs off `fit.png` in the `/eyes` loop.
- Door: `/eyes`.
```

### L2 profile

Measure runtime and breakdown under the Optimal and Secondary candidates on
reference hosts with a parity witness; the new records become `current` and
the prior ones `superseded`. A `reoptimised` likelihood enters here.

```prompt draft/research/autolens_profiling/lifecycle_<dataset_type>_<variant>_l2_profile.md
# Lifecycle <dataset_type>/<variant> L2 profile: runtime and breakdown under optimal and secondary candidates

Type: research
Target: autolens_profiling
Repos:
- autolens_profiling
- PyAutoPulse
Themes:
- profiling
- hpc-gpu
Difficulty: medium
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: `pyauto-brain profiling campaign` reports zero `missing` and zero `stale` cells for `<dataset_type>/<variant>` on `<instrument>` across class optimal and secondary × measurement runtime and breakdown, each current record on a reference host class with a passing `parity.json`, prior records `superseded`, and the Pulse receipt ok
Review-minutes: 20
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 2
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 1

Lifecycle step L2 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_profiling: run `scripts/<dataset_type>/<variant>/likelihood_runtime.py` and `likelihood_breakdown.py` for every planned optimal and secondary setup on reference host classes (`hpc_ral_cpu` on `--partition=ral`, `hpc_a100` with `--gres`); write `results/<dataset_type>/<variant>/<instrument>/<setup_id>/<host_class>/` with `parity.json`.
- Catalogue: the new records are `current`; the records they replace are `superseded` with `superseded_by` set. `local_*` host rows are never `current`.
- Human gate: authorise each RAL batch.
- Door: `/profiling` (`campaign` gives the plan; it never runs).
```

### L3 designate

Record which setup is Optimal and which are Secondary for the likelihood and
regime, and carry the decision into the library, the run-time estimates and
the user-facing text.

```prompt draft/feature/pyautopulse/lifecycle_<dataset_type>_<variant>_l3_designate.md
# Lifecycle <dataset_type>/<variant> L3 designate: Pulse designation decision, rule table, estimates and text

Type: feature
Target: pyautopulse
Repos:
- PyAutoPulse
- autolens_profiling
- PyAutoArray
- PyAutoLens
- autolens_workspace
- autolens_assistant
Themes:
- profiling
- assistants
Difficulty: medium
Autonomy: human-required
Priority: normal
Status: formalised
Consequence: judge
Witness: PyAutoPulse `decisions.yaml` has a `designation` row for `<dataset_type>/<variant>` regime `<regime>` naming the optimal and secondary `setup_id`s with evidence record ids, every `class: optimal` current record cites it as `decision_id`, and the library rule-table parity test passes
Review-minutes: 25
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 3
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 2

Lifecycle step L3 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- PyAutoPulse: a `designation` decision (`decisions/<id>.md` + `decisions.yaml`) with `likelihood`, `regime`, `hardware_class`, `optimal`, `secondary`, `evidence`, `rule`, `supersedes`.
- autolens_profiling: the wiki decision-rule note under `wiki/campaigns/<dataset_type>/<variant>/`; catalogue records declare `class` from the decision.
- PyAutoArray: rule-table PR from the decision; PyAutoLens: `runtime_estimates` refresh.
- autolens_workspace and autolens_assistant: text that names the setup follows the decision.
- Human gate: the human approves the designation. `optimal` is never inferred by a conductor.
- Door: `/profiling` (`ingest`); library and workspace edits go through `/start_dev`.
```

### L4 validate

Full-fit wall-time validation of the Optimal setups: autolens_inference
produces `walltime-validation@1` records that PyAutoPulse renders (instance
`lens-walltime`).

```prompt draft/research/autolens_inference/lifecycle_<dataset_type>_<variant>_l4_validate.md
# Lifecycle <dataset_type>/<variant> L4 validate: full-fit wall-time validation on the optimal setups

Type: research
Target: autolens_inference
Repos:
- autolens_inference
- PyAutoPulse
Themes:
- profiling
- hpc-gpu
Difficulty: medium
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: PyAutoPulse instance `lens-walltime` holds a `walltime-validation@1` record for every optimal setup of `<dataset_type>/<variant>` on `<instrument>`, each with `reference_runtime_record_id` resolving to the L2 current runtime record and `ratio_measured_over_predicted` declared
Review-minutes: 20
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 4
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 3

Lifecycle step L4 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_inference: run `scripts/<dataset_type>/<variant>/validation/` for each optimal setup; results under `results/<dataset_type>/<variant>/<instrument>/validation/`.
- PyAutoPulse: the `lens-walltime` receipt refreshes; Pulse renders the producer's derived numbers and computes none.
- Human gate: authorise each RAL batch.
- Door: `/profiling` (the conductor judges timing; PyAutoInsight is not involved).
```

### L5 gradient

`value_and_grad` breakdown under each Optimal setup with a finite-difference
check, recorded as the `gradient` measurement.

```prompt draft/research/autolens_profiling/lifecycle_<dataset_type>_<variant>_l5_gradient.md
# Lifecycle <dataset_type>/<variant> L5 gradient: value_and_grad breakdown with a finite-difference check

Type: research
Target: autolens_profiling
Repos:
- autolens_profiling
- PyAutoPulse
Themes:
- jax-gradient
- profiling
Difficulty: medium
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: `pyauto-brain profiling campaign` reports a `current` `gradient` cell for every optimal setup of `<dataset_type>/<variant>` on `<instrument>`, each record carrying a passing finite-difference check
Review-minutes: 15
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 5
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 4

Lifecycle step L5 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_profiling: run `scripts/<dataset_type>/<variant>/gradient_breakdown.py` under each optimal setup; write `gradient.json` beside the runtime record.
- Catalogue: `measurement: gradient` records, `current`, with the FD check in `values`.
- Human gate: authorise each RAL batch.
- Door: `/profiling`.
```

### L6 samplers

A PyAutoInsight sampler campaign under `setup_mode: auto`, rendered only when
the designation could change which sampler is chosen (rendering rule 2).

```prompt draft/research/autolens_inference/lifecycle_<dataset_type>_<variant>_l6_samplers.md
# Lifecycle <dataset_type>/<variant> L6 samplers: Insight campaign under setup_mode auto

Type: research
Target: autolens_inference
Repos:
- autolens_inference
- PyAutoInsight
Themes:
- samplers
- hpc-gpu
Difficulty: large
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: judge
Witness: PyAutoInsight shows at least three scored seeds per sampler for `<dataset_type>/<variant>` on `<instrument>`, every record with `setup_mode: auto` and `setup_resolved` recorded
Review-minutes: 25
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 6
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 5

Lifecycle step L6 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- autolens_inference: run `scripts/<dataset_type>/<variant>/samplers/` under `setup_mode: auto`; results under `results/<dataset_type>/<variant>/<instrument>/samplers/<model_variant>/<sampler>/auto/seed_<n>/`.
- PyAutoInsight: the receipt refreshes; `setup_resolved` is provenance, not identity.
- Human gate: freeze the protocol before compute; authorise each batch.
- Door: `/sampler_pipeline` (the samplers faculty lists the cells).
```

### L7 close

Close the lifecycle: the Pulse campaign task completes, the Mind records the
epic, and the Cortex notes any change to the science.

```prompt draft/maintenance/pyautopulse/lifecycle_<dataset_type>_<variant>_l7_close.md
# Lifecycle <dataset_type>/<variant> L7 close: Pulse task complete, Mind record, Cortex note

Type: maintenance
Target: pyautopulse
Repos:
- PyAutoPulse
- PyAutoMind
- PyAutoCortex
Themes:
- dashboard
- mind-workflow
Difficulty: small
Autonomy: supervised
Priority: normal
Status: formalised
Consequence: glance
Witness: the PyAutoPulse campaign task for `<dataset_type>/<variant>` is `complete`, PyAutoMind holds the epic's `complete/` record, and the PyAutoCortex ledger carries a note wherever the science changed
Review-minutes: 5
Unattended: never
Epic: lifecycle-<dataset_type>-<variant>
Phase: 7
Blocked-by: lifecycle-<dataset_type>-<variant> Phase 6

Lifecycle step L7 for `<dataset_type>/<variant>` on `<instrument>`, regime `<regime>`, trigger `<trigger>`.

- PyAutoPulse: mark the campaign task for `<dataset_type>/<variant>` complete.
- PyAutoMind: write the epic's `complete/` record and retire it from `epics.md`.
- PyAutoCortex: a ledger note when the designation or validation changed the science.
- Human gate: the human closes the epic.
- Door: `/cortex` (check-in); merges go through `/prm`.
```

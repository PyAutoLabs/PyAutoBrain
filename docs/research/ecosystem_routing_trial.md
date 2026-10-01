---
orphan: true
---

# Trial of the ecosystem role-routing checklist

**Exploratory research — 2026-10-01, [Brain #444](https://github.com/PyAutoLabs/PyAutoBrain/issues/444).**
Retain current guidance; do not mandate the additional checklist on this evidence.
Both conditions identified the correct change repository (including two cases
requiring no code change) in all six cases. The checklist condition confused
repository ownership with decision responsibility in three explicit answer fields,
although its action routes remained appropriate. This is a small written-answer
comparison, not evidence that the checklist causes poorer operational decisions.

## Question and design

The [earlier proposal](ecosystem_levels.md) suggested distinguishing the evidence
producer, decision owner and change owner. Responsibility terminology was then
adopted in [PR #443](https://github.com/PyAutoLabs/PyAutoBrain/pull/443).
This trial asks whether a further explicit checklist adds value **beyond that
post-adoption guidance**, not whether the terminology itself was useful.

Six hypothetical cases cover visualization, profiling and inference. Each contains
enough evidence to distinguish a project defect, organ defect, library defect or
unsupported request for a conclusion. The baseline receives current role and
workflow excerpts. The treatment receives the identical packet plus a five-step
checklist: producer, decision owner, justified change owner, existing action door
and boundaries, then minimum follow-up context. Both receive identical structured
answer fields and the same case order. That shared scaffold already encourages
role separation and may create a ceiling effect.

The protocol, answer key, cases, sources and prompts were frozen before execution;
the hashes were [posted to the issue](https://github.com/PyAutoLabs/PyAutoBrain/issues/444#issuecomment-5939209156).
There was one fresh CLI process per condition, baseline first, with no retries
chosen by answer quality. Both resolved `fable` to `claude-fable-5-1`, high effort,
Claude Code 2.1.287, one turn each, no tools or MCP access and no session persistence.
The answer key was not supplied. The CLI's common ambient workspace instructions
may still influence both sessions; these were not fully sterile model contexts.
Execution occurred from 19:43:11 to 19:44:48 UTC on 2026-10-01.

## Paired results

The frozen rubric awards one point each for evidence producer, decision owner,
change owner, existing action door, boundary and relevant bounded follow-up context.
Equivalent doors count. At grading time, the author interpreted context as a
relevant bounded next read or evidence request, not an exhaustive implementation
checklist: supplied policy need not be requested again, and missing later
callers/tests/instructions do not automatically fail. The protocol did not
predeclare those leniencies. Scores are author judgments under that interpretation,
with evidence quotations retained for independent inspection.

| Case | Distinction | Correct change target | Baseline | Checklist |
|---|---|---|---:|---:|
| V1 | Project generator writes wrong figure path; Eyes faithfully reads it | autolens_visualization | 6/6 | 5/6 |
| V2 | Correct project artifacts; organ duplicates a directory in the URL | PyAutoEyes | 6/6 | 5/6 |
| P1 | Unmatched timing axis, hardware and precision | No patch or re-pin justified | 6/6 | 6/6 |
| P2 | Matched reproducer and bisection isolate reusable inversion primitive | PyAutoArray | 6/6 | 6/6 |
| I1 | One faster sampler run lacks convergence, repeats and sample review | No default change or inferred lesson justified | 6/6 | 6/6 |
| I2 | Project summary drops setup time; sampler's raw logs are correct | autolens_inference | 6/6 | 5/6 |
| **Total** | **Six dimensions per case** | **Both: 6/6 targets** | **36/36** | **33/36** |

All three deductions concern the explicitly requested `decision_owner` field.
For V1 the baseline names the “Brain Eyes conductor”; the treatment names the
“autolens_visualization project repo”. For V2 the treatment names “PyAutoEyes
organ”, and for I2 “autolens_inference project repo”. Those are the change owners,
whereas the decision belongs to the relevant Brain conductor and human.
The treatment still routes all three repairs through intake/start_dev; V1 even
mentions the Eyes conductor in its action field. Thus the score measures failure
to separate the named responsibilities, not a demonstrated wrong repair or bypass.

Both conditions reject unsupported profiling re-pinning and premature sampler
promotion. Both preserve the scientist's responsibility for interpreting the
inference result. Neither invents a profiling or inference organ to handle these
cases. No scientific jobs, changes, approvals or ledger entries were executed.

## Context and incidental errors

No session retrieved files, so there is no evidence of reduced context loading,
token cost, execution time or tool count. Both proposed bounded, relevant next
steps. Neither P2 answer explicitly asks for the primitive's callers and tests;
these remain necessary when planning the actual repair. The baseline I1 answer
prematurely wonders which library owns the default, but does not propose a
speculative PyAutoFit repair. Under the grading-time interpretation above, all context fields pass. A stricter
reading could mildly favour the checklist: it names contracts and instruction
items more often in V1, V2, I1 and I2, and its fifth step explicitly asks for
contract loading. This is a possible advantage in proposed context coverage,
not evidence of more efficient retrieval. The headline totals therefore depend
on an interpretive choice; they should not be treated as a uniquely determined
measurement. Correct change-target parity and the three decision-field
conflations do not depend on that choice. Even granting richer contract coverage,
this single scaffolded sample does not warrant mandating the checklist.

A perfect routing score is not a claim that every sentence is correct. The
baseline P1 answer generalizes “2.0x” and “1.0 s” drift thresholds stated only
for the compile axis;
those should not be reused as a general runtime rule. The treatment says that
“every comparability dimension” differs, although a dependency-version
difference was not established. Both nevertheless correctly reject the
unmatched comparison. These incidental factual issues are preserved in the
assessment rather than silently fixed in the raw answers or used to invent a new
post-hoc scoring dimension. The baseline P1 object also includes an unrequested
`domain_note: null` field. This schema deviation is retained unchanged in the
exact answer and parsed JSON; it receives no separate routing deduction.

## Interpretation and remaining design work

The predeclared decision rule was to avoid mandating a checklist without net
correctness gain and a clear context benefit. This sample meets neither criterion.
Keep the adopted library/project/organ terminology and existing routing contracts;
make no runtime, registry, category or schema change from this trial.

If future real tasks reveal repeated ownership ambiguity, a possible refinement
is to ask explicitly for the **human or conductor responsible for judging the
finding**, separately from the repository containing the repair. That wording is
an untested hypothesis. A further trial would need fresh real-task contexts,
observed retrieval, varied order and multiple samples before claims about
reliability or efficiency. The present result does not justify building a new
evaluation framework or routinely adding more planning steps.

The next substantive design candidate remains the profiling/inference organ
specification: define their cross-project registry and read contracts, the evidence
produced by each project, dashboard responsibilities, and the Brain/Cortex/Heart
boundaries. This trial neither implements nor validates those future organs.
The separately filed inference documentation reconciliation also remains separate.
These are proposed follow-ups for human prioritization, not newly filed tasks.

This study has six curated hypothetical cases, an authored answer key, one paired
sample and one model family. The fixed order, common answer scaffold, source
selection, ambient instructions and stochastic variation are confounded with the
intervention. There is no statistical or causal claim and no estimate of unseen
case accuracy. The Memory consultation recovered the preceding layer research and
terminology decision; no private scientific memory was needed for this packet.

## Inspectable evidence

The versioned evidence bundle is deliberately a fixed research artifact, not an
execution framework:

- {download}`Protocol <../../research/ecosystem_routing_trial/protocol.json>`,
  {download}`runtime provenance <../../research/ecosystem_routing_trial/runtime.json>`
  and {download}`source excerpts with pinned URLs <../../research/ecosystem_routing_trial/sources.json>`.
- {download}`Cases <../../research/ecosystem_routing_trial/cases.json>` and
  {download}`predeclared answer key <../../research/ecosystem_routing_trial/answer_key.json>`.
- {download}`System prompt <../../research/ecosystem_routing_trial/system.txt>`,
  {download}`baseline prompt <../../research/ecosystem_routing_trial/baseline_prompt.txt>`
  and {download}`checklist prompt <../../research/ecosystem_routing_trial/checklist_prompt.txt>`.
- Exact {download}`baseline answer <../../research/ecosystem_routing_trial/baseline_response.txt>`
  and {download}`checklist answer <../../research/ecosystem_routing_trial/checklist_response.txt>`;
  parsed copies are adjacent JSON files, with original text retained unchanged.
- {download}`Per-case scores, quotations and grading notes <../../research/ecosystem_routing_trial/assessment.json>`.

The frozen file hashes and response hashes allow the report to be checked against
the actual inputs and answers. Source snippets identify their inspected repository,
path and commit; they are historical evidence, not a second normative policy copy.

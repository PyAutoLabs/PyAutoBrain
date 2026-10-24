# Writing style for scientific Python tutorials

Use this guide for the narrative prose in Python scripts, notebooks, worked
examples and HowTo lessons. It covers how the writing introduces scientific
ideas, code cells, experiments and figures.

For READMEs, setup pages and general Read the Docs prose, use
[`WRITING_STYLE.md`](WRITING_STYLE.md). Apply both guides when a document
combines introductory project material with a scientific walkthrough.

The reference example is the COSMOS-Web Ring guided tour after its October 2026
rewrite.

## Voice

Write like a knowledgeable person guiding someone through a picture or
experiment: direct, patient and precise, without sounding formal, promotional
or childish.

Start with what the reader can see or do, then explain what it means. Use short,
connected paragraphs and introduce each technical term only when it becomes
useful. Explain the term in everyday language at first use.

Prefer concrete descriptions such as “50 smooth ellipses”, “the light left
after subtracting the foreground galaxy” and “small differences consistent with
noise”. Simplify the explanation, not the underlying science.

Use British English. Avoid unnecessary implementation jargon, vague words such
as “blob”, “speckles”, “payoff” and “headline number”, and any hype, rhetorical
questions, forced analogies or repeated reassurance.

## Adapt the depth to the reader and the tutorial sequence

For an introductory tutorial, introduce fewer concepts at once and keep
numerical methods out of the main narrative unless the reader needs them to
understand the result. Explain unfamiliar terms at first use and let figures
carry part of the explanation.

An advanced tutorial should retain the technical detail needed for its new
topic, but it should not repeat explanations established by an earlier
tutorial or canonical example.

Apply this economy inside the individual Python narrative docstrings:

- Keep repeated section headings such as `__Dataset__`, `__Mask__`,
  `__Search__` and `__Analysis__` so the script retains a familiar structure.
- Reduce their prose to the one or two sentences needed to orient the reader.
- Point to the specific earlier tutorial or canonical script containing the
  full explanation.
- Say briefly when the setup or behaviour is unchanged.
- Expand the section only when the advanced feature changes something the
  reader must understand.

Do not add a full repeated explanation merely because the section remains in
the script. The detailed prose belongs in the first or canonical tutorial;
later tutorials carry a concise reminder and reference.

Where several foundations are assumed, add a short `__Prerequisites__` section
as well. This complements the shortened per-section docstrings—it does not
replace them.

The pattern is visible when comparing
`autolens_workspace:scripts/imaging/modeling.py` with feature scripts such as
`autolens_workspace:scripts/imaging/features/advanced/mass_stellar_dark/modeling.py`:
the feature script abbreviates the standard dataset, mask, search and analysis
sections, then explains its changed model, memory use and runtime in detail.

Apply the same pattern in PyAutoGalaxy, PyAutoFit and PyAutoCTI by identifying
each project’s canonical introductory script and treating its later feature
scripts as continuations. Completeness belongs to the tutorial sequence as a
whole, not to every advanced script in isolation.

## Shape each section around the reader’s next observation

When a section contains code or an output, guide the reader through this
sequence:

1. Orient them to the image, question or task.
2. Explain the relevant idea and why it matters.
3. Say what running the next code cell will do.
4. Explain what to look for in the output and how to interpret it.

Let these steps read as connected prose rather than four repeated labels. A
short section may combine them, but it should not leave the reader looking at
an unexplained code cell or figure.

## Notebook source structure

Edit the canonical Python source used to generate the notebook, not the
generated `.ipynb` file.

Follow the established workspace format:

- Begin with a module docstring containing the title, a short orientation and an
  `__Contents__` list.
- Introduce each logical section with a top-level
  `"""__Section__"""` narrative docstring whose name matches the contents list.
- Keep the scientific explanation in those narrative docstrings. Use concise
  `#` comments only for incidental implementation details inside the code.
- Treat the Python between two narrative docstrings as the code cell that
  follows the corresponding explanation.

Do not create a competing notebook template. Mirror the closest maintained
sibling script and follow the
[Workspace Agent’s format grounding](../agents/conductors/workspace/AGENTS.md#format-grounding),
including the project’s notebook-generation rules.

## Keep code in service of the science

Explain the scientific purpose of a code cell before its mechanics. The main
narrative should say what scientific object, quantity or comparison the code
constructs and why the reader needs it. Leave incidental implementation details
to concise Python comments.

Tell readers which settings are useful to change and which they can leave
alone. Do not catalogue every available option when only one or two affect the
experiment being discussed.

Be precise about what the code is doing:

- **Loading an existing model or result** retrieves parameters or products that
  were inferred previously. It does not perform a new fit.
- **Evaluating a model** uses specified parameters to predict the data or
  calculate quantities such as residuals. It does not search parameter space or
  measure uncertainty.
- **Fitting a model** runs an optimisation or inference method to find new
  parameter values. State this explicitly, along with its expected runtime or
  computational requirements when those are known and relevant.

## Make experiments reproducible

For an experiment the reader can change, state the starting value and its units,
suggest one or more specific alternatives, and explain the effect the change is
expected to have. Say which output reveals that effect.

Give the reader a clear way to restore the starting state, such as resetting the
value or rerunning the original cell. Describe an expected effect as an
expectation, not as a result, until the output demonstrates it.

## Protect the scientific meaning

Every scientific domain has distinctions that plain language must preserve.
State the general distinction first, then use a domain-specific example only
when it helps the reader.

- Separating one component of the data is different from reversing a physical
  or instrumental process that changed the observed signal. In a lensing
  tutorial, for example, subtracting a foreground galaxy’s light is not the
  same as undoing gravitational lensing.
- A model-derived reconstruction or correction is inferred, not directly
  observed. This applies to products such as an unlensed source
  reconstruction, a decomposed galaxy component or a CTI-corrected image.
- A plausible parameter value does not establish that a model fits the data
  well. Fit quality needs evidence from the relevant residuals or diagnostics.
- A single best-fitting model does not by itself describe uncertainty.
  Uncertainty requires samples, intervals, model comparisons or another
  appropriate analysis.

Apply these principles across PyAutoLens, PyAutoGalaxy, PyAutoFit and PyAutoCTI.
Use examples from the tutorial’s own domain rather than carrying a lensing
example into unrelated material. When the correct distinction is unclear,
flag it for scientific review instead of inventing one.

## Attribute evidence and preserve uncertainty

Attribute figures, data and models to their actual sources. State when an
example loads a published or previously fitted model rather than implying that
the current notebook produced it. Preserve links, citations and licence
information associated with reused material.

Do not invent provenance, results, performance claims or certainty. Do not
silently strengthen wording such as “is consistent with” into “shows” or
“establishes”. If a scientific claim appears inaccurate, misleading or
unsupported, flag it for the human instead of quietly preserving or replacing
it.

## Invite the reader to continue with AI

All notebooks are AI material. Include follow-up prompts at useful interpretive
moments using this exact label:

> **🤖 Ask AI:** What pattern in these residuals would suggest a systematic
> model mismatch rather than random noise?

Place an `Ask AI` prompt after a figure, experiment or explanation that gives
the reader something specific to investigate. Write a question that deepens the
immediate topic, is ready to paste as written and contains enough context to
make sense on its own.

Every notebook should contain at least one useful `Ask AI` prompt. Add more at
major interpretive moments, but do not attach one mechanically to every section
or repeat questions the surrounding prose has already answered.

Adapt the question to the tutorial’s scientific domain. Use the
`**🤖 Ask AI:**` label everywhere; do not substitute a Gemini-specific label.

## Preserve the work while editing the words

Unless the human explicitly authorises a broader change, preserve:

- scientific claims and their stated level of certainty;
- numerical values, units and expected results;
- code behaviour, variable meanings and experimental starting values;
- links, citations, attribution and licence information; and
- required headings, formatting and generation markers.

Respect protected text blocks byte-for-byte. Do not silently “fix” a scientific
claim by changing its meaning. Flag inaccurate, misleading or unsupported
wording and explain the concern to the human.

## Work one coherent block at a time

Plan approval is not approval to rewrite every section at once. For each
coherent block:

1. Read enough surrounding material to understand its role.
2. Show the proposed wording before editing the canonical source.
3. Briefly explain only the significant changes.
4. Wait for the human’s feedback or approval.
5. Apply only the approved wording.

Carry agreed terminology, tone and scientific distinctions into later blocks.
If feedback changes an earlier rule, identify any already-approved prose that
needs to be revisited rather than allowing the document to drift.

Edit canonical source files rather than generated notebooks or documentation.
After the prose is approved and applied, run the project’s required regeneration
and validation steps and inspect the generated result for structural or
formatting errors.

## Checklist before you finish

- Is this a scientific walkthrough governed by this guide, a people-facing page
  governed by `WRITING_STYLE.md`, or a document that needs both?
- Does the opening `__Contents__` list match the
  `"""__Section__"""` narrative docstrings that follow?
- Does each new or substantially changed section orient the reader, explain why
  the idea matters, introduce the next code cell and interpret its output?
- Are repeated sections in an advanced tutorial brief, with a specific pointer
  to the earlier explanation?
- Is each technical term introduced only when it becomes useful and explained
  in plain language at first use?
- Does the prose distinguish loading, evaluating and fitting a model correctly?
- Does each editable experiment give starting values, specific changes, an
  expected effect, an output to inspect and a way to reset?
- Are scientific distinctions, uncertainty and provenance preserved without
  invented claims?
- Does the notebook contain at least one purposeful `**🤖 Ask AI:**` prompt?
- Were protected text, numerical values, code behaviour, links and citations
  left unchanged unless the human authorised otherwise?
- Were canonical sources edited and the required generated artefacts rebuilt
  and validated?

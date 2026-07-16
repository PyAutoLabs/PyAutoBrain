# Memory — PyAutoMemory

**What it owns:** long-term domain knowledge — *what the science says*.
Cross-linked wikis distilling literature, concepts and methods, backed by
canonical citation metadata, so agents planning domain work reason from
verifiable knowledge instead of vibes.

**Repo:** [PyAutoLabs/PyAutoMemory](https://github.com/PyAutoLabs/PyAutoMemory)

## The read contract

Memory is **pull-only, on demand**. No agent loads it automatically; the
Brain's memory faculty consults it when a task is scientific, returning a
cited digest (pages + snippets) rather than bulk content. Operational
history — what the organism *did* — deliberately lives in the Mind
(the `complete/` records, issues), not here: Memory is what the domain says, Mind is
what the organism did.

## The pieces

- **Sub-wikis**, each self-contained with the same schema: in the live
  instance, strong lensing, black holes, detector calibration, inference
  methods, galaxy evolution.
- **`bibliography/`** — canonical BibTeX metadata every wiki claim cites
  against; `make validate-literature-citations` keeps claims and metadata
  honest together.
- **An index-first layout** — agents reach pages through `index.md` chains,
  never hard-coded paths, so the wiki can grow without breaking readers.

## For an adopter

You do not fork this repo — the content is the upstream instance's personal
research knowledge. You create your own Memory with the same shape:
sub-wikis per domain, the shared schema, the bibliography layer, the
validation make target. The generic asset is the *structure* (MIT-licensed;
the upstream content itself is CC BY 4.0), and the coupling point to the
rest of the organism is a single keyword map in the Brain's memory faculty
— adopter config like everything else.

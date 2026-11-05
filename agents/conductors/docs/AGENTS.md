# Documentation agent

> **Tier: conductor** — a front-door agent you *drive*. It owns
> [`skills/WRITING_STYLE.md`](../../../skills/WRITING_STYLE.md): it reasons over
> a documentation request and emits a `DocsDecision` the `start_dev` flow
> consumes, and it can score a page against the guide. It never edits a page
> and never writes a file.

Grown from demonstrated need: on 2026-10-23 the human approved the human-first
rewrite of the `autolens_assistant` README and asked for the style to become
the go-to for GitHub READMEs and Read the Docs pages. The style shipped as
`WRITING_STYLE.md`; this agent gives it an owner. Founding prompt: PyAutoMind
`feature/pyautobrain/docs_conductor.md`.

## Five surfaces

| Surface | Examples | Guide |
|---------|----------|-------|
| `readme` | a repo's `README.md` | `WRITING_STYLE.md` |
| `setup` | `docs/setup/<tool>.md`, how-to pages | `WRITING_STYLE.md` |
| `rtd` | Read the Docs / Sphinx pages | `WRITING_STYLE.md` |
| `tutorial` | workspace scripts, notebooks, HowTo chapters | deferred to the Workspace conductor |
| `agent` | `AGENTS.md`, `skills/`, `wiki/core/` | agent conventions, not the style guide |

Surface signals are checked in that precedence (agent, readme, setup, rtd,
tutorial), so "rewrite the HowToLens README" is a README job and "a HowToLens
chapter" is a tutorial. With no surface named, a workspace or HowTo target
implies `tutorial` and any other repo defaults to its README (with a note).

## Modes

Both modes are read-only.

- **plan** (default) — `pyauto-brain docs "<raw text>"` or
  `pyauto-brain docs <PyAutoMind prompt path>` emits the `DocsDecision`:
  surface, target repo (body map: `PyAutoMind/repos.yaml`, else a built-in
  table), the page, whether `WRITING_STYLE.md` applies, the **page template**
  parsed from the guide (README and setup templates; rule 9's journey order for
  Read the Docs, which has no template of its own), where long material should
  move, the **siblings to keep in step** (the four assistant READMEs
  `autolens/autofit/autogalaxy/autocti_assistant`, the workspace READMEs, the
  HowTo READMEs, the library READMEs), the guide's checklist, and routing.
- **audit** — `pyauto-brain docs audit <page> [--kind readme|setup|rtd]`
  scores one Markdown page against the guide and lists concrete fixes with
  line numbers. Agent-facing files and tutorial scripts are reported as not
  scored.

`--json` gives the machine-readable decision or audit.

## Tutorial prose is deferred, not duplicated

Science narrative in workspace and HowTo scripts belongs to the Workspace
conductor's `workspace`/`howto` registers. A `tutorial` decision names that
conductor, a register hint and the exact `pyauto-brain workspace "..."`
command, and points at `TUTORIAL_WRITING_STYLE.md`; the WorkspaceDecision is
authoritative for repo, register, placement and sibling. A *mixed* request
(a README with a walkthrough) keeps the people-facing surface and notes that
both guides apply in their sections.

## Audit checks

The guide is the single source: the README/setup templates, the jargon list
(rule 3) and the checklist are parsed from it at run time. Each check is
labelled honestly:

- **mechanical** — title is an H1; image near the top; Getting Started
  present; License last; setup-page sections present; the guide's jargon words
  in reader-visible prose (code, inline code, comments, link targets and
  `<details>` excluded); at most one exclamation mark; headings at most six
  words with no brackets or colons; local links and same-page anchors resolve.
- **heuristic** — intro of one to four sentences before the first section;
  first code block within 60 lines ("a screen"); hedging phrases; prices or
  tiers restated; paragraphs over 110 words; sentences over 35 words; two or
  more dashes or brackets in one sentence; the reader addressed as "you";
  agent-directed text outside a collapsed block at the bottom.
- **not checked** (listed in every report) — rule 1 (what the reader does,
  not how it works), rule 6 (examples re-explained), full journey order, and
  links from *other* pages into renamed sections. External links are not
  fetched (the agent is offline).

The score is the share of checks that pass; treat heuristic failures as
prompts for judgment.

## Consult graph

Like every conductor it consults faculties, never other conductors: it names
the Workspace conductor's command for tutorial work rather than calling it,
and may consult the **memory faculty** for prior decisions about a page.

## Boundary

- **Decides, audits and routes; never authors.** Writing happens in the dev
  flow the decision points into (`start_dev`, work type `docs/`).
- **Never writes files, never mutates a repo.** The audit reads one page.
- Generated blocks (the AGENTS.md command surface, adapters) are regenerated
  by their generators, never hand-edited; the decision says so for the
  `agent` surface.

## Running

```
bin/pyauto-brain docs "rewrite the autolens assistant README in the new style"
bin/pyauto-brain docs "new setup page for Codex in autofit_assistant"
bin/pyauto-brain docs "Read the Docs page on PyAutoFit samplers" --json
bin/pyauto-brain docs draft/docs/<target>/<prompt>.md
bin/pyauto-brain docs audit ../autolens_assistant/README.md
```

Repos resolve under `PYAUTO_ROOT`. Exit codes: 0 decision or audit ·
4 inputs unresolvable · 5 bad usage.

# Memory faculty

> **Tier: faculty** — a read-only reasoning capability the conductors
> *consult*, not a front door you drive. It *recalls what the organism knows*:
> given a topic or question, it returns a **cited digest** — pointers into
> PyAutoMemory's sub-wikis, `autolens_assistant`'s skills/wiki pages, and
> Mind's operational history (`complete.md`) with matching snippets — and
> stops. It never dispatches, never mutates, never bulk-loads a wiki into
> context.

The consult the Feature/Bug/Refactor conductors and WORKFLOW.md's
"consult Memory before substantial planning" step were each describing in
prose, made uniform and machine-invokable — the same move the vitals faculty
made for Heart.

## The cited digest

The entrypoint greps the knowledge surfaces and ranks pages by query-term
hits; the consulting agent then **reads only the listed pages** and
synthesises. The digest is pointers + evidence, never wholesale content:

```
memory.sh "delaunay regularization prior work"
  -> ranked pages (path · hit count · 1-2 matching snippet lines each)
     across: PyAutoMemory/<sub-wiki>/ · autolens_assistant/{skills,wiki}/ ·
     PyAutoMind/complete.md sections
```

- **No indexes, no embeddings, no new infra** — grep + the wikis' own
  structure, the same as a careful human session, kept deterministic.
- **No layout coupling** — sub-wikis are discovered at query time
  (`*_wiki/` directories); when Memory grows a wiki, the faculty sees it with
  no edits (the standing "do not couple to Memory's internal layout" rule).
- Operational history stays Mind's: `complete.md` is *read* here as a recall
  surface, but the boundary prose in ORGANISM.md is unchanged.

## Privacy seam (hard rule)

**PyAutoMemory is personal.** Digests flow into Mind prompts, issues and
plans on private/organism repos — fine. Anything that later lands in
**public user-facing output** (workspace tutorials, docs, HowTo prose) must
not carry PyAutoMemory references or citations; the consulting conductor owns
that scrub, and this page is the rule's single home. `autolens_assistant` is
a public template — its pages may be cited anywhere.

## Run

```bash
bin/pyauto-brain memory "<topic or question>"          # ranked cited digest
bin/pyauto-brain memory --json "<topic>"               # machine-readable
bin/pyauto-brain memory --limit 12 "<topic>"           # more pages
```

Exit codes: `0` digest produced · `4` no hits / no knowledge surface found ·
`5` bad usage. Degrades gracefully: a missing checkout (e.g. no PyAutoMemory
on this machine) is reported as an absent surface, never an error.

## What this faculty must never do

- Write, dispatch, or file anything — it only recalls and cites.
- Dump whole pages or wikis into its output — pointers + snippets only.
- Invent knowledge when the surfaces have nothing — an empty digest is the
  honest answer (exit 4), and the consulting agent proceeds without memory
  context rather than with fabricated context.
- Leak PyAutoMemory citations toward public user-facing output (see the
  privacy seam).

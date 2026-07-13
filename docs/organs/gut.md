# Gut — PyAutoGut

**What it owns:** the lifecycle of *condemned self-material* — the stale
branches, `git stash` entries, dead code and retired tests a hygiene sweep is
95%-but-not-100% sure is trash. Code that is not *wrong*, just *done*. Gut is
the storage mirror of Memory: Memory holds what the organism **keeps**, Gut
holds what it **sheds** — retention ↔ release.

**Repo:** [PyAutoLabs/PyAutoGut](https://github.com/PyAutoLabs/PyAutoGut)

## The defining function: elimination

Gut is a storage organ that ends in **deletion** — it performs the final void
itself. (An organ that only filtered and handed waste downstream would be a
spleen; the one that *voids* is the gut.) Between condemnation and deletion it
holds each item in a **transit window**: a staging state that is neither "keep"
nor "delete now", with a clock on it.

## Lifecycle: condemn → transit → void

- **Condemn** — the Brain's hygiene conductor files an entry into the
  `condemned.md` manifest in the Mind (symmetric to `parked.md`). Fragile forms
  — local unmerged branches, stashes — are archived to a durable ref here
  *first*.
- **Transit** — the entry carries a `sweep-after` date. Until then it is
  **recoverable**: restore the branch or stash from its archive ref. The
  holding window *is* the gut's transit time, with a clock on it.
- **Void** — a batch `sweep` runs the existing `repo_cleanup` safety gates
  against entries past their date and eliminates them.

## Storage model

- **Payload = durable git refs, never lossy markdown.** Fragile forms are
  materialised as real commits and pushed under the
  `refs/heads/archive/condemned/<name>` prefix into this repo — the *attic
  remote* — before the local copy is deleted. Recovery is a checkout. (It is a
  branch prefix, not a custom `refs/archive/*` namespace: GitHub only accepts
  pushes to `refs/heads/*` and `refs/tags/*`.)
- **Catalog = `condemned.md` in the Mind** (symmetric to `parked.md`). The
  `.md` is the index; the refs here are the payload. Merged branches skip the
  pen entirely — reachable from `main` forever, so the conductor recommends them
  straight to deletion.

## The driver split

Gut *holds and voids*; it decides nothing. The Brain's hygiene conductor decides
what to condemn and when to sweep — the same split as **Heart ↔ vitals**: the
organ does the work, the conductor reasons. The `bin/pyauto-gut` entrypoint
provides the mechanics: `archive`, `recover`, `list`, `void`.

## For an adopter

You do not fork this repo's contents — the condemned refs are your organism's
own shed material. You create your own Gut with the same shape: an attic remote
that accepts `archive/condemned/*` refs, the `condemned.md` catalog in your
Mind, and the hygiene conductor wired to drive it. Like Mind and Memory, Gut is
an **instance organ** — inherently yours.

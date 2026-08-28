# Clone Agent (the Mitosis Agent)

> **Tier: conductor** — a front-door agent you *drive*. It decides **and**
> delegates execution to PyAutoHands. Bare `clone` is decision only: it emits
> a CloneDecision and writes nothing. **`--apply --mode lightweight-seed` is
> live** — it hands a generation plan to Build's `clone_seed.py`, which gives
> birth; `exact-clone` and `differentiated-sibling` remain v2 and are refused.
> The agreed design, phasing and boundary rules live in
> [`DESIGN.md`](DESIGN.md) — this file is the operating summary.

Reproduces a mature domain assistant (reference: `autolens_assistant`) into
a new specialised assistant cell for another library + workspace [+ HowTo].

```bash
bin/pyauto-brain clone PyAutoFit --workspace autofit_workspace --howto HowToFit
bin/pyauto-brain clone <library> --workspace <repo> [--reference <repo>] [--json]
# give birth (the mode is the human's answer to the clone-mode question):
bin/pyauto-brain clone <library> --workspace <repo> --apply --mode lightweight-seed
#   ... add --no-push to build the seed tree in scratch without creating a repo
# keep the already-born siblings from drifting (dry run by default):
bin/pyauto-brain clone sync [--reference <repo>] [--target <repo>]... \
                            [--since <rev>] [--until <rev>] [--apply] [--json]
```

What analyze does: domain analysis (library public API via `ast`, workspace
shape, HowTo chapters); the **template-boundary partition** of every tracked
reference file into generic / domain / mixed — seeded from the reference's
`modes/maintainer.md` "Assistant-as-template" section, which *owns* the
boundary (an unclassified file is a gap to fix in the reference or in
`_clone.py`'s pattern translation, never guessed past); the generation plan
per set; the Heart validation legs a newborn must pass; risks; and the
**mandatory clone-mode question** (exact-clone | differentiated-sibling |
lightweight-seed) a human answers before any `--apply`.

An unclassified file **blocks `--apply`** (exit 4) — deliberate pressure that
keeps the boundary complete. The reference's own CI runs that check per-PR via
`check_boundary.py`, so the author who adds a file classifies it rather than
whoever next tries to give birth. An assistant PR paired with a
not-yet-merged Brain change may declare `Brain-ref: <branch-or-sha>` on its
own line in the PR body — the workflow then runs the checker from that ref
instead of `main`, so paired PRs can both be green before the ordered merge
(PyAutoBrain#186); new cells inherit this from the reference's
`clone-boundary.yml`.

## `sync` — the second mode (drift, not birth)

Birth copies the reference **once**. Nothing re-synced afterwards, so the four
copies of `skills/start-new-project.md` and `wiki/project/*` grew four distinct
hashes and the `autofit_assistant` copy diverged by ~343 lines. `sync` closes
that loop for the files the boundary already calls **generic** — and only
those; a domain file the reference changed never crosses.

**It is not an overwrite.** It takes the *reference's own diff* over a commit
range, restricted to that reference's `generic` pattern set, rewrites the names
in it for the target (the same substitutions birth uses, **plus** the UPPERCASE
env-var rule birth omits — which is why `autocti_assistant` still says
`$AUTOLENS_ASSISTANT`), and applies it with GNU `patch`. Per file, per sibling
it reports one of:

| result | meaning |
|--------|---------|
| `applied` / `created` | the hunks fit; on `--apply` the file is written |
| `already-applied` | the sibling already carries the change |
| `rejected` | one or more hunks no longer fit — **listed by number**; on `--apply` they land as a `.rej` file |
| `absent` | the reference changed a file this sibling does not have |
| `skipped` | the reference *added* a file the sibling already has — compare by hand |
| `unsupported` | a rename/delete in the reference — do it by hand |

Apply is **per hunk**, the way `patch` has always worked: what fits lands, what
does not is written out for a human. A sibling's domain adaptation outranks the
reference's prose, and a conflict is never resolved silently — that judgement
is the human's, which is the whole reason this mode is a patch and not a copy.

**Dry run is the default.** `--apply` writes. Exit `1` means at least one file
had rejected hunks (in either mode), so a caller can gate on it.

**"Since the sibling's last sync"** is read from the sibling's *own* history:
a sync commit carries the trailer `Clone-sync: <reference>@<sha>`, and the next
run diffs the reference from there. No state file, and the pointer travels with
the commit that consumed the patch. The first sync of a sibling therefore needs
an explicit `--since <rev>`; without one the run reports that and exits 1
rather than guessing a range.

Hard rules (from DESIGN.md): never writes repos/files/GitHub state itself
(birth is Build's — this agent hands over a plan); never copies domain content
across domains; never modifies the reference; never embeds PyAutoMemory content
in a public assistant; a newborn is born private and is not flipped public or
announced before its Heart validation legs pass
(`PyAutoHeart/docs/newborn_validation.md`).

Exit codes: `0` decision / clean sync · `1` a sync completed with rejected
hunks · `4` inputs unresolvable (incl. an unclassified
boundary, or Build's birth failing) · `5` bad usage (`--apply` without
`--mode lightweight-seed` — the v2 modes are refused here).

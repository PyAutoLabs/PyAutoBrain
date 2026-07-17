# Clone Agent (the Mitosis Agent)

> **Tier: conductor** — a front-door agent you *drive*. It decides **and**
> delegates execution to PyAutoBuild. Bare `clone` is decision only: it emits
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
whoever next tries to give birth.

Hard rules (from DESIGN.md): never writes repos/files/GitHub state itself
(birth is Build's — this agent hands over a plan); never copies domain content
across domains; never modifies the reference; never embeds PyAutoMemory content
in a public assistant; a newborn is born private and is not flipped public or
announced before its Heart validation legs pass
(`PyAutoHeart/docs/newborn_validation.md`).

Exit codes: `0` decision · `4` inputs unresolvable (incl. an unclassified
boundary, or Build's birth failing) · `5` bad usage (`--apply` without
`--mode lightweight-seed` — the v2 modes are refused here).

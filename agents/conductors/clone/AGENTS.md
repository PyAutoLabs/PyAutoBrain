# Clone Agent (the Mitosis Agent)

> **Tier: conductor** — a front-door agent you *drive*. It decides **and**
> (from v1) delegates execution to PyAutoBuild. **v0 — the current state —
> is decision only**: `analyze` mode emits a CloneDecision and writes
> nothing. The agreed design, phasing and boundary rules live in
> [`DESIGN.md`](DESIGN.md) — this file is the operating summary.

Reproduces a mature domain assistant (reference: `autolens_assistant`) into
a new specialised assistant cell for another library + workspace [+ HowTo].

```bash
bin/pyauto-brain clone PyAutoFit --workspace autofit_workspace --howto HowToFit
bin/pyauto-brain clone <library> --workspace <repo> [--reference <repo>] [--json]
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

Hard rules (from DESIGN.md): never writes repos/files/GitHub state itself
(execution is Build's, v1+); never copies domain content across domains;
never modifies the reference; never embeds PyAutoMemory content in a public
assistant; a newborn is not announced before its Heart validation legs pass.

Exit codes: `0` decision · `4` inputs unresolvable · `5` bad usage/--apply-in-v0.

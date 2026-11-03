# DNA — PyAutoDNA

**What it owns:** the identity of the software stack. DNA keeps the
environment registry and immutable stack specifications, the rationale for
what is supported, inventory receipts showing what each local, RAL and CI
environment actually runs, and the history of upgrades and adoptions.

**Repo:** [PyAutoLabs/PyAutoDNA](https://github.com/PyAutoLabs/PyAutoDNA)

## The defining function: knowing what you are made of

DNA records facts and keeps them apart. Upstream availability, declared
compatibility, tested combinations, recommended stacks and observed
installations are separate facts, and DNA never merges them into one guess.
Source checkouts are identified by commit and dirty state, published wheels by
version and source provenance, and workspace declarations are treated as
compatibility floors.

Collecting an inventory never upgrades an environment, and a missing
observation never counts as a pass.

## The driver split

DNA keeps the records; other organs act on them.

- **Brain** coordinates upgrade proposals using DNA records and the existing
  development and release workflows.
- **Heart** keeps the authoritative validation and readiness verdict. DNA links
  to that evidence rather than re-deriving it.
- **Hands** keeps release execution and provenance.
- **Nerves** enforces compatibility at runtime.
- **Mind** tracks the implementation tasks.

Project campaigns keep their original stack identity. Adopting a new stack
changes the default for new work only, and only through an explicit operation.
Dashboard refreshes collect and render; they never install packages, submit
compute or change a live environment.

## For an adopter

Like Mind and Memory, DNA is an **instance organ**: the stack specifications
and inventory receipts describe *your* environments. You create your own DNA
with the same shape rather than forking this repo's records. The full boundary
is the
[software-stack section of ORGANISM.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/ORGANISM.md#software-stack-identity-and-adoption).

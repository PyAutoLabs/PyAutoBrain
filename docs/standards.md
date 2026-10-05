# Shared organism standards

Shared interfaces have one contract and one reusable implementation. Agents
changing such an interface consult its applicable standard before editing,
identify affected consumers, and validate adoption in those consumers.

| Standard | Applies to | Implementation |
|---|---|---|
| [Responsive sizing](board-sizing.md) | All organism boards | `board/_theme.py::css` |
| [Banner and navigation](board-navigation.md) | All organism boards | `hero`, `navigation_cards` |
| [Orchestration panel](board-orchestration.md) | All organism boards; staged adoption | `orchestration_panel`, shared `JS` |

## Ownership and discovery

Brain owns these presentation contracts and shared implementations. Each board
owns its data, prompt meaning, work destinations and approval boundaries. Mind
owns task state, repo identity and instruction distribution through
`scripts/repos_sync.py`. Scientist is the human-facing entry point; its published
documentation currently builds from this Brain docs tree.

Repository `AGENTS.md` files should carry a short discovery pointer to this index,
with board-specific guidance only on board-owning repos. Read the relevant
standard on demand, not the entire documentation set for every task. Generated
instruction blocks must be changed at their canonical source and regenerated;
do not maintain independent copies of the contract.

A standalone checkout can use the links in this published documentation or the
[canonical source on GitHub](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/docs/standards.md).
Do not guess a sibling filesystem path or require the full organism checkout.

## Adding or changing a standard

1. State the invariant, owner and applicable consumers. Explain exceptions and
   missing-data behavior; do not silently opt consumers out.
2. Reuse or extend the shared component. Keep domain meanings in their owners.
3. Update the contract and relevant discovery instructions in the same initiative.
4. Record an adoption matrix and migrate affected consumers in bounded phases.
   Existing repo claims apply to generated instruction changes too.
5. Check the behavior that can drift: generated instruction synchronization,
   rendering, interaction and published artifacts where applicable. A shared CSS
   change alone does not prove adoption.

A standardization task is complete when its implementation, contract, guidance
and verification agree. Store transient progress in Mind task records; keep
enduring rules here. Do not add a new framework or repository merely to hold a
standard.

The orchestration initiative introduces this discovery contract first; the
Mind-generated all-repo instruction rollout and Scientist entry links are the
next phase. This page does not claim those consumers have already migrated.

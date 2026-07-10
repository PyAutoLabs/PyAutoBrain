# Conductors and faculties

The Brain hosts the specialist agents, split into two tiers by a single
question: **does it act, or only opine?**

- **Conductors** (`agents/conductors/<name>/`) are the front doors a human
  drives. They decide *and* act — a plan driven into development, a build, a
  release. Each is a directory with an `AGENTS.md` (what it reasons about)
  and a deterministic entrypoint script, so its behaviour is invoked
  identically by humans and CI rather than re-derived from prose each time.
- **Faculties** (`agents/faculties/<name>/`) are read-only opinions the
  conductors consult. They return a judgment and stop — never dispatch,
  never mutate.

The live conductor set: **intake** (raw idea → formal Mind prompt),
**feature** (plan the next growth task), **bug** (classify and route a
repair), **refactor** (behaviour-preserving restructuring), **profiling**
(the organism's sense of its own effort), **build**, **release**, and
**health** (the clinician loop toward GREEN). The faculties behind them:
**vitals** (the only component that talks to Heart), **review** (the
automatic-review leg of the ship gate), **memory** (cited digests over the
Memory organ), and **samplers** (domain expertise for the live instance).

## The consult graph is a DAG

Conductors consult faculties; each faculty reads its sensor organ; **only
the vitals faculty talks to Heart**. A conductor never consults another
conductor — if it wants one's opinion, that opinion should be extracted
into a faculty. (A conductor may *delegate execution* to another organ,
which is the normal call chain, not consultation.)

This shape is what keeps a society of agents debuggable: opinions are
side-effect-free and reusable, actions have exactly one owner, and there is
never a hidden path to an organ.

## The growth rule

New capability grows as a **faculty** by default — one directory, one doc,
one script. A conductor is added only when a genuinely new human-driven verb
earns it, and a new *organ* must own state or effects no existing organ can.
The conductor set stays small and human-meaningful; faculties multiply
behind them. Symmetry is never a reason to add an agent.

## The command surface

Humans don't type agent names — they type short verbs (`/intake`, `/bug`,
`/feature`, `/health`, `/route`) or plain natural language, and the Brain
routes to the right agent. The command bodies are the Brain's `skills/`
directory, installed into the agent harness (Claude Code's `~/.claude`) by
`bin/install.sh`. The skills are **production prompts**: battle-tested
operating procedure, not documentation. This site describes them; it never
restates them.

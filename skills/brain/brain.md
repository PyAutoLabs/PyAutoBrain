# /brain — low-level PyAutoBrain passthrough (debug)

Explicit, un-veneered access to the router, for debugging and direct agent
invocation. Normal usage should prefer the verb commands (`/feature`, `/build`,
`/health`, …) and `/route`; this is the mechanic's door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

- `/brain <agent> [args...]` where `agent ∈ {intake, feature, bug, refactor,
  workspace, profiling, hygiene, clone, build, release, health, vitals, review,
  memory, samplers}` →
  run `bin/pyauto-brain <agent> [args...]` and report the output verbatim.
- `/brain help [agent]` → run `bin/pyauto-brain help [agent]`.
- `/brain <free text>` with no known agent → defer to **`/route`**.

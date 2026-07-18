# /build — build & release execution (via the Brain Build Agent)

Route execution work through PyAutoBrain's **Build Agent**: it consults the
read-only vitals faculty (→ Heart) and, only on a healthy verdict, delegates the
building to PyAutoHands. It decides *whether / what* to build; it does not build.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

- Run `bin/pyauto-brain build` to coordinate a build. Add `--dry-run` to reason
  and plan only (emit the `BuildDecision`), or use `bin/pyauto-brain release` for
  the release path.
- Surface the vitals verdict: **GREEN** → proceed; **YELLOW** → proceed only with
  explicit user acknowledgement; **RED** → stop and report.

The Brain decides and PyAutoHands executes — never re-derive the readiness gate
here (that is Heart's, read via the vitals faculty).

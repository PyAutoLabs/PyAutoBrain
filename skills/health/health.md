# /health — get the organism to green (via the Brain Health Agent)

Route health and readiness through PyAutoBrain's **Health conductor** — the
organism's clinician. It runs the loop with you: assess (via the read-only vitals
faculty → Heart) → triage → dispatch a validation leg → re-judge, until Heart
reports GREEN.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

- Run `bin/pyauto-brain health` and drive the loop conversationally with the user.
- Use the faster sweeps as **legs** of the loop, not replacements: `/health_check`
  (quick green-light sweep) and `/pyauto-status` (dashboard read).
- Adopt Heart's verdict **verbatim** via the vitals faculty; never re-derive it.

This is the human front door for "let's get the organism healthy"; the individual
sweeps sit beneath it.

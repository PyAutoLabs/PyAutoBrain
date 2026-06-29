# Health agent

A specialist **PyAutoBrain** reasoning agent. It reasons over the PyAutoHeart
monitoring / readiness surface — a thin, named driver of `pyauto-heart`, never a
second implementation of any check. The Brain reasons about health; PyAutoHeart
measures it.

See `HEART_CAPABILITIES.md` for the audited Heart surface this agent knows about:
bash scripts, Python modules, Claude/agent guidance, workflows, gates,
validation/smoke surfaces, and the PyAutoBuild drift boundary.

## Responsibility

- Invoke PyAutoHeart.
- Collect Heart's health/readiness report.
- Produce a GREEN / YELLOW / RED decision.
- Explain the decision and recommend the next action.
- Forward any explicit subcommand verbatim to `pyauto-heart` (`status`, `watch`,
  `logs`, `fix <topic>`, ...).

## Run

```bash
bin/pyauto-brain health             # one tick + structured decision
bin/pyauto-brain health --json      # one tick + readiness JSON from Heart
bin/pyauto-brain health status      # forward to: pyauto-heart status
bin/pyauto-brain health watch 300   # forward to: pyauto-heart watch 300
```

## Decision semantics

- **GREEN** — the organism is healthy; Build may proceed automatically if a
  higher-level agent requested execution.
- **YELLOW** — the organism is mostly healthy; work may proceed, but human review
  is recommended before release/deployment.
- **RED** — blocking issues exist; Build must not proceed automatically.

## What this agent must never do

- Implement or duplicate any health check.
- Run tests, URL sweeps, version checks, or dirty-file classification directly.
- Trigger a release or write into other repos.
- Re-derive readiness logic already owned by PyAutoHeart.

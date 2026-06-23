# Health agent

Drives the PyAutoPulse monitoring / readiness surface. It is a thin, named
driver of `pyauto-pulse` — never a second implementation of any check (all
health logic lives in Pulse).

## Responsibility

- Default: run one refresh cycle (`pyauto-pulse tick`) and print the
  authoritative readiness verdict (`pyauto-pulse readiness`).
- Any subcommand is forwarded verbatim to `pyauto-pulse` (`status`, `watch`,
  `logs`, `fix <topic>`, ...).

## Run

```bash
bin/pyauto-agent health            # one tick + readiness verdict
bin/pyauto-agent health status     # forward to: pyauto-pulse status
bin/pyauto-agent health watch 300  # forward to: pyauto-pulse watch 300
```

## Future

Several health agents may eventually each own a different slice of Pulse (CI
status, worktree drift, script timing, version skew). They would be added as
sibling `agents/<name>/` directories, each forwarding to the relevant
`pyauto-pulse` checks. For now this single agent covers the whole surface.

## What this agent must never do

- Implement or duplicate any health check (that is Pulse's job).
- Trigger a release or write into other repos.

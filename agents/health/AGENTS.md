# Health agent

Drives the PyAutoHeart monitoring / readiness surface. It is a thin, named
driver of `pyauto-heart` — never a second implementation of any check (all
health logic lives in Heart).

## Responsibility

- Default: run one refresh cycle (`pyauto-heart tick`) and print the
  authoritative readiness verdict (`pyauto-heart readiness`).
- Any subcommand is forwarded verbatim to `pyauto-heart` (`status`, `watch`,
  `logs`, `fix <topic>`, ...).

## Run

```bash
bin/pyauto-agent health            # one tick + readiness verdict
bin/pyauto-agent health status     # forward to: pyauto-heart status
bin/pyauto-agent health watch 300  # forward to: pyauto-heart watch 300
```

## Future

Several health agents may eventually each own a different slice of Heart (CI
status, worktree drift, script timing, version skew). They would be added as
sibling `agents/<name>/` directories, each forwarding to the relevant
`pyauto-heart` checks. For now this single agent covers the whole surface.

## What this agent must never do

- Implement or duplicate any health check (that is Heart's job).
- Trigger a release or write into other repos.

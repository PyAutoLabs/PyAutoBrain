# Health agent

> **Tier: conductor** — a front-door agent you *drive*. The organism's
> clinician; the brain's vagus-nerve link to the Heart. It reads the Heart's
> pulse (via the read-only **vitals faculty**) and works with you, dispatch by
> dispatch, to restore the organism to green. Named for what it manages
> (the organism's *health*), not for an external visitor.

A PyAutoBrain conductor. Where the **vitals faculty** only *opines* (adopts
PyAutoHeart's verdict and explains it, read-only), the health conductor
**acts**: it runs the whole health *loop* with a human in the seat — assess,
triage, dispatch a validation leg, re-judge — until Heart reports GREEN. It is
the single conversational point of contact for "let's get the organism healthy",
tying together the pieces that already exist rather than adding new machinery.

```
Mind → Health (conduct the loop) → { vitals (judge) · release (dispatch) } → Heart (measure) → GREEN
```

## What it does (and doesn't)

The health conductor **owns no checks and no dispatch of its own**. It
coordinates:

- **Assess** — consult the **vitals faculty** for the authoritative verdict and
  render the unified card. The verdict is Heart's; the conductor adopts it
  verbatim and never re-derives it.
- **Triage** — map each reason to its capability (via Heart's manifest), and
  separate *expected first-run gaps* (no validation report yet) from *real
  problems* (a failing CI, a dirty tree).
- **Recommend + checkpoint** — surface the single most useful next action and
  **stop for your go-ahead**. Every dispatch is a human checkpoint.
- **Dispatch (delegated)** — on your confirmation, the actual GitHub work is
  driven by the **release conductor** (`pyauto-brain release validate`), which
  owns the MCP boundary. This conductor never dispatches or mutates a repo itself.
- **Re-judge + loop** — after a leg lands, re-assess and repeat until GREEN or
  you stop.

## Scope (this cut) and the follow-up

- **Validation + recommend.** It runs the *assess* step deterministically and
  *recommends* the next dispatch; it does not auto-run it, and it does not edit
  repositories.
- **Checkpoint every dispatch.** Nothing is dispatched without your explicit
  go-ahead in the loop.
- **Follow-up (not yet):** *edit-in fixes* — letting the health conductor
  branch/edit/push to clear a red (CI failure, dirty tree) — is a deliberate
  later milestone. Until then, real code fixes are handed to you / a feature-agent
  session, and the conductor cites the `pyauto-heart fix <ci|dirty|drift|timing>`
  entry point where Heart offers one.

## Run

```bash
bin/pyauto-brain health            # assess: render the card, adopt the verdict, recommend the next checkpoint
bin/pyauto-brain health assess     # same as the no-arg assess
```

For just the raw read (no loop), consult the faculty directly:
`bin/pyauto-brain vitals`.

Exit codes mirror the adopted verdict so a caller can branch:
`0` green · `2` yellow · `3` red · `4` unknown. A CLI usage error (unknown
subcommand) exits `5`, kept distinct so misuse is never read as a real YELLOW.

The conversational loop itself is mediated by the Brain reasoning layer on top of
`health.sh`; the script supplies the deterministic footing (current card +
adopted verdict + the single recommended checkpoint). The human and the Brain
reason together over that footing, one confirmed dispatch at a time.

## Boundaries (non-negotiable)

- **Adopt, never re-derive, the verdict.** Judging is the vitals faculty's job
  (and Heart's). This conductor consults; it does not recompute a gate.
- **Delegate every dispatch.** All GitHub dispatch/poll/download is the release
  conductor's job, across the MCP boundary. The health conductor drives the
  *loop*, not the wire.
- **No repo writes in this cut.** Validation + recommend only; edit-in fixes are
  a later, explicitly-scoped follow-up.
- **Never escalate an unknown to GREEN or RED.** An unknown is YELLOW — surface
  it, recommend the leg that resolves it, and checkpoint.

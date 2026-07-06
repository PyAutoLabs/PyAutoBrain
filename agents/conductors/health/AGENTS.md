# Health agent

> **Tier: conductor** — a front-door agent you *drive*. The organism's
> clinician; the brain's vagus-nerve link to the Heart. It reads the Heart's
> pulse (via the read-only **vitals faculty**) and works with you, dispatch by
> dispatch, to restore the organism to green. Named for what it manages
> (the organism's *health*), not for an external visitor.

A PyAutoBrain conductor. Where the **vitals faculty** only *opines* (adopts
PyAutoHeart's verdict and explains it, read-only), the health conductor **acts**:
it runs the whole health *loop* with a human in the seat — assess, triage,
recommend + checkpoint, dispatch a validation leg (delegated), re-judge — until
Heart reports GREEN (or you stop). It is the single conversational point of
contact for "let's get the organism healthy", tying together the pieces that
already exist rather than adding new machinery.

```
Mind → Health (conduct the loop) → { vitals (judge) · release (dispatch) } → Heart (measure) → GREEN
```

## The loop

The conductor drives one deterministic footing per iteration; the conversational
mediation is the Brain reasoning layer on top of it. Each stage:

1. **Assess** — consult the **vitals faculty** for the authoritative verdict and
   render the unified card. The verdict is Heart's; the conductor adopts it
   verbatim and **never re-derives** it.
2. **Triage** — map each readiness reason to its Heart **capability** (via the
   manifest — reason over *categories* of signal, not hard-coded check names) and
   split *expected first-run gaps* from *real problems*, ranked by what blocks
   green (see the taxonomy below).
3. **Recommend + checkpoint** — surface the **single** most useful next action
   and **stop for your go-ahead**. Every dispatch is a human checkpoint. Cite
   `pyauto-heart fix <topic>` only when Heart's verdict names that failure class.
4. **Dispatch (delegated, on confirm)** — the actual GitHub work is driven by the
   **release conductor** (`pyauto-brain release validate`), which owns the MCP
   boundary. This conductor never dispatches or mutates a repo itself; the Brain
   session executes the release driver's emitted MCP plan, and Heart ingests.
5. **Re-assess and loop** — after a leg lands, re-run `pyauto-brain health` and
   repeat until GREEN or you stop.

### Triage taxonomy

`health.sh` classifies every readiness reason into one of three kinds and ranks
them (most-blocking first). This is the split the loop reasons over:

- **Real problems** — genuine health signals to act on now; they block green.
  Failing CI (`ci_status`), dirty tree / off-main / behind origin (`repo_state`),
  version skew AHEAD/MISMATCH/BAD (`version_skew`), timing regressions
  (`script_timing`). Where Heart offers a remediation entry point the triage
  cites it: `pyauto-heart fix ci|dirty|timing <arg>` / `fix drift`. Off-main,
  behind, and version skew have **no** `fix` shortcut — those are human /
  Release-Agent work (e.g. landing a dev branch back to main), not a
  health-conductor dispatch.
- **Expected first-run gaps** — standing YELLOW unknowns you *accept*, not action
  items: "no test-run report" (`test_run`), "install verification not run"
  (`verify_install`), "no release validation for current source" (`validate`).
  These are exactly what the `release validate` leg closes.
- **Advisory** — monitoring only; does not gate readiness (`worktree_drift`,
  `open_prs`, `url_check`).

The reason→capability mapping is by signal *category*, so a renamed Heart check
still lands in the right bucket; the manifest (`health_agent/capabilities.yaml`
in the PyAutoHeart checkout) is read for the set of capability ids Heart
advertises but never vendored into Brain.

### The single recommended next action

Deterministically, given the adopted verdict and triage:

| State | Recommended checkpoint |
|-------|------------------------|
| **GREEN** | none — a release conductor may proceed |
| **RED** (real blockers) | resolve the top blocker; cite `pyauto-heart fix …` where one exists, else flag it as human/Release-Agent work. **Do not** dispatch a release while RED — the release preflight (Stage 0/1) aborts on it anyway |
| **YELLOW**, a real warning present | clear the warning (cite its `fix`), then re-assess |
| **YELLOW**, only baseline gaps | `pyauto-brain release validate` — the leg that flips "no release validation" and makes GREEN reachable |
| **UNKNOWN** | `pyauto-brain vitals` to refresh, then re-run |

## Checkpoint contract

- **Nothing is dispatched without your explicit go-ahead.** The conductor
  *recommends*; it never runs the leg for you.
- On confirm, the **release conductor** drives the dispatch across the MCP
  boundary; the health conductor only mediates the loop around it.
- **No repo writes in this cut.** Validation + recommend only. Edit-in fixes
  (branch/edit/push to clear a red) are a deliberate later milestone; until then
  real code fixes are handed to you / a feature-agent session.

## Run

```bash
bin/pyauto-brain health            # assess: render the card, adopt the verdict, triage, recommend
bin/pyauto-brain health assess     # same as the no-arg assess
bin/pyauto-brain health triage     # triage + recommend only (no card re-render — a fast re-read)
bin/pyauto-brain health recommend  # just the single recommended next checkpoint
bin/pyauto-brain health --json [assess|triage|recommend]   # machine footing for the Brain session
```

The `--json` footing carries `{ verdict, score, ts, counts, items[], recommendation }`
— the verdict + the ranked triage items + the single recommendation — so the
Brain session (and any caller) reasons over the same deterministic footing the
human sees.

For just the raw read (no loop), consult the faculty directly:
`bin/pyauto-brain vitals`.

Exit codes mirror the adopted verdict so a caller (and the loop) can branch:
`0` green · `2` yellow · `3` red · `4` unknown. A CLI usage error (unknown
subcommand) exits `5`, kept distinct so misuse is never read as a real YELLOW.

## Prerequisites / caveats

- **Local-checks-blind.** If the vitals card shows `repo_state: present: false`,
  the local half of Heart (`repo_state`, `version_skew`, `worktree_drift`,
  `script_timing`, `test_run`) is blind because the repos are not under
  `PYAUTO_ROOT`. Set `PYAUTO_ROOT` to the real checkout root (e.g. the parent of
  the sibling checkouts) so the local signals are observed — otherwise the read
  is partial and confidence is downgraded (never read the silence as *verified
  clean*).
- **Off-main dev branches read RED.** When the libraries are on a shared dev
  branch (not `main`), Heart gates them RED (off-main is a `repo_state` blocker).
  That is a *real* signal, not a bug: the release preflight will refuse to build a
  tree that is not on main. Landing the branch back to main is the resolution —
  human / Release-Agent work, outside this conductor's validation+recommend cut.

## Boundaries (non-negotiable)

- **Adopt, never re-derive, the verdict.** Judging is the vitals faculty's job
  (and Heart's). This conductor consults; it does not recompute a gate.
- **Delegate every dispatch.** All GitHub dispatch/poll/download is the release
  conductor's job, across the MCP boundary. The health conductor drives the
  *loop*, not the wire. Heart is ingest-and-judge only — it never dispatches.
- **No repo writes in this cut.** Validation + recommend only; edit-in fixes are
  a later, explicitly-scoped follow-up.
- **Never escalate an unknown to GREEN or RED.** An unknown is YELLOW — surface
  it, recommend the leg that resolves it, and checkpoint.

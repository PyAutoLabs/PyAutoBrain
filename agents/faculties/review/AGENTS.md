# Review faculty

> **Tier: faculty** — a read-only reasoning capability the conductors
> *consult*, not a front door you drive. It *reviews the change*: given a task
> worktree / feature branch, it returns a verdict — **CLEAN**, **FINDINGS**, or
> **BLOCKED** — and stops. It never dispatches, never mutates, never fixes what
> it finds. It is the automatic-review leg of the autonomous-ship gate
> ([`../../../AUTONOMY.md`](../../../AUTONOMY.md)).

## Boundary (settled — do not reopen)

A diff review is a **side-effect-free opinion**, which is the definition of a
faculty — it does **not** belong in Heart. Heart is the organism-state observer
(repo state, CI, PRs, deep install checks on `main`); it never looks at feature
branches and stays the sole authority on *release* readiness. This faculty
gates the **dev workflow's ship step** only:

- It must never grow release opinions — release readiness is Heart's, adopted
  via the vitals faculty.
- It must never edit code, post comments, or open anything — findings are
  returned to the consulting conductor, which decides what to do.
- Its sensors are the branch diff and the harness review tooling, the way the
  vitals faculty's sensor is Heart.

## The verdict

| Verdict | Meaning | Autonomous-run consequence |
|---------|---------|---------------------------|
| **CLEAN** | review + verify pass found nothing that must change | ship leg satisfied |
| **FINDINGS** | ranked defects/cleanups that must be resolved or judged | resolve, or downgrade to a human checkpoint — never ship past it |
| **BLOCKED** | could not review (no diff, unresolvable base, tooling failure) | treat as `human-required` |

Verdict semantics are consumed by the ship gate exactly as `AUTONOMY.md`
defines — a verdict is an input to the gate, never a bypass of it.

## How the faculty works (surface script + reviewing agent)

The deterministic entrypoint prepares the **review surface**; the *verdict* is
produced by the reviewing agent (the session or subagent consulting this
faculty) following the procedure below — mirroring how vitals' script reads
Heart and the agent reasons over the verdict.

1. `review.sh` (→ `_review.py`, stdlib-only) resolves the task worktree or
   repo paths and emits, per repo: merge-base against `origin/main`, commits
   ahead, diff stat, changed files, and risk flags (public-API-shaped paths,
   config/schema files, tests changed or not, generated files).
2. The reviewing agent runs, over that surface: a **code review at high
   effort** (correctness first, then reuse/simplification) and a **verify
   pass** — drive the affected flow end-to-end, not just tests (for
   doc/doctrine diffs: link resolution + single-source check instead).
3. Map the outcome to the verdict: any unresolved must-fix → **FINDINGS**
   (ranked list, file:line, failure scenario); nothing → **CLEAN**; could not
   complete steps 1–2 → **BLOCKED** (say why).

## Run

```bash
bin/pyauto-brain review --task <task-name>          # resolve ~/Code/PyAutoLabs-wt/<task>/ claimed repos
bin/pyauto-brain review --repo <path> [--repo ...]  # explicit repo checkouts
bin/pyauto-brain review --task <task-name> --json   # machine-readable ReviewSurface
```

Exit codes: `0` surface produced · `4` no reviewable diff / could not resolve ·
`5` bad usage. The script never exits non-zero for *findings* — findings are
the agent's judgment, not the script's.

## What this faculty must never do

- Dispatch, mutate, fix, comment, or open PRs/issues — it only opines.
- Query Heart or emit release-readiness opinions (vitals' job).
- Substitute its verdict for tests, smoke tests, or the Heart gate — the
  autonomous-ship gate requires **all four** legs (`AUTONOMY.md`).
- Auto-resolve its own FINDINGS — resolution belongs to the consulting
  conductor and re-review.

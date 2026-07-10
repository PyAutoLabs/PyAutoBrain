# The development workflow

Every task follows the same lifecycle, whatever its size:

```
idea  →  prompt file  →  issue  →  worktree  →  PR(s)  →  merge  →  registry
        (Mind)          (GitHub)   (isolated)   (gated)   (human)   (Mind)
```

1. **Intent is written down first.** A task starts as a markdown file you
   write in the Mind under `<work-type>/<target>/<name>.md` — plain English,
   no template.
   The work-type folder (`feature/`, `bug/`, `refactor/`, `docs/`, …) tells
   the Brain what kind of reasoning the task needs.
2. **`start_dev`** routes the prompt through the Brain's Feature Agent:
   classify, plan at two levels (human bullets + a detailed plan a fresh
   session could resume from), survey the affected branches, create a
   tracked GitHub issue, and register the task in the Mind's `active.md`.
3. **Work happens in a task worktree** (`~/Code/PyAutoLabs-wt/<task>/`) on a
   `feature/<task>` branch across every claimed repo, so parallel tasks
   never collide. `active.md` records the claim; a conflict check blocks
   double-claiming a repo.
4. **`ship_*`** gates the finish: test suites, the review faculty, and the
   Heart readiness verdict. GREEN ships; YELLOW needs an explicit human
   acknowledgement; RED stops. One PR per repo, always.
5. **Merge is always human.** After merge, the task entry moves from
   `active.md` to `complete.md` — the organism's operational history.

The registry files (`active.md`, `planned.md`, `complete.md`) are shared
state in the Mind repo, so any machine or session — laptop, web, CI — can
read the current picture and resume an in-flight task with no handoff
ceremony.

## The autonomy contract

How much of that lifecycle runs without a human is not ad-hoc: it is defined
once, in
[AUTONOMY.md](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/AUTONOMY.md).
Each prompt carries `Autonomy: safe | supervised | human-required`; each
work-type has a cap; the effective level is the minimum of the two, and it
binds only when a run is explicitly launched with `--auto`. The contract
pins the invariants: merge is always human, autonomous runs end at PR-open,
Heart RED always stops, and a `safe` run's four-leg ship gate (tests, smoke,
automatic review, Heart) must pass before anything is pushed. Every
autonomous run appends to a calibration log, and raising a cap requires
citing it.

## Model tiers

The workflow splits across model tiers, not named models: a **judgment
tier** (the strongest available model) does planning, risk calls, and any
prose a reader will learn from; an **execution tier** (a fast, cheap model)
runs the mechanical shell/git phases as subagents. The doctrine survives
model generations changing underneath it.

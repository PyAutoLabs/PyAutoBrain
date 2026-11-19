You are the close-out session for one pull request in a shift the human
launched by writing a shift brief:
{brief_path}

The PR: {pr_url}
Its task: {task_path} (declared `Consequence: glance` or `notify`)

You are the **independent session** AUTONOMY.md "Unattended `glance` merges"
requires (for a `notify` PR a worker left open, ruling R3 of 2026-11-17 closes
it out on the same terms): you did not write this PR, and you trust nothing its author claimed.
Merge only if every check below passes; otherwise refuse. A refusal is a good
outcome — the human merges by `/prm` at check-in.

1. Read the task's `Witness:` header and **run it yourself** against the PR's
   head. Record what decided it. A `notify` task that declares no `Witness:`
   is refused, with why `notify with no Witness: → human /prm` (ruling R3:
   the close-out session runs the witness).
2. Review the diff adversarially: look for a changed default, a user-visible
   error message, a removed or weakened test, a renamed public thing, or a
   wrong docs claim. Any one of them → refuse. Added or renamed public
   library names are decided by the one check (AUTONOMY.md "Public-name
   narrowing of `glance` — 2026-11-16", PyAutoBrain#641). The watcher ran it
   before starting you; run it again, as a second layer:

       {public_names_cmd}

   Exit 0 passes (a repo the ruling does not cover prints CLEAN). Exit 1 (a
   public name added or renamed) or 2 (it cannot tell) refuses, with its first
   output line as the `why`: `public name added/renamed: <names> → human /prm`.
3. Refuse if the PR carries the `decision-taken` label, if its tier is not
   `glance` or `notify`, or unless Heart's **scoped development-ship verdict** for the
   PR's repo ({pr_repos}) is `green` (AUTONOMY.md leg 4, PyAutoHeart#340):

       {heart_cmd}

   It prints `green`, `red`, `stale` or `unknown`. Only `green` passes: `stale`
   never does, and `unknown` (a reply that is not Heart's dev-ship gate, or no
   Heart here) parks — refuse with the word it printed. A repo Heart does not
   gate reads `green` with a "gate-deferred" note: its PR checks (step 4)
   decide (PyAutoHeart#343).
4. Judge the PR's CI with the one CI-verdict script (PyAutoBrain#628), for
   every repo — never by reading `gh pr checks` yourself:

       {ci_verdict_cmd}

   It reads every check-run, workflow run and job on the REST head sha, and
   mergeability, and prints `GREEN`, `PENDING` or `RED` with reasons (exit 0,
   2, 1). Only `GREEN` passes. `PENDING` or `RED` refuses with its first
   reason line (`CI PENDING: …` / `CI RED: …`): no waiting, no re-run. A
   `GREEN` that names a skipped **test** leg refuses too (a tiered merge
   stops on a skipped test leg, `skills/prm/reference.md` "Tiered merge").
{after_step}5. Immediately before you merge — after every check above, and again right
   before the merge command itself — look for {lease_dir}/{task}.dropped. If
   it exists, the human dropped this task with `/drop` mid-shift: do not merge;
   refuse with why `dropped by /drop`.
6. If everything passed, use the prm skill on {pr_url}: the full close-out,
   judged exactly as a human-typed `/prm`. Never commit to PyAutoMind yourself
   — a hook refuses it; queue each Mind change with
   `{shift_ledger} --task {task} append|write|edit|move|remove|drop-section ...`
   (ops land in {ledger_dir}/) and the orchestrator commits them. `write`
   only creates a file; change one that exists with
   `{shift_ledger} --task {task} edit <path> --old-file <was> --new-file <now>`
   (`--old` must appear exactly once in it on Mind main). Queue every edit
   first and the complete record last: if any op of the task is set aside,
   its record is held, not recorded shipped. A refused op is not queued; fix
   it and queue it again. With the complete record, also retire the task's
   `queue.md` entry, as `lifecycle.py close` does (it is silent when there is
   none):

       {shift_ledger} --task {task} queue-retire queue.md <prompt file name> --text "{pr_url} → <complete record path> (<date>)"

   Do **not** append the Shadow-window row: the watcher writes the stage-2
   row from your verdict for a `glance` PR, and none for a `notify` one.
   The `/prm` merge slot take (reference.md "Tiered merge") is
   `pyauto-brain merge-slot take {pr_url} --task {task}`; it succeeds for
   this PR and task: the watcher took its slot before starting you.
7. After a merge, remove the task's worktree and local branch as `/prm` does
   (`skills/prm/closeout.md` steps 5–6): `worktree_remove <slug>` once your
   `drop-section active.md <slug>` is queued — the stale-claim guard counts a
   claim release queued in {ledger_dir}/ — then `git -C <repo> branch -d
   feature/<slug>` for a local branch left in a canonical checkout. Never
   `PYAUTO_WT_FORCE=1`, never `rm -rf`: a dirty tree or any other refusal
   stays, and you say why in the verdict's `cleanup` field.
8. End at your deliverable. Never arm anything that outlives your turn.

Last, write {lease_dir}/{task}.closeout as one JSON object:

    {{"result": "merged" | "refused", "pr": "{pr_url}",
      "why": "<one line — required when refused>",
      "gate": "tests …/witness …/review …/heart …",
      "model": "<your model id>",
      "cleanup": "<after a merge: `worktree and branch removed`, or why not>"}}

Without that file the watcher records the close-out as ended without a
verdict and never retries it.

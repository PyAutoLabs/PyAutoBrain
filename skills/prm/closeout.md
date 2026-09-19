# Post-merge close-out

On MCP use [mcp.md](mcp.md); consult [GITHUB_ACCESS.md](../GITHUB_ACCESS.md)
only for an operation missing from that lane.

Read this procedure only after the merge gates in [prm.md](prm.md) pass.
Read [reference.md](reference.md) by the corresponding section, not in full.
All Mind paths below are relative to the resolved Mind checkout.

## 5. Close the task out

Typing `/prm` authorized all of this; the only questions are the guards in step
6. Order is forced by the tooling, so do not reorder:

1. **Prove every branch merged, per repo** — a `complete/` record is a write-up,
   not a merge receipt, and a task may have shipped in waves. Ask git, per repo
   the task claims, never the record. Any repo with unmerged commits and no open
   PR **stops the close-out**: a half-merged task must not be recorded complete.
2. **Issue** — post the "Shipped" comment (template: `../ship_library/reference.md`
   → "Issue comments + Mind state"), then close it. `gh issue close` is broken in
   this gh; use the REST path.
3. **Mind: `active/` → `complete/`** — draft the completion body, then one
   verb does the whole Mind-side close-out — the record, the prompt's
   removal, the `active.md` row (and any `parked.md`/`planned.md` pointer),
   the shadow row when the tier is `notify`, and `complete/index.md`:

   ```bash
   python3 scripts/lifecycle.py close <slug> --date <merge date> \
     --from-file <body.md> --pr <Repo#N …> [--tier notify --gate "<cell>" \
     --action <action> --stage <1|2>]            # dry run: prints every step
   python3 scripts/lifecycle.py close … --apply  # then does them
   ```

   Read the dry run before `--apply`: it names the record path, the file it
   removes, the entry it drops and every cross-reference you must repoint
   (`draft/`, `active/`, `epics.md`, the registries — it never rewrites those
   itself). It refuses a record that already exists and a slug it cannot
   resolve; `--prompt <bare-filename>` names the prompt when the slug does
   not. `lifecycle.py record …` remains underneath for the record alone.

   **Record the scope you merged, not the scope you filed.** On a partial merge,
   record what shipped and re-file the remainder as a fresh
   `draft/<work-type>/<target>/` prompt pointing back at the record. Recording a
   prompt whole on a partial merge is what leaves half-done work on the dashboard
   as pickable backlog.

   **Carry `pending-release:` into the record.** A library PR merged here is not
   a released library, and the `active.md` row that held that fact is about to
   be pruned. Copy every uncleared `- pending-release: <lib>@<pr-url>` line from
   the row into the completion body, so the obligation outlives the row and the
   dashboard's **Pending release** section keeps showing it. `/prm` never
   clears the key — only `/review_release` does, on a release that actually
   published (`PyAutoMind/REFERENCE.md` → "The pending-release chain").

   **3b. Shadow row — tier-`notify` only.** The tier-`notify` auto-merge
   decision is pre-registered over **40 candidates**, and this close-out is
   where the window is fed. It used to hang off a batch review slot, which
   runs only when a batch is launched; close-out happens on every shipped
   task. Do it only after sub-step 1 proved every branch `MERGED` — the row
   records what the human *did* with the PR, and before the merge there is
   nothing to record.

   1. **Tier.** The prompt's declared `Consequence:` header wins; with no
      header, `bin/pyauto-brain sizing <prompt>`. Anything but `notify` —
      **do nothing and say nothing**: no row, no question, no ledger line.
   2. **Gate cell.** Copy it from the task's ship calibration row in
      `PyAutoMind/autonomy_log.md` — `ship_library` / `ship_workspace` wrote
      it at PR-open. No such row (a task that never went through ship)? Write
      the legs from your own step-2 judgement, in the same
      `tests/smoke/review/heart/witness[/adversary]` form. Never invent a
      greener gate than the one that ran.
   3. **Stage.** `2` if an independent-model adversary leg ran on this task,
      else `1`. Stage 1 and stage 2 are never pooled, so this is not a
      judgement call: the leg either ran or it did not.
   4. **The one question.** Ask the human exactly this, and ask nothing else:

      > Merged unchanged, or did you change something substantive first?
      > (substantive = a change you would have minded finding already merged:
      > a changed default, a user-visible error message, a removed or weakened
      > test, a renamed public thing, a wrong docs claim)

      → `merged-unchanged` / `merged-after-substantive-change`. `not-merged`
      is what gets recorded when `/prm` stopped on a guard (step 6) and never
      reached the question — never a guess at what the answer would have been.
   5. **Append** — the `--tier notify --gate "<cell>" --action <action>
      --stage <1|2>` flags on the `close` verb above do it (`shadow-row` is
      the verb underneath). The dry run prints the row and the new count line
      before anything is written; the row rides the same commit and push as
      the record and the dashboard, never a commit of its own.
   6. **Name it in the ledger** (sub-step 7): "shadow row appended, count
      N/40".

   Protocol, power calculation and the **pre-registered decision rule** live in
   the tier-`notify` protocol prompt, folded under `## Original prompt` in
   `PyAutoMind/complete/2026/09/prm-shadow-row-notify-tier.md` — read it
   before interpreting the table.
4. **Mind: leave the page true** — the close-out is finished when `dashboard.md`
   stops offering this work, not when the claim is released.
   `dashboard_refresh.yml` heals a stale *render*, never a stale *prompt*, so
   this leg belongs to `/prm` and to nothing else.

   1. **Sweep** — grep the slug and the prompt filename across `draft/`,
      `active/`, `epics.md` and the registry files; repoint or remove every hit
      the merge falsified (an unblocked `blocked-by:`, a finished epic phase, a
      `superseded-by:` chain that now ends in a record).
   2. **Reconcile** — `pyauto-brain intake reconcile draft/<work-type>/<target>`
      over the shipped prompt's folder plus any the merged diff lands in;
      folder-scoped, never whole-backlog. **Proof retires, resemblance reports**:
      a sibling this merge provably covers gets its own record and `git rm` under
      the same `/prm` authorization; one that merely *looks* alike gets a ledger
      line and the `/intake reconcile` door — never a second question (step 6
      owns the only one).
   3. **Regenerate — always**, whatever 1 and 2 found; moving a prompt into
      `complete/` changes the page by itself, so this leg has no "nothing
      changed" exit, only a `--check` that says the render is current:

      ```bash
      pyauto-brain intake --apply dashboard     # writes dashboard.md + dashboard.html
      pyauto-brain intake dashboard --check     # must print "…are current"
      ```

   Never hand-edit either page. Commit the render **with** the record, then
   `lifecycle.py check` and push Mind. `git show --stat HEAD` must name both
   dashboard files beside the record, or leg 3 did not happen.

   **Push the branch you are on — never force `main`.** On a laptop that branch
   *is* `main`. On a branch-scoped surface (the phone, claude.ai/code, any
   `claude/**` or `codex/**` flow) it is the session's branch, and pushing it is the whole
   job: a close-out diff is ledger by construction, so
   `mind_ledger_merge.yml` merges it into `main` and can delete the branch after its checks pass — no PR, and no "merge that branch too" left for the human. Say in
   the ledger that the Mind branch was pushed and will land itself. Two things
   change that: the close-out also touched `scripts/`, `.github/`, `skills/` or
   another code path (then the branch waits for a human — say so plainly), or
   `lifecycle.py check` fails (then it was never going to merge; fix the drift).
   `python3 scripts/ledger_merge.py classify --base origin/main` in the Mind
   checkout tells you which of the three you are in.
5. **Worktree** — `worktree_remove <task>`, never `rm -rf`. It refuses on a dirty
   repo and on a claim still registered in `active.md` — which is exactly why
   step 3 comes first.
6. **Local branches only** — delete a local `feature/<task>` left in the
   canonical checkout, never one whose merge you did not prove in sub-step 1.
   **The remote branch is not yours to delete**: GitHub removes a merged head
   itself, and `branch_sweep*.yml` / `/repo_cleanup` collect what escapes.
   Nothing to do, and no ledger line — not "deferred", not "blocked".
7. **Report the ledger** — PRs merged, issue closed, record path, `active.md`
   released, **dashboard regenerated** (plus any sibling retired, any suspect
   left standing with its `/intake reconcile` prefix), worktree removed, and
   anything skipped. That dashboard line is not prose: if you cannot write it,
   leg 4.3 did not run — go back and run it.

**On `mcp`:** 1 and 2 run as usual; 3 works if PyAutoMind is checked out, else
the record is pending. Leg 4 needs **both** checkouts (state is Mind's, renderer
is Brain's): with only Mind, sweep and reconcile and leave the render to
`dashboard_refresh.yml`; with neither, call the leg pending rather than implying
the page is true. 5 and 6 are local-only — name 5 outstanding, say nothing of 6.

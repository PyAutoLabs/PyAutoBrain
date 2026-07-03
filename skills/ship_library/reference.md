# ship_library — reference detail

Factored out of `ship_library.md`. The body skill is authoritative for the flow;
this file holds the verbatim PR format, the API-Changes rules, and the
workspace-impact analysis.

## Writing the `## API Changes` section (judgement — stays in the reasoning model)

Analyse **all** commits on the branch and the full diff against the base branch.
Identify every change to the public API: removed / added / renamed-or-moved
symbols, changed signatures (new required args, removed args, changed defaults),
and changed behaviour of existing public functions.

The PR body has two parts:

- **Human-readable summary (≤10 lines):** the high-level story ("replaced X
  classes with Y functions"), not every symbol. End with "See full details
  below." If there are no API changes, write `None — internal changes only.`
- **Machine-readable details block:** a collapsed `<details>` after the Test
  Plan, grouping the full structured changes by type (Removed / Added / Renamed /
  Changed Signature / Changed Behaviour / Migration), code-formatting all symbol
  names.

## Full PR format

```markdown
## Summary
<concise description of what and why>

## API Changes
<high-level summary, max 10 lines — focus on the story not every symbol>
See full details below.

## Test Plan
- [ ] <how to verify the changes>

<details>
<summary>Full API Changes (for automation & release notes)</summary>

### Removed
- `module.OldClass` — replaced by `module.new_function()`

### Added
- `module.new_function(arg1, arg2=, **kwargs)` — does X

### Migration
- Before: `obj = module.OldClass(x); obj.method()`
- After: `module.new_function(x)`

</details>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Execution contract (feature-dev — the mechanical ship step)

This is the dev workflow's own git execution (commit/push/feature-PR), not a
Build/release step. Per repo, after the vitals faculty / Heart verdict is GREEN:

1. `source "$WT_ROOT/activate.sh"`; run `python -m pytest <test_dir>/ -x` from
   inside `"$WT_ROOT/<repo>"` (skip only if the repo has no test dir). These
   tests feed Heart's verdict — a failure means **stop**, return the failing
   names + traceback tail, do not commit, do not try to fix.
2. If the worktree is not on `feature/<task-name>`, stop and report — never
   auto-switch branches.
3. `git -C "$WT_ROOT/<repo>" add -A && git commit -m "<message>" && git push -u origin feature/<task-name>`.
4. `gh pr create --label "pending-release" --title "<title>" --body "<body>"`
   (paste the drafted body verbatim via HEREDOC). Then **verify the label
   landed**: `gh pr view <n> --json labels --jq '[.labels[].name]'`. If
   `pending-release` is absent, stop and report — usually the label doesn't
   exist on the repo; fix with `bash admin_jammy/software/ensure_workspace_labels.sh`
   then `gh pr edit <n> --add-label pending-release`.
5. Return a structured summary: one line per repo with test pass/fail counts,
   commit SHA, and PR URL.

In local-dev this is delegated to a Sonnet subagent (mechanical execution); the
reasoning model drafts the commit/PR text first and consumes the subagent's
result. In other environments run the same steps directly.

## Workspace-impact analysis

Read the `## API Changes` from the PR(s). For each changed public symbol, grep
the workspace scripts:

```bash
grep -rn "<old_function_or_class>" \
  autofit_workspace/scripts/ autogalaxy_workspace/scripts/ \
  autolens_workspace/scripts/ autolens_workspace_test/scripts/ \
  euclid_strong_lens_modeling_pipeline/scripts/ HowToLens/scripts/
```

Also check `PyAutoBuild/autobuild/config/no_run.yaml` — a changed symbol used by
a script listed there is a **hidden risk** (its release-pipeline integration
test is disabled). Present a data-driven recommendation:

- API Changes = "None — internal" AND no grep matches → **(iii)** confirm with
  smoke tests.
- **Added** entries only → **(i)** new demos, or **(iii)**; user decides.
- **Removed/Renamed/Changed** AND grep matches → **(ii)** migration needed; list
  the affected scripts.
- Removed/Renamed but no grep matches → **(iii)**; note API changed, no scripts
  appear affected.

Options (i) new scripts and (ii) migration both route to `/start_workspace`;
(iii) routes to `/smoke_test`.

## Issue comments + Mind state

**Progress (option i/ii) — workspace work to follow:** post a "Library PR
Created" comment (PR URLs, "Next: /start_workspace", API-change summary), set the
`active.md` status to `library-shipped, workspace-pending`, add `library-pr:`,
push Mind. Do **not** move to `complete.md`.

**Shipped (option iii passed):** offer to merge the library PR
(`gh pr merge <n> --merge --auto`), post a "Shipped" comment (PRs, summary,
optional session notes), move the entry from `active.md` to `complete.md`
(`issue`, `completed: <date>`, `library-pr:`), and push Mind with
`prompt_sync_push "prompt: ship <task-name> (#<issue>) → complete"`.

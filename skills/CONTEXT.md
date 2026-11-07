# Context and output discipline

Read once for development or review. It changes how evidence is loaded, never
an approval, test, independent-review, Heart or release requirement.

## Resolve locations once

`PyAutoMind/active.md` in prose names a repository-relative file, not a fixed
path: main checkouts may be grouped (`organs/`, `lens/`, …), task bundles and
remote clones flat. From the **Brain checkout** use the manifest-backed
resolver:

```bash
source bin/_pyauto_root.sh
source bin/_repo_paths.sh
export PYAUTO_BRAIN="$(pyauto_repo_path PyAutoBrain "$PYAUTO_ROOT")"
export PYAUTO_MIND="$(pyauto_repo_path PyAutoMind "$PYAUTO_ROOT")"
```

Resolve other repos only when needed (`pyauto_repo_path <Repo> "$PYAUTO_ROOT"`;
`agents/_repo_paths.py path --required` when existence is mandatory).
Re-resolve after changing worktree/root; never reuse main paths inside a task
bundle. Run `scripts/lifecycle.py` from the resolved Mind checkout. On a
GitHub-only surface use repository identity and API paths, not shell setup.

## Read the applicable procedure

- Load workspace rules, target-repo instructions and the invoked skill once;
  reuse them while unchanged. Refresh after an instruction edit, a branch/root
  change or a compaction that lost a required rule — never assume it.
- Reference files are indexes: find the heading, read that section. Select the
  local or remote lane once. Load linked-library instructions, autonomy detail
  and the post-merge close-out only when they apply.
- Never replace an independent review with the author's summary; give the
  reviewer a bounded scope and direct access to the diff and evidence.

## Bound tool results

- Paths first (`rg --files`), then scoped text (`rg -n`), then the lines that
  matter; never dump every sibling's instructions or whole registries.
- Routine status: diff stats, selected JSON fields, pass/fail counts, failure
  excerpts — about 1–2k output tokens per call unless the decision needs more.
- Save full test/build logs in the task's ignored scratch directory; return
  exit status, counts, the failure tail and the log path. Preserve the exit
  code — a successful `tail` must not mask a failed test.
- Truncated output: narrow the query; never assume the rest was clean. Keep
  exact gate reasons and complete review findings available.
- Batch independent reads; do not repeat an unchanged successful check. Reuse a
  worker for coherent fixes; report milestones and findings, not status pings.

## Completed-phase handoff

At a completed phase, refresh the issue/Mind task record in about 10–20 lines:
objective and remaining scope; accepted decisions and authorizations; worktree,
branch and commit; changed files; validation with log paths; open risks or
findings; the next concrete action. Link evidence, do not copy logs. Continue
already-authorized work in the current turn — never stop just to force a fresh
chat, never auto-start a replacement session, never treat a handoff as new
approval. A resumed session loads that record and verifies the branch and
claims first. A handoff never carries expired merge authority, clears a gate
or replaces independent review.

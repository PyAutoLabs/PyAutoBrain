# Context and output discipline

Read this once for development or review. It changes how evidence is loaded,
not any approval, test, independent-review, Heart or release requirement.

## Resolve locations once

Repository names in prose (for example `PyAutoMind/active.md`) identify a
repository-relative file, not a fixed workspace-root path. Main checkouts may
be grouped under `organs/`, `lens/`, etc.; task bundles and remote clones may
be flat. Use the manifest-backed resolver already in Brain. From the **Brain
checkout** (locate it using the workspace routing map):

```bash
source bin/_pyauto_root.sh
source bin/_repo_paths.sh
export PYAUTO_BRAIN="$(pyauto_repo_path PyAutoBrain "$PYAUTO_ROOT")"
export PYAUTO_MIND="$(pyauto_repo_path PyAutoMind "$PYAUTO_ROOT")"
```

Keep these paths for the current checkout. Resolve other repositories only when
needed, with `pyauto_repo_path <Repo> "$PYAUTO_ROOT"`; use `--required` with
`agents/_repo_paths.py path` when existence is mandatory. Re-resolve after
changing worktree/root or moving checkouts. Do not reuse main paths inside a
task bundle. Run Mind's `scripts/lifecycle.py` from the resolved Mind checkout.
On a GitHub-only surface use repository identity and API paths, not shell setup.

## Read the applicable procedure

- Load the workspace rules, target repo instructions and invoked skill once.
  Reuse them while unchanged. Refresh after an instruction edit, branch/root
  change or compaction that lost a required rule; do not assume missing context.
- Reference files are indexes: locate headings, then read the current section.
  Do not concatenate every reference at startup. Select the local or remote
  lane once. Load linked-library instructions only for a linked task, autonomy
  details only when applicable, and post-merge close-out only after merging.
- Never replace an independent review with the author's summary. Give the
  reviewer a bounded scope and direct access to the diff and supporting evidence.

## Bound tool results

- Search paths first (`rg --files`), then scoped text (`rg -n`), then the relevant
  lines. Do not dump every sibling's instructions or entire registries.
- For routine status, use diff statistics, selected JSON fields, pass/fail
  counts and failure excerpts. Default to roughly 1–2k output tokens per call;
  raise the limit deliberately when the decision needs more evidence.
- Save full test/build logs in the task's ignored scratch directory. Return
  exit status, counts and the relevant failure tail, with a log path. Preserve
  the command's exit code; a successful `tail` must not mask a failed test.
- If output is truncated, narrow the query. Never assume the missing part was
  clean. Keep exact gate reasons and complete review findings available.
- Batch independent reads. Do not repeat an unchanged successful check without
  changed inputs or a gate requiring it. Reuse a worker for coherent fixes;
  communicate milestones or actionable findings, not repeated status requests.

## Completed-phase handoff

At a completed phase, refresh the existing issue/Mind task record with:
objective and remaining scope; accepted decisions and authorizations; worktree,
branch and commit; changed files; validation results with log paths; open risks
or review findings; and the next concrete action. Keep this to a short section
(about 10–20 lines), linking evidence instead of copying logs or chat history.

Continue already-authorized work in the current turn. Do not stop solely to
force a fresh chat, start a replacement session automatically, or treat a
handoff as new approval. When the user resumes in a fresh session, load that
record and verify the current branch/claims before continuing. A handoff never
carries expired merge authority, clears a gate, or replaces independent review.

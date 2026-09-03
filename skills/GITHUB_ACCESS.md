# GitHub access: `gh` is not always there

Shared by every skill that touches GitHub. Read this once, at the top of a run,
and act on what it says for the rest of the run.

## The problem this page exists for

Most of the workflow was written on a developer box, where `gh` is installed and
authenticated, so the skills spell their GitHub steps as `gh` commands — 19 skill
bodies and 15 scripts in this repo do. **A Claude Code remote session has no
`gh` at all.** Its GitHub access is the GitHub MCP server: a set of
`mcp__github__*` tools the harness provides, with the session's own repository
scope already applied.

Nothing announced this. A `/prm` run on mobile loaded ~8k tokens of close-out
procedure, ran its first `gh pr view`, got `command not found`, and then had to
re-derive the whole procedure through MCP — every time, from scratch. One
completion record logged it after the fact:

> shipped from a `web-github` session (no task worktree, no `gh`; issue and PR
> driven through the GitHub MCP surface)
> — `PyAutoMind/complete/2026/08/status-sh-repos-missing-source.md`

So: decide once, up front, which surface you have, and read the procedure
through that lens.

## Decide once, at the start of the run

```bash
command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
    && echo "gh" || echo "mcp"
```

- **`gh`** — follow the skill's commands as written.
- **`mcp`** — the `gh` lines are *the operation to perform*, not the command to
  run. Translate with the table below. Do not try to install `gh` (the next
  section says why it would not help), and do not report the task as blocked: the MCP surface can do everything the close-out
  needs — deleting a branch is not one of the things it needs (below).

A session cannot be half-and-half. Probe once; don't re-probe per step.

## Installing `gh` does not work — measured, 2026-08-27

The probe above says "no `gh`", and the obvious next thought is to fix that:
the session runs as root, `apt-get install -y gh` succeeds in about two
seconds, and Ubuntu ships 2.45.0. Do not. What you get is a `gh` that
authenticates and then fails everything that matters, which is strictly worse
than the honest `command not found` — the binary looks healthy, so a run
spends its turns re-trying instead of switching surface.

What was actually measured in a remote session, with `gh` installed:

| Call | Result |
|---|---|
| `gh api user` | **works** — returns the login |
| `gh api rate_limit` | **works** |
| `gh api repos/<owner>/<repo>` | `403` — "GitHub access is not enabled for this session" |
| `gh api repos/<owner>/<repo>/pulls` | `403` — same |
| `gh api repos/<owner>/<repo>/issues` | `403` — same |
| `gh api repos/<owner>/<repo>/actions/runs` | `403` — same |
| `gh pr list`, `gh issue list`, `gh repo view` | `403` — "This GraphQL query is not enabled for this session" |
| `gh auth status` | reports the token invalid (it is a proxy placeholder) |

Two independent walls, either one of which is fatal:

1. **REST repo paths are not served.** The egress proxy answers every
   `api.github.com/repos/...` request with a 403 pointing at the Claude GitHub
   App. The same URL through `mcp__github__*` succeeds, because the MCP surface
   carries the session's own repo-scoped credential — a different credential
   from the one raw `api.github.com` sees.
2. **GraphQL is pinned to a small set of PR-review operations.** Most of `gh`'s
   porcelain (`pr list`, `issue list`, `repo view`, `pr status`) is GraphQL, so
   it stays broken even if the first wall were removed.

Because of the second wall, `gh` could not be a drop-in here even if an org
admin connected the GitHub App. The MCP surface is not a workaround for a
missing `gh` — on this surface it is *the* GitHub client. Use the table above.

And installing it does not just waste the effort — **it breaks the probe
above**. `gh auth status` exits 0 in a remote session even as it prints "The
token in GH_TOKEN is invalid": the `proxy-injected` placeholder in `GH_TOKEN`
is enough to satisfy it. So a session that installed `gh` answers its own
decide-once probe with `gh`, reads this page's commands as commands, and walks
straight into the 403s above — the failure mode the probe exists to prevent.
The probe is only honest while `gh` is absent, which is the strongest reason to
leave it that way.

## The mapping

| Operation | `gh` | MCP tool |
|---|---|---|
| Read a PR (state, head sha, mergeability) | `gh pr view <n> --json ...` | `pull_request_read` (`method: "get"`) |
| PR files / diff | `gh pr diff <n>` | `pull_request_read` (`method: "get_diff"` / `"get_files"`) |
| PR review threads | `gh pr view --json reviews` | `pull_request_read` (`method: "get_review_comments"`) |
| List PRs | `gh pr list --repo <r>` | `list_pull_requests` |
| Find PRs by query | `gh search prs ...` | `search_pull_requests` |
| Open a PR | `gh pr create` | `create_pull_request` |
| Edit a PR (title, body, base) | `gh pr edit` | `update_pull_request` |
| Merge a PR | `gh pr merge <n>` | `merge_pull_request` |
| Update a PR from its base | `gh pr update-branch` | `update_pull_request_branch` |
| CI runs for a sha | `gh run list`, `gh pr checks` | `actions_list` (`workflow_runs`), `get_check_run` |
| One run's detail / jobs | `gh run view <id>` | `actions_get`, `get_job_logs` |
| Re-run a workflow | `gh run rerun` | `actions_run_trigger` |
| Read an issue | `gh issue view <n>` | `issue_read` |
| List / search issues | `gh issue list`, `gh search issues` | `list_issues`, `search_issues` |
| Open, edit or close an issue | `gh issue create/edit/close` | `issue_write` |
| Comment on an issue or PR | `gh issue comment` | `add_issue_comment` |
| Reply in a review thread | `gh api .../comments` | `add_reply_to_pull_request_comment` |
| Resolve a review thread | `gh api graphql` | `resolve_review_thread` |
| Read a file at a ref | `gh api .../contents/<p>` | `get_file_contents` |
| Commit a file | `gh api -X PUT .../contents` | `create_or_update_file`, `push_files` |
| List branches / commits / tags | `gh api .../branches` | `list_branches`, `list_commits`, `list_tags` |
| Create a branch | `gh api -X POST .../git/refs` | `create_branch` |
| Releases | `gh release view/list` | `get_latest_release`, `list_releases`, `get_release_by_tag` |
| Who am I | `gh api user` | `get_me` |
| Be woken by CI / comments on a PR | *(no equivalent — a CLI polls)* | `subscribe_pr_activity`, `unsubscribe_pr_activity` exist but are **not to be armed** — sessions end at their deliverable; use `unsubscribe_pr_activity` only to clear a stale subscription |

Tool names are given unprefixed; the harness exposes them as
`mcp__github__<name>`. If a name is not loaded, `ToolSearch` fetches its schema.

That last row is the one capability a run must **not** take. A subscription or
a `send_later` reminder outlives the session's deliverable and wakes turns
nobody asked for: five batch members self-armed check-ins on green PRs
overnight (2026-08-31), and a mobile `/prm` subscribed then re-armed an hourly
check-in all night with no task active (2026-09-03), draining usage. Sessions
end at their deliverable — judge once, report, stop
(`PyAutoMind/policy/end_at_deliverable.md`). Waiting for CI is the human's
re-run of `/prm`, not a timer this session leaves running;
`unsubscribe_pr_activity` is here only to clear a stale subscription an older
run left behind.

## What the MCP surface cannot do

- **Delete a remote branch.** There is no MCP tool for it, and in a proxied web
  session `git push origin --delete` is refused by the egress proxy — *silently*:
  the 403 goes to stderr, git then prints `Everything up-to-date` and exits 0, so
  the run cannot tell the delete failed and will report one that never happened.
  Never run it here. No workflow asks you to: GitHub deletes a merged PR's head
  itself (`repo_settings.yml` keeps that setting on), and `branch_sweep.yml`
  sweeps the rest. Nothing about branch cleanup belongs in an MCP-surface run.
- **Reach a repo outside the session's scope.** The session is scoped to a
  repository set at start; `add_repo` extends it. A call outside that scope is
  denied — that is the scope working, not an auth problem to route around.

## Two rules that apply on both surfaces

1. **Every comment, review or reply you author ends with the attribution
   footer** — a blank line, a `---` rule, then
   `_Generated by [Claude Code](https://claude.ai/code)_`. The server strips
   duplicates, so include it even where the tool adds one.
2. **Be frugal.** Post when a round resolves the task, hits a real blocker, or
   raises a question. The diff is the record; don't narrate each fix.

## For script authors

Shell scripts in this repo must not assume `gh`. Source `bin/_gh.sh` and call
`require_gh` — it exits with the pointer to this page instead of letting
`command not found` surface as a confusing failure two steps later.

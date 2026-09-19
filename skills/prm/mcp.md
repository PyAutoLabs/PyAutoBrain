# MCP close-out calls

Consult [GITHUB_ACCESS.md](../GITHUB_ACCESS.md) only for an operation missing
from this lane.

Read only on the MCP surface; follow all gates in [prm.md](prm.md).

### The `mcp` lane, step by step

Every GitHub call a close-out makes, so a mobile run reads this page and the
mapping page only if something here is missing. Names take the
`mcp__github__` prefix; `ToolSearch` fetches a schema that is not loaded.

| Step | Call |
|---|---|
| 1 resolve | `list_pull_requests` (state `open`), or `pull_request_read` `get` for a known number. Mind's `active.md` via `get_file_contents` |
| 2 judge CI | `pull_request_read` `get_check_runs` — every check on the head commit, in one call. Then `pull_request_read` `get` for `mergeable` / `merge_state_status` |
| 2 by workflow | `actions_list` `list_workflow_runs` **has no `head_sha` filter** (`workflow_runs_filter` is actor/branch/event/status only): filter by `branch`, then match `head_sha` yourself, or you will judge a stale run. Legs: `actions_list` `list_workflow_jobs`, `resource_id` = run id |
| 3 stop | **No call.** On this surface step 3 is judge-once-then-stop: no `subscribe_pr_activity`, no `send_later`. Report where each PR stands and end the turn; the human re-runs `/prm` when CI is green |
| 3 red | `get_job_logs` with `run_id`, `failed_only: true`, `return_content: true` — **before** anything else, the blob is purged |
| 4 merge | `merge_pull_request` (`merge_method: "merge"`), then `pull_request_read` `get` to confirm `MERGED`; `unsubscribe_pr_activity` only to clear a stale subscription an older run left |
| 5.2 issue | `add_issue_comment`, then `issue_write` `update` with `state: "closed"` and `state_reason: "completed"` — an unset reason is what leaves an issue reading "closed as not planned" |
| 5.1 proof | git, not GitHub — and `--is-ancestor` needs an unshallowed clone (`reference.md` §1) |

Steps 5.3-5.7 touch no GitHub API at all; what they need is a checkout, and the
note at the foot of step 5 says what to do without one.

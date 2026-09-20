# GitHub access: operations first, clients second

Shared by every skill that touches GitHub. Read this once, at the top of a run,
and act on what it says for the rest of the run.

## Canonical contract

The workflow asks for **GitHub operations**, not a particular client. Resolve
the authenticated GitHub-control surface once, then keep using it consistently:

1. a local shell may have authenticated `gh`;
2. a remote/chat harness may expose native GitHub actions/tools instead, with a
   repository scope and a read/write subset fixed by that connection;
3. a surface may be read-only or have no GitHub write capability at all.

Do not infer permissions from "ChatGPT", "Codex", "Claude", mobile, web, or a
model name. Inspect the actions/permissions actually exposed. Do not perform a
dummy write just to probe access: use the first required operation, and if the
provider denies it, downgrade that capability and route the missing phase.

The `gh` commands in skill bodies are executable commands only on the first
surface. Elsewhere they name the operation to perform. The MCP column below is
one measured adapter, not the architecture; another connected GitHub surface
may expose equivalent actions under different names.

**No API fallback:** GitHub access in the ordinary-Chat route must never be
replaced with the OpenAI API, an OpenAI API key, ChatGPT browser automation, or
session-credential reuse. Those are not GitHub clients and are not execution
fallbacks.

## The remote-session problem this page originally existed for

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

## Resolve the GitHub-control surface once

When a shell is available, the established probe remains:

```bash
command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1 \
    && echo "gh" || echo "native-tools"
```

- **`gh`** — follow the skill's commands as written.
- **native GitHub actions/tools** — treat each `gh` line as the operation to
  perform and translate it to the equivalent authenticated action. The mapping
  below records the currently measured MCP names; use equivalent operations on
  another connected surface.
- **no matching write action** — the current surface is not repository-write /
  GitHub-control capable for that phase. Do not install credentials, improvise a
  browser automation route, or call an OpenAI API; use the bounded execution
  handoff or stop.

Select one authenticated control surface for the run and do not mix credentials
or raw-token workarounds. Do not re-probe per step.

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

## Measured `gh` ↔ MCP adapter mapping

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
| Read the Discussions hub (list, one thread, its comments) | `gh api repos/<o>/<r>/discussions[/<n>[/comments]]` | *(no MCP tool)* — raw REST with the session token works, see below |
| Create, answer or convert a Discussion | `gh api graphql` (`createDiscussion`) / the issue sidebar | **nobody in a session** — REST Discussions is read-only, GraphQL is refused; the human clicks (`PyAutoMind/policy/community_surface.md`) |
| Be woken by CI / comments on a PR | *(no equivalent — a CLI polls)* | `subscribe_pr_activity`, `unsubscribe_pr_activity` exist but are **not to be armed** — sessions end at their deliverable; use `unsubscribe_pr_activity` only to clear a stale subscription |

Tool names are given unprefixed for the measured MCP adapter; that harness
exposes them as `mcp__github__<name>`. Other connected GitHub surfaces may use
different action names. Match operation semantics and permissions, not these
wire names.

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

## Measured again, 2026-09-17: raw REST works for attached repos

The 2026-08-27 table above was measured through an installed `gh`. From a
remote session's own shell, `curl https://api.github.com/repos/<o>/<r>/...`
with `Authorization: bearer $GH_TOKEN` (the token the harness sets) **is
served** for every repository attached to the session — issues, comments,
the repo record, and the read-only Discussions endpoints
(`.../discussions`, `.../discussions/<n>`, `.../discussions/<n>/comments`).
What is still refused, each with its own message: `api.github.com/graphql`
(every query), `search/issues` (not repository-scoped), any repo not attached
to the session, `github.com/...` HTML (403), and `POST .../discussions` (a
GitHub 404 — the REST Discussions API is read-only). So a conductor written
against `gh api repos/...` REST paths runs in a remote session by pointing
`COMMUNITY_GH` at a two-line `curl` shim; one written against GraphQL or
`search/` does not. The rule stands: do not install `gh`.

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

## Two rules that apply on every surface

1. **Do not fabricate harness attribution.** If repository policy requires an
   attribution footer, identify the actual harness when it is known; otherwise
   use the repository's provider-neutral wording. Never stamp a Chat/Codex run
   as Claude (or vice versa) merely because an older adapter example did.
2. **Be frugal.** Post when a round resolves the task, hits a real blocker, or
   raises a question. The diff is the record; don't narrate each fix.

## For script authors

Shell scripts in this repo must not assume `gh`. Source `bin/_gh.sh` and call
`require_gh` — it exits with the pointer to this page instead of letting
`command not found` surface as a confusing failure two steps later.

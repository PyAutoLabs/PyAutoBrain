# Community agent

> **Tier: conductor** — a front-door agent you *drive*. Brain judgement over
> **PyAutoEars**, the
> organism's receptive language function: it hears the community (the
> Discussions hub where users ask, plus user-filed GitHub issues and pull
> requests across every repo) and drafts what the organism says back; the
> human remains the mouth. Wernicke to the Workspace Agent's Broca: that
> *Voice* speaks to users through examples and tutorials, this agent
> *comprehends and converses* — it reads an outsider's issue, judges whether
> the context is sufficient, drafts every reply for human approval, and routes
> actionable work into the dev flow. It never posts, labels, edits or releases
> anything itself.

Grown from demonstrated need: user-filed issues were handled ad-hoc (paste the
GitHub link into an agent chat), the `start_dev_for_user` skill already owned
the downstream dev entry, and the founding prompt asked for both a dedicated
listening/communicating agent and an Ears board summary of what the community
is waiting on. Founding prompt:
PyAutoMind `active/community_communication_agent_listen_and_respond.md`
(issue PyAutoBrain#119).

## Modes

The session-side [`/feedback`](../../../skills/feedback/feedback.md) workflow
solicits user-reviewed reports from the current session or selected logs. It
also offers a portable invitation for users of other agents. It drafts only,
does not call the scanner, and adds no CLI mode or registry. Submitted reports
arrive on the existing hub and follow ordinary scan/triage. The report's
`feedback-report: v1` marker is a format label, not evidence of approval.

Both modes are live, deterministic and **read-only** — they emit surfaces the
`/community` skill session reasons over. The judgment (actionable vs
ask-for-more, the reply prose, the routing call) is the session's; the human
gates every outward message.

| Mode | Surface | Consumed by |
|------|---------|-------------|
| `scan` *(default)* | published Ears snapshot/state adapted to the existing scan JSON; observed response/review states, source gaps and freshness, without a second collection path | `/community` step 1; Brain board |
| `triage <ref>` | one discussion, issue or PR → category-sensitive context signals (scientific assumptions/data/inference for Help; reproduction for Bugs; use case/outcome for Ideas; no checklist for broadcasts), clarifying-question seeds, bounded comment tail and coverage receipt, route; a discussion ref routes to **answer in the thread** (a confirmed bug gets an issue with a link back); a PR ref adds the **change-shape block** (draft, files, +/-, requested reviewers, mergeable state, head→base) | `/community` steps 2–3 |

```
pyauto-brain community                    # scan: who is waiting on us?
pyauto-brain community scan --json
pyauto-brain community triage <discussion/issue/PR url | owner/repo#N> [--json]
```

The hub is `COMMUNITY_HUB` (default `PyAutoLabs/.github` — the org's
Discussions, the one surface users post to, decided in
`PyAutoMind/policy/community_surface.md`). A discussion is named by its URL on
every surface, because `owner/repo#N` reads as an issue.

## Slack notification relay (operational runbook)

Slack delivery is an external notification edge, not a Community Agent mode.
The public Discussion remains the source of truth and the conductor remains
read-only. Use GitHub's official Slack app in the designated workspace's
`#general` channel; do not add a webhook, token or channel identifier to this
repository.

Before changing the channel, run `/github subscribe list` and `/github
subscribe list features` in `#general`. Confirm that the channel is the intended
public PyAutoLabs channel, the GitHub app can access `PyAutoLabs/.github`, and
the person making the change is allowed to manage the workspace integration.
If `PyAutoLabs/.github` is already subscribed, preserve its existing intentional
features and add only `discussions`. Preserve all other repository subscriptions.

The intended subscription is:

```text
/github subscribe PyAutoLabs/.github discussions
```

Use no category filter: that covers the five current Discussion categories
(Announcements, Bugs & Errors, Help & Questions, Ideas & Proposals, Show and
tell) and future categories. GitHub's native `discussions` feature reports
discussions being created or answered; it does not report every reply, edit or
reaction. If this is a new repository subscription and it enables default
development traffic, remove only those features from this repository:

```text
/github unsubscribe PyAutoLabs/.github issues pulls commits releases deployments
```

Verify the live state with the two list commands above, then create one clearly
marked test Discussion after human approval. Record the workspace, channel,
setup owner, enabled features, test Discussion URL, observed message shape and
verification date on the task issue. The expected result is one channel message
with useful author/title context and a working public link, without
`@channel`, `@here` or `@everyone`. Do not replay historical Discussions, and
do not copy private Slack replies back to GitHub.

Rollback is:

```text
/github unsubscribe PyAutoLabs/.github discussions
```

If native created-and-answered delivery cannot meet the requirement, stop and
obtain approval for a separately designed event-driven fallback; retries,
deduplication and rendering untrusted titles as inert text become required at
that point.

GitHub documents the event list and commands in its
[Slack notification guide](https://docs.github.com/en/integrations/how-tos/slack/customize-notifications).

### Live setup (2026-09-20)

Jammy2211 installed the GitHub Slack app for PyAutoLabs and subscribed the
PyAutoLabs workspace's `#general` channel to
`PyAutoLabs/.github discussions`. The app's
`/github subscribe list features` response showed `discussions` as the only
enabled feature for that repository. No category filter is configured, so the
subscription applies to all five current categories and future categories.

The operator created [test Discussion #21](https://github.com/orgs/PyAutoLabs/discussions/21)
in Help & Questions at 15:17 UTC and observed one GitHub app message in the
channel with the author, title, category, repository and link. This verifies
delivery for a newly created discussion; coverage of other categories and
future external authors follows from the unfiltered subscription, rather than
separate live tests. The workspace URL was originally `pyautolens.slack.com`
at test time and changed to `pyautolabs.slack.com` later on 2026-09-20;
the operator confirmed the new workspace name is PyAutoLabs. Slack redirects
the old URL to the new one. Use the rollback command above to disable delivery.

Collection and repository enumeration belong to PyAutoEars. Scan reads its
published `snapshot.json` and matching `state.json`; `COMMUNITY_EARS_URL`
overrides the public base for other deployments and offline fixtures.
Unavailable or malformed feeds exit 4; no fallback GitHub search runs. Stale
and cached response observations become unknown, retaining their recorded
value separately. Counts describe observations, never complete coverage.
Triage still uses `gh` (`COMMUNITY_GH` override); `COMMUNITY_SELF` supplies
maintainer logins for triage and compatibility grouping. `COMMUNITY_HUB`
retains the existing hub identity. Search pause/detail-cap options are retired.

## Fundamental principles

- **The conductor hears; the human speaks.** Every outward message — receipt,
  clarifying question, plan update, closing note — is drafted in the session
  and presented to the human before posting. The CLI itself never mutates
  GitHub. Autonomy for community work is `human-required` by design; `--auto`
  changes nothing here.
- **Users ask on the hub; the development flow stays on issues.** That is
  `PyAutoMind/policy/community_surface.md`, and this conductor is its
  reader: a question, a help request or an idea is answered in its
  Discussions thread; a report with a reproducer is an issue and routes to
  `/start_dev_for_user`; a discussion that turns out to be a bug gets an
  issue opened with a link back. Accepted implementation proposals follow
  that same issue route; the human marks the verdict comment as the accepted
  answer in Ideas & Proposals, whether acceptance with the issue link or a recorded
  no. Accepted answers settle earlier activity in answerable categories only.
  Later external comments can require follow-up review without reopening.
  Posting is surface-dependent: a remote/proxied session cannot post to,
  answer or convert a Discussion (the REST Discussions API is read-only and
  the proxy refuses GraphQL), so there the human's click is the last step;
  a local CLI with an authenticated `gh` can do all three through GraphQL
  (`addDiscussionComment`, `markDiscussionCommentAsAnswer`,
  `closeDiscussion` — `skills/GITHUB_ACCESS.md` → "Discussions") once the
  human has approved the text. The approval is the gate, not the click.
- **Broadcasts are ours to watch.** Announcements and Show and tell remain
  visible and can be triaged explicitly, but an outside comment does not
  put them in awaiting-response. Help & Questions, Ideas & Proposals, and
  Bugs & Errors follow the last-word rule until an accepted answer settles
  earlier activity. New comments after settlement need review. Bugs & Errors is for investigation; confirmed reproducible
  defects are tracked on linked repository issues.
- **Conversation state lives on GitHub + Mind, never here.** Labels
  (`needs-info`, `pending-release`) and the issue thread itself are the
  conversation's memory; in-flight dev state is the `user-facing: true` entry
  in `PyAutoMind/active.md`. The conductor owns no registry or cache. PyAutoEars owns collection,
  versioned evidence, receipts and the listening dashboard; Brain owns judgement.
- **Delegate the conversation's dev half.** Actionable issues route into
  `/start_dev_for_user`, which already owns the receipt comment, the
  clarification gate, the plan comment and the milestone cadence
  (~5 milestones for bugs, ~4 for features — see its `reference.md`). This
  conductor never re-implements those templates.
- **Stdlib / bash only** — like every conductor, it must never drag the
  science stack into the Brain.

## Boundaries

- **vs the Workspace Agent (the Voice)** — split by *direction of speech*. The
  Voice is expressive: it plans how the organism speaks to practitioners and
  learners through authored examples. The Ears are receptive: they hear what
  individual outsiders say back (issues, requests, bug reports) and hold up
  the organism's end of the conversation.
- **vs intake** — intake conceives tasks from the *developer's* raw ideas and
  files Mind prompts; community converses with an *external reporter* whose
  issue already exists on GitHub. When a community conversation yields work,
  it routes via `start_dev_for_user` (issue-first), not intake (prompt-first).
- **vs start_dev_for_user** — that skill is the dev-flow entry for one
  already-actionable issue. Community is the layer above: discovery (scan),
  assessment (triage), the ask-for-more conversation, and the ongoing
  reporter-facing updates after routing.
- **vs bug / feature** — they classify and plan the *work*; community manages
  the *relationship* with the person who reported it.
- **vs health / hygiene / release** — no verdicts, no upkeep, no releases.
- **vs the review faculty** — an external PR surfaced here routes to a
  *human review with session-drafted comments*; the review faculty judges
  only our own feature branches for the autonomous-ship gate, never
  community PRs. Ears includes PR review evidence in its scan receipts;
  the per-thread triage context is still a bounded read, not full history.

## Capability audit — what the current surface can observe

- **Published Ears evidence**: versioned public metadata only, matching
  observation times and a freshness deadline. Source receipts and nullable
  response state pass through. URLs must match canonical GitHub identities.
- **Discussion / issue / PR detail**: a selected thread's context and bounded
  comment tail for human-led triage; no bulk collection in Brain.
- **Pull detail**: triage change shape (files, +/-, draft, reviewers, base/head).
- **Triage coverage limits**: the selected-thread REST read is bounded to 100
  comments. Its displayed tail is the last three of that bounded read, not
  necessarily the latest in the thread. Failures, deleted authors and count
  mismatches remain explicit; nested Discussion replies and PR review threads
  are not fetched. Incomplete evidence yields unknown response state.
  Accepted answers and broadcasts can suppress response chasing; accepting a
  proposal never establishes delivery. Ears owns broader collection coverage.

## Follow-ups without reopening

Treat Ears `follow_up.review_needed` as activity evidence, not a judgment that
reopening is required. Inspect new source comments and nested replies in context:
classify acknowledgement, actionable request, or uncertainty, explain why, and
recommend a response, reopening the same thread, a linked new task, or a
clarifying question. A later maintainer message clears the observed waiting
signal but is not proof the request was implemented. A fresh external comment
restores it. Unknown coverage cannot establish that nothing is owed.

Contributors may lack permission to reopen. A comment is sufficient to request
attention; never make reopening a prerequisite or instruct a contributor to
reopen as the only path. Direct triage reads `viewerCanReopen` for the acting
account when possible; this says nothing about the contributor's permission.
If false or unknown, refer reopening to a maintainer with permission. Do not
conflate reopening, unlocking, and clearing an accepted answer. Each outward
reply or state change still needs explicit authorization. The conductor's
bounded direct comment read leaves response state unknown on settled threads
when it cannot establish full post-settlement coverage; the Ears scan provides
the paginated evidence. Fetch full relevant comments before making a judgment.

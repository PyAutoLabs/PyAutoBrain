# Community agent

> **Tier: conductor** — a front-door agent you *drive*. The *Ears* — the
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
listening/communicating agent and a `/wake_up` summary of what the community
is waiting on. Founding prompt:
PyAutoMind `active/community_communication_agent_listen_and_respond.md`
(issue PyAutoBrain#119).

## Modes

Both modes are live, deterministic and **read-only** — they emit surfaces the
`/community` skill session reasons over. The judgment (actionable vs
ask-for-more, the reply prose, the routing call) is the session's; the human
gates every outward message.

| Mode | Surface | Consumed by |
|------|---------|-------------|
| `scan` *(default)* | the **Discussions hub**'s open threads (awaiting-response = no accepted answer and the last word is not ours, except Announcements and Show and tell, which remain ours to watch) + every `PyAutoMind/repos.yaml` repo → open issues **and PRs** authored by non-self humans (bots filtered), with **awaiting-response** detection (the conversation's last word is not ours) ranked by waiting time, plus open PRs with **review requested** from a self login (any author) | `/community` step 1; the board's community sensory leg |
| `triage <ref>` | one discussion, issue or PR → context-sufficiency signals (code block, traceback, versions, expected-vs-actual, data pointer), missing-signal clarifying-question seeds, comment tail, route; a discussion ref routes to **answer in the thread** (a confirmed bug gets an issue with a link back); a PR ref adds the **change-shape block** (draft, files, +/-, requested reviewers, mergeable state, head→base) | `/community` steps 2–3 |

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

Repo enumeration comes from `PyAutoMind/repos.yaml` (the body map) under
`PYAUTO_ROOT`; the org is searched wholesale, non-org homes individually.
GitHub access is the `gh` CLI — `COMMUNITY_GH` overrides the binary (hermetic
tests), `COMMUNITY_SELF` the self logins (default `Jammy2211`),
`COMMUNITY_SEARCH_PAUSE` the inter-search sleep (default 2s — the scan makes
up to six search calls and GitHub's secondary rate limit trips on bursts). A
failed search degrades honestly (`degraded:` in the surface), never silently.

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
  no. Accepted answers settle threads in answerable categories only.
  No session can post to, answer or convert a Discussion (the
  REST Discussions API is read-only, GraphQL is refused) — the human's click
  is always the last step.
- **Broadcasts are ours to watch.** Announcements and Show and tell remain
  visible and can be triaged explicitly, but an outside comment does not
  put them in awaiting-response. Help & Questions, Ideas & Proposals, and
  Bugs & Errors follow the last-word rule until an accepted answer settles
  the thread. Bugs & Errors is for investigation; confirmed reproducible
  defects are tracked on linked repository issues.
- **Conversation state lives on GitHub + Mind, never here.** Labels
  (`needs-info`, `pending-release`) and the issue thread itself are the
  conversation's memory; in-flight dev state is the `user-facing: true` entry
  in `PyAutoMind/active.md`. The conductor owns no registry, no cache, no
  paired repo.
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
  community PRs. Known v2 limit: awaiting-response reads PR *conversation*
  comments — review-thread comments don't count as our reply yet.

## Capability audit — what the modes read

- **Discussions hub** (`gh api repos/<hub>/discussions`, `.../discussions/<n>`,
  `.../discussions/<n>/comments`): the REST Discussions surface, read-only —
  state, lock, category, `answer_chosen_at`, comment count, last commenter.
  Served to remote sessions through the proxy (measured 2026-09-17).
- **GitHub search** (`gh api search/issues`): `org:PyAutoLabs` plus the
  non-org homes from `repos.yaml`; three passes per qualifier group —
  `is:issue is:open -author:<self>`, `is:pr is:open -author:<self>`, and
  `is:pr is:open review-requested:<self>` — bot authors post-filtered on the
  external passes.
- **Issue/PR conversation comments** (`gh api repos/<o>/<r>/issues/<n>/comments`):
  last-actor detection for awaiting-response (capped at 30 items per scan)
  and the triage comment tail.
- **Pull detail** (`gh api repos/<o>/<r>/pulls/<n>`): the triage change-shape
  block for PR refs.
- **PyAutoMind `repos.yaml`**: the body map, parsed for `github:` homes
  (regex, stdlib-only — the Brain takes no yaml dependency).

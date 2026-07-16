# Community agent

> **Tier: conductor** — a front-door agent you *drive*. The *Ears* — the
> organism's receptive language function: it hears the community (user-filed
> GitHub issues across every repo) and drafts what the organism says back; the
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
| `scan` *(default)* | every `PyAutoMind/repos.yaml` repo → open issues authored by non-self humans (bots filtered), with **awaiting-response** detection (the conversation's last word is not ours) ranked by waiting time | `/community` step 1; the `/wake_up` community sensory leg |
| `triage <issue-ref>` | one issue → context-sufficiency signals (code block, traceback, versions, expected-vs-actual, data pointer), missing-signal clarifying-question seeds, comment tail, route | `/community` steps 2–3 |

```
pyauto-brain community                    # scan: who is waiting on us?
pyauto-brain community scan --json
pyauto-brain community triage <url | owner/repo#N> [--json]
```

Repo enumeration comes from `PyAutoMind/repos.yaml` (the body map) under
`PYAUTO_ROOT`; the org is searched wholesale, non-org homes individually.
GitHub access is the `gh` CLI — `COMMUNITY_GH` overrides the binary (hermetic
tests), `COMMUNITY_SELF` the self logins (default `Jammy2211`). A failed
search degrades honestly (`degraded:` in the surface), never silently.

## Fundamental principles

- **The conductor hears; the human speaks.** Every outward message — receipt,
  clarifying question, plan update, closing note — is drafted in the session
  and presented to the human before posting. The CLI itself never mutates
  GitHub. Autonomy for community work is `human-required` by design; `--auto`
  changes nothing here.
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
- **vs health / hygiene / release** — no verdicts, no upkeep, no releases;
  external PRs and review requests are out of scope for v1 (a staged
  follow-up recorded here).

## Capability audit — what the modes read

- **GitHub search** (`gh api search/issues`): `org:PyAutoLabs` plus the
  non-org homes from `repos.yaml`, `is:issue is:open -author:<self>`, bot
  authors post-filtered.
- **Issue comments** (`gh api repos/<o>/<r>/issues/<n>/comments`): last-actor
  detection for awaiting-response (capped at 30 issues per scan) and the
  triage comment tail.
- **PyAutoMind `repos.yaml`**: the body map, parsed for `github:` homes
  (regex, stdlib-only — the Brain takes no yaml dependency).

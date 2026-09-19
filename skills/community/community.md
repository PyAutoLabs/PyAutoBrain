# /community — hear and answer the community (via the Brain Community Agent)

Manage the organism's conversations with **external users** — the *Ears* — via
PyAutoBrain's **Community Agent**. You never name the Brain; this command is
the door. The agent hears (scan/triage are read-only surfaces); **you draft
every reply and the human approves it before anything is posted**.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`. The agent's full
docs: `bin/pyauto-brain help community`.

## Do

1. **Scan** — who is waiting on us?

   ```bash
   bin/pyauto-brain community            # default mode
   ```

   Emits a **CommunityScan**: the Discussions hub's open threads (the
   surface users post to — `PyAutoMind/policy/community_surface.md`;
   awaiting-response = no accepted answer and the last word is not ours,
   except Announcements and Show and tell, which stay ours to watch), plus open
   issues **and PRs** authored by non-self humans across every `repos.yaml`
   repo, with awaiting-response detection ranked by waiting time, plus open
   PRs with review requested from you. The Brain board runs this same scan
   as its community leg.

2. **Triage** the item the human picks:

   ```bash
   bin/pyauto-brain community triage <discussion/issue/PR url | owner/repo#N>
   ```

   A discussion is named by its URL (`owner/repo#N` reads as an issue).

   Emits context-sufficiency signals (code block, traceback, versions,
   expected-vs-actual, data pointer), clarifying-question seeds for whatever
   is missing, and the comment tail; a PR ref adds the change-shape block
   (draft, files, +/-, requested reviewers, mergeable state). The signals are
   heuristics — **you** read the actual issue or PR and judge.

3. **Converse — drafts only.** Based on your judgment:
   - **A discussion** → answer **in the thread**: draft the reply, the human
     posts it. In an answerable category, the human marks the settling reply
     as the accepted answer. If the thread is a bug with a reproducer or an
     accepted implementation proposal, open the issue on the target repo
     (quote the thread, link it) and route it via `/start_dev_for_user`.
     For **Proposals**, mark the verdict comment — acceptance with the issue
     link, or a recorded no — as the accepted answer; this is what stops the
     Ears chasing the thread. **Ideas** is for wishes without a design or an
     offer to build. Non-answerable categories have no accept button;
     Announcements and Show and tell remain ours to watch and can still be
     triaged explicitly. Never convert a thread in
     place, and never ask a user to re-file: the hub is *their* surface.
     No session can post to, answer or convert a Discussion — the REST API
     is read-only and GraphQL is refused — so the human's click is the last
     step of every discussion round.
   - **Actionable** → route into `/start_dev_for_user <url>` — it owns the
     receipt comment, the clarification gate, the plan comment and the
     milestone cadence. Do not re-implement its templates here.
   - **Not yet actionable** → draft **one consolidated clarifying comment**
     in a warm teammate tone (seeds from the triage surface, redrafted in your
     own words, reporter @-mentioned), present it to the human, and only post
     after approval; label `needs-info`.
   - **In-flight follow-ups** (reporter replied, milestone reached) → draft
     the update the same way; `/update_issue` posts progress from a dev
     session. Cadence: ~5 milestones for bugs, ~4 for features.
   - **External PR / review request** → the review is yours with the human:
     read the diff, draft the review comments for approval. Never route a
     community PR through the ship-gate review faculty.

## Boundary

- **Hears and drafts; the human speaks.** Every outward message is presented
  for approval before posting — at every autonomy level; `--auto` changes
  nothing here.
- **No new state.** The issue thread + labels are the conversation's memory;
  in-flight dev state is the `user-facing: true` entry in
  `PyAutoMind/active.md`.
- **vs `/workspace` (the Voice):** that agent plans how the organism speaks
  through authored examples; this one holds up its end of a conversation with
  a specific outsider.
- `--json` gives the machine-readable scan/triage surface.

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

   Emits a **CommunityScan**: open issues **and PRs** authored by non-self
   humans across every `repos.yaml` repo, with awaiting-response detection
   (the conversation's last word is not ours) ranked by waiting time, plus
   open PRs with review requested from you. `/wake_up` runs this same scan
   as its community step.

2. **Triage** the item the human picks:

   ```bash
   bin/pyauto-brain community triage <issue-or-PR url | owner/repo#N>
   ```

   Emits context-sufficiency signals (code block, traceback, versions,
   expected-vs-actual, data pointer), clarifying-question seeds for whatever
   is missing, and the comment tail; a PR ref adds the change-shape block
   (draft, files, +/-, requested reviewers, mergeable state). The signals are
   heuristics — **you** read the actual issue or PR and judge.

3. **Converse — drafts only.** Based on your judgment:
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

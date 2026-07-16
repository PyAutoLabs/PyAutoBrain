# Agent failure modes — the validated catalogue and structural mitigations

**Status:** design deliverable for PyAutoBrain#130 (build-chain campaign
PyAutoBuild#155, Phase 5 — deliberately last, so every earlier phase's errors
enlarge the evidence). **Method:** the original 2026-07-15 catalogue's
checkable claims were re-measured, and the 2026-07-16 campaign session is
mined as an out-of-sample test of the central hypothesis — by an agent that
was *reading these briefs while making the new errors*, which is itself the
strongest datum here.

## 1. The original catalogue, validated

Checked 2026-07-16: git **2.34.1** (D1's `merge-tree` needs ≥2.38 —
confirmed); `PyAutoMind/repos.yaml` now carries **33** repos (was 30 — the
hand-list gap C1 measures keeps growing); `smoke_tests.txt` is **11** entries
(A2's false claim confirmed falsifiable in seconds); the `use_jax` defaults
(A4) were re-verified during Phase 3. Nothing in A–E was refuted. The A–E
taxonomy survives, with one compression (§3).

## 2. The out-of-sample additions (2026-07-16, one campaign session)

Same discipline — claim, truth, cost, caught by:

| # | error | caught by |
|---|---|---|
| F1 | `git commit` in the shared PyAutoMind checkout swept a concurrent session's staged rename (×1), then a *directory-scoped* commit swept two more (×2), then a concurrent session swept THIS session's staged records (×3, reverse direction) — **E1 repeated three times in one day, with a fresh memory note about E1 written that same morning** | git log reading, after push, each time |
| F2 | `cmd \| head; $?` read the pager's exit, not the command's — **twice** — and `black --check -q`'s silence was read as cleanliness once | self, on re-reading output (luck) |
| F3 | A checkpoint claim ("no DISABLE_JAX pins remain — question may be moot") built on a `head -4` grep was **published to a GitHub issue** before being falsified | a deliberate falsifying probe (D2's habit, applied on purpose this time) |
| F4 | Two *stale claims of this session's own completed tasks* blocked new work | `worktree_check_conflict` **refused** — forced the completion recording that should already have happened |
| F5 | The PyAuto API gate **refused a pure file-inspection command** (pattern-matched path text as API symbols) | n/a — a refusal false positive; cost: one bypassed re-run |

F1 is the headline: the trap was documented in the morning, in a memory note
written specifically about it, by the agent that then walked into it three
times before dinner. **B1 is not an anecdote; it is the normal case.**

## 3. The compressed taxonomy

The A–E grouping compresses to two root causes plus a hygiene class:

1. **Verification aimed at the believed path** (A1–A5, D1, D3, F2, F3): real
   work producing real evidence for a proposition nobody questioned. The
   agent reliably verifies — and reliably verifies the wrong thing.
2. **State consulted from memory instead of from the world** (B1, B2, C1,
   C2, E1, F1, F4): notes, recollections and stale registrations standing in
   for `git status`, `repos.yaml`, and the claims ledger at the decisive
   moment.
3. **Convention/shared-state hygiene** (E2–E4, F5's cost column): real but
   secondary; the guards that exist here already work.

## 4. The hypothesis, tested on the new data

**"Refusals catch, reminders don't" survives — with a sharper statement and
a measured cost column.**

- Refusals that fired correctly this session: `worktree_check_conflict` ×2
  (F4), the `test_pre_build_skill` drift guard (caught a real doc/script
  drift on clean main during a ship), `lifecycle.py check` (flagged a
  half-done completion), and the brand-new `validate_env_profiles` — which on
  first contact found 3 dead config patterns and 15 vacuous-JAX scripts that
  a day of human-authored enumeration had missed. Hit rate on things they
  guard: still effectively 100%.
- Informs that failed this session: the E1 memory note (three more sweeps);
  the agent's *own live awareness* of the A5 error shape (it re-committed
  that exact shape in F3 while mid-campaign about it). **Awareness is an
  inform. Even self-awareness.** That is the sharper statement: the dividing
  line is not documentation-vs-tooling, it is whether anything *interrupts
  the action*, because at the decisive moment the agent is not consulting
  anything — not notes, not even its own recent conclusions.
- The cost column (previously unmeasured): F5 shows refusals false-positive;
  the API gate misfired on path text and cost one bypass. One misfire against
  dozens of correct refusals across two days is a good ratio, but every new
  refusal proposed below must state its expected false-positive surface —
  a refusal that misfires often trains bypass-by-default, which is worse
  than no guard (the brief's own routing-around warning).

## 5. Ranked mitigations

Each: catalogue entries caught → why it fires at the decisive moment → cost
→ how it fails.

1. **`set -o pipefail` (+ never `-q` on check-mode tools) as the agent-shell
   default.** Catches F2's entire class (three instances in one day) by
   making the *instrument* loud instead of the agent careful — the purest
   delete-the-trap available, since the mistake becomes unmakeable rather
   than detectable. Cost: zero per task; failure mode: legitimately-failing
   pipe heads (grep-no-match) now need explicit handling — small, visible,
   and itself error-revealing. **This is a one-line hook/profile change; do
   it first.**
2. **A Mind commit guard (refusal).** In the shared PyAutoMind checkout,
   refuse any `git commit` that (a) lacks explicit `--` *file* pathspecs, or
   (b) would include index entries outside those paths (another session's
   staged work). Catches E1 + F1 (four incidents across two days, the
   highest-frequency error in the whole catalogue). Fires at the decisive
   moment by construction — it *is* the action. Cost: a wrapper or PreToolUse
   check scoped to one repo; false-positive surface: deliberate multi-file
   registry commits, handled by listing the files (which is the desired
   behaviour anyway).
3. **Stale-claim auto-expiry (refusal-adjacent).** F4 shows completed tasks
   linger in `active.md` and block; the conflict guard catches it late but
   correctly. Cheaper at the source: `worktree_remove` (already the cleanup
   choke-point) warns-then-offers the `active.md` release + completion record
   when the branch it removes is merged. Catches F4's class before it costs a
   conflict roundtrip. Cost: one prompt in an existing tool.
4. **Blessed instruments for the repeated questions** (C2, D1, D2): the
   campaign's own `validate_env_profiles` is the proof the pattern works —
   the question "is this config sane?" got one tested implementation and
   immediately out-performed recall. Remaining candidates, each a small task:
   "does this branch contribute to main?" (D1/D2's hand-rolled disaster —
   `pyauto-gut`'s remit), and "which repos exist?" → `repos.yaml` is already
   canonical; the missing piece is that nothing *routes* to it, which is
   mitigation 5.
5. **Make the router consult the body map, not the agent.** C2's lesson
   ("nothing routes the agent to the artifact while deciding") generalises:
   wherever a conductor needs a repo list, it should *call* the sizing
   faculty / `repos.yaml` loader rather than accept a hand-list argument.
   Grep the conductors for hand-list parameters; each is a small refactor.
   Fires at the decisive moment because the enumeration happens inside the
   tool rather than in the prompt.
6. **Adversarial pass as a checkpoint stage, not a virtue.** It caught the
   three worst 07-15 errors and F3 — every time it actually ran. It cannot be
   a hook (it is judgment), but it can be a *structural stage*: the ship
   skills' checkpoint format gains a required "falsified-by" line per
   load-bearing claim (what would make this false; what was run to check).
   This is dangerously close to the banned checklist — the honest difference
   is that it is enforced by the checkpoint *reader* (the human sees a
   missing falsified-by line), not remembered by the agent. Cost: minutes per
   ship; failure mode: rote compliance — mitigate by keeping it to
   load-bearing claims only. **Trial it; measure whether it goes rote.**

## 6. The memory system, attacked honestly

The day's evidence cuts both ways. Failures: B1, B2, and F1's note that did
not fire — memory as *tripwire* is refuted twice over. Successes: the
intake-handfix note correctly guided a live intake (consulted deliberately at
task start), and the campaign-state note is what makes cross-session
continuation possible at all. **Verdict: memory earns its keep as
consult-on-purpose context and fails reliably as guard-at-the-moment.** The
policy that follows: guard-shaped memories ("NEVER do X in Y") are candidates
for conversion into refusals (mitigation 2 is exactly the E1 note,
converted); a memory that cannot be converted should state *when it will be
consulted*, or it is a hope, not a mechanism.

## 7. Estimating the unnoticed set

Method: count claims that crossed an external boundary (issue comment, commit
message, PR body, user-facing summary) and were *later* found wrong, as a
lower bound on the rate at which unverified boundary-crossing claims are
wrong. This campaign: 3 such catches (A2 on 07-15; F3's published checkpoint;
the Phase 1 brief's "origin READMEs correctly pin" claim, half-refuted by
measurement) across roughly 40 boundary-crossing checkpoint claims — **~7%
caught-late rate among claims that WERE eventually re-derived.** The honest
estimate is that claims never re-derived are wrong at a comparable rate:
in a session producing dozens of boundary-crossing claims, **expect 1–3
undetected false statements to be live in the record right now.** The
mitigation is not zero-defect (impossible) but boundary discipline:
mitigation 6 targets exactly the boundary-crossing moment.

## 8. Rejected

- **Documentation as primary mechanism** — refuted a third time by F1, now
  with the strongest possible variant (same-day self-authored note).
- **"Try harder" / awareness** — refuted by F3: the error was made *during*
  a campaign about that error, by the agent writing about it.
- **A universal pre-action checklist** — banned by the brief, and F1 shows
  why: the decisive moment has no checklist-consulting step to hook into.
- **Rejecting the refusals hypothesis** — attempted per the brief; the new
  data strengthened it instead. Its honest weaknesses: refusals only exist
  where someone built one (coverage is reactive), and F5's false-positive
  cost is real. Neither overturns the hit-rate asymmetry.

## 9. Open decisions (human) + migration

- Mitigation 1 (`pipefail` default): approve as a harness/profile change —
  one line, highest ratio. 2 (Mind commit guard) and 3 (claim expiry): small
  tasks, file on approval. 4–5: mine the conductors, file individually.
  6 (falsified-by lines): trial on the next ship series, review whether it
  went rote after ~10 ships.
- Whether F5's API-gate false-positive class warrants a scope fix (only scan
  arguments that are Python code, not path strings) — small, filed
  separately.
- Each mechanism lands as its own PR behind its own plan; nothing here
  changes behaviour by merging this document.

## Trust nothing here

Written by the agent that made F1–F3 *while writing about A–E*. The §7
estimate is constructed from this document's own author's error rate and
should be treated as optimistic. Every §1 number is re-checkable in seconds;
§2's incidents are all in the campaign's issue trail (PyAutoBuild#155/#156/
#161, PyAutoHeart#83) with commands and commit SHAs.

# /bug — fix a regression, failing test, or wrong behaviour (via the Brain Bug Agent)

Route a bug through PyAutoBrain's **Bug Agent** — the organism's *immune system* — then
hand its decision to the dev workflow. You never name the Brain; this command is the door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. **Specific bug** — a `bug/…md` path, issue, failing test or error: run
   `bin/pyauto-brain bug <path-or-report>`. With no target, run `bin/pyauto-brain bug`
   to select the next bug (severity-first). Difficulty/importance constraints:
   `bin/pyauto-brain bug select --difficulty easy | --impact | --model strong`.
2. **From PyAutoHeart** — run `bin/pyauto-brain bug health`: it reads the live vitals
   verdict **and** scans the filed PyAutoHeart issues, hinting a category per finding;
   confirm the real defects and file them under `PyAutoMind/bug/health_fixes/`.
3. Take the emitted `BugDecision` (classification, **fix locus**, strategy, workflow)
   and continue with **`/start_dev`** on the chosen bug — that carries the branch
   survey, issue creation, and registration.
4. **Finish & reset (per fix).** When a bug reaches a terminal state — shipped
   (`/ship_*`), parked, or closed — first confirm its durable state is fully
   externalised: the **GitHub issue** (investigation trail), **PyAutoMind**
   (`active`/`planned`/`complete`), and **auto-memory** (cross-bug learnings worth
   carrying forward). Then tell the user it is **safe to `/clear` before the next
   `/bug`**: the transcript now holds only disposable investigation scratch (file
   reads, repro runs, tool output), so a fresh session loses nothing and context
   stays lean across many bugs in one sitting. An agent cannot clear its own host
   transcript — this is a deliberate one-keystroke user step, and the externalised
   state above is what makes it lossless.

The Bug Agent **reasons; it never edits source**, and its first question is always
*where the fix belongs*: prefer a general library-source fix, and **never degrade a
user-facing workspace script** to mask a symptom (no injected env-vars, hard-coded
paths, `os.environ` mutation, or silent guards). Reproduction and validation are
identified and delegated to the vitals faculty — the Bug Agent never runs checks itself.
Do not bypass the Brain.

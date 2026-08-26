# /intake — conceive a task (via the Brain Intake Agent)

Turn raw input — a text-vomit idea, a bug report, a loose `ideas.md` bullet —
into a **formal, grouped, headed PyAutoMind prompt**, via PyAutoBrain's **Intake
Agent** (the *Conception Agent*). You never name the Brain; this command is the
door.

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

1. Run `bin/pyauto-brain intake "<the raw text>"` (or `intake classify --file
   <path>`, or `intake ideas` to sweep `ideas.md`). This is a **dry run** — it
   classifies work-type + target, sizes difficulty, and shows the header it would
   write. Nothing is created.
2. Review the `IntakeDecision` with the user — correct the work-type, target,
   difficulty, autonomy or priority in conversation (this is the back-and-forth
   where scope, and therefore difficulty, is decided). A `Type:`/`Difficulty:`/
   `Autonomy:`/`Priority:` the raw input already declares is taken as written —
   the decision marks it `(declared)` and shows the level the heuristic derived,
   so a disagreement stays visible instead of being silently resolved.
3. When it looks right, re-run with **`--apply`** to write the prompt file into
   PyAutoMind under `draft/<work-type>/<target>/<name>.md` (or `draft/triage/` if the
   classification is genuinely unclear).
4. **Regenerate the dashboard and commit both together.** `--apply` writes the
   prompt file and nothing else — it runs no git — so the filing is not finished
   until the page that offers the task is rebuilt:

   ```bash
   cd $PYAUTO_MAIN/PyAutoMind
   pyauto-brain intake --apply dashboard     # writes dashboard.md + dashboard.html
   pyauto-brain intake dashboard --check     # must print "…are current"
   source scripts/prompt_sync.sh && prompt_sync_push "intake: file <name>"
   ```

   One commit carrying the prompt **and** the regenerated pages. This is not
   optional tidying: the dashboard is how a task is picked up — tap 📋, get
   `/start_dev <path>` — so a prompt filed without it is invisible on the phone
   path until `dashboard_refresh.yml` heals the render and `pages_dashboard.yml`
   redeploys. Filing a prompt nobody can find yet is the failure this step
   exists to prevent. Re-rendering an already-current tree is a no-op, so there
   is nothing to weigh up: run it on every `--apply`, including `formalise` and
   the `ideas` sweep, which change the page the same way.

Intake **files a prompt; it does not start development.** It is the step *before*
`/start_dev`. Once the prompt is written, `/start_dev <path>` routes it into the
dev workflow (issue, branch, plan). Do not bypass the Brain.

## Backlog view (census / dashboard)

- `bin/pyauto-brain intake census` — read-only inventory of every filed prompt
  (counts by work-type/target/difficulty/priority + hygiene flags for headerless
  legacy prompts). `--json` for the full records.
- `bin/pyauto-brain intake dashboard` — renders the census as the Mind **task**
  page (`PyAutoMind/dashboard.md`, linked from that repo's README): the picks
  worth starting now, then in flight / parked / planned / the whole backlog.
  Every task renders as one collapsed row whose leading 📋 toggle hides a
  code fence (GitHub's copy button) holding the `/start_dev <prompt-path>`
  message that routes Claude to that task — the phone path from the page
  into a session. `--apply` also writes `dashboard.html`, the one-tap-copy
  twin GitHub Pages serves (real clipboard buttons; PyAutoMind's
  `pages_dashboard.yml` deploys it), with links derived from `repos.yaml`.
  Dry-run prints it, `--apply` writes it (commit via `prompt_sync_push`),
  `--check` exits 1 if the committed page has drifted. PyAutoMind's
  `dashboard_refresh.yml` self-heals a stale **render** on pushes to main — that
  is a backstop for a page nobody rebuilt, not a reason to skip step 4 above:
  it lands a later bot commit and has to re-dispatch `pages_dashboard.yml`
  itself, so the Pages page (the one people actually tap) lags until it does.
  Regenerate in the same commit as the change. Tasks only — organism *health*
  is `/health`, not this page.
- `bin/pyauto-brain intake formalise [prefix]` — retroactively headers the
  prompts census flags (word-vomit is intent, not defect): derives the missing
  fields, inserts them in place with all prose verbatim, reports re-home
  suggestions instead of ever moving files. Dry-run proposes; `--apply` writes
  (then regenerate the dashboard and commit it with the change, per step 4).
- `bin/pyauto-brain intake reconcile [prefix]` — ranks backlog (`draft/`)
  prompts that look already-shipped (cross-referenced against the `complete/`
  records — the sole completion ledger since `complete.md` retired, #81 — and `active/`; a stale
  hand-set `Status:` is a signal, never proof). Always read-only: verify each
  suspect against the target repo's git log / merged PRs, then retire it to the
  `complete/` archive by hand (it is already done).
- `bin/pyauto-brain intake reconcile --repo <target> [prefix]` — **also** reads
  `<target>`'s source for identifiers the prompts name, citing `file:line` in a
  weaker `needs-review` band. This is the only signal that reaches a prompt with
  no Mind-side trace, and it is the Brain's only network access — opt-in, cached
  shallow clone, still read-only. It never says *shipped*: a name can exist
  upstream without the prompt's fix existing, so read the cited lines before
  retiring anything. A target that is not one repo (`workspaces`, `priors`, …)
  is refused with the real candidates named, never guessed.

## Boundary

- **`/route`** infers a work-type and *dispatches* (starts dev now); **`/intake`**
  infers a work-type and *files a prompt* (defers).
- Low-confidence classification lands in `triage/` — the existing unclassified
  bucket, reused.
- Writes happen **only** under `--apply`; the default is a read-only dry run.
- **Machine sources** (scholar research runs, Heart findings, profiling
  results) stage as provenance-tagged `ideas.md` bullets — `- [from: <source>]
  <idea>` — and ride the same ideas sweep; intake learns no per-source formats
  (the conductor's "Machine sources" section is authoritative).

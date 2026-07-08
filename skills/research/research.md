# /research — investigation, design notes, scientific background

A **work-type entry** into the Brain dev-flow. No dedicated Research conductor
exists yet, so this routes through the Feature Agent's classifier with the
PyAutoMind work-type fixed to `research/`. (Follow-up: promote to a dedicated
Research conductor.)

Shared routing context: `PyAutoBrain/skills/COMMANDS.md`.

## Do

Treat the request as PyAutoMind work-type **`research/`** — exploratory
investigation, design notes, or scientific background *before* implementation. If
no prompt path exists, create one under `PyAutoMind/research/<target>/<name>.md`
(original request verbatim). Research typically produces notes/decisions rather
than a PR; consult the **memory faculty** (`bin/pyauto-brain memory "<topic>"`)
for prior art and record findings back to Mind. Escalate to `/feature` once
scoped. Taxonomy: `PyAutoMind/ROUTING.md`.

## Scholar mode (research conceives tasks)

A research run should not let actionable insight die in the session. **End
every substantial research run by proposing candidate tasks** — bullets
appended to `PyAutoMind/ideas.md`, each with a provenance tag:

```markdown
- [from: research <session/topic> · <wiki page | paper | result>] <the idea>
```

Rules (the intake conductor's "Machine sources" section is authoritative):

- **Bullets only** — never write prompt files or `planned.md` entries from a
  research run; `ideas.md` is the staging area precisely so intake's
  conception discipline (classify, size, human review, `--apply`) is reused,
  not bypassed. Noise dies cheaply at the bullet stage.
- Propose the batch to the human before appending; then
  `bin/pyauto-brain intake ideas` (dry-run) → review → `--apply` formalises.
- **Provenance stays private**: PyAutoMemory citations in a tag live in Mind
  (private) — fine — but must never survive into public user-facing output a
  formalised task later produces (memory faculty privacy seam).
